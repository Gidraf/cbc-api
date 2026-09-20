"""A second model reads what the bank holds, and fixes it.

The checks and the aimed rewrite land on new batches. This runs the same
loop over what is already filed, on a model the operator chooses — a
different vendor from the one that wrote the items, so the second opinion
is a second opinion — and writes the outcome back: rewritten items
replace their originals (an approved one is versioned, a draft edited in
place), items that still fail are held `needs_review` with the reasons,
and items that pass are stamped reviewed and, if asked, approved.

No item is deleted. Everything is on the row for the console to show.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

logger = logging.getLogger("cbc-bank-review")

MAX_PASSES = 2
GROUP_LIMIT = 60   # one reader call and one rewrite call per group


def review(*, grade: str, subject: str, sub_strand: str = "", provider: str | None = None,
           model: str | None = None, fix: bool = True, approve_clean: bool = False,
           limit: int = 5000, progress: Any = None) -> dict[str, Any]:
    from . import bank_recheck, question_check, question_rows, questions_remediation
    from .llm_client import llm_client
    from .pipeline import pipeline_orchestrator
    from .question_dna import question_dna_service

    def note(what: str, detail: str = "", status: str = "ok") -> None:
        if progress is not None:
            try:
                progress(what, detail, status)
            except Exception:  # noqa: BLE001
                pass

    # 0. What needs no model, first, so the reader is not paid to find braces.
    shapes = bank_recheck.run(grade=grade, subject=subject, sub_strand=sub_strand, limit=limit)
    note("Shapes", f"{shapes['repaired_count']} repaired without a model")

    resolved = pipeline_orchestrator.router.resolve_for_stage("reviewer_panel", provider, model)
    note("Reader", f"{resolved.provider} · {resolved.model}")

    rows = question_dna_service.list_questions(
        grade=grade or None, subject=subject or None, sub_strand=sub_strand or None,
        limit=limit, order="curriculum")
    by_id = {str(r.get("question_id")): r for r in rows}
    items = [q for q in question_rows.flatten_all(rows)
             if str(q.get("status") or "") not in ("rejected", "superseded")]

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in items:
        cur = item.get("curriculum") or {}
        key = (str(cur.get("grade") or grade), str(cur.get("subject") or subject),
               str(cur.get("sub_strand") or ""))
        groups.setdefault(key, []).append(item)

    report: dict[str, Any] = {
        "reader": f"{resolved.provider} · {resolved.model}", "checked": len(items), "groups": [],
        "rewritten": 0, "held": 0, "cleared": 0, "approved": 0, "shapes_repaired": shapes["repaired_count"],
        "findings_by_kind": {},
    }
    for (g, s, ss), group in groups.items():
        for start in range(0, len(group), GROUP_LIMIT):
            chunk = group[start:start + GROUP_LIMIT]
            outcome = _review_group(chunk, grade=g, subject=s, sub_strand=ss, resolved=resolved,
                                    fix=fix, approve_clean=approve_clean, by_id=by_id,
                                    llm_client=llm_client, question_check=question_check,
                                    questions_remediation=questions_remediation,
                                    question_dna_service=question_dna_service)
            report["groups"].append(outcome)
            for k in ("rewritten", "held", "cleared", "approved"):
                report[k] += outcome[k]
            for kind, n in outcome["findings_by_kind"].items():
                report["findings_by_kind"][kind] = report["findings_by_kind"].get(kind, 0) + n
            note("Reviewed", f"{ss or s}: {outcome['rewritten']} rewritten, {outcome['held']} held, "
                             f"{outcome['cleared']} clean")
    return report


def _review_group(items: list[dict[str, Any]], *, grade: str, subject: str, sub_strand: str,
                  resolved: Any, fix: bool, approve_clean: bool, by_id: dict[str, Any],
                  llm_client: Any, question_check: Any, questions_remediation: Any,
                  question_dna_service: Any) -> dict[str, Any]:
    from . import question_audit
    from .question_normalizer import question_normalizer

    # Labels unique within the group: several batches each have a Q1, and
    # the loop names items by label.
    labels: dict[str, str] = {}
    originals: dict[str, dict[str, Any]] = {}
    for n, item in enumerate(items, start=1):
        item["display_label"] = f"Q{n}"
        labels[f"Q{n}"] = str(item.get("question_id"))
        originals[str(item.get("question_id"))] = item
    strand = str((items[0].get("curriculum") or {}).get("strand") or "") if items else ""
    notes_text = _notes_for(grade, subject, sub_strand)

    def audit(batch: list[dict[str, Any]]) -> list[Any]:
        return question_audit.audit(batch, generate=llm_client.generate, model_config=resolved,
                                    notes_text=notes_text, grade=grade, subject=subject,
                                    sub_strand=sub_strand)

    def rewrite(to_redo: list[dict[str, Any]], reasons: list[str], asks: list[str]) -> list[dict[str, Any]]:
        from ..routes.questions import _bind_figure, _draw_question_figures
        from .langfuse_seed import SEED_PROMPT_BLOCKS
        from .prompt_store import render

        directive = render(
            "questions-rewrite-directive", SEED_PROMPT_BLOCKS["questions-rewrite-directive"],
            sub_strand=sub_strand, grade=grade, subject=subject,
            items_json=json.dumps([{k: v for k, v in q.items()
                                    if k not in ("dna_id", "status", "version", "review_audit", "provenance",
                                                 "created_at", "updated_at")} for q in to_redo],
                                  ensure_ascii=False, indent=1),
            reasons="\n".join(f"- {r}" for r in reasons) or "(none)",
            asks_block="")
        messages = [{"role": "system", "content": _system_for(grade, subject, sub_strand, notes_text)},
                    {"role": "user", "content": directive}]
        resp = llm_client.generate(resolved, messages, temperature=0.2)
        raw = resp.content.get("questions", []) if isinstance(resp.content, dict) else resp.content
        out: list[dict[str, Any]] = []
        for candidate in (raw if isinstance(raw, list) else []):
            if not isinstance(candidate, dict):
                continue
            replaces = str(candidate.get("replaces") or "")
            candidate = _draw_question_figures([candidate], [], grade=grade, subject=subject,
                                               strand=strand, sub_strand=sub_strand)[0]
            batch = question_normalizer.normalize_batch(
                [candidate], grade=grade, subject=subject, strand=strand, sub_strand=sub_strand,
                diagram_resolver=lambda r, t: _bind_figure(r))
            for item in batch.items:
                public = item.to_public_dict(include_answers=True)
                if replaces:
                    public["replaces"] = replaces
                out.append(public)
        return out

    best, result = questions_remediation.run(
        items, grade=grade, subject=subject, strand=strand, sub_strand=sub_strand,
        existing=[], rewrite=rewrite if fix else None, audit=audit, max_passes=MAX_PASSES)

    outcome = {"sub_strand": sub_strand, "items": len(items), "rewritten": 0, "held": 0, "cleared": 0,
               "approved": 0, "dropped_as_copies": list(result.dropped), "findings_by_kind": {},
               "outstanding": list(result.outstanding), "stopped_because": result.stopped_because}
    stamp = {"reviewed_by": f"{resolved.provider} · {resolved.model}", "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "findings_before": list(result.findings_before)}

    # Which item each outstanding finding names.
    held: dict[str, list[str]] = {}
    for says in result.outstanding:
        m = re.match(r"^(Q\d+)\b", says)
        qid = labels.get(m.group(1)) if m else None
        if qid:
            held.setdefault(qid, []).append(says)
        kind = says.split(":")[0] if ":" in says[:40] else "set"
        outcome["findings_by_kind"][kind] = outcome["findings_by_kind"].get(kind, 0) + 1

    # Replacements: the item now carrying the original's label.
    by_label_now = {str(q.get("display_label")): q for q in best}
    for old_id in result.rewritten:
        old = originals.get(old_id)
        new = by_label_now.get(str((old or {}).get("display_label")))
        if old is None or new is None or new is old:
            continue
        content = {k: v for k, v in new.items()
                   if k not in ("question_id", "universal_id", "display_label", "version", "status", "pedagogy",
                                "curriculum", "dna_id", "created_at", "updated_at", "review_audit", "provenance")}
        row = by_id.get(old_id) or {}
        audit_row = {**(row.get("review_audit") or {}), **stamp, "rewritten": True}
        try:
            question_dna_service.update_question(old_id, content, review_audit=audit_row)
            outcome["rewritten"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not write the rewrite of %s: %s", old_id, exc)
        if old_id in held:
            question_dna_service.set_status(old_id, "needs_review",
                                            review_audit={**audit_row, "recheck": {"findings": held[old_id]}})
            outcome["held"] += 1

    for qid in list(result.dropped):
        row = by_id.get(qid) or {}
        question_dna_service.set_status(qid, "needs_review", review_audit={
            **(row.get("review_audit") or {}), **stamp,
            "recheck": {"findings": ["a copy of another item in the bank; one of them goes"]}})
        outcome["held"] += 1

    for qid, item in originals.items():
        if qid in result.rewritten or qid in result.dropped:
            continue
        row = by_id.get(qid) or {}
        audit_row = {**(row.get("review_audit") or {}), **stamp}
        if qid in held:
            question_dna_service.set_status(qid, "needs_review",
                                            review_audit={**audit_row, "recheck": {"findings": held[qid]}})
            outcome["held"] += 1
            continue
        audit_row.pop("recheck", None)
        status = str(row.get("status") or "draft")
        if approve_clean and status != "approved":
            question_dna_service.set_status(qid, "approved", review_audit=audit_row)
            outcome["approved"] += 1
        else:
            question_dna_service.set_status(qid, "draft" if status == "needs_review" else status,
                                            review_audit=audit_row)
        outcome["cleared"] += 1
    return outcome


def _notes_for(grade: str, subject: str, sub_strand: str) -> str:
    try:
        from . import notes_digest, substrand_bundle

        row = substrand_bundle.load(grade, subject, sub_strand) or {}
        return notes_digest.for_questions(row.get("notes") or {}).text
    except Exception as exc:  # noqa: BLE001
        logger.debug("No notes for %s/%s/%s: %s", grade, subject, sub_strand, exc)
        return ""


def _system_for(grade: str, subject: str, sub_strand: str, notes_text: str) -> str:
    from . import assessment_format, figure_sketch

    return (f"You are rewriting assessment items for {grade} {subject} — {sub_strand} — for a Kenyan CBC "
            f"paper. Return the same JSON schema the items arrive in, one object per item, under "
            f"\"questions\", each carrying \"replaces\" with the question_id it stands in for.\n\n"
            f"{assessment_format.prompt_block(grade, 0, subject)}\n\n{figure_sketch.prompt_block()}\n\n"
            f"WHAT WAS TAUGHT:\n{(notes_text or '(no lesson notes on file)')[:8000]}")
