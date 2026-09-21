"""A paper being built.

The composer made a paper in one click and froze it; a person who wanted
the third question changed, two more diagrams, or a smaller font had no
way to say so. A draft is the paper between those two moments: its scope
(a sub-strand, a term worked out by hours, or topics the builder named),
the items it holds — chosen from the bank or written for it — the
builder's own corrections to any of them, the print settings, and the
composition. It renders at any point exactly as the frozen paper will,
and freezing it is one more call.

Corrections live on the draft until the freeze, which writes them to the
bank (a draft item edited in place, an approved one versioned) so the
frozen paper prints them and the bank keeps them.
"""
from __future__ import annotations

import logging
import secrets
import time
from typing import Any

logger = logging.getLogger("cbc-exam-drafts")

KINDS = {
    "topical": "Topical assessment", "midterm": "Mid-term examination", "endterm": "End of term examination",
    "assessment": "Assessment", "opener": "Opener examination", "cat": "Continuous assessment test",
    "mock": "Mock examination", "custom": "",
}

# The fields a builder may correct on an item. Everything else — ids,
# curriculum, provenance — is the bank's.
EDITABLE = ("question_text", "stimulus_context", "options", "structured_parts", "marking_scheme",
            "model_answer", "expression", "max_marks")


# Compact pages, but the full worked scheme — the depth is the product —
# and no DRAFT stamp: the studio's paper is the seller's paper.
DEFAULT_SETTINGS: dict[str, Any] = {"density": "compact", "scheme_detail": "full", "watermark": False}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ── the row ─────────────────────────────────────────────────────────────────

def create(*, owner: str, grade: str, subject: str, kind: str = "topical", title: str = "",
           term: int | None = None, scope: dict[str, Any] | None = None,
           settings: dict[str, Any] | None = None) -> dict[str, Any]:
    from ..infra.db import execute, to_json
    from .grade_order import normalize_grade

    draft_id = "draft-" + secrets.token_urlsafe(8)
    execute(
        """
        INSERT INTO exam_drafts (draft_id, owner, title, grade, subject, kind, term, scope, settings)
        VALUES (:id, :owner, :title, :grade, :subject, :kind, :term, CAST(:scope AS jsonb), CAST(:settings AS jsonb))
        """,
        {"id": draft_id, "owner": owner, "title": title, "grade": normalize_grade(grade), "subject": subject,
         "kind": kind if kind in KINDS else "custom", "term": term,
         "scope": to_json(scope or {"mode": "smart"}),
         "settings": to_json(settings or dict(DEFAULT_SETTINGS))},
    )
    return get(draft_id)


def get(draft_id: str, owner: str = "") -> dict[str, Any]:
    from ..errors import raise_api_error
    from ..infra.db import fetch_one

    row = fetch_one("SELECT * FROM exam_drafts WHERE draft_id = :id", {"id": draft_id})
    if not row or (owner and row.get("owner") != owner and not _is_staff(owner)):
        raise_api_error("NOT_FOUND", f"No draft {draft_id}.")
    return dict(row)


def _is_staff(owner: str) -> bool:
    return owner.startswith("admin:") or owner.startswith("operator:")


def list_for(owner: str, *, everyone: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    rows = fetch_all(
        "SELECT draft_id, owner, title, grade, subject, kind, term, status, exam_id, "
        "       jsonb_array_length(items) AS item_count, created_at, updated_at "
        "FROM exam_drafts WHERE (:everyone OR owner = :owner) ORDER BY updated_at DESC LIMIT :limit",
        {"owner": owner, "everyone": everyone, "limit": limit},
    ) or []
    return [dict(r) for r in rows]


def update(draft_id: str, patch: dict[str, Any], *, owner: str = "") -> dict[str, Any]:
    """Title, kind, term, scope, settings, and the item list (order, removal,
    corrections) — whatever the builder changed."""
    from ..infra.db import execute, to_json

    row = get(draft_id, owner)
    if row.get("status") == "frozen":
        from ..errors import raise_api_error

        raise_api_error("VALIDATION_FAILED", "This draft is frozen; copy it to change it.")
    fields: dict[str, Any] = {}
    for key in ("title", "kind", "grade", "subject"):
        if key in patch and patch[key] is not None:
            fields[key] = str(patch[key])
    if "term" in patch:
        fields["term"] = patch["term"]
    for key in ("scope", "settings", "items", "snapshot"):
        if key in patch and patch[key] is not None:
            fields[key] = patch[key]
    if not fields:
        return row
    sets = []
    params: dict[str, Any] = {"id": draft_id}
    for key, value in fields.items():
        if key in ("scope", "settings", "items", "snapshot"):
            sets.append(f"{key} = CAST(:{key} AS jsonb)")
            params[key] = to_json(value)
        else:
            sets.append(f"{key} = :{key}")
            params[key] = value
    execute(f"UPDATE exam_drafts SET {', '.join(sets)}, updated_at = NOW() WHERE draft_id = :id", params)
    return get(draft_id)


def delete(draft_id: str, *, owner: str = "") -> None:
    from ..infra.db import execute

    get(draft_id, owner)
    execute("DELETE FROM exam_drafts WHERE draft_id = :id", {"id": draft_id})


# ── scope ───────────────────────────────────────────────────────────────────

def scope_sub_strands(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The sub-strands this draft covers, as {strand, sub_strand}.

    smart: the term's share of the design by hours (or the whole subject
    for an end-of-year paper); topics: the ones the builder ticked.
    """
    from . import product_orders

    scope = dict(row.get("scope") or {})
    grade, subject = str(row.get("grade") or ""), str(row.get("subject") or "")
    if scope.get("mode") == "topics" and scope.get("sub_strands"):
        wanted = {str(s).strip().lower() for s in scope["sub_strands"]}
        rows = product_orders.sub_strands_for(grade, subject)
        chosen = [r for r in rows if str(r.get("sub_strand") or "").strip().lower() in wanted]
        # A topic the design does not list (a hand-typed one) is kept by name.
        known = {str(r.get("sub_strand") or "").strip().lower() for r in chosen}
        chosen += [{"strand": "", "sub_strand": s} for s in scope["sub_strands"]
                   if str(s).strip().lower() not in known]
        return chosen
    if scope.get("mode") == "topical" and scope.get("sub_strand"):
        rows = product_orders.sub_strands_for(grade, subject)
        hit = next((r for r in rows if str(r.get("sub_strand") or "").lower() == str(scope["sub_strand"]).lower()), None)
        return [hit or {"strand": str(scope.get("strand") or ""), "sub_strand": str(scope["sub_strand"])}]
    term = row.get("term")
    if term:
        return product_orders.term_scope(grade, subject, int(term))
    return product_orders.sub_strands_for(grade, subject)


def bank_summary(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Per sub-strand in scope: how many items the bank holds, how many
    carry a figure, whether a guide exists — what the builder decides on."""
    from . import product_orders
    from .question_dna import question_dna_service

    out = []
    grade, subject = str(row.get("grade") or ""), str(row.get("subject") or "")
    for entry in scope_sub_strands(row):
        ss = str(entry.get("sub_strand") or "")
        try:
            items = question_dna_service.list_questions(grade=grade, subject=subject, sub_strand=ss, limit=1000)
        except Exception:  # noqa: BLE001
            items = []
        usable = [i for i in items if str(i.get("status") or "") not in ("needs_review", "rejected", "superseded")]
        figures = sum(1 for i in usable if (i.get("content") or {}).get("diagram"))
        out.append({"strand": entry.get("strand", ""), "sub_strand": ss, "items": len(usable),
                    "with_figures": figures, "held": len(items) - len(usable),
                    "has_notes": product_orders._has_notes(grade, subject, ss) if ss else False,
                    "writing": _writing(grade, subject, ss)})
    return out


def _writing(grade: str, subject: str, sub_strand: str) -> dict[str, Any] | None:
    """The queue's work on this sub-strand right now — so the row can say
    "writing the guide, then the questions" rather than only 0 items."""
    from ..infra.db import fetch_all

    try:
        rows = fetch_all(
            """
            SELECT job_id, kind, status, created_at,
                   (payload->'steps'->>COALESCE((payload->>'index')::int, 0)) AS step
            FROM jobs
            WHERE REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')
              AND LOWER(subject) = LOWER(:subject) AND LOWER(sub_strand) = LOWER(:ss)
              AND kind IN ('pipeline', 'notes', 'questions', 'diagram')
              AND status IN ('queued', 'running', 'paused')
            ORDER BY created_at ASC LIMIT 5
            """,
            {"grade": grade, "subject": subject, "ss": sub_strand},
        ) or []
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None
    running = next((r for r in rows if r["status"] == "running"), rows[0])
    stage = str(running.get("step") or running.get("kind") or "")
    return {"status": running["status"], "stage": stage, "jobs": len(rows), "job_id": running["job_id"]}


# ── filling it ──────────────────────────────────────────────────────────────

def fill(draft_id: str, *, count: int = 30, diagram_count: int | None = None, seed: str = "",
         format_key: str = "auto", owner: str = "") -> dict[str, Any]:
    """Compose the paper from the bank for the draft's scope and keep the
    result on the draft: the items in order, the sections, the format.

    `diagram_count` is a floor: after the deal, non-figure items in a
    section are swapped for figure items of the same kind the bank has,
    until that many carry a figure or the bank runs out.
    """
    from . import paper_builder, question_rows
    from .question_dna import question_dna_service

    row = get(draft_id, owner)
    grade, subject = str(row.get("grade") or ""), str(row.get("subject") or "")
    scope = scope_sub_strands(row)
    names = [str(s.get("sub_strand") or "") for s in scope if s.get("sub_strand")]
    rows = question_dna_service.list_questions(grade=grade, subject=subject, limit=3000)
    pool = question_rows.flatten_all(rows)
    if names:
        wanted = {n.lower() for n in names}
        pool = [q for q in pool if str((q.get("curriculum") or {}).get("sub_strand") or "").lower() in wanted]
    kind = "topical" if len(names) == 1 else "term"
    paper = paper_builder.compose(
        pool, kind=kind, grade=grade, subject=subject,
        sub_strand=names[0] if len(names) == 1 else "", seed=seed or secrets.token_hex(3),
        title=str(row.get("title") or ""), allow_drafts=True, format_key=format_key, count=count,
        term=row.get("term"))
    if diagram_count:
        _raise_figure_floor(paper, pool, diagram_count)
    snapshot = {**paper.to_dict(),
                "sections": [{**s.to_dict(), "instructions": s.instructions} for s in paper.sections]}
    items = [{"question_id": str(q.get("question_id")), "overrides": {}} for q in paper.items]
    # Keep the builder's corrections for items that stayed on the paper.
    previous = {str(i.get("question_id")): dict(i.get("overrides") or {}) for i in (row.get("items") or [])
                if isinstance(i, dict)}
    for item in items:
        if previous.get(item["question_id"]):
            item["overrides"] = previous[item["question_id"]]
    settings = {**(row.get("settings") or {}), "count": count, "diagram_count": diagram_count,
                "format": format_key, "seed": paper.seed}
    update(draft_id, {"items": items, "snapshot": snapshot, "settings": settings}, owner=owner)
    return {"items": len(items), "shortfall": paper.shortfall, "sections": [s.to_dict() for s in paper.sections],
            "with_figures": sum(1 for q in paper.items if q.get("diagram")),
            "has_drafts": paper.has_drafts, "total_marks": paper.total_marks}


def _raise_figure_floor(paper: Any, pool: list[dict[str, Any]], floor: int) -> None:
    on_paper = {str(q.get("question_id")) for q in paper.items}
    have = sum(1 for q in paper.items if q.get("diagram"))
    if have >= floor:
        return
    spare = [q for q in pool if q.get("diagram") and str(q.get("question_id")) not in on_paper]
    for section in paper.sections:
        kinds = {str(q.get("question_type") or "") for q in section.items}
        for index, question in enumerate(section.items):
            if have >= floor or not spare:
                return
            if question.get("diagram"):
                continue
            swap = next((s for s in spare if str(s.get("question_type") or "") in kinds), None)
            if swap is None:
                continue
            spare.remove(swap)
            section.items[index] = swap
            have += 1


DIFFICULTY = {
    # default_difficulty for the writer, and the words that go with it.
    "easy": (0.35, "Set the batch at the EASIER end for this grade: single-step and two-step items, "
                   "familiar situations, no trick; still nothing below the grade."),
    "medium": (0.55, ""),
    "hard": (0.8, "Set the batch at the HARDER end for this grade: multi-step items, combined operations, "
                  "situations that must be translated before they can be worked, and at least a third "
                  "at analysis or evaluation."),
    "mixed": (0.6, "Spread the batch across the grade's range: a quarter easier, half at the grade, "
                   "a quarter stretching, in that proportion."),
}


def generate(draft_id: str, *, count: int = 30, sub_strand: str = "", difficulty: str = "mixed",
             figures: int | None = None, owner: str = "", queued_by: str = "") -> dict[str, Any]:
    """Queue the questions the scope lacks, one job per sub-strand short
    of its share, the way an order does — or for the one sub-strand named,
    there and then. `fill` again when they land (the bank row says when)."""
    import math

    from . import job_queue, product_orders

    row = get(draft_id, owner)
    grade, subject = str(row.get("grade") or ""), str(row.get("subject") or "")
    scope = scope_sub_strands(row)
    if not scope:
        from ..errors import raise_api_error

        raise_api_error("NOT_FOUND", f"No sub-strands for {subject} at {grade} in this scope.")
    per = max(product_orders.MIN_ITEMS_PER_SUB_STRAND, math.ceil(2 * count / len(scope)))
    if sub_strand:
        scope = [e for e in scope if str(e.get("sub_strand") or "").lower() == sub_strand.lower()] or \
                [{"strand": "", "sub_strand": sub_strand}]
    queued = []
    for entry in scope:
        ss = str(entry.get("sub_strand") or "")
        have = product_orders._items_in_bank(grade, subject, ss)
        if have >= per and not sub_strand:
            continue
        if _writing(grade, subject, ss):
            queued.append({"sub_strand": ss, "already": True})
            continue
        # The chain an order runs: the guide where none exists, the lesson
        # figures where none are drawn, then the questions. A shortcut straight
        # to questions failed with "assets is missing".
        steps = []
        if not product_orders._has_notes(grade, subject, ss):
            steps.append("notes")
        if product_orders._drawn_figures(grade, subject, ss) == 0:
            steps.append("diagram")
        steps.append("questions")
        level, words = DIFFICULTY.get(difficulty, DIFFICULTY["mixed"])
        if figures:
            words = (words + " " if words else "") + \
                    f"Set at least {figures} of the items on a figure, a table or a chart, given as `figure` data."
        job = job_queue.enqueue(
            "pipeline", grade, subject,
            {"steps": steps, "index": 0, "custom_instructions": words, "count": max(per - have, 5),
             "difficulty": level, "scope_strand": str(entry.get("strand") or "")},
            strand=str(entry.get("strand") or ""), sub_strand=ss, queued_by=queued_by or "builder",
        )
        queued.append({"sub_strand": ss, "writing": max(per - have, 5), "job_id": job.job_id, "steps": steps})
    if queued:
        job_queue.start_worker()
    return {"queued": queued, "per_sub_strand": per}


def live(row: dict[str, Any], sub_strand: str) -> dict[str, Any]:
    """What is happening for one sub-strand right now, for a screen that
    keeps the builder company while the worker writes: the job's own
    narration, the figures as each is filed, the questions as they land."""
    from ..infra.db import fetch_all, fetch_one
    from . import diagram_svg, question_rows
    from .question_dna import question_dna_service

    grade, subject = str(row.get("grade") or ""), str(row.get("subject") or "")
    job = fetch_one(
        """
        SELECT job_id, kind, status, created_at, started_at, finished_at, error,
               (payload->'steps'->>COALESCE((payload->>'index')::int, 0)) AS step,
               result->'progress' AS progress
        FROM jobs
        WHERE REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')
          AND LOWER(subject) = LOWER(:subject) AND LOWER(sub_strand) = LOWER(:ss)
          AND kind IN ('pipeline', 'notes', 'questions', 'diagram')
        ORDER BY (status IN ('running', 'queued', 'paused')) DESC, created_at DESC LIMIT 1
        """,
        {"grade": grade, "subject": subject, "ss": sub_strand},
    )
    since = str((job or {}).get("created_at") or "") if job else ""
    narration: list[dict[str, Any]] = []
    previews: list[dict[str, Any]] = []
    if job and isinstance(job.get("progress"), dict):
        narration = list((job["progress"] or {}).get("steps") or [])[-30:]
        previews = list((job["progress"] or {}).get("items") or [])
    elif job and isinstance(job.get("progress"), list):
        narration = list(job["progress"])[-30:]

    figures = []
    try:
        for r in fetch_all(
            """
            SELECT diagram_id, title, alt_text, created_at, svg_markup, storage_url, scene_document
            FROM diagram_registry
            WHERE REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')
              AND LOWER(subject) = LOWER(:subject)
              AND (LOWER(COALESCE(metadata->>'sub_strand', '')) = LOWER(:ss) OR LOWER(title) LIKE LOWER(:like))
            ORDER BY created_at DESC LIMIT 12
            """,
            {"grade": grade, "subject": subject, "ss": sub_strand, "like": f"%{sub_strand}%"},
        ) or []:
            svg = diagram_svg.svg_for(r) if hasattr(diagram_svg, "svg_for") else str(r.get("svg_markup") or "")
            figures.append({"diagram_id": r["diagram_id"], "title": r.get("title") or r.get("alt_text") or "",
                            "created_at": str(r.get("created_at") or ""), "svg": svg[:120_000],
                            "new": bool(since and str(r.get("created_at") or "") >= since)})
    except Exception as exc:  # noqa: BLE001
        logger.debug("No figures for %s: %s", sub_strand, exc)

    questions = []
    try:
        rows = question_dna_service.list_questions(grade=grade, subject=subject, sub_strand=sub_strand,
                                                   order="recent", limit=40)
        for q in question_rows.flatten_all(rows):
            questions.append({**q, "new": bool(since and str(q.get("created_at") or "") >= since)})
    except Exception as exc:  # noqa: BLE001
        logger.debug("No questions for %s: %s", sub_strand, exc)

    return {
        "sub_strand": sub_strand,
        "job": {k: (str(v) if k in ("created_at", "started_at", "finished_at") else v)
                for k, v in (job or {}).items() if k != "progress"} if job else None,
        "narration": narration,
        # The batch as the writer hands it over and as the checks work it —
        # every item with its status, before any of it reaches the bank.
        "writing": previews,
        "figures": figures,
        "questions": questions,
    }


# ── the paper as it stands ──────────────────────────────────────────────────

def paper_for(row: dict[str, Any]) -> Any:
    """The draft as a Paper: the snapshot's sections, the bank's items, the
    builder's corrections laid over them."""
    from . import paper_builder, question_rows
    from .question_dna import question_dna_service

    ids = [str(i.get("question_id")) for i in (row.get("items") or []) if isinstance(i, dict)]
    overrides = {str(i.get("question_id")): dict(i.get("overrides") or {}) for i in (row.get("items") or [])
                 if isinstance(i, dict)}
    questions = []
    for qid in ids:
        try:
            q = question_rows.flatten(question_dna_service.get_question(qid))
        except Exception:  # noqa: BLE001
            continue
        q = {**q, **{k: v for k, v in overrides.get(qid, {}).items() if k in EDITABLE and v is not None}}
        if "max_marks" in overrides.get(qid, {}):
            q["pedagogy"] = {**(q.get("pedagogy") or {}), "max_marks": overrides[qid]["max_marks"]}
        questions.append(q)
    snapshot = dict(row.get("snapshot") or {})
    if not snapshot.get("sections"):
        # No composition yet: one section, the items in order.
        snapshot = {"kind": "topical", "title": row.get("title"), "grade": row.get("grade"),
                    "subject": row.get("subject"),
                    "sections": [{"letter": "", "heading": "", "instructions": "", "question_ids": ids}]}
    snapshot = {**snapshot, "title": row.get("title") or snapshot.get("title") or "",
                "grade": row.get("grade"), "subject": row.get("subject")}
    mast = dict(snapshot.get("masthead") or {})
    kind = str(row.get("kind") or "")
    if KINDS.get(kind):
        mast["kind_line"] = (KINDS[kind] + (f" — TERM {row.get('term')}" if row.get("term") and kind != "topical" else "")).upper()
    elif kind == "custom" and row.get("title"):
        mast["kind_line"] = str(row.get("title")).upper()
    snapshot["masthead"] = mast
    return paper_builder.thaw(snapshot, questions)


def render(row: dict[str, Any], *, answers: bool = False, with_scheme: bool = False,
           answer_sheet: bool = False, settings: Any = None) -> str:
    from . import print_settings, question_paper

    paper = paper_for(row)
    if settings is None:
        settings = print_settings.from_params(row.get("settings") or {})
    return question_paper.render_paper(
        paper, answers=answers, with_scheme=with_scheme, answer_sheet=answer_sheet,
        assets=question_paper.figures_for(paper.items), settings=settings)


def items_detail(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Every item on the draft with its DNA: the bank row, the corrections,
    the engine's working, the checks' verdict, and who wrote it."""
    from . import question_check, question_rows, solution_builder
    from .question_dna import question_dna_service

    out = []
    grade, subject = str(row.get("grade") or ""), str(row.get("subject") or "")
    for entry in (row.get("items") or []):
        if not isinstance(entry, dict):
            continue
        qid = str(entry.get("question_id"))
        try:
            stored = question_dna_service.get_question(qid)
        except Exception:  # noqa: BLE001
            out.append({"question_id": qid, "missing": True})
            continue
        public = question_rows.flatten(stored)
        shown = {**public, **{k: v for k, v in (entry.get("overrides") or {}).items() if k in EDITABLE}}
        worked = solution_builder.build(shown)
        try:
            report = question_check.check([shown], grade=grade, subject=subject,
                                          sub_strand=str((public.get("curriculum") or {}).get("sub_strand") or ""))
            findings = [f.to_dict() for f in report.findings]
        except Exception:  # noqa: BLE001
            findings = []
        out.append({
            "question_id": qid, "status": stored.get("status"), "version": stored.get("version"),
            "question": shown, "overrides": entry.get("overrides") or {},
            "curriculum": stored.get("curriculum_link") or {}, "pedagogy": stored.get("pedagogical_dna") or {},
            "provenance": stored.get("provenance") or {}, "review_audit": stored.get("review_audit") or {},
            "working": {"source": worked.source, "answer": worked.chosen or worked.answer,
                        "steps": [{"text": s.text, "why": s.why} for s in worked.steps[:8]]},
            "findings": findings,
            "rung": question_check.rung_of(shown, grade=grade, subject=subject),
        })
    return out


# ── correcting, reviewing, freezing ─────────────────────────────────────────

def set_override(draft_id: str, question_id: str, fields: dict[str, Any], *, owner: str = "") -> dict[str, Any]:
    """The builder's correction to one item, on the draft. Empty fields clears it."""
    row = get(draft_id, owner)
    items = [dict(i) for i in (row.get("items") or []) if isinstance(i, dict)]
    clean = {k: v for k, v in (fields or {}).items() if k in EDITABLE}
    for item in items:
        if str(item.get("question_id")) == question_id:
            item["overrides"] = {**(item.get("overrides") or {}), **clean} if clean else {}
            break
    else:
        items.append({"question_id": question_id, "overrides": clean})
    return update(draft_id, {"items": items}, owner=owner)


def reorder(draft_id: str, question_ids: list[str], *, owner: str = "") -> dict[str, Any]:
    """The items in the order given, dropped ones gone; the sections keep
    their letters and the items flow into them in that order."""
    row = get(draft_id, owner)
    keep = [str(q) for q in question_ids]
    items = {str(i.get("question_id")): i for i in (row.get("items") or []) if isinstance(i, dict)}
    new_items = [items.get(q) or {"question_id": q, "overrides": {}} for q in keep]
    snapshot = dict(row.get("snapshot") or {})
    sections = [dict(s) for s in (snapshot.get("sections") or []) if isinstance(s, dict)]
    if sections:
        kept = set(keep)
        # Items stay in their section; new ids (added from the bank) join the last.
        placed: set[str] = set()
        for section in sections:
            ids = [q for q in (section.get("question_ids") or []) if q in kept]
            placed |= set(ids)
            section["question_ids"] = ids
        extra = [q for q in keep if q not in placed]
        if extra:
            sections[-1]["question_ids"] = list(sections[-1].get("question_ids") or []) + extra
        # Order within each section follows the order given.
        rank = {q: i for i, q in enumerate(keep)}
        for section in sections:
            section["question_ids"].sort(key=lambda q: rank.get(q, 1e9))
        snapshot["sections"] = sections
    return update(draft_id, {"items": new_items, "snapshot": snapshot}, owner=owner)


def queue_review(draft_id: str, *, provider: str = "", model: str = "", fix: bool = True,
                 owner: str = "", queued_by: str = "") -> dict[str, Any]:
    """A second model over the draft's sub-strands — the items on the paper
    included — before it prints."""
    from . import job_queue

    row = get(draft_id, owner)
    jobs = []
    for entry in scope_sub_strands(row):
        ss = str(entry.get("sub_strand") or "")
        job = job_queue.enqueue(
            "review", str(row.get("grade")), str(row.get("subject")),
            {"sub_strand": ss, "provider": provider, "model": model, "fix": fix, "approve_clean": False},
            sub_strand=ss, queued_by=queued_by or "builder",
        )
        jobs.append({"sub_strand": ss, "job_id": job.job_id})
    if jobs:
        job_queue.start_worker()
    return {"queued": len(jobs), "jobs": jobs}


def freeze(draft_id: str, *, created_by: str, base: str, owner: str = "") -> dict[str, Any]:
    """Write the corrections to the bank, then freeze the paper as an exam
    with a share token — the same row an order or the composer makes."""
    from ..infra.db import execute, to_json
    from ..models import now_iso
    from .grade_order import grade_ordinal, normalize_grade
    from .ids import mint_exam_id
    from .question_dna import question_dna_service

    row = get(draft_id, owner)
    # Corrections into the bank first, so the frozen ids print them.
    renamed: dict[str, str] = {}
    for entry in (row.get("items") or []):
        if not isinstance(entry, dict) or not entry.get("overrides"):
            continue
        qid = str(entry.get("question_id"))
        try:
            stored = question_dna_service.get_question(qid)
            content = {**(stored.get("content") or {}),
                       **{k: v for k, v in entry["overrides"].items() if k in EDITABLE and k != "max_marks"}}
            audit = {**(stored.get("review_audit") or {}), "edited_by": created_by, "edited_at": _now(),
                     "edited_in": draft_id}
            new = question_dna_service.update_question(qid, content, review_audit=audit)
            if str(new.get("question_id")) != qid:
                renamed[qid] = str(new.get("question_id"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not write the correction to %s: %s", qid, exc)
    if renamed:
        items = [{**i, "question_id": renamed.get(str(i.get("question_id")), i.get("question_id"))}
                 for i in (row.get("items") or []) if isinstance(i, dict)]
        snapshot = dict(row.get("snapshot") or {})
        for section in snapshot.get("sections") or []:
            if isinstance(section, dict):
                section["question_ids"] = [renamed.get(q, q) for q in (section.get("question_ids") or [])]
        row = update(draft_id, {"items": items, "snapshot": snapshot}, owner=owner)

    paper = paper_for(row)
    if not paper.items:
        from ..errors import raise_api_error

        raise_api_error("VALIDATION_FAILED", "The draft has no items to freeze.")
    grade_slug = normalize_grade(str(row.get("grade")))
    exam_id = mint_exam_id(grade_slug, str(row.get("subject")))
    token = secrets.token_urlsafe(18)
    paper.exam_id = exam_id
    paper.scheme_url = f"{base}/api/v1/exams/{exam_id}/scheme?token={token}"
    snapshot = {**paper.to_dict(), "frozen_at": now_iso(), "draft_id": draft_id,
                "print_settings": dict(row.get("settings") or {}),
                "questions": [{"question_id": q.get("question_id"), "version": q.get("version", 1),
                               "status": q.get("status", "")} for q in paper.items],
                "sections": [{**s.to_dict(), "instructions": s.instructions} for s in paper.sections]}
    execute(
        """
        INSERT INTO exams (exam_id, title, grade, grade_ordinal, subject, strand, sub_strand, time_allowed,
                           total_marks, instructions, question_ids, snapshot, created_by, share_token)
        VALUES (:exam_id, :title, :grade, :grade_ordinal, :subject, :strand, :sub_strand, :time_allowed,
                :total_marks, CAST(:instructions AS jsonb), CAST(:question_ids AS jsonb),
                CAST(:snapshot AS jsonb), :created_by, :share_token)
        """,
        {"exam_id": exam_id, "title": paper.title or row.get("title") or "", "grade": grade_slug,
         "grade_ordinal": grade_ordinal(grade_slug), "subject": str(row.get("subject")),
         "strand": paper.strand, "sub_strand": paper.sub_strand, "time_allowed": paper.time_allowed,
         "total_marks": int(round(paper.total_marks)), "instructions": to_json(paper.instructions),
         "question_ids": to_json([q.get("question_id") for q in paper.items]),
         "snapshot": to_json(snapshot), "created_by": created_by, "share_token": token},
    )
    execute("UPDATE exam_drafts SET status = 'frozen', exam_id = :eid, updated_at = NOW() WHERE draft_id = :id",
            {"eid": exam_id, "id": draft_id})
    from . import print_settings

    qs = print_settings.query_string(print_settings.from_params(row.get("settings") or {}))
    share = f"{base}/api/v1/exams/{exam_id}/print?token={token}&{qs}"
    share_pdf = f"{base}/api/v1/exams/{exam_id}/print.pdf?token={token}&{qs}"
    return {"exam_id": exam_id, "question_count": len(paper.items), "total_marks": paper.total_marks,
            "render_urls": {"paper": share, "answer_sheet": f"{share}&answer_sheet=true",
                            "booklet": f"{share}&with_scheme=true", "marking_scheme": f"{share}&answers=true",
                            "paper_pdf": share_pdf, "booklet_pdf": f"{share_pdf}&with_scheme=true",
                            "scheme_public": paper.scheme_url}}


def duplicate(draft_id: str, *, owner: str) -> dict[str, Any]:
    row = get(draft_id, owner)
    copy = create(owner=owner, grade=str(row["grade"]), subject=str(row["subject"]), kind=str(row["kind"]),
                  title=(str(row.get("title") or "") + " (copy)").strip(), term=row.get("term"),
                  scope=dict(row.get("scope") or {}), settings=dict(row.get("settings") or {}))
    return update(copy["draft_id"], {"items": row.get("items") or [], "snapshot": row.get("snapshot") or {}},
                  owner=owner)
