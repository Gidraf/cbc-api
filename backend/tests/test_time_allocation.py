"""The design's own time figure, read rather than assumed.

`allocated_hours` holds what the design printed — "7 lessons" for pre-primary,
"4 hours" for DTE. Treating that string as a number produced one instruction
carrying three different quantities: "7 lessons CONTACT HOURS (240 minutes)"
and "GENERATE ALL 7 lessons HOUR MODULES (Hour 1 … Hour 4)".
"""
from __future__ import annotations

import pytest

from app.services.time_allocation import parse


def test_pre_primary_lessons_stay_lessons() -> None:
    allocation = parse("7 lessons", "grade-pp1")

    assert (allocation.count, allocation.unit) == (7, "lessons")
    assert allocation.minutes_each == 30, "a PP1 lesson is 30 minutes, not 60"
    assert allocation.total_minutes == 210
    assert allocation.modules == 7, "seven lessons means seven modules, not four"


def test_hours_stay_hours() -> None:
    allocation = parse("4 hours", "dte-1")

    assert allocation.unit == "hours"
    assert allocation.minutes_each == 60
    assert allocation.total_minutes == 240


def test_a_missing_figure_is_a_gap_not_a_four() -> None:
    """Defaulting to 4 wrote a fabricated allocation that was indistinguishable
    afterwards from one KICD actually published."""
    allocation = parse("", "grade-pp1")

    assert not allocation.known
    assert allocation.phrase() == "not stated in the design"
    assert allocation.modules == 1, "one module, not four invented hours"
    assert allocation.total_minutes == 0


def test_a_bare_number_takes_the_grade_s_own_unit() -> None:
    assert parse("9", "grade-pp2").unit == "lessons"


@pytest.mark.parametrize("stated", ["7 lessons", "( 8 lessons)", "8 Lessons", "(9 lessons)"])
def test_the_designs_bracketing_and_case_do_not_matter(stated) -> None:
    assert parse(stated, "grade-pp1").unit == "lessons"


def test_the_phrase_never_converts_the_designs_own_words() -> None:
    allocation = parse("7 lessons", "grade-pp1")

    assert allocation.phrase().startswith("7 lessons")
    assert allocation.stated == "7 lessons"


def test_an_absurd_figure_cannot_demand_absurd_output() -> None:
    assert parse("400 lessons", "grade-pp1").modules == 12
