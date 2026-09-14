"""An order: one request in, a printed product out.

"Give me a Grade 7 Mathematics mid-term 1 assessment" is one sentence,
and until now it was eleven steps in the console: find the sub-strands
Term 1 covers, run notes on each, run the diagram station on each, run
fifty questions on each, compose, freeze, print. Each step was a button
and a wait, and the person clicking them was the product's bottleneck.

An order does the steps. It works out the scope (which sub-strands a term
covers, or the one sub-strand of a topical test), finds what already
exists (a guide filed, figures drawn, enough items in the bank) and runs
only what is missing, in order, then composes and freezes the paper and
hands back the print links. Under the queue the provider answers the
prompts; under an agent task the agent does. The steps are the stations'
own — an order adds no new way of producing anything, only the sequence.

Term scope: the designs do not say which term teaches what. Schools take
the strands in the design's order across three terms, weighted by the
hours each sub-strand is given, so that is the split used here — and an
order can be handed an explicit list of sub-strands instead.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("cbc-product-orders")

# Items in the bank per sub-strand before a paper is composed from it. A
# 30-item paper over three sub-strands needs ten from each and room to
# choose; twice the share, floor twenty.
MIN_ITEMS_PER_SUB_STRAND = 20


@dataclass
class Progress:
    steps: list[dict[str, Any]] = field(default_factory=list)

    def note(self, what: str, detail: str = "", status: str = "ok") -> None:
        self.steps.append({"what": what, "detail": detail, "status": status})
        logger.info("Order: %s — %s", what, detail)


def sub_strands_for(grade: str, subject: str) -> list[dict[str, Any]]:
    """The design's sub-strands, in the design's order, with their hours."""
    from ..infra.db import fetch_all
    from ..services.grade_sql import clause as grade_clause
    from . import time_allocation

    rows = fetch_all(
        f"""
        SELECT strand_id, strand_name, sub_strand_id, sub_strand_name, allocated_hours
        FROM curriculum_substrands
        WHERE {grade_clause("grade", "grade")} AND LOWER(subject) = LOWER(:subject)
        ORDER BY id
        """,
        {"grade": grade, "subject": subject},
    )
    out = []
    for row in rows:
        allocation = time_allocation.parse(row.get("allocated_hours"), grade)
        out.append({"strand": row["strand_name"], "strand_id": row.get("strand_id") or "",
                    "sub_strand": row["sub_strand_name"], "sub_strand_id": row.get("sub_strand_id") or "",
                    "hours": float(allocation.count or 0) if allocation.known else 0.0})
    return out


def term_scope(grade: str, subject: str, term: int, *, terms: int = 3) -> list[dict[str, Any]]:
    """The sub-strands a term covers: the design's order, split by hours."""
    rows = sub_strands_for(grade, subject)
    if not rows:
        return []
    weights = [r["hours"] or 1.0 for r in rows]
    total = sum(weights)
    per_term = total / terms
    out, cumulative = [], 0.0
    for row, weight in zip(rows, weights):
        which = min(terms, int(cumulative // per_term) + 1) if per_term else 1
        cumulative += weight
        if which == term:
            out.append(row)
    return out


def scope_for(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Which sub-strands this order covers."""
    grade, subject = str(params.get("grade") or ""), str(params.get("subject") or "")
    named = params.get("sub_strands")
    rows = sub_strands_for(grade, subject)
    if isinstance(named, list) and named:
        wanted = {str(n).strip().lower() for n in named}
        return [r for r in rows if r["sub_strand"].strip().lower() in wanted]
    kind = str(params.get("kind") or "term")
    if kind == "topical":
        target = str(params.get("sub_strand") or "").strip().lower()
        return [r for r in rows if r["sub_strand"].strip().lower() == target]
    if kind == "strand":
        target = str(params.get("strand") or "").strip().lower()
        return [r for r in rows if r["strand"].strip().lower() == target]
    return term_scope(grade, subject, int(params.get("term") or 1))


def _has_notes(grade: str, subject: str, sub_strand: str) -> bool:
    from . import artifact_registry

    try:
        return bool(artifact_registry.search(grade=grade, subject=subject, sub_strand=sub_strand,
                                             kind="notes", limit=1))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not look for notes on %s: %s", sub_strand, exc)
        return False


def _drawn_figures(grade: str, subject: str, sub_strand: str) -> int:
    try:
        from . import lesson_assets

        return sum(1 for a in lesson_assets.collect(grade, subject, sub_strand)
                   if a.get("kind") == "diagram" and (a.get("svg") or a.get("url")))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not count figures on %s: %s", sub_strand, exc)
        return 0


def _items_in_bank(grade: str, subject: str, sub_strand: str) -> int:
    try:
        from .question_dna import question_dna_service

        return question_dna_service.count_questions(grade=grade, subject=subject, sub_strand=sub_strand)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not count items on %s: %s", sub_strand, exc)
        return 0


def run(params: dict[str, Any], run_station: Callable[[str, dict[str, Any]], Any],
        freeze: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """The whole order. `run_station(kind, params)` runs one station the
    way the queue does; `freeze(params)` composes and freezes the paper."""
    grade, subject = str(params.get("grade") or ""), str(params.get("subject") or "")
    count = int(params.get("count") or 30)
    progress = Progress()
    scope = scope_for(params)
    if not scope:
        raise ValueError(f"No sub-strands found for {subject} at {grade} in that scope. "
                         f"Ingest the design first, or name the sub-strands.")
    progress.note("Scope", ", ".join(r["sub_strand"] for r in scope))
    per_sub_strand = max(MIN_ITEMS_PER_SUB_STRAND, math.ceil(2 * count / len(scope)))
    want_figures = bool(params.get("diagrams", True))

    for row in scope:
        base = {"grade": grade, "subject": subject, "strand": row["strand"], "sub_strand": row["sub_strand"],
                "custom_instructions": str(params.get("custom_instructions") or "")}
        if not _has_notes(grade, subject, row["sub_strand"]):
            progress.note("Notes", f"{row['sub_strand']}: writing the guide")
            run_station("notes", dict(base))
        else:
            progress.note("Notes", f"{row['sub_strand']}: already filed", "skip")
        if want_figures:
            if _drawn_figures(grade, subject, row["sub_strand"]) == 0:
                progress.note("Figures", f"{row['sub_strand']}: planning and drawing")
                try:
                    run_station("diagram", dict(base))
                except Exception as exc:  # noqa: BLE001
                    progress.note("Figures", f"{row['sub_strand']}: {exc}", "warn")
            else:
                progress.note("Figures", f"{row['sub_strand']}: already drawn", "skip")
        have = _items_in_bank(grade, subject, row["sub_strand"])
        if have < per_sub_strand:
            missing = per_sub_strand - have
            progress.note("Questions", f"{row['sub_strand']}: {have} in the bank, writing {missing}")
            run_station("questions", {**base, "count": missing})
        else:
            progress.note("Questions", f"{row['sub_strand']}: {have} in the bank", "skip")

    paper = freeze({
        "grade": grade, "subject": subject, "kind": str(params.get("kind") or "term"),
        "strand": str(params.get("strand") or (scope[0]["strand"] if len({r['strand'] for r in scope}) == 1 else "")),
        "sub_strand": str(params.get("sub_strand") or ""),
        "sub_strands": [r["sub_strand"] for r in scope],
        "count": count, "format": str(params.get("format") or "auto"),
        "term": params.get("term"), "seed": str(params.get("seed") or ""),
        "drafts": True, "title": str(params.get("title") or ""),
    })
    progress.note("Paper", f"{paper.get('exam_id')}: {paper.get('question_count')} questions, "
                           f"{paper.get('total_marks')} marks")
    return {"paper": paper, "progress": progress.steps,
            "scope": [r["sub_strand"] for r in scope],
            "render_urls": paper.get("render_urls") or {}}
