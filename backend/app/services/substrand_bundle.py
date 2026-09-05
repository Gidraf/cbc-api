"""What has been generated for one sub-strand, from wherever it was filed.

Questions must be grounded in this grade's own content, so the station refuses
without it. It looked in one place: `substrand_resources`, a row written only
by the explicit publish-bundle step and by the older pipeline.

Nothing on the Content Factory board writes that row. The stations file
ARTIFACTS — a versioned, reviewable `notes`, `diagram`, `activity` each — so a
sub-strand with a lesson plan written, reviewed, scored and approved, with
diagrams drawn and activities authored, had no bundle row at all and questions
refused with "No generated content found".

This reads the artifacts first and falls back to the published row, so content
filed either way is found. The shape returned is the bundle's, because that is
what the caller already expects.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("cbc-substrand-bundle")


def _newest(kind: str, grade: str, subject: str, sub_strand: str) -> dict[str, Any] | None:
    from . import artifact_registry

    try:
        found = artifact_registry.search(grade=grade, subject=subject,
                                         sub_strand=sub_strand, kind=kind, limit=1)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not look for %s in %s/%s: %s", kind, grade, subject, exc)
        return None
    if not found:
        return None

    content = found[0].get("content")
    if isinstance(content, dict) and content:
        return content
    try:
        artifact = artifact_registry.get(str(found[0].get("artifact_id") or ""))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read %s artifact: %s", kind, exc)
        return None
    got = getattr(artifact, "content", None)
    return got if isinstance(got, dict) else None


def from_artifacts(grade: str, subject: str, sub_strand: str) -> dict[str, Any] | None:
    """The bundle assembled from what the stations filed, or None."""
    notes = _newest("notes", grade, subject, sub_strand)
    diagram_content = _newest("diagram", grade, subject, sub_strand) or {}
    activity_content = _newest("activity", grade, subject, sub_strand) or {}

    diagrams = (diagram_content.get("visuals")
                or diagram_content.get("diagrams") or [])
    activities = (activity_content.get("activities")
                  or activity_content.get("experiments") or [])

    # Notes are the floor. A question grounded in diagrams alone is a question
    # about a picture rather than about what the lesson teaches.
    if not notes:
        return None

    return {
        "notes": notes,
        "diagrams": diagrams if isinstance(diagrams, list) else [],
        "activities": activities if isinstance(activities, list) else [],
        "curriculum": {"grade": grade, "subject": subject,
                       "sub_strand": sub_strand},
        "source": "artifacts",
    }


def from_published(grade: str, subject: str, sub_strand: str) -> dict[str, Any] | None:
    """The older published bundle row, for content filed before the stations."""
    from ..infra.db import fetch_one
    from .grade_order import normalize_grade

    slug = normalize_grade(grade)
    try:
        row = fetch_one(
            """
            SELECT * FROM substrand_resources
            WHERE LOWER(curriculum->>'subject') = :subject
              AND LOWER(curriculum->>'sub_strand') LIKE :ss
              AND LOWER(curriculum->>'grade') IN (:grade, :alt_grade)
            ORDER BY updated_at DESC LIMIT 1
            """,
            {"subject": subject.lower().strip(),
             "ss": f"%{sub_strand.lower().strip()}%",
             "grade": slug, "alt_grade": slug.replace("grade-", "")},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read the published bundle: %s", exc)
        return None
    if not row:
        return None
    return {
        "notes": row.get("notes") or {},
        "diagrams": row.get("diagrams") or [],
        "activities": row.get("activities") or {},
        "curriculum": row.get("curriculum") or {},
        "source": "published",
    }


def load(grade: str, subject: str, sub_strand: str) -> dict[str, Any] | None:
    """Everything generated for this sub-strand, however it was filed.

    Artifacts first: they are what the board produces now, they are versioned,
    and they are newer than any published row for the same sub-strand.
    """
    return (from_artifacts(grade, subject, sub_strand)
            or from_published(grade, subject, sub_strand))


def what_is_missing(bundle: dict[str, Any] | None) -> list[str]:
    """Which stations still owe something, named for an operator to act on."""
    if not bundle:
        return ["notes", "diagram", "activity"]
    missing: list[str] = []
    if not bundle.get("notes"):
        missing.append("notes")
    if not bundle.get("diagrams"):
        missing.append("diagram")
    if not bundle.get("activities"):
        missing.append("activity")
    return missing
