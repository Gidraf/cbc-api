"""Refuse a rubric that would mismark a child.

Three defects found in one PP1 CRE run, none of them subject-specific:

* The rubric for "The Birth of Jesus Christ" carried, as its Meeting level,
  "Identifies the Holy Bible from other books" — lifted from the rubric table
  two pages earlier. A teacher would assess a child's grasp of the nativity by
  whether they can pick out the Bible.

* "The Wise Men" asks learners to identify TWO ways the wise men celebrated.
  Its rubric put Meeting at one way and Exceeding at two, so a child who did
  exactly what the outcome asks is marked as exceeding it, and three of the
  four levels said "one way" with different amounts of help.

* The design itself contradicts itself: sub-strand 5.1's outcome says "state
  ONE difference between the church and other buildings" and its rubric
  indicator says "tell THREE differences". That is KICD's error, not ours, and
  the right response is to name it rather than silently pick a side.

All three are decidable from data already on the record — the sub-strand's own
outcomes and the rubric's own text. None needs a model, and none knows anything
about Christianity, agriculture or any other subject.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-rubric-integrity")

_LEVELS = ("exceeding", "meeting", "approaching", "below")

# Number words as KICD writes them in outcomes and rubric levels.
_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_NUMBER_RE = re.compile(
    r"\b(" + "|".join(_NUMBERS) + r"|\d{1,2})\b", re.IGNORECASE
)
# "more than three" is a comparative, not the count itself.
_COMPARATIVE = re.compile(r"\b(more than|at least|over|beyond|fewer than|less than)\b", re.IGNORECASE)

# Words that carry no topic. Without stripping these, every rubric shares
# enough vocabulary with every other to look related.
_GENERIC = {
    "ability", "identify", "identifies", "name", "names", "tell", "tells",
    "mention", "mentions", "demonstrate", "demonstrates", "state", "states",
    "list", "lists", "describe", "describes", "explain", "explains", "show",
    "shows", "with", "from", "them", "their", "this", "that", "when", "prompted",
    "guidance", "support", "assistance", "ease", "continued", "some", "part",
    "partly", "learner", "learners", "able", "does", "not", "and", "the", "for",
    "way", "ways", "thing", "things", "more", "than", "one", "two", "three",
    "four", "five", "expectations", "expectation", "level", "indicator",
}


@dataclass(slots=True)
class RubricFinding:
    severity: str          # "error" blocks use; "design_defect" is KICD's, reported
    check: str
    sub_strand: str
    message: str
    level: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "check": self.check,
                "sub_strand": self.sub_strand, "level": self.level,
                "message": self.message}


@dataclass(slots=True)
class RubricReport:
    findings: list[RubricFinding] = field(default_factory=list)
    checked: int = 0

    @property
    def errors(self) -> list[RubricFinding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def design_defects(self) -> list[RubricFinding]:
        return [f for f in self.findings if f.severity == "design_defect"]

    @property
    def sound(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "sound": self.sound,
            "errors": [f.to_dict() for f in self.errors],
            "design_defects": [f.to_dict() for f in self.design_defects],
        }


def _topic_terms(text: str) -> set[str]:
    words = re.findall(r"[a-z']+", (text or "").lower())
    return {w for w in words if len(w) > 3 and w not in _GENERIC}


def _stated_number(text: str) -> int | None:
    """The count a level or outcome asks for, ignoring comparatives."""
    if not text:
        return None
    body = _COMPARATIVE.sub(" ", text)
    match = _NUMBER_RE.search(body)
    if not match:
        return None
    token = match.group(1).lower()
    return _NUMBERS.get(token) or (int(token) if token.isdigit() else None)


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z ]", "", (text or "").lower()).strip()


def check_one(
    sub_strand_name: str,
    slos: list[Any],
    rubric: dict[str, Any],
) -> list[RubricFinding]:
    """Everything decidable about one rubric against its own sub-strand."""
    findings: list[RubricFinding] = []
    indicator = str(rubric.get("indicator") or "")
    levels = {lvl: str(rubric.get(lvl) or "") for lvl in _LEVELS}
    outcome_texts = [str(s.get("text") if isinstance(s, dict) else s) for s in (slos or [])]
    outcome_terms = _topic_terms(" ".join(outcome_texts + [sub_strand_name]))

    # ── 1. A level about something this sub-strand does not teach ───────────
    if outcome_terms:
        for level, text in levels.items():
            terms = _topic_terms(text)
            if not terms:
                continue
            shared = terms & outcome_terms
            if not shared and len(terms) >= 2:
                findings.append(RubricFinding(
                    "error", "foreign_concept", sub_strand_name, level=level,
                    message=(
                        f"The {level} level says \"{text[:90]}\" — none of its terms "
                        f"({', '.join(sorted(terms)[:4])}) appear anywhere in this "
                        f"sub-strand's outcomes. A rubric level lifted from another "
                        f"table marks a child on something they were never taught."
                    ),
                ))

    # ── 2. A scale that does not climb ──────────────────────────────────────
    counts = {lvl: _stated_number(levels[lvl]) for lvl in _LEVELS}
    ladder = [(lvl, counts[lvl]) for lvl in ("below", "approaching", "meeting", "exceeding")
              if counts[lvl] is not None]
    for (lower, low_n), (higher, high_n) in zip(ladder, ladder[1:]):
        if high_n < low_n:
            findings.append(RubricFinding(
                "error", "scale_inverted", sub_strand_name, level=higher,
                message=(
                    f"{higher} asks for {high_n} but {lower} asks for {low_n}. "
                    f"The levels have to climb, or a learner is marked down for "
                    f"doing more."
                ),
            ))

    # ── 3. Meeting must be what the outcome actually asks for ───────────────
    outcome_number = next(
        (n for n in (_stated_number(t) for t in outcome_texts) if n is not None), None
    )
    meeting_number = counts["meeting"]
    if outcome_number is not None and meeting_number is not None:
        if meeting_number < outcome_number:
            findings.append(RubricFinding(
                "error", "meeting_below_outcome", sub_strand_name, level="meeting",
                message=(
                    f"The outcome asks for {outcome_number} but Meeting Expectations "
                    f"asks for only {meeting_number}. A learner who does exactly what "
                    f"the outcome requires would be marked as exceeding it."
                ),
            ))
        elif meeting_number > outcome_number and indicator:
            indicator_number = _stated_number(indicator)
            if indicator_number is not None and indicator_number != outcome_number:
                # The design disagrees with itself. Repairing it silently picks
                # a side on KICD's behalf; a teacher meets the contradiction in
                # the classroom either way.
                findings.append(RubricFinding(
                    "design_defect", "outcome_rubric_disagree", sub_strand_name,
                    message=(
                        f"The KICD design contradicts itself here: the learning "
                        f"outcome asks for {outcome_number}, and its own rubric "
                        f"indicator asks for {indicator_number} "
                        f"(\"{indicator[:80]}\"). Neither has been changed. Decide "
                        f"which the school will assess against."
                    ),
                ))

    # ── 4. Levels that do not distinguish anything ──────────────────────────
    seen: dict[str, str] = {}
    for level in _LEVELS:
        key = _normalise(levels[level])
        if not key:
            continue
        if key in seen:
            findings.append(RubricFinding(
                "error", "levels_identical", sub_strand_name, level=level,
                message=(
                    f"{level} and {seen[key]} say the same thing "
                    f"(\"{levels[level][:70]}\"). Two levels a teacher cannot tell "
                    f"apart are one level with two names."
                ),
            ))
        seen[key] = level

    return findings


def check(sub_strands: list[dict[str, Any]]) -> RubricReport:
    """Check every rubric attached to every sub-strand."""
    report = RubricReport()
    for sub in sub_strands or []:
        if not isinstance(sub, dict):
            continue
        name = str(sub.get("sub_strand_name") or sub.get("name") or "")
        slos = sub.get("slos") or []
        for rubric in sub.get("assessment_rubrics") or []:
            if not isinstance(rubric, dict) or not rubric.get("indicator"):
                continue
            report.checked += 1
            report.findings += check_one(name, slos, rubric)
    if report.errors:
        logger.warning(
            "%d rubric defect(s) across %d rubric(s): %s",
            len(report.errors), report.checked,
            "; ".join(f.check for f in report.errors[:4]),
        )
    return report


def drop_unsound(sub_strands: list[dict[str, Any]]) -> RubricReport:
    """Remove rubrics that would mismark a child, in place, and say what went.

    A wrong rubric is worse than an absent one: `rubric_filler` writes an
    honest replacement from the outcomes when there is nothing, and labels it
    `generated_from_outcomes`. It cannot do that for a rubric that is present
    and wrong, because nothing downstream can tell the difference.
    """
    report = check(sub_strands)
    if not report.errors:
        return report

    broken = {(f.sub_strand, f.check) for f in report.errors}
    by_sub: dict[str, list[str]] = {}
    for name, _check in broken:
        by_sub.setdefault(name, [])

    for sub in sub_strands or []:
        if not isinstance(sub, dict):
            continue
        name = str(sub.get("sub_strand_name") or sub.get("name") or "")
        if name not in by_sub:
            continue
        kept = []
        for rubric in sub.get("assessment_rubrics") or []:
            if not isinstance(rubric, dict) or not rubric.get("indicator"):
                kept.append(rubric)
                continue
            if check_one(name, sub.get("slos") or [], rubric):
                findings = check_one(name, sub.get("slos") or [], rubric)
                if any(f.severity == "error" for f in findings):
                    continue
            kept.append(rubric)
        sub["assessment_rubrics"] = kept
    return report
