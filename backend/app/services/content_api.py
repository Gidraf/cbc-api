"""The content API's view of the bank: questions as a developer receives them.

One public shape, kept apart from the stored one so the bank can change
without breaking anyone's app: the question, its options, the answer, the
marking scheme, the worked answer, the marks, where it sits in the
curriculum, and its figure as SVG — as a learner sees it, gaps left blank.
Items a reviewer turned away (rejected, needs review, superseded) are never
served.
"""
from __future__ import annotations

from typing import Any

HIDDEN = ("needs_review", "rejected", "superseded")
MAX_LIMIT = 50


def _where(f: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    from .grade_order import normalize_grade

    cond = ["status <> ALL(:hidden)", "superseded_by IS NULL"]
    params: dict[str, Any] = {"hidden": list(HIDDEN)}
    if f.get("grade"):
        cond.append("curriculum_link->>'grade' = :grade")
        params["grade"] = normalize_grade(str(f["grade"]))
    for key, col in (("subject", "subject"), ("strand", "strand"), ("sub_strand", "sub_strand")):
        if f.get(key):
            cond.append(f"LOWER(curriculum_link->>'{col}') = LOWER(:{key})")
            params[key] = str(f[key]).strip()
    if f.get("question_type"):
        cond.append("content->>'question_type' = :qtype")
        params["qtype"] = str(f["question_type"])
    figures = str(f.get("figures") or "any")
    if figures == "only":
        cond.append("COALESCE(content->'diagram'->>'diagram_id', '') <> ''")
    elif figures == "none":
        cond.append("COALESCE(content->'diagram'->>'diagram_id', '') = ''")
    return " AND ".join(cond), params


def search(filters: dict[str, Any], *, limit: int = 20, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    """Stored rows matching the filters, in curriculum order, and how many match."""
    from ..infra.db import fetch_all, fetch_one

    where, params = _where(filters)
    limit = max(1, min(int(limit), MAX_LIMIT))
    rows = fetch_all(f"""SELECT * FROM question_dna WHERE {where}
                         ORDER BY grade_ordinal NULLS LAST, curriculum_link->>'subject', curriculum_link->>'strand',
                                  curriculum_link->>'sub_strand', question_id
                         LIMIT :limit OFFSET :offset""", {**params, "limit": limit, "offset": max(0, int(offset))}) or []
    total = fetch_one(f"SELECT COUNT(*) AS n FROM question_dna WHERE {where}", params) or {}
    return rows, int(total.get("n") or 0)


def one(question_id: str) -> dict[str, Any] | None:
    from ..infra.db import fetch_one

    row = fetch_one("SELECT * FROM question_dna WHERE question_id = :q AND status <> ALL(:hidden)",
                    {"q": question_id, "hidden": list(HIDDEN)})
    return row


def curriculum() -> list[dict[str, Any]]:
    """Every grade, subject, strand and sub-strand with questions to serve."""
    from ..infra.db import fetch_all

    rows = fetch_all("""SELECT curriculum_link->>'grade' AS grade, curriculum_link->>'subject' AS subject,
                               curriculum_link->>'strand' AS strand, curriculum_link->>'sub_strand' AS sub_strand,
                               MIN(grade_ordinal) AS ordinal, COUNT(*) AS questions,
                               COUNT(*) FILTER (WHERE COALESCE(content->'diagram'->>'diagram_id', '') <> '') AS with_figures
                        FROM question_dna WHERE status <> ALL(:hidden) AND superseded_by IS NULL
                        GROUP BY 1, 2, 3, 4 ORDER BY MIN(grade_ordinal) NULLS LAST, 2, 3, 4""",
                     {"hidden": list(HIDDEN)}) or []
    return [{k: r[k] for k in ("grade", "subject", "strand", "sub_strand", "questions", "with_figures")} for r in rows]


def public(row: dict[str, Any], *, figures: bool = True) -> dict[str, Any]:
    """The shape a developer receives."""
    from . import question_rows

    q = question_rows.flatten(row)
    link = q.get("curriculum") or {}
    ped = q.get("pedagogy") or {}
    out: dict[str, Any] = {
        "id": q.get("question_id"),
        "grade": link.get("grade"), "subject": link.get("subject"), "strand": link.get("strand"),
        "sub_strand": link.get("sub_strand"), "learning_outcome": link.get("slo_id") or "",
        "type": q.get("question_type") or ped.get("question_type") or "",
        "context": q.get("stimulus_context") or "",
        "question": q.get("question_text") or "",
        "parts": q.get("structured_parts") or [],
        "options": [{"id": o.get("id"), "text": o.get("text")} for o in (q.get("options") or []) if isinstance(o, dict)],
        "answer": q.get("correct_answer") or "",
        "correct_option": next((o.get("id") for o in (q.get("options") or []) if isinstance(o, dict) and o.get("is_correct")), None),
        "worked_answer": q.get("model_answer") or "",
        "marking_scheme": q.get("marking_scheme") or "",
        "marks": ped.get("max_marks") or 1,
        "difficulty": ped.get("difficulty_index"),
        "bloom_level": ped.get("bloom_level") or "",
        "estimated_minutes": ped.get("estimated_time_mins"),
        "has_figure": False,
        "figure": None,
        "math_format": "LaTeX between $…$",
    }
    binding = q.get("diagram")
    if isinstance(binding, dict) and (binding.get("diagram_id") or binding.get("svg_markup")):
        out["has_figure"] = True
        out["figure"] = {"title": binding.get("diagram_title") or "", "svg": None}
        if figures:
            try:
                from .question_paper import figure_markup, figures_for

                out["figure"]["svg"] = figure_markup(q, figures_for([q]), answers=False) or None
            except Exception:  # noqa: BLE001
                out["figure"]["svg"] = None
    return out
