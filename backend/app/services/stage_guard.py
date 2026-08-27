"""Refuse to generate before the parents exist, and provide the skill.

The generation endpoints receive flat payloads — a strand name, a sub-strand
name, some notes — not the artefact graph. This turns one into the other, runs
the lineage check, and returns the assembled context together with the teaching
skill (deriving one if the subject has none yet).

Anything a stage depends on and cannot get stops the run with a 422 naming what
to produce first. Generating around a hole means inventing whatever the missing
parent would have said, and that content reads exactly like content that was
grounded.
"""
from __future__ import annotations

import logging
from typing import Any

from ..errors import raise_api_error
from .content_lineage import (
    ACTIVITY,
    ASSET_PLAN,
    DIAGRAM,
    HOUR_NOTE,
    QUESTION,
    STRAND,
    SUBSTRAND,
    Artifact,
    MissingParentContext,
    build_context,
    descend,
)
from .skill_provisioning import ensure_skill

logger = logging.getLogger("cbc-stage-guard")


def _artifact(kind: str, title: str, content: Any = None, parents: list[Artifact] | None = None,
              hour: int | None = None) -> Artifact | None:
    """An artefact from whatever the payload carried, or None if it carried nothing."""
    if not title and not content:
        return None
    body = content if isinstance(content, dict) else ({"summary": str(content)} if content else {})
    ident = f"{kind}:{title}".strip(":")
    if parents:
        return descend(kind, ident, parents, title=title, content=body, hour=hour)
    return Artifact(kind=kind, id=ident, title=title, content=body, hour=hour)


def _hours_from(notes_content: Any) -> list[Artifact]:
    """Each hour module in a notes payload as its own artefact."""
    from .document_index import parse_pages  # noqa: F401  (kept local, cheap)

    mods = []
    if isinstance(notes_content, dict):
        mods = notes_content.get("hour_modules") or []
    if not isinstance(mods, list):
        return []

    out: list[Artifact] = []
    for index, module in enumerate(mods):
        if not isinstance(module, dict):
            continue
        hour = module.get("hour_index") or index + 1
        out.append(Artifact(
            kind=HOUR_NOTE,
            id=f"hour:{hour}",
            title=module.get("hour_title") or f"Hour {hour}",
            content=module,
            hour=hour,
        ))
    return out


def require_context(
    stage: str,
    *,
    grade: str,
    subject: str,
    strand: str = "",
    sub_strand: str = "",
    notes_content: Any = None,
    target_hour: int | None = None,
    assets: list[Any] | None = None,
    level: str = "",
    essence_statement: str = "",
    general_learning_outcomes: list[str] | None = None,
    design_pages: str = "",
    derive_skill: bool = True,
) -> dict[str, Any]:
    """Assemble a stage's context, or refuse with what to do about it."""
    strand_artifact = _artifact(STRAND, strand)
    substrand_artifact = (
        _artifact(SUBSTRAND, sub_strand, parents=[strand_artifact] if strand_artifact else None)
        if sub_strand else None
    )

    hours = _hours_from(notes_content)
    for hour in hours:
        if substrand_artifact:
            hour.parents = [substrand_artifact.id]
            hour.citations = list(substrand_artifact.citations)

    hour_note = None
    if target_hour is not None:
        hour_note = next((h for h in hours if h.hour == target_hour), None)
        if hours and hour_note is None:
            raise_api_error(
                "MISSING_PARENT_CONTEXT",
                f"Hour {target_hour} has no lesson notes. Generate the notes for "
                f"'{sub_strand}' first — an asset belongs to a specific hour.",
            )

    asset_artifacts = [
        a for a in (
            _artifact(DIAGRAM, str(item.get("title") or item.get("name") or ""), item)
            if isinstance(item, dict) else None
            for item in (assets or [])
        ) if a
    ]

    skill, skill_provenance = ensure_skill(
        subject, grade,
        level=level,
        essence_statement=essence_statement,
        general_learning_outcomes=general_learning_outcomes,
        derive=derive_skill,
    )

    try:
        context = build_context(
            stage,
            strand=strand_artifact,
            substrand=substrand_artifact,
            hour_note=hour_note,
            notes=hours,
            assets=asset_artifacts,
            skill=skill,
            design_pages=design_pages,
        )
    except MissingParentContext as exc:
        raise_api_error("MISSING_PARENT_CONTEXT", str(exc))

    context["skill"] = skill_provenance
    if skill_provenance.get("status") == "derived":
        logger.info(
            "Derived a teaching skill for %s (%s) mid-run; it is unreviewed.", subject, grade
        )
    return context
