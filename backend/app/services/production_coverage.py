"""How much of a grade's curriculum has actually been produced, in one place.

Coverage was computed inside the coverage ROUTE. So the pipeline board, which
is where an operator actually stands while working, had a different and much
weaker idea of progress: it counted sub-strands touched, not curriculum met.
A stage tile read "0 of 0" beside a Coverage screen reading 34%, and neither
number explained the other.

This computes it once, from the two things it has always depended on:

    the REQUIREMENT   each sub-strand's own KICD blueprint — allocated hours,
                      required diagrams, experiments, learning outcomes
    the GENERATION    what is filed in the artifacts table for that sub-strand

Both sides are keyed through `scope_key`, because keying them by hand in four
places is what made a grade with every station run report 0%.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from . import coverage, scope_key

logger = logging.getLogger("cbc-production-coverage")

# Which board stage each measured dimension belongs to. `material`, `media` and
# `simulation` have no blueprint requirement of their own — the design says how
# many diagrams and experiments a sub-strand needs, not how many recordings —
# so they are counted per sub-strand and marked as such rather than given an
# invented target.
STAGE_DIMENSION: dict[str, str] = {
    "notes": "notes",
    "diagram": "visuals",
    "activity": "practicals",
    "questions": "questions",
}

DIMENSIONS = ("notes", "visuals", "practicals", "questions")


@dataclass
class Dimension:
    generated: int = 0
    required: int = 0
    estimated: bool = False

    @property
    def remaining(self) -> int:
        return max(0, self.required - self.generated)

    @property
    def percentage(self) -> int:
        if self.required <= 0:
            return 0
        return min(100, round(self.generated / self.required * 100))

    def to_dict(self) -> dict[str, Any]:
        return {"generated": self.generated, "required": self.required,
                "remaining": self.remaining, "percentage": self.percentage,
                "estimated": self.estimated,
                "says": (f"{self.generated} of {self.required} produced"
                         + (f", {self.remaining} remaining" if self.remaining
                            else " — complete")
                         + (" (target estimated: this sub-strand's design gave "
                            "no figure)" if self.estimated else ""))}


@dataclass
class SubStrand:
    """One sub-strand's own numbers, so a table and a board agree.

    The sub-strand chooser had its own percentage from a second computation,
    and read 0% for a sub-strand the coverage panel on the same screen showed
    as the only one with anything filed. Two numbers about the same thing, on
    the same page, disagreeing.
    """
    subject: str = ""
    strand: str = ""
    name: str = ""
    dimensions: dict[str, Dimension] = field(default_factory=dict)

    @property
    def percentage(self) -> int:
        required = sum(d.required for d in self.dimensions.values())
        if not required:
            return 0
        done = sum(min(d.generated, d.required) for d in self.dimensions.values())
        return min(100, round(done / required * 100))

    @property
    def filed(self) -> bool:
        return any(d.generated for d in self.dimensions.values())

    def to_dict(self) -> dict[str, Any]:
        return {"subject": self.subject, "strand": self.strand, "name": self.name,
                "percentage": self.percentage, "filed": self.filed,
                "dimensions": {k: v.to_dict() for k, v in self.dimensions.items()}}


@dataclass
class Report:
    grade: str = ""
    subject: str = ""
    substrands: int = 0
    measured: int = 0
    dimensions: dict[str, Dimension] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)
    per_substrand: list[SubStrand] = field(default_factory=list)

    @property
    def percentage(self) -> int:
        """Across the measured dimensions, weighted by what each requires.

        Averaging the percentages would let a sub-strand needing one diagram
        count as much as one needing twelve.
        """
        required = sum(d.required for d in self.dimensions.values())
        if not required:
            return 0
        generated = sum(min(d.generated, d.required) for d in self.dimensions.values())
        return min(100, round(generated / required * 100))

    def for_stage(self, stage: str) -> Dimension | None:
        name = STAGE_DIMENSION.get(stage)
        return self.dimensions.get(name) if name else None

    def to_dict(self) -> dict[str, Any]:
        return {"grade": self.grade, "subject": self.subject,
                "substrands": self.substrands, "measured": self.measured,
                "percentage": self.percentage,
                "dimensions": {k: v.to_dict() for k, v in self.dimensions.items()},
                "unmatched_generations": self.unmatched,
                "substrand_rows": [r.to_dict() for r in self.per_substrand]}


def _blueprints(grade: str, subject: str) -> list[dict[str, Any]]:
    from ..infra.db import fetch_all
    from .grade_sql import clause

    conditions = [clause("grade", "grade")]
    params: dict[str, Any] = {"grade": grade}
    if subject:
        conditions.append("LOWER(subject) = LOWER(:subject)")
        params["subject"] = subject
    try:
        return fetch_all(
            f"""
            SELECT subject, strand_name, sub_strand_name, allocated_hours,
                   required_diagrams, experiments, slos
            FROM curriculum_substrands
            WHERE {' AND '.join(conditions)}
            """, params) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("No blueprint for %s/%s: %s", grade, subject, exc)
        return []


def _counted(bundle: dict[str, Any]) -> dict[str, int]:
    """What is filed for one sub-strand, per dimension."""
    notes = bundle.get("notes") if isinstance(bundle.get("notes"), dict) else {}
    modules = (notes.get("modules") or notes.get("hour_modules")
               or notes.get("key_concepts") or [])
    activities = bundle.get("activities") or []
    if isinstance(activities, dict):
        practicals = len(activities.get("activities") or []) + \
                     len(activities.get("experiments") or [])
    else:
        practicals = len(activities) if isinstance(activities, list) else 0
    return {
        "notes": len(modules) if isinstance(modules, list) else 0,
        "visuals": len(bundle.get("diagrams") or []),
        "practicals": practicals,
        "questions": len(bundle.get("questions") or []),
    }


def report(grade: str, subject: str = "") -> Report:
    """One grade (and optionally one subject) against its own design."""
    from . import substrand_bundle

    out = Report(grade=grade, subject=subject,
                 dimensions={d: Dimension() for d in DIMENSIONS})

    blueprints = _blueprints(grade, subject)
    if not blueprints:
        return out

    try:
        filed = substrand_bundle.index_for_grade(grade, subject)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read what is filed for %s: %s", grade, exc)
        filed = {}

    required_scopes: set[tuple[str, str]] = set()
    for row in blueprints:
        scope = scope_key.key(row.get("subject"), row.get("sub_strand_name"))
        required_scopes.add(scope)
        out.substrands += 1

        requirement = coverage.derive_requirement(row)
        bundle = filed.get(scope) or {}
        if bundle:
            out.measured += 1
        counted = _counted(bundle)

        row_out = SubStrand(subject=str(row.get("subject") or ""),
                            strand=str(row.get("strand_name") or ""),
                            name=str(row.get("sub_strand_name") or ""))
        out.per_substrand.append(row_out)

        for name, needed, estimated in (
            ("notes", requirement.hours, requirement.estimated["hours"]),
            ("visuals", requirement.visuals, requirement.estimated["visuals"]),
            ("practicals", requirement.practicals, requirement.estimated["practicals"]),
            ("questions", requirement.questions, requirement.estimated["questions"]),
        ):
            dimension = out.dimensions[name]
            dimension.required += needed
            dimension.generated += counted.get(name, 0)
            dimension.estimated = dimension.estimated or estimated
            row_out.dimensions[name] = Dimension(
                generated=counted.get(name, 0), required=needed,
                estimated=estimated)

    # Work filed under a name the design does not use is invisible: it scores
    # nothing, unlocks nothing, and used to say nothing.
    out.unmatched = scope_key.report_misses(required_scopes, set(filed))
    return out
