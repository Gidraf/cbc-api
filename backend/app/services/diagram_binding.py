"""Bind questions to the diagrams they actually test.

The previous matcher counted words longer than three characters shared between a
diagram title and a question stem, so "water", "system" or "process" was enough
to attach an unrelated visual. Binding now reports a method and a confidence, and
declines to bind rather than attaching a weak match — an unbound diagram question
is caught by validation, whereas a wrongly bound one prints and looks fine.
"""
from __future__ import annotations

import logging
from typing import Any

from ..question_models import DiagramBinding
from .dna_scoring import similarity, tokens

logger = logging.getLogger("cbc-diagram-binding")

# Below this, a semantic match is not trustworthy enough to print.
MIN_SEMANTIC_CONFIDENCE = 0.28


def _diagram_identity(diagram: dict[str, Any]) -> str:
    return str(diagram.get("asset_id") or diagram.get("diagram_id") or "").strip()


def _diagram_text(diagram: dict[str, Any]) -> str:
    """Everything about a diagram that describes what it depicts."""
    scene = diagram.get("scene_document") or {}
    part_labels = ""
    if isinstance(scene, dict):
        part_labels = " ".join(
            str(p.get("label") or "") for p in (scene.get("parts") or []) if isinstance(p, dict)
        )

    accessibility = diagram.get("accessibility") or {}
    return " ".join(
        str(v)
        for v in [
            diagram.get("title") or diagram.get("diagram_title"),
            diagram.get("micro_concept"),
            diagram.get("concept") or diagram.get("pedagogical_purpose"),
            diagram.get("description") or diagram.get("vivid_prompt"),
            accessibility.get("alt_text") or diagram.get("alt_text"),
            part_labels,
        ]
        if v
    )


def _build(
    diagram: dict[str, Any],
    method: str,
    confidence: float,
    requested_parts: list[str] | None = None,
    region_id: str | None = None,
) -> DiagramBinding:
    """Construct the binding, resolving requested part IDs against the scene document."""
    scene = diagram.get("scene_document") or {}
    known_parts: set[str] = set()
    label_layers: list[str] = []

    if isinstance(scene, dict):
        known_parts = {
            str(p.get("part_id")) for p in (scene.get("parts") or [])
            if isinstance(p, dict) and p.get("part_id")
        }
        # Layers the question should hide so the learner labels them itself.
        label_layers = [
            str(layer.get("layer_id"))
            for layer in (scene.get("layers") or [])
            if isinstance(layer, dict) and layer.get("removable") and layer.get("layer_id")
        ]

    resolved_parts = [p for p in (requested_parts or []) if p in known_parts] if known_parts else []

    return DiagramBinding(
        diagram_id=_diagram_identity(diagram) or "diag_unknown",
        diagram_title=str(diagram.get("title") or diagram.get("diagram_title") or "").strip(),
        region_id=region_id,
        part_ids=resolved_parts,
        hide_layers=label_layers if resolved_parts else [],
        storage_url=str(diagram.get("storage_url") or ""),
        binding_method=method,  # type: ignore[arg-type]
        binding_confidence=round(confidence, 4),
    )


def resolve_binding(
    raw_question: dict[str, Any],
    question_type: str,
    diagrams: list[dict[str, Any]],
    anchored_diagram: dict[str, Any] | None = None,
) -> DiagramBinding | None:
    """Pick the diagram a question tests, or return ``None``.

    Resolution order: an operator-chosen anchor, then an explicit ``diagram_ref``
    naming a known asset, then semantic similarity above a confidence floor.
    """
    requested_parts = [str(p) for p in (raw_question.get("diagram_part_ids") or []) if p]
    region_id = str(raw_question.get("diagram_region_id") or "").strip() or None

    if anchored_diagram:
        return _build(anchored_diagram, "anchored", 1.0, requested_parts, region_id)

    if not diagrams:
        return None

    diagram_ref = str(raw_question.get("diagram_ref") or "").strip().lower()
    if diagram_ref:
        for diagram in diagrams:
            identity = _diagram_identity(diagram).lower()
            if identity and (identity == diagram_ref or diagram_ref in identity or identity in diagram_ref):
                return _build(diagram, "explicit", 1.0, requested_parts, region_id)

    stem = " ".join(
        str(v)
        for v in [
            raw_question.get("question_text"),
            raw_question.get("stimulus_context"),
            raw_question.get("micro_concept"),
            " ".join(
                str(p.get("sub_question") or "")
                for p in (raw_question.get("structured_parts") or [])
                if isinstance(p, dict)
            ),
        ]
        if v
    )

    if not tokens(stem):
        return None

    best: tuple[float, dict[str, Any]] | None = None
    for diagram in diagrams:
        descriptor = _diagram_text(diagram)
        if not descriptor.strip():
            continue
        score, _method = similarity(stem, descriptor)
        if best is None or score > best[0]:
            best = (score, diagram)

    if best and best[0] >= MIN_SEMANTIC_CONFIDENCE:
        return _build(best[1], "semantic", best[0], requested_parts, region_id)

    if question_type == "diagram_based":
        logger.info(
            "No diagram cleared the confidence floor for a diagram_based question "
            "(best %.3f of %d candidates); leaving unbound for validation to reject.",
            best[0] if best else 0.0,
            len(diagrams),
        )

    return None
