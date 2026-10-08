"""How much of a subject the bank covers, sub-strand by sub-strand.

The night planner decides what to write next from this: which sub-strands
are furthest from their share of the target, which have no teacher's guide
yet (questions need one), and which were reviewed longest ago. Reading the
whole bank to find out was the slow way — the question list timed out at
900 items — so the counts come from one grouped query.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("cbc-coverage")

# Items that do not count towards a sub-strand's share: held for a person,
# turned down, or replaced by a newer version.
_NOT_USABLE = ("needs_review", "rejected", "superseded")


def _counts(grade: str, subject: str) -> dict[str, dict[str, Any]]:
    from ..infra.db import fetch_all
    from .grade_sql import clause as grade_clause

    rows = fetch_all(
        f"""
        SELECT LOWER(TRIM(curriculum_link->>'sub_strand')) AS sub_strand,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status NOT IN ('needs_review', 'rejected', 'superseded')) AS usable,
               COUNT(*) FILTER (WHERE status = 'approved') AS approved,
               COUNT(*) FILTER (WHERE status NOT IN ('needs_review', 'rejected', 'superseded')
                                AND content->'diagram' IS NOT NULL
                                AND jsonb_typeof(content->'diagram') = 'object') AS with_figures,
               MAX(review_audit->>'reviewed_at') AS last_reviewed,
               MAX(created_at) AS last_written
        FROM question_dna
        WHERE {grade_clause("curriculum_link->>'grade'", "grade")}
          AND LOWER(curriculum_link->>'subject') = LOWER(:subject)
        GROUP BY 1
        """,
        {"grade": grade, "subject": subject},
    ) or []
    return {str(r.get("sub_strand") or ""): r for r in rows}


def for_subject(grade: str, subject: str, *, with_notes: bool = True) -> dict[str, Any]:
    """Every sub-strand the design lists, with what the bank holds for it.

    `with_notes=False` skips the per-sub-strand guide lookup, for a caller
    that only needs to count sub-strands (the planner sizing a target).
    """
    from . import product_orders

    design = product_orders.sub_strands_for(grade, subject)
    counts = _counts(grade, subject)
    out: list[dict[str, Any]] = []
    for row in design:
        name = str(row.get("sub_strand") or "")
        c = counts.get(name.strip().lower(), {})
        last_written = c.get("last_written")
        out.append({
            "strand": row.get("strand") or "",
            "sub_strand": name,
            "hours": row.get("hours") or 0,
            "questions": int(c.get("usable") or 0),
            "approved": int(c.get("approved") or 0),
            "held": int(c.get("total") or 0) - int(c.get("usable") or 0),
            "with_figures": int(c.get("with_figures") or 0),
            "last_reviewed": c.get("last_reviewed") or None,
            "last_written": last_written.isoformat() if hasattr(last_written, "isoformat") else last_written,
            "has_notes": product_orders._has_notes(grade, subject, name) if (with_notes and name) else None,
        })
    return {
        "grade": grade, "subject": subject, "sub_strands": out,
        "totals": {
            "sub_strands": len(out),
            "questions": sum(r["questions"] for r in out),
            "with_figures": sum(r["with_figures"] for r in out),
            "with_notes": sum(1 for r in out if r["has_notes"]) if with_notes else None,
            "never_reviewed": sum(1 for r in out if r["questions"] and not r["last_reviewed"]),
        },
    }
