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
