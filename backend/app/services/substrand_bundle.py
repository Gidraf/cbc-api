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


# ── the whole grade at once ─────────────────────────────────────────────────

_KIND_SLOT: dict[str, str] = {
    "notes": "notes",
    "diagram": "diagrams",
    "activity": "activities",
    "question": "questions",
}


def index_for_grade(grade: str, subject: str = "") -> dict[tuple[str, str], dict[str, Any]]:
    """Every sub-strand's generated content for one grade, from the artifacts.

    Keyed `(subject.lower(), sub_strand.lower())`, which is how the coverage
    report indexes what it was handed.

    Coverage read `substrand_resources` — the publish-bundle row — so a grade
    whose every station had run reported NOTES 0/0, VISUALS 0/0, everything
    0/0, and the material and diagram stations locked with "none exist yet for
    this sub-strand". The board could not see its own work.

    One query for the grade rather than one per sub-strand: a grade has
    hundreds, and the coverage screen is not a place to make hundreds of round
    trips.
    """
    from ..infra.db import fetch_all
    from .grade_sql import clause

    conditions = [clause("a.grade", "grade"), "a.kind IN :kinds"]
    params: dict[str, Any] = {"grade": grade,
                              "kinds": tuple(_KIND_SLOT)}
    if subject:
        conditions.append("LOWER(a.subject) = LOWER(:subject)")
        params["subject"] = subject

    try:
        rows = fetch_all(
            f"""
            SELECT DISTINCT ON (a.artifact_key)
                   a.subject, a.sub_strand_name, a.kind, a.content
            FROM artifacts a
            WHERE {' AND '.join(conditions)}
            ORDER BY a.artifact_key, a.version DESC
            """,
            params,
        ) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not index artifacts for %s: %s", grade, exc)
        return {}

    index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        subject_key = str(row.get("subject") or "").strip().lower()
        sub_strand = str(row.get("sub_strand_name") or "").strip()
        if not subject_key or not sub_strand:
            continue

        key = (subject_key, sub_strand.lower())
        bundle = index.setdefault(key, {
            "notes": {}, "diagrams": [], "activities": [], "questions": [],
            "curriculum": {"grade": grade, "subject": row.get("subject"),
                           "sub_strand": sub_strand},
            "source": "artifacts",
        })

        content = row.get("content")
        if not isinstance(content, dict):
            continue
        kind = str(row.get("kind") or "")
        if kind == "notes":
            bundle["notes"] = content
        elif kind == "diagram":
            bundle["diagrams"] = (content.get("visuals")
                                  or content.get("diagrams") or [])
        elif kind == "activity":
            bundle["activities"] = (content.get("activities")
                                    or content.get("experiments") or [])
        elif kind == "question":
            bundle["questions"] = (content.get("questions")
                                   or content.get("items") or [])
    return index
