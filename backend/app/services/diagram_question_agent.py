"""Author questions *from* a diagram instead of matching one to a question.

The existing path writes questions first and then looks for a diagram whose
description resembles the stem (:mod:`.diagram_binding`). That can only ever be
a guess, and it cannot ask about a part of a figure, because nothing decided
which part to remove.

This module inverts it. Given a diagram's scene document, it:

1. chooses an occlusion — which named parts to blank — and records what each
   removal costs the learner (:func:`~.diagram_scene.plan_occlusion`);
2. renders the learner's copy and the marking copy from that one plan;
3. asks the model to write questions *about the gaps*, giving it the parts
   catalogue rather than a slice of raw SVG;
4. **derives the answer key from the occlusion, not from the model.**

Step 4 is the point. The model is allowed to phrase a question; it is not
allowed to decide what the hidden part was, because the diagram already knows.
A model that mislabels part B produces a paper whose marking scheme disagrees
with its own figure, and that error is invisible until it has been printed.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from .diagram_scene import (
    apply_occlusion,
    describe_scene_for_prompt,
    occludable_parts,
    plan_occlusion,
)

logger = logging.getLogger("cbc-diagram-question-agent")

# Marks awarded per blanked part when the model does not say otherwise.
DEFAULT_MARKS_PER_SLOT = 1


class OcclusionNotPossible(RuntimeError):
    """The diagram cannot support the requested occlusion."""


def _ground_truth_parts(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Removed facts keyed by their printed marker."""
    return {str(fact["slot"]): fact for fact in (plan.get("removed_facts") or []) if fact.get("slot")}


def build_agent_prompt(
    diagram: dict[str, Any],
    plan: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> str:
    """The instruction given to the model.

    It receives the parts catalogue, what was blanked, and what is still
    visible — everything needed to judge whether a question is answerable from
    the learner's copy alone.
    """
    ctx = context or {}
    scene = diagram.get("scene_document") or {}

    hidden_lines = "\n".join(
        f"  - slot {fact['slot']}: was \"{fact['label']}\""
        + (f" (function: {fact['function']})" if fact.get("function") else "")
        for fact in plan.get("removed_facts") or []
    )
    retained_lines = "\n".join(
        f"  - {part['label']}" + (f" ({part['function']})" if part.get("function") else "")
        for part in plan.get("retained_parts") or []
    ) or "  (nothing else is labelled)"

    return (
        "You are writing exam questions about a diagram a learner is looking at.\n\n"
        f"Grade: {ctx.get('grade', '')}   Subject: {ctx.get('subject', '')}\n"
        f"Strand: {ctx.get('strand', '')} / {ctx.get('sub_strand', '')}\n\n"
        "=== THE DIAGRAM ===\n"
        f"{describe_scene_for_prompt(scene)}\n\n"
        "=== WHAT THE LEARNER CANNOT SEE ===\n"
        "These labels have been removed and replaced with a lettered box on the paper:\n"
        f"{hidden_lines}\n\n"
        "=== WHAT THE LEARNER CAN STILL SEE ===\n"
        f"{retained_lines}\n\n"
        "=== RULES ===\n"
        "1. Every question must be answerable from the visible diagram plus grade-level knowledge.\n"
        "2. Refer to a blanked part ONLY by its letter, e.g. \"the part labelled A\".\n"
        "   Never name a hidden part in the question text — that gives the answer away.\n"
        "3. Do not ask about anything absent from the parts catalogue above.\n"
        "4. Ask for function or consequence, not only recall, where the grade allows:\n"
        "   \"state the function of the part labelled B\" is worth more than \"name B\".\n"
        "5. Return strict JSON only.\n\n"
        "=== RETURN ===\n"
        "{\n"
        '  "questions": [\n'
        "    {\n"
        '      "question_text": "<stem referring to slots by letter>",\n'
        '      "slots_tested": ["A", "B"],\n'
        '      "structured_parts": [\n'
        '        {"part_id": "(a)", "sub_question": "Name the part labelled A.", "marks": 1},\n'
        '        {"part_id": "(b)", "sub_question": "State the function of the part labelled A.", "marks": 2}\n'
        "      ],\n"
        '      "bloom_level": "Recall | Understanding | Application | Analysis",\n'
        '      "micro_concept": "<what this tests>"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )


def _answer_for(fact: dict[str, Any], sub_question: str) -> str:
    """The model answer for one sub-question, taken from the diagram.

    Whether the learner was asked to *name* the part or to explain what it
    *does* decides which recorded fact is the answer.
    """
    asks_function = any(
        word in sub_question.lower()
        for word in ("function", "role", "purpose", "what does", "why is", "use of")
    )
    if asks_function and fact.get("function"):
        return str(fact["function"])
    return str(fact.get("label") or "")


def _repair_question(
    raw: dict[str, Any],
    truth: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Check one generated question against the diagram, fixing what it can.

    Answers are overwritten from ground truth rather than trusted. A question
    that references a slot the diagram never blanked is dropped — there is no
    correct answer to give it.
    """
    notes: list[str] = []

    slots = [str(s).strip().upper() for s in (raw.get("slots_tested") or []) if str(s).strip()]
    unknown = [s for s in slots if s not in truth]
    if unknown:
        notes.append(f"references unknown slot(s) {unknown}")
        return None, notes

    # A stem that names a hidden part hands the learner the answer.
    stem = str(raw.get("question_text") or "")
    for slot in slots:
        label = str(truth[slot].get("label") or "").strip()
        if label and label.lower() in stem.lower():
            notes.append(f"stem revealed the hidden label '{label}' for slot {slot}")
            return None, notes

    parts: list[dict[str, Any]] = []
    for index, part in enumerate(raw.get("structured_parts") or []):
        if not isinstance(part, dict):
            continue
        sub_question = str(part.get("sub_question") or "").strip()
        if not sub_question:
            continue

        # Which slot this sub-question is about: the one it names, else the
        # single slot the question tests.
        mentioned = [s for s in slots if f" {s}" in sub_question.upper() or f"{s}." in sub_question.upper()]
        slot = mentioned[0] if mentioned else (slots[0] if len(slots) == 1 else None)
        if slot is None:
            notes.append(f"sub-question {index + 1} does not identify which slot it tests")
            continue

        fact = truth[slot]
        supplied = str(part.get("model_answer") or "").strip()
        derived = _answer_for(fact, sub_question)
        if supplied and derived and supplied.lower() != derived.lower():
            notes.append(
                f"sub-question {index + 1}: model answered '{supplied}', diagram says '{derived}' — used the diagram"
            )

        parts.append({
            "part_id": str(part.get("part_id") or f"({chr(97 + index)})"),
            "sub_question": sub_question,
            "marks": int(part.get("marks") or DEFAULT_MARKS_PER_SLOT),
            "model_answer": derived,
            "slot": slot,
            "part_ref": fact["part_id"],
        })

    if not parts:
        notes.append("no sub-question could be tied to a blanked part")
        return None, notes

    raw["structured_parts"] = parts
    raw["slots_tested"] = slots
    raw["question_type"] = "diagram_based"
    raw["max_marks"] = sum(p["marks"] for p in parts)
    raw["diagram_part_ids"] = [truth[s]["part_id"] for s in slots]
    return raw, notes


def author_questions_from_diagram(
    diagram: dict[str, Any],
    *,
    generate: Callable[[str], dict[str, Any]],
    mode: str = "label_blanks",
    max_blanks: int = 3,
    part_ids: list[str] | None = None,
    region_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce diagram-grounded questions, the learner's figure and the marking figure.

    ``generate`` takes the prompt and returns parsed JSON, so the agent can be
    exercised without a provider.
    """
    scene = diagram.get("scene_document") or {}
    if not scene.get("parts"):
        raise OcclusionNotPossible("diagram has no scene document; nothing is addressable")

    if not occludable_parts(scene, mode):
        raise OcclusionNotPossible(
            f"no part of '{diagram.get('title') or diagram.get('diagram_id')}' can be blanked in mode '{mode}'"
        )

    plan = plan_occlusion(scene, mode=mode, max_blanks=max_blanks, part_ids=part_ids)
    if not plan["answerable"]:
        raise OcclusionNotPossible(
            "the occlusion leaves nothing for the learner to reason from; "
            "reduce max_blanks or choose a different mode"
        )

    rendered = apply_occlusion(diagram, plan, region_id=region_id)
    truth = _ground_truth_parts(plan)

    prompt = build_agent_prompt(diagram, plan, context)
    try:
        response = generate(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Diagram question agent generation failed: %s", exc)
        raise

    raw_questions = response.get("questions") if isinstance(response, dict) else None
    if not isinstance(raw_questions, list):
        raw_questions = []

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    # Carried on every accepted question so resolve_binding produces an exact
    # "authored" binding instead of falling through to similarity matching.
    occlusion_ref = {
        "mode": plan["mode"],
        "hidden_part_ids": plan["hidden_part_ids"],
        "slots": plan["slots"],
    }

    for raw in raw_questions:
        if not isinstance(raw, dict):
            continue
        repaired, notes = _repair_question(dict(raw), truth)
        if repaired is None:
            rejected.append({"question_text": raw.get("question_text", ""), "reasons": notes})
            logger.info("Rejected diagram question: %s", "; ".join(notes))
            continue
        repaired["diagram_ref"] = str(diagram.get("asset_id") or diagram.get("diagram_id") or "")
        repaired["diagram_occlusion"] = occlusion_ref
        if region_id:
            repaired["diagram_region_id"] = region_id
        if notes:
            repaired["answer_corrections"] = notes
        accepted.append(repaired)

    return {
        "questions": accepted,
        "rejected": rejected,
        "occlusion": occlusion_ref,
        "removed_facts": plan["removed_facts"],
        "paper_svg": rendered["paper_svg"],
        "answer_svg": rendered["answer_svg"],
        "prompt": prompt,
    }
