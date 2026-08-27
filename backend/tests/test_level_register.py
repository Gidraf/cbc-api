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


def test_every_grade_gets_a_different_register_not_a_shared_band_one() -> None:
    """PP1 and PP2 were identical, as were Grades 1/2/3 and 4/5/6. A band is not
    a grade: content pitched the same at Grade 1 and Grade 3 is wrong for one."""
    from app.services.curriculum_catalogue import all_grade_slugs

    blocks = {g: register_block(g) for g in all_grade_slugs()}
    assert len(set(blocks.values())) == len(blocks), "some grades share a register"

    # The pairs that used to collide.
    assert blocks["grade-pp1"] != blocks["grade-pp2"]
    assert blocks["grade-1"] != blocks["grade-3"]
    assert blocks["grade-10"] != blocks["grade-12"]


def test_age_is_a_per_grade_fact_not_a_band_one() -> None:
    """PP2 inherited "4-5 years old" from the Pre-Primary band."""
    assert register_for_grade("grade-pp1").typical_ages == "4-5 years old"
    assert register_for_grade("grade-pp2").typical_ages == "5-6 years old"
    assert register_for_grade("grade-1").typical_ages == "6-7 years old"
    assert register_for_grade("grade-12").typical_ages == "17-18 years old"
    assert "adult" in register_for_grade("grade-dte").typical_ages


@pytest.mark.parametrize(
    ("grade", "year", "prev", "nxt"),
    [
        ("grade-pp1", "first of 2 years of Pre-Primary", "", "PP2"),
        ("grade-pp2", "second of 2 years of Pre-Primary", "PP1", "Grade 1"),
        ("grade-1", "first of 3 years of Lower Primary", "PP2", "Grade 2"),
        ("grade-3", "third of 3 years of Lower Primary", "Grade 2", "Grade 4"),
        ("grade-9", "third of 3 years of Junior School", "Grade 8", "Grade 10"),
        ("grade-12", "third of 3 years of Senior School", "Grade 11", ""),
    ],
)
def test_each_grade_knows_where_it_sits_in_the_progression(
    grade: str, year: str, prev: str, nxt: str
) -> None:
    r = register_for_grade(grade)
    assert r.year_in_level == year
    assert r.builds_on == prev
    assert r.prepares_for == nxt


def test_the_progression_forbids_re_teaching_and_pre_empting() -> None:
    block = register_block("grade-pp2")
    assert "arrive having completed PP1; do not re-teach it" in block
    assert "go on to Grade 1; do not pre-empt its content" in block


def test_dte_trainees_are_not_promoted_from_grade_12() -> None:
    """They are adults entering a diploma, so "do not re-teach Grade 12" would
    be the wrong instruction."""
    r = register_for_grade("grade-dte")
    assert r.builds_on == ""
    assert r.prepares_for == ""
    assert "do not re-teach" not in register_block("grade-dte")


def test_pp1_carries_the_scope_its_own_design_states() -> None:
    notes = " ".join(register_for_grade("grade-pp1").grade_notes)
    assert "letter SOUNDS only" in notes
    assert "do not read or write words" in notes
    assert "Nothing beyond 10" in notes
    assert "30 minutes each" in notes


def test_pp2_states_what_the_pp1_design_supports_and_no_more() -> None:
    """The PP1 design says three-letter words are a PP-level outcome, and PP1
    itself only does sounds — so that work belongs to PP2. Everything past
    that must be read from the PP2 design, not guessed."""
    notes = " ".join(register_for_grade("grade-pp2").grade_notes)
    assert "three-letter words belong to PP2, not PP1" in notes
    assert "read the PP2 design" in notes


def test_a_grade_whose_design_is_unread_says_so_instead_of_inventing_one() -> None:
    """An invented "Grade 5 covers fractions to 1/8" reads exactly like a real
    one, and there is no way to tell them apart afterwards."""
    for grade in ("grade-5", "grade-8", "grade-11"):
        notes = register_for_grade(grade).grade_notes
        assert notes == [
            "The specific content for this grade must be read from its own KICD "
            "design document. Do not carry over another grade's scope."
        ], grade
