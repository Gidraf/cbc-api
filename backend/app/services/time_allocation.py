"""Read the design's own time figure without converting it into a lie.

`allocated_hours` holds what the design printed: "7 lessons" for pre-primary,
"4 hours" for DTE, sometimes nothing. Treating that string as a number produced
one instruction containing three different quantities —

    Allocated Syllabus Time: 7 lessons CONTACT HOURS (240 instructional minutes)
    YOU MUST GENERATE ALL 7 lessons COMPLETE HOUR MODULES (Hour 1 … Hour 4)

— and a PP1 lesson is 30 minutes, so even the minutes were wrong. The figure is
parsed here once, kept in the design's own unit, and only converted to minutes
where the grade's register says how long its unit is.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_COUNT = re.compile(r"(\d+(?:\.\d+)?)")
_UNITS = (
    ("lesson", "lessons"),
    ("period", "periods"),
    ("hour", "hours"),
    ("week", "weeks"),
    ("session", "sessions"),
)


@dataclass(slots=True)
class TimeAllocation:
    count: float = 0.0
    unit: str = ""
    minutes_each: int = 0
    stated: str = ""

    @property
    def known(self) -> bool:
        return bool(self.count and self.unit)

    @property
    def total_minutes(self) -> int:
        return int(self.count * self.minutes_each) if self.known and self.minutes_each else 0

    @property
    def modules(self) -> int:
        """How many teaching blocks to author. Never zero, never absurd."""
        return max(1, min(int(self.count), 12)) if self.known else 1

    def phrase(self) -> str:
        """The design's own words, for a prompt that must not paraphrase them."""
        if not self.known:
            return "not stated in the design"
        base = f"{self.count:g} {self.unit}"
        if self.total_minutes:
            return f"{base} ({self.minutes_each} minutes each, {self.total_minutes} minutes in total)"
        return base

    def to_dict(self) -> dict[str, Any]:
        return {
            "stated": self.stated, "count": self.count, "unit": self.unit,
            "minutes_each": self.minutes_each, "total_minutes": self.total_minutes,
            "modules": self.modules, "known": self.known,
        }


def parse(stated: Any, grade: str = "") -> TimeAllocation:
    """Read "7 lessons" as seven lessons, and "" as a gap rather than a four."""
    text = str(stated or "").strip()
    allocation = TimeAllocation(stated=text)
    if not text:
        return allocation

    number = _COUNT.search(text)
    if not number:
        return allocation
    allocation.count = float(number.group(1))

    lowered = text.lower()
    for singular, plural in _UNITS:
        if singular in lowered:
            allocation.unit = plural
            break
    else:
        # A bare number in a column headed by the design's own unit.
        allocation.unit = _default_unit(grade)

    if allocation.unit in ("lessons", "periods", "sessions"):
        allocation.minutes_each = _lesson_minutes(grade)
    elif allocation.unit == "hours":
        allocation.minutes_each = 60
    return allocation


def _register(grade: str):
    from .level_register import register_for_grade

    try:
        return register_for_grade(grade)
    except Exception:  # noqa: BLE001
        return None


def _default_unit(grade: str) -> str:
    register = _register(grade)
    return (getattr(register, "time_unit", "") or "lessons") if register else "lessons"


def _lesson_minutes(grade: str) -> int:
    register = _register(grade)
    return int(getattr(register, "lesson_minutes", 0) or 0) if register else 0
