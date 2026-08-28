"""Fill in the assessment rubrics the design's own tables would not give up.

KICD prints its rubric as a four-column table, and the extracted text of those
pages is the worst-mangled part of every design: cells wrap mid-phrase, columns
interleave, and whole levels go missing. One run produced nine rubrics of which
four were wrong — one carrying a row from a different strand entirely. The next
run produced two, both correct, and dropped seven that exist in the design.

So the rubric is taken from the design where the table is readable, and written
from the sub-strand's own outcomes where it is not. Which of the two happened is
recorded on every rubric, because a rubric read from KICD and a rubric derived
from its outcomes are different things and a reviewer must be able to tell them
apart.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-rubric-filler")

# KICD's own four levels. A rubric missing one is not a rubric.
LEVELS = ("exceeding", "meeting", "approaching", "below")


@dataclass(slots=True)
class RubricReport:
    from_design: list[str] = field(default_factory=list)
    generated: list[str] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_design": self.from_design,
            "generated": self.generated,
            "failed": self.failed,
            "complete": not self.failed,
        }


def _rows_of(rubric: Any) -> list[dict[str, Any]]:
    """A rubric arrives as one row or a list of them, under several names."""
    if isinstance(rubric, dict):
        for key in ("rubric", "rows", "criteria"):
            value = rubric.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
        return [rubric] if any(level in rubric for level in LEVELS) else []
    if isinstance(rubric, list):
        return [r for r in rubric if isinstance(r, dict)]
    return []


def is_usable(rubric: Any) -> bool:
    """Does this rubric have an indicator and all four levels, with content?

    A partial rubric is worse than none: a teacher marking against three levels
    silently has nowhere to put the fourth kind of answer.
    """
    rows = _rows_of(rubric)
    if not rows:
        return False
    for row in rows:
        if not str(row.get("indicator") or "").strip():
            return False
        for level in LEVELS:
            if not str(row.get(level) or "").strip():
                return False
    return True


def needs_filling(sub_strands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The sub-strands whose rubric could not be read from the design."""
    return [
        s for s in sub_strands
        if isinstance(s, dict)
        and not is_usable(s.get("assessment_rubric") or s.get("assessment_rubrics"))
    ]


def fill(
    sub_strands: list[dict[str, Any]],
    generate: Any,
) -> RubricReport:
    """Generate the missing rubrics in place, and record which are which.

    `generate` is called with one sub-strand and returns its rubric rows. It is
    passed in so this module stays testable without a model, and so the caller
    owns the prompt and the provider.
    """
    report = RubricReport()

    for sub_strand in sub_strands:
        if not isinstance(sub_strand, dict):
            continue
        name = str(sub_strand.get("sub_strand_name") or sub_strand.get("name") or "?")
        existing = sub_strand.get("assessment_rubric") or sub_strand.get("assessment_rubrics")

        if is_usable(existing):
            sub_strand["rubric_source"] = "design"
            report.from_design.append(name)
            continue

        try:
            rows = generate(sub_strand)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not write a rubric for '%s': %s", name, exc)
            report.failed.append({"sub_strand": name, "error": str(exc)[:200]})
            continue

        rows = [r for r in (rows or []) if isinstance(r, dict)]
        if not is_usable(rows):
            # A generated rubric that is itself incomplete helps nobody, and
            # storing it would hide the gap behind something that looks filled.
            report.failed.append({
                "sub_strand": name,
                "error": "the generated rubric was itself incomplete",
            })
            continue

        sub_strand["assessment_rubric"] = rows
        sub_strand["rubric_source"] = "generated_from_outcomes"
        report.generated.append(name)

    if report.generated:
        logger.info(
            "Wrote %d rubric(s) from outcomes where the design's table could not "
            "be read: %s", len(report.generated), ", ".join(report.generated),
        )
    return report
