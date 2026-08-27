"""Find the design document a generation must be grounded in — or say why not.

Four endpoints each carried their own copy of "look the design up, dig the text
out of raw_payload, carry on if it isn't there". They disagreed on all three
parts, so the same missing document produced a 404 in one place, a 422 in
another, and in the two that matter most — strand and sub-strand generation — an
HTTP 200 holding an empty list. From the console that is indistinguishable from
"this strand genuinely has no sub-strands", which is how a missing CRE design
survived several rounds of looking straight at it.

Three failure modes hid behind that silence, and they are fixed here rather than
merely reported:

* The newest design row is not always the one with a document. ``design_id``
  embeds a hash of the text, so every re-ingest whose text differs by a byte
  writes a NEW row instead of updating the old one. ``ORDER BY updated_at DESC
  LIMIT 1`` then picks the newest, document or not. This walks the candidates
  and takes the newest one that actually holds a document.
* A learning area of a combined design may never have been ingested on its own.
  Rather than fail, the section is re-split out of the dataset the same way
  ``/factory/ingest-learning-area`` splits it.
* A design filed under the wrong grade reads exactly like a missing one. That
  was a real bug (PP1 sections landing under grade-pp2), so when the subject is
  found under another grade the error says which, instead of "not found".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-design-source")

# How many rows back to look for one that carries a document.
_MAX_CANDIDATES = 12

# Below this a dataset item is a stub or a placeholder, not a design.
_MIN_DESIGN_CHARS = 2_000

_TEXT_KEYS = ("source_text", "raw_text", "text", "output")


@dataclass(slots=True)
class SourceMaterial:
    """The document a generation will be grounded in, and where it came from."""

    text: str = ""
    origin: str = "none"
    design_id: str = ""
    grade: str = ""
    subject: str = ""
    essence_statement: str = ""
    level: str = ""
    general_learning_outcomes: list[str] = field(default_factory=list)
    rows_examined: int = 0
    rows_without_document: int = 0
    other_grades: list[str] = field(default_factory=list)
    split_found: list[str] = field(default_factory=list)

    @property
    def grounded(self) -> bool:
        return bool(self.text.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "grounded": self.grounded,
            "origin": self.origin,
            "chars": len(self.text),
            "design_id": self.design_id,
            "grade": self.grade,
            "subject": self.subject,
            "rows_examined": self.rows_examined,
            "rows_without_document": self.rows_without_document,
            "found_under_other_grades": self.other_grades,
            "learning_areas_in_dataset": self.split_found,
        }


def _document_of(raw_payload: Any) -> str:
    if not isinstance(raw_payload, dict):
        return ""
    for key in _TEXT_KEYS:
        value = raw_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _from_stored_design(grade: str, subject: str, design_id: str) -> SourceMaterial:
    """The newest stored design that actually holds a document."""
    from ..infra.db import fetch_all

    found = SourceMaterial(grade=grade, subject=subject)
    rows = fetch_all(
        """
        SELECT design_id, grade, subject, level, essence_statement,
               general_learning_outcomes, raw_payload
        FROM curriculum_designs
        WHERE (design_id = :design_id)
           OR ((grade = :grade OR grade = :alt_grade) AND LOWER(subject) = LOWER(:subject))
        ORDER BY updated_at DESC
        LIMIT :cap
        """,
        {
            "design_id": design_id or "",
            "grade": grade,
            "alt_grade": (grade or "").replace("grade-", ""),
            "subject": subject,
            "cap": _MAX_CANDIDATES,
        },
    ) or []

    found.rows_examined = len(rows)
    for row in rows:
        text = _document_of(row.get("raw_payload"))
        if not text:
            found.rows_without_document += 1
            continue
        found.text = text
        found.origin = "stored design"
        found.design_id = str(row.get("design_id") or "")
        found.grade = str(row.get("grade") or grade)
        found.subject = str(row.get("subject") or subject)
        found.level = str(row.get("level") or "")
        found.essence_statement = str(row.get("essence_statement") or "")
        outcomes = row.get("general_learning_outcomes")
        found.general_learning_outcomes = list(outcomes) if isinstance(outcomes, list) else []
        # Metadata from the newest row even when its document came from an older
        # one would misattribute the text, so both are taken from the same row.
        break

    if not found.grounded:
        found.essence_statement = ""
        for row in rows:
            if not found.essence_statement:
                found.essence_statement = str(row.get("essence_statement") or "")
            if not found.level:
                found.level = str(row.get("level") or "")

    return found


def _other_grades(subject: str, grade: str) -> list[str]:
    """Grades this subject IS ingested under — a mis-filed design, most likely."""
    from ..infra.db import fetch_all

    try:
        rows = fetch_all(
            """
            SELECT DISTINCT grade FROM curriculum_designs
            WHERE LOWER(subject) = LOWER(:subject) AND grade <> :grade
            ORDER BY grade
            """,
            {"subject": subject, "grade": grade},
        ) or []
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not check other grades for %s: %s", subject, exc)
        return []
    return [str(r.get("grade") or "") for r in rows if r.get("grade")]


def _from_dataset(grade: str, subject: str, found: SourceMaterial) -> None:
    """Re-split the learning area out of the grade's design document.

    A combined design holds seven learning areas. If one was never ingested on
    its own, its text is still there to be cut out — the same cut
    ``/factory/ingest-learning-area`` makes.
    """
    from .curriculum_catalogue import expected_subjects
    from .dataset_ingest import candidate_items
    from .design_sections import split_learning_areas

    published = expected_subjects(grade)
    seen: set[str] = set()

    try:
        items = candidate_items(grade)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dataset unreachable while looking for %s: %s", subject, exc)
        return

    for item in items:
        text = str(item.get("expected_output") or "")
        if len(text) < _MIN_DESIGN_CHARS:
            continue

        sections = split_learning_areas(text, published) if len(published) > 1 else []
        for section in sections:
            seen.add(section.learning_area)
            if section.learning_area.lower() == subject.lower() and not found.grounded:
                found.text = section.text
                found.origin = "re-split from dataset"
                found.grade = grade
                found.subject = section.learning_area

        # A grade with one design per subject has nothing to split.
        if not sections and not found.grounded and len(published) <= 1:
            found.text = text
            found.origin = "dataset document"
            found.grade = grade
            found.subject = subject

    found.split_found = sorted(seen)


def resolve(
    grade: str,
    subject: str,
    *,
    design_id: str = "",
    supplied: str = "",
) -> SourceMaterial:
    """The design text to generate from, and an account of where it came from.

    Never raises: a caller that can legitimately run ungrounded checks
    ``.grounded`` itself. Callers that cannot use :func:`require`.
    """
    if supplied and supplied.strip():
        return SourceMaterial(
            text=supplied, origin="caller", grade=grade, subject=subject,
        )

    found = _from_stored_design(grade, subject, design_id)
    if not found.grounded:
        _from_dataset(grade, subject, found)
    if not found.grounded:
        found.other_grades = _other_grades(subject, grade)

    logger.info(
        "Source for %s %s: %s (%d chars, %d row(s) examined).",
        grade, subject, found.origin, len(found.text), found.rows_examined,
    )
    return found


def require(
    grade: str,
    subject: str,
    *,
    design_id: str = "",
    supplied: str = "",
) -> SourceMaterial:
    """The design text, or a 422 that says which of the three failures happened.

    Generating without the design does not fail — it succeeds, quietly, with an
    empty list or with content invented from the model's prior knowledge. Asked
    for Christian Religious Education strands ungrounded, it returned "Listening
    and Speaking", a Language Activities strand. So this refuses instead.
    """
    from ..errors import raise_api_error

    found = resolve(grade, subject, design_id=design_id, supplied=supplied)
    if found.grounded:
        return found

    reasons: list[str] = []
    if found.rows_examined and found.rows_without_document == found.rows_examined:
        reasons.append(
            f"{found.rows_without_document} design row(s) exist for it but none stores "
            "the document text"
        )
    elif not found.rows_examined:
        reasons.append("it has no ingested design")
    if found.other_grades:
        reasons.append(
            f"a design for '{subject}' IS ingested under {', '.join(found.other_grades)} "
            "— it may have been filed under the wrong grade"
        )
    if found.split_found and subject not in found.split_found:
        reasons.append(
            f"the grade's design document splits into: {', '.join(found.split_found)}"
        )

    raise_api_error(
        "MISSING_PARENT_CONTEXT",
        f"No curriculum design text for '{subject}' ({grade}), so nothing can be "
        f"generated from it: {'; '.join(reasons) or 'no source could be located'}. "
        f"Ingest it with POST /factory/ingest-learning-area "
        f'{{"grade": "{grade}", "subject": "{subject}"}}, or inspect the split with '
        f"GET /factory/split-preview?grade={grade}.",
        detail=found.to_dict(),
    )
    raise AssertionError("unreachable")  # pragma: no cover
