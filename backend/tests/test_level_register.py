"""What may be asked of a learner follows from who the learner is.

Every authoring prompt here was written for a secondary agriculture student, and
few-shot examples set the register more strongly than abstract instructions do.
That is how a pre-primary sub-strand on greetings came back demanding a
flowchart from a child who cannot read, and a mandatory toxic-chemical audit for
a lesson about saying "good morning".
"""
from __future__ import annotations

import pytest

from app.services.level_register import register_block, register_for_grade


def test_pre_primary_forbids_what_a_four_year_old_cannot_do() -> None:
    r = register_for_grade("grade-pp1")

    assert r.level == "Pre-Primary"
    assert r.grade_label == "PP1"
    cannot = " ".join(r.cannot).lower()
    assert "read any written question" in cannot
    assert "flowchart" in cannot
    assert "chemicals" in cannot
    assert "laboratory" in cannot
    # The lesson is 30 minutes and the design counts lessons, not hours.
    assert r.time_unit == "lessons"
    assert r.lesson_minutes == 30
    assert r.uses_themes is True


def test_the_block_names_the_hours_trap_explicitly() -> None:
    """Every PP1 sub-strand came back as "4 hours"; the design states lessons."""
    block = register_block("grade-pp1")
    assert "lessons, not hours" in block
    assert "One lesson is 30 minutes" in block
    assert "never convert" in block.lower()


def test_pre_primary_examples_are_not_set_on_a_farm() -> None:
    block = register_block("grade-pp1")
    assert "self, family, home, neighbourhood, school" in block
    assert "Not farms, industry, counties or national development." in block


def test_dte_learners_are_adults_not_children() -> None:
    """Content written for a child would be wrong for a trainee teacher."""
    r = register_for_grade("grade-dte")

    assert r.level == "Tertiary"
    assert "ADULT" in r.audience
    assert "not children" in r.audience
    assert r.time_unit == "hours"
    assert "trainee teacher" in r.scenario_world


@pytest.mark.parametrize(
    ("grade", "level"),
    [
        ("grade-pp2", "Pre-Primary"),
        ("grade-1", "Lower Primary"),
        ("grade-3", "Lower Primary"),
        ("grade-4", "Upper Primary"),
        ("grade-6", "Upper Primary"),
        ("grade-7", "Junior School"),
        ("grade-9", "Junior School"),
        ("grade-10", "Senior School"),
        ("grade-12", "Senior School"),
    ],
)
def test_every_published_grade_resolves_to_its_level(grade: str, level: str) -> None:
    assert register_for_grade(grade).level == level


def test_only_junior_and_above_may_be_asked_for_lab_work() -> None:
    for grade in ("grade-pp1", "grade-2"):
        assert "no experiments" in register_for_grade(grade).practicals.lower() or \
               "everyday" in register_for_grade(grade).practicals.lower()
    for grade in ("grade-8", "grade-11"):
        assert "laborator" in register_for_grade(grade).practicals.lower() or \
               "practical" in register_for_grade(grade).practicals.lower()


def test_an_unknown_grade_does_not_fall_back_to_the_most_demanding_level() -> None:
    """Guessing upward is how a four-year-old ends up with a titration."""
    r = register_for_grade("grade-does-not-exist")

    assert r.level == "Unknown"
    assert "Do not assume fluent literacy" in r.literacy
    assert "Do not invent practical work" in r.practicals
    assert register_for_grade(None).level == "Unknown"
    assert register_for_grade("").level == "Unknown"


def test_grade_spelling_is_normalised_before_the_register_is_chosen() -> None:
    for spelling in ("pp1", "PP1", "grade-pp1", "Grade PP1"):
        assert register_for_grade(spelling).level == "Pre-Primary"
    for spelling in ("7", "grade 7", "GRADE-7"):
        assert register_for_grade(spelling).level == "Junior School"
