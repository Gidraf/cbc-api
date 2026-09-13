"""A question as the renderer reads it, from a row as the bank stores it.

The bank keeps an item in four columns — `curriculum_link`,
`pedagogical_dna`, `content`, `review_audit` — and the renderers read the
API shape, where `question_text` and `options` sit at the top and the marks
sit under `pedagogy`. The printed paper was handed the rows as they came
out of the table, read `question_text` off the top of each, found nothing,
and printed a numbered list of empty stems with ruled space under them.

One flattening, used by everything that prints from the bank.
"""
from __future__ import annotations

from typing import Any


def flatten(row: dict[str, Any]) -> dict[str, Any]:
    """The API shape of a stored row. A row already in that shape is returned
    as it is, so callers need not know which they were given."""
    if not isinstance(row, dict):
        return {}
    content = row.get("content") if isinstance(row.get("content"), dict) else None
    if content is None and "question_text" in row:
        out = dict(row)
        out.setdefault("pedagogy", row.get("pedagogical_dna") or {})
        out.setdefault("curriculum", row.get("curriculum_link") or {})
        return out

    pedagogy = dict(row.get("pedagogy") or row.get("pedagogical_dna") or {})
    curriculum = dict(row.get("curriculum") or row.get("curriculum_link") or {})
    out: dict[str, Any] = {**(content or {})}
    for key in ("question_id", "universal_id", "display_label", "version", "status",
                "dna_id", "created_at", "updated_at", "review_audit", "provenance"):
        if key in row:
            out[key] = row[key]
    out["pedagogy"] = pedagogy
    out["curriculum"] = curriculum
    out.setdefault("question_type", pedagogy.get("question_type", ""))
    provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
    out.setdefault("provenance_citation", provenance.get("source_citations", ""))
    return out


def flatten_all(rows: list[Any]) -> list[dict[str, Any]]:
    return [flatten(r) for r in (rows or []) if isinstance(r, dict)]
