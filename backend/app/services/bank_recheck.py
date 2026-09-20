"""Run today's checks over what the bank already holds.

Every check lands on new batches. The bank was filled before some of them
existed — the same-task check, the scheme-as-object repair, the inline part
list — so a paper dealt from it still printed a debt of KSh 3,400 beside a
debt of KSh 3,500 and a marking scheme in braces. This walks a scope of the
bank, repairs in place what needs no model (schemes, stems, keys the engine
can prove), and marks the rest `needs_review` with the findings on the row,
so the composer leaves it out and the console shows why.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("cbc-bank-recheck")


def run(*, grade: str = "", subject: str = "", sub_strand: str = "",
        dry_run: bool = False, limit: int = 5000) -> dict[str, Any]:
    from . import question_check, question_rows
    from .question_dna import question_dna_service
    from .question_normalizer import scheme_text, strip_inline_parts, StructuredPart

    rows = question_dna_service.list_questions(
        grade=grade or None, subject=subject or None, sub_strand=sub_strand or None,
        limit=limit, order="curriculum")
    items = question_rows.flatten_all(rows)
    by_id = {str(r.get("question_id")): r for r in rows}

    report: dict[str, Any] = {
        "checked": len(items), "repaired": [], "flagged": [], "cleared": [],
        "findings_by_kind": {}, "dry_run": dry_run,
    }

    # 1. Repairs that need no model: the scheme's shape, the stem's part list.
    for item in items:
        content = dict((by_id.get(str(item.get("question_id"))) or {}).get("content") or {})
        if not content:
            continue
        changed = False
        scheme = content.get("marking_scheme")
        fixed_scheme = scheme_text(scheme)
        if fixed_scheme != (scheme if isinstance(scheme, str) else ""):
            content["marking_scheme"] = fixed_scheme
            item["marking_scheme"] = fixed_scheme
            changed = True
        parts = [StructuredPart(part_id=str(p.get("part_id") or ""), sub_question=str(p.get("sub_question") or ""),
                                marks=int(p.get("marks") or 0), model_answer=str(p.get("model_answer") or ""))
                 for p in (content.get("structured_parts") or []) if isinstance(p, dict)]
        text = str(content.get("question_text") or "")
        trimmed = strip_inline_parts(text, parts)
        if trimmed != text:
            content["question_text"] = trimmed
            item["question_text"] = trimmed
            changed = True
        if changed:
            report["repaired"].append({"question_id": item.get("question_id"), "what": "scheme/stem shape"})
            if not dry_run:
                question_dna_service.update_question(str(item["question_id"]), content)

    # 2. The checks, per sub-strand, each item against the others in its
    #    sub-strand: the engine on every key, the same-task check across
    #    batches that never saw each other.
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in items:
        cur = item.get("curriculum") or {}
        key = (str(cur.get("grade") or ""), str(cur.get("subject") or ""), str(cur.get("sub_strand") or ""))
        groups.setdefault(key, []).append(item)

    for (g, s, ss), group in groups.items():
        # Approved and older first, so of two clones the newer draft is the
        # one flagged.
        group.sort(key=lambda q: (0 if str(q.get("status")) == "approved" else 1, str(q.get("created_at") or "")))
        try:
            result = question_check.check(group, grade=g, subject=s, sub_strand=ss, existing=[])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Re-check of %s/%s/%s failed: %s", g, s, ss, exc)
            continue
        for fix in result.repaired:
            report["repaired"].append({"sub_strand": ss, "what": fix})
        flagged: dict[str, list[str]] = {}
        for found in result.findings:
            report["findings_by_kind"][found.kind] = report["findings_by_kind"].get(found.kind, 0) + 1
            for qid in found.items:
                flagged.setdefault(qid, []).append(f"{found.kind}: {found.says}")
        for item in group:
            qid = str(item.get("question_id"))
            row = by_id.get(qid) or {}
            audit = dict(row.get("review_audit") or {})
            if qid in flagged:
                report["flagged"].append({"question_id": qid, "sub_strand": ss, "why": flagged[qid]})
                if not dry_run and str(row.get("status")) != "approved":
                    audit["recheck"] = {"findings": flagged[qid], "status_before": row.get("status")}
                    question_dna_service.set_status(qid, "needs_review", review_audit=audit)
            elif audit.get("recheck") and str(row.get("status")) == "needs_review":
                # Flagged last time, clean now (its twin was removed, say).
                report["cleared"].append(qid)
                if not dry_run:
                    before = str((audit.get("recheck") or {}).get("status_before") or "draft")
                    audit.pop("recheck", None)
                    question_dna_service.set_status(qid, before if before != "needs_review" else "draft",
                                                    review_audit=audit)
    report["repaired_count"] = len(report["repaired"])
    report["flagged_count"] = len(report["flagged"])
    return report
