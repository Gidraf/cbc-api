"""Turn a sub-strand's programmable diagrams into questions that test them.

A diagram-based question written from a *description* of a figure can only ask
about it in general — "study the diagram and answer" — because the writer never
knew which parts the figure actually has. The result is a question that reads
fine and cannot be marked against the picture beside it.

These are written from the figure itself. Parts are blanked, the learner's copy
shows lettered markers where they were, and the marking scheme is taken from the
diagram rather than from the model, so the paper and its answers cannot disagree.

One figure yields several questions: a different occlusion is a different
question, which is what makes the diagram library worth building once.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from .diagram_question_agent import OcclusionNotPossible, author_questions_from_diagram
from .diagram_scene import occludable_parts

logger = logging.getLogger("cbc-occlusion-questions")

# Blanking one part asks recall; blanking several asks the learner to read the
# whole figure. Both are worth having, so vary it rather than fixing it.
DEFAULT_PLANS: tuple[tuple[str, int], ...] = (
    ("label_blanks", 3),
    ("label_blanks", 1),
    ("missing_parameters", 2),
)


def programmable_diagrams(diagrams: list[Any]) -> list[dict[str, Any]]:
    """The diagrams that can carry an occlusion question.

    A diagram with no scene document is a picture: it can be shown, but no part
    of it can be addressed, so nothing can be blanked.
    """
    usable: list[dict[str, Any]] = []
    for diagram in diagrams or []:
        if not isinstance(diagram, dict):
            continue
        scene = diagram.get("scene_document") or {}
        if not isinstance(scene, dict) or not scene.get("parts"):
            continue
        if not occludable_parts(scene, "label_blanks") and not occludable_parts(scene, "hide_parts"):
            continue
        usable.append(diagram)
    return usable


def author_for_substrand(
    diagrams: list[Any],
    *,
    generate: Callable[[str], dict[str, Any]],
    context: dict[str, Any] | None = None,
    plans: tuple[tuple[str, int], ...] = DEFAULT_PLANS,
    max_per_diagram: int = 2,
) -> dict[str, Any]:
    """Author occlusion questions across every programmable diagram available.

    A diagram that cannot support an occlusion is skipped with its reason, not
    failed: a sub-strand should still get questions from the figures that do
    work.
    """
    usable = programmable_diagrams(diagrams)
    questions: list[dict[str, Any]] = []
    renders: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for diagram in usable:
        produced = 0
        for mode, blanks in plans:
            if produced >= max_per_diagram:
                break
            try:
                result = author_questions_from_diagram(
                    diagram, generate=generate, mode=mode, max_blanks=blanks, context=context,
                )
            except OcclusionNotPossible as exc:
                skipped.append({
                    "diagram": diagram.get("title") or diagram.get("diagram_id"),
                    "mode": mode, "reason": str(exc),
                })
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("Occlusion question failed for %s (%s): %s",
                               diagram.get("diagram_id"), mode, exc)
                skipped.append({
                    "diagram": diagram.get("title") or diagram.get("diagram_id"),
                    "mode": mode, "reason": str(exc)[:200],
                })
                continue

            for question in result["questions"]:
                question["question_type"] = "diagram_based"
                question["occlusion_mode"] = mode
                questions.append(question)
                produced += 1

            if result["questions"]:
                renders.append({
                    "diagram_id": diagram.get("diagram_id") or diagram.get("asset_id"),
                    "title": diagram.get("title", ""),
                    "mode": mode,
                    "paper_svg": result["paper_svg"],
                    "answer_svg": result["answer_svg"],
                    "removed_facts": result["removed_facts"],
                })

    return {
        "questions": questions,
        "renders": renders,
        "skipped": skipped,
        "diagrams_available": len(diagrams or []),
        "diagrams_programmable": len(usable),
        "summary": (
            f"{len(questions)} question(s) authored from {len(usable)} programmable "
            f"diagram(s) of {len(diagrams or [])} available."
        ),
    }


def filed_for_sub_strand(grade: str, subject: str, sub_strand: str,
                         titles: list[str] | None = None) -> list[dict[str, Any]]:
    """Every drawn figure the registry holds for a sub-strand, WITH its scene.

    The questions station read the bundle's `diagrams` — the planner's
    briefs, which carry no scene document — so nothing was programmable and
    no occlusion question was ever authored. The drawings themselves are in
    the registry, instrumented, with their parts. Never raises.
    """
    try:
        from ..infra.db import fetch_all
        from . import diagram_svg
        from .grade_sql import clause as grade_clause

        rows = fetch_all(
            f"""
            SELECT diagram_id, title, svg_markup, scene_document, storage_url, alt_text, metadata
            FROM diagram_registry
            WHERE {grade_clause("grade", "grade")}
              AND LOWER(subject) = LOWER(:subject)
              AND (LOWER(COALESCE(metadata->>'sub_strand', '')) = LOWER(:sub_strand)
                   OR LOWER(title) = ANY(:titles))
            ORDER BY created_at DESC
            LIMIT 40
            """,
            {"grade": grade, "subject": subject, "sub_strand": sub_strand,
             # Rows drawn before the sub-strand was stamped on them are found
             # by the title the bundle knows them under.
             "titles": [str(t).strip().lower() for t in (titles or []) if str(t).strip()]},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read filed figures for %s/%s: %s", grade, sub_strand, exc)
        return []
    out: list[dict[str, Any]] = []
    for row in rows or []:
        full = diagram_svg.with_svg(row)
        out.append({
            "asset_id": row.get("diagram_id"), "diagram_id": row.get("diagram_id"),
            "title": row.get("title") or "", "diagram_title": row.get("title") or "",
            "svg_markup": full.get("svg_markup") or "", "scene_document": row.get("scene_document") or {},
            "storage_url": row.get("storage_url") or "", "alt_text": row.get("alt_text") or "",
        })
    return out


def merge_figures(bundle: list[Any], filed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The bundle's figures with the registry's scene documents attached,
    plus any drawing the registry has that the bundle does not."""
    by_id = {str(d.get("diagram_id") or d.get("asset_id") or ""): d for d in filed}
    by_title = {str(d.get("title") or "").strip().lower(): d for d in filed if d.get("title")}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in bundle or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("diagram_id") or item.get("asset_id") or "")
        match = by_id.get(key) or by_title.get(str(item.get("title") or item.get("diagram_title") or "").strip().lower())
        merged = dict(item)
        if match:
            for field in ("scene_document", "svg_markup", "storage_url", "diagram_id"):
                if not merged.get(field) and match.get(field):
                    merged[field] = match[field]
            seen.add(str(match.get("diagram_id") or ""))
        out.append(merged)
    for figure in filed:
        if str(figure.get("diagram_id") or "") not in seen:
            out.append(figure)
    return out
