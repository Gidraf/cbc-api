"""What a reviewer must be shown besides the artifact itself.

The artifact was always sent. What was not sent, for most kinds, is the thing
it has to be judged against — and a reviewer with no design still returns a
`curriculum_alignment` score, confidently, because nothing tells it that the
column it is comparing against is blank.

The lookup was written for sub-strands and used for everything. A strand
artifact has no `sub_strand_name`, so the query matched no row, returned an
empty string, and the failure was logged at DEBUG and swallowed. Strand reviews
have been scoring alignment against nothing.

Each kind needs a different comparison:

* a strand list is judged against the design's own summary of strands;
* a sub-strand, and everything derived from one — notes, diagrams, activities,
  media prompts, questions — is judged against that sub-strand's row.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-review-context")

# Kinds that hang off a single sub-strand, and are judged against its row.
_SUB_STRAND_SCOPED = frozenset({
    "sub_strand", "notes", "hour_module", "diagram", "photo_prompt",
    "video_prompt", "experiment", "activity", "question", "answer",
})

_STRAND_SCOPED = frozenset({"strand", "ingest"})


# How much descendant content to show. Enough to judge whether the parent is
# right; not so much that the reviewer starts reviewing the children instead.
MAX_DESCENDANT_CHARS = 25_000


@dataclass(slots=True)
class ReviewGrounding:
    text: str = ""
    descendants: str = ""
    source: str = "none"
    found: bool = False
    missing_reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "grounded": self.found, "source": self.source,
            "chars": len(self.text), "descendant_chars": len(self.descendants),
            "missing_reason": self.missing_reason,
            **self.details,
        }


def _strand_grounding(grade: str, subject: str, strand: str) -> ReviewGrounding:
    """The design's own account of this learning area's strands."""
    from ..infra.db import fetch_all, fetch_one
    from .curriculum_catalogue import expected_structure

    parts: list[str] = []
    details: dict[str, Any] = {}

    reference = expected_structure(grade, subject)
    if reference.get("strands"):
        parts.append(
            "Strands KICD publishes for this learning area:\n"
            + "\n".join(f"- {s}" for s in reference["strands"])
            + f"\n\nThe design allocates {reference.get('lessons', '?')} lessons across "
            f"{reference.get('sub_strand_count', '?')} sub-strands"
            + (f", summarised on page(s) {', '.join(str(p) for p in reference['source_pages'])}."
               if reference.get("source_pages") else ".")
        )
        details["reference_strands"] = len(reference["strands"])

    stored = fetch_one(
        """
        SELECT metadata FROM curriculum_designs
        WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')) AND LOWER(subject) = LOWER(:subject)
          AND metadata ? 'strands'
        ORDER BY updated_at DESC LIMIT 1
        """,
        {"grade": grade, "alt_grade": grade.replace("grade-", ""), "subject": subject},
    )
    saved = ((stored or {}).get("metadata") or {}).get("strands") or []
    if saved:
        parts.append(
            "Strands already saved for this learning area:\n"
            + "\n".join(f"- {s.get('strand_name', '')}" for s in saved if s.get("strand_name"))
        )
        details["saved_strands"] = len(saved)

    rows = fetch_all(
        """
        SELECT DISTINCT strand_name, COUNT(*) AS sub_strands,
               STRING_AGG(sub_strand_name, ', ' ORDER BY sub_strand_id) AS names
        FROM curriculum_substrands
        WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')) AND LOWER(subject) = LOWER(:subject)
        GROUP BY strand_name ORDER BY strand_name
        """,
        {"grade": grade, "alt_grade": grade.replace("grade-", ""), "subject": subject},
    ) or []
    if rows:
        parts.append(
            "Sub-strands already stored, by strand:\n"
            + "\n".join(f"- {r['strand_name']} ({r['sub_strands']}): {r['names']}" for r in rows)
        )
        details["stored_strands"] = len(rows)

    if not parts:
        return ReviewGrounding(
            missing_reason=(
                f"Nothing is published or stored for '{subject}' ({grade}), so a strand "
                "list has nothing to be judged against."
            ),
        )
    return ReviewGrounding(
        text="\n\n".join(parts), source="design summary and stored structure",
        found=True, details=details,
    )


def _sub_strand_grounding(grade: str, subject: str, sub_strand: str) -> ReviewGrounding:
    from ..routes.curriculum import _substrand_design_block

    if not sub_strand:
        return ReviewGrounding(
            missing_reason="The artifact names no sub-strand, so its design row "
                           "cannot be located.",
        )

    text, slos = _substrand_design_block(grade, subject, sub_strand)
    if not text:
        return ReviewGrounding(
            missing_reason=(
                f"'{sub_strand}' is not stored for {subject} ({grade}). Ingest the "
                "learning area, or save its sub-strands, before reviewing content "
                "derived from it."
            ),
        )
    return ReviewGrounding(
        text=text, source="the sub-strand's stored design row", found=True,
        details={"slo_count": len(slos)},
    )


def _descendants(grade: str, subject: str, strand: str) -> str:
    """The saved sub-strands under a strand, so the strand can be judged in place.

    A strand list read alone is five names, and a reviewer asked whether it is
    complete has only the names to go on. Shown what actually hangs off each
    strand, it can tell a real strand list from a plausible one — whether the
    lesson counts sum to what the design allocates, whether a strand is carrying
    sub-strands that belong under another.
    """
    from ..infra.db import fetch_all

    rows = fetch_all(
        """
        SELECT strand_name, sub_strand_id, sub_strand_name, allocated_hours, slos
        FROM curriculum_substrands
        WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')) AND LOWER(subject) = LOWER(:subject)
        ORDER BY strand_id, sub_strand_id
        """,
        {"grade": grade, "alt_grade": grade.replace("grade-", ""), "subject": subject},
    ) or []
    if not rows:
        return ""

    lines: list[str] = []
    current = ""
    for row in rows:
        name = str(row.get("strand_name") or "")
        if name != current:
            current = name
            lines.append(f"\n{name}:")
        slos = row.get("slos")
        count = len(slos) if isinstance(slos, list) else 0
        lines.append(
            f"  {row.get('sub_strand_id') or ''} {row.get('sub_strand_name') or ''}"
            f" — {row.get('allocated_hours') or 'time not stated'}, {count} outcome(s)"
        )
    return "\n".join(lines).strip()[:MAX_DESCENDANT_CHARS]


def for_artifact(artifact: Any) -> ReviewGrounding:
    """The design text this artifact must be judged against.

    Never raises. A grounding that cannot be found is reported as missing, with
    the reason — silence here is how a strand review scored alignment against
    nothing and reported a number for it.
    """
    kind = getattr(artifact, "kind", "")
    grade = getattr(artifact, "grade", "")
    subject = getattr(artifact, "subject", "")

    try:
        if kind in _STRAND_SCOPED:
            grounding = _strand_grounding(grade, subject, getattr(artifact, "strand_name", ""))
            grounding.descendants = _descendants(grade, subject, "")
            return grounding
        if kind in _SUB_STRAND_SCOPED:
            return _sub_strand_grounding(
                grade, subject, getattr(artifact, "sub_strand_name", "")
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not assemble review grounding for %s: %s",
                       getattr(artifact, "artifact_id", "?"), exc)
        return ReviewGrounding(missing_reason=f"The design lookup failed: {exc}"[:300])

    return ReviewGrounding(
        missing_reason=f"'{kind}' has no defined comparison, so there is nothing "
                       "to judge it against.",
    )
