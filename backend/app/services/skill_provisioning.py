"""Get the teaching skill for a subject, deriving one if none exists yet.

A skill is the professor's know-how for a subject and grade — the persona to
write as, how notes should read, what visuals suit it, how it is properly
assessed, what safety it demands. Without one, generation falls back to a
generic profile, which is invisible in the output until a teacher tells you it
reads wrong.

It is also derivable from the same place everything else comes from: the
published design and the strands and sub-strands already extracted from it. So
rather than blocking, or generating unskilled, a stage that finds no skill can
synthesise one from the parent context it already holds — once — and every
later generation for that subject reuses it.

Deriving is deliberately *not* silent. The caller is told the skill was created
on the fly and from what, because a skill invented mid-run is a draft nobody has
reviewed, not an established teaching standard.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("cbc-skill-provisioning")

EXISTING = "existing"
DERIVED = "derived"
UNAVAILABLE = "unavailable"


def _design_context(grade: str, subject: str) -> dict[str, Any]:
    """The essence statement and outcomes the design already gave us."""
    try:
        from ..infra.db import fetch_one
    except Exception:  # noqa: BLE001
        return {}

    row = fetch_one(
        """
        SELECT design_id, level, essence_statement, general_learning_outcomes
        FROM curriculum_designs
        WHERE (grade = :grade OR grade = :alt) AND LOWER(subject) = LOWER(:subject)
        ORDER BY updated_at DESC LIMIT 1
        """,
        {"grade": grade, "alt": (grade or "").replace("grade-", ""), "subject": subject},
    )
    return dict(row) if row else {}


def ensure_skill(
    subject: str,
    grade: str,
    *,
    level: str = "",
    essence_statement: str = "",
    general_learning_outcomes: list[str] | None = None,
    derive: bool = True,
) -> tuple[Any, dict[str, Any]]:
    """The skill for this subject and grade, and how it was obtained.

    Returns ``(skill, provenance)``. ``skill`` is ``None`` only when no skill
    exists and one could not be derived — the caller then generates unskilled
    knowingly rather than by accident.
    """
    from .content_type_classifier import ai_generate_profile_from_dataset, get_profile_from_db

    subject = (subject or "").strip()
    grade = (grade or "").strip()
    if not subject:
        return None, {"status": UNAVAILABLE, "reason": "No subject given."}

    existing = get_profile_from_db(subject, grade)
    if existing:
        return existing, {
            "status": EXISTING,
            "subject": getattr(existing, "subject", subject),
            "grade": getattr(existing, "grade", grade),
        }

    if not derive:
        return None, {
            "status": UNAVAILABLE,
            "reason": f"No teaching skill for {subject} ({grade}), and deriving was not requested.",
        }

    # Derive from the parent context: whatever the caller holds, topped up from
    # the design if it has more.
    design = _design_context(grade, subject)
    essence = essence_statement or design.get("essence_statement") or ""
    outcomes = general_learning_outcomes or design.get("general_learning_outcomes") or []
    resolved_level = level or design.get("level") or "Basic Education"

    if not (essence or outcomes):
        # Nothing to derive from. Inventing a persona out of a subject name
        # produces a plausible-sounding skill grounded in nothing, which is the
        # failure this pipeline is built to avoid.
        return None, {
            "status": UNAVAILABLE,
            "reason": (
                f"No teaching skill for {subject} ({grade}) and nothing to derive one from — "
                f"the design has no essence statement or learning outcomes. "
                f"Ingest the design for this subject first."
            ),
        }

    try:
        skill = ai_generate_profile_from_dataset(
            subject=subject,
            grade=grade or "all",
            level=resolved_level,
            essence_statement=essence,
            general_learning_outcomes=list(outcomes),
            save_to_db=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not derive a skill for %s (%s): %s", subject, grade, exc)
        return None, {"status": UNAVAILABLE, "reason": f"Deriving the skill failed: {exc}"}

    logger.info(
        "Derived a teaching skill for %s (%s) from the design's essence statement and %d outcome(s).",
        subject, grade, len(outcomes),
    )
    return skill, {
        "status": DERIVED,
        "subject": subject,
        "grade": grade,
        "derived_from": {
            "design_id": design.get("design_id", ""),
            "essence_statement": bool(essence),
            "outcome_count": len(outcomes),
        },
        # Said plainly so it reaches the operator: this is a draft, not a
        # reviewed teaching standard.
        "review_note": (
            "This skill was derived automatically and has not been reviewed. "
            "Check it on the Teaching skills screen before relying on the content it shapes."
        ),
    }
