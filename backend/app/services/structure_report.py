"""Compare what is in the database against what the design actually publishes.

Three times running, the console showed the same fifteen entries under
"Pre-Primary 1" and the only way to judge them was to read the KICD PDF by hand
and count. That is not a workable loop: a learning area holding another's
strands looks exactly like a correct one, and a subject that is really a level
looks like a subject.

This turns "how accurate is this?" into a number, and — more usefully — into
the specific next step. It reads only; it changes nothing.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .curriculum_catalogue import (
    PRE_PRIMARY_STRUCTURE, expected_structure, expected_subjects, has_combined_design,
)

logger = logging.getLogger("cbc-structure-report")


def _norm(name: str) -> str:
    """Compare on words alone: "1.0 Creation" and "Creation" are one strand."""
    words = re.split(r"[^a-z0-9]+", str(name or "").lower())
    return " ".join(w for w in words if w and not w.replace(".", "").isdigit())


@dataclass(slots=True)
class AreaReport:
    subject: str
    expected_strands: list[str] = field(default_factory=list)
    found_strands: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)
    expected_sub_strands: int = 0
    found_sub_strands: int = 0
    ingested: bool = False

    @property
    def status(self) -> str:
        if not self.ingested:
            return "not_ingested"
        if self.missing or not self.found_strands:
            return "incomplete"
        if self.found_sub_strands < self.expected_sub_strands:
            return "strands_only"
        return "complete"

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "status": self.status,
            "strands": {
                "expected": len(self.expected_strands),
                "found": len(self.found_strands),
                "matched": len(self.matched),
                "missing": self.missing,
                "unexpected": self.unexpected,
            },
            "sub_strands": {
                "expected": self.expected_sub_strands,
                "found": self.found_sub_strands,
            },
        }


def _next_step(report: AreaReport) -> str:
    if not report.ingested:
        return f"Ingest the {report.subject} section of the design."
    if not report.found_strands:
        return f"Run generate-strands then save-strands for {report.subject}."
    if report.missing:
        return (
            f"{len(report.missing)} strand(s) missing for {report.subject}. "
            "Re-run generate-strands; the design lists them all."
        )
    if report.found_sub_strands < report.expected_sub_strands:
        return (
            f"Run generate-substrands for each of {report.subject}'s "
            f"{len(report.found_strands)} strand(s) — "
            f"{report.found_sub_strands} of {report.expected_sub_strands} saved."
        )
    return ""


def build_report(grade: str) -> dict[str, Any]:
    """What this grade holds, against what its design publishes."""
    from ..infra.db import fetch_all

    alt = grade.replace("grade-", "") if grade.startswith("grade-") else f"grade-{grade}"
    rows = fetch_all(
        """
        SELECT subject, strand_name, COUNT(*) AS sub_strand_count
        FROM curriculum_substrands
        WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))
        GROUP BY subject, strand_name
        ORDER BY subject, strand_name
        """,
        {"grade": grade, "alt": alt},
    )

    by_subject: dict[str, dict[str, int]] = {}
    for row in rows:
        subject = str(row.get("subject") or "").strip()
        strand = str(row.get("strand_name") or "").strip()
        if not subject or not strand:
            continue
        by_subject.setdefault(subject, {})[strand] = int(row.get("sub_strand_count") or 0)

    published = expected_subjects(grade)
    published_norm = {_norm(s) for s in published}

    # A subject in the database that the grade does not publish is the symptom
    # that started all of this: "Pre-Primary 1" is a level, not a learning area.
    unpublished = [s for s in by_subject if _norm(s) not in published_norm]

    areas: list[AreaReport] = []
    for subject in published:
        structure = expected_structure(grade, subject)
        found = by_subject.get(subject) or {}
        # Tolerate spelling drift between the catalogue and what was stored.
        if not found:
            for stored, strands in by_subject.items():
                if _norm(stored) == _norm(subject):
                    found = strands
                    break

        expected_strands = list(structure.get("strands", []))
        expected_norm = {_norm(s): s for s in expected_strands}
        found_norm = {_norm(s): s for s in found}

        matched = [expected_norm[k] for k in expected_norm if k in found_norm]
        missing = [expected_norm[k] for k in expected_norm if k not in found_norm]
        unexpected = [found_norm[k] for k in found_norm if expected_norm and k not in expected_norm]

        areas.append(AreaReport(
            subject=subject,
            expected_strands=expected_strands,
            found_strands=list(found),
            matched=matched,
            missing=missing,
            unexpected=unexpected,
            expected_sub_strands=int(structure.get("sub_strand_count", 0)),
            found_sub_strands=sum(found.values()),
            ingested=bool(found),
        ))

    total_expected_strands = sum(len(a.expected_strands) for a in areas)
    total_matched = sum(len(a.matched) for a in areas)
    total_expected_subs = sum(a.expected_sub_strands for a in areas)
    total_found_subs = sum(a.found_sub_strands for a in areas)

    problems: list[str] = []
    for subject in unpublished:
        strands = by_subject[subject]
        problems.append(
            f"'{subject}' is not a learning area this grade publishes, yet holds "
            f"{len(strands)} strand(s) and {sum(strands.values())} sub-strand(s). "
            + ("It is the LEVEL, not a learning area — the combined design was "
               "ingested whole instead of split, so every area overwrote the last. "
               "Clear the grade and re-ingest."
               if has_combined_design(grade) else
               "Check what was ingested under this name.")
        )
    for area in areas:
        step = _next_step(area)
        if step:
            problems.append(step)

    return {
        "grade": grade,
        "combined_design": has_combined_design(grade),
        "learning_areas": [a.to_dict() for a in areas],
        "unpublished_subjects": unpublished,
        "totals": {
            "learning_areas_expected": len(areas),
            "learning_areas_ingested": sum(1 for a in areas if a.ingested),
            "strands_expected": total_expected_strands,
            "strands_matched": total_matched,
            "sub_strands_expected": total_expected_subs,
            "sub_strands_found": total_found_subs,
            "strand_completeness": (
                round(100 * total_matched / total_expected_strands) if total_expected_strands else None
            ),
            "sub_strand_completeness": (
                round(100 * total_found_subs / total_expected_subs) if total_expected_subs else None
            ),
        },
        "next_steps": problems,
        "reference": (
            {k: {"strands": len(v["strands"]), "sub_strands": v["sub_strand_count"]}
             for k, v in PRE_PRIMARY_STRUCTURE.items()}
            if has_combined_design(grade) else {}
        ),
    }
