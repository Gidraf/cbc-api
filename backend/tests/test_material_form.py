"""The material's SHAPE follows the band, not just its reading level.

Written from one Grade 9 Mathematics lesson on Integers in which fourteen of
eighteen sections opened "Today, we are going to...", nothing was harder than
"3 + (-2)", and the learner was never once asked to work anything.
"""
from __future__ import annotations

import pytest

from app.services import material_form as mf


# The openings, verbatim, from that lesson.
G9 = {"material": [
    {"module_number": 1, "topic": "Introduction",
     "say": "Today, we are going to explore integers. Integers are whole numbers "
            "that can be positive, negative, or zero."},
    {"module_number": 1, "topic": "Operations",
     "say": "Today, we will explore the four basic operations with integers. "
            "Let's start with addition."},
    {"module_number": 1, "topic": "Applications",
     "say": "Today, we will explore how integers are used in our daily lives. "
            "Can anyone think of a situation? Yes, that's right! Exactly!"},
    {"module_number": 2, "topic": "Order of operations",
     "say": "Now, let's discuss the order of operations when working with integers."},
]}

TEXTBOOK = {"material": [
    {"module_number": 1, "topic": "What is an integer?",
     "say": "An integer is a positive whole number, a negative whole number, or "
            "zero. Examples: 2, -3, 5, 0, 7.\n\nExercise\n"
            "1. -5 and +1\n2. -3 and +4\n3. -7 and -9\n4. -20 and -36\n5. 1 and -25"},
]}


@pytest.mark.parametrize("grade, key, exercises", [
    ("grade-pp1", "spoken", False),
    ("grade-pp2", "spoken", False),
    ("grade-1", "spoken", False),
    ("grade-3", "spoken", False),
    ("grade-4", "guided", True),
    ("grade-6", "guided", True),
    ("grade-7", "exposition", True),
    ("grade-9", "exposition", True),
    ("grade-12", "exposition", True),
    ("grade-dte", "exposition", True),
])
def test_each_band_gets_its_own_form(grade: str, key: str, exercises: bool) -> None:
    form = mf.form_for(grade)
    assert form.key == key
    assert form.wants_exercises is exercises


def test_the_grade_9_material_that_prompted_this_fails_every_form_check() -> None:
    assert len(mf.announced(G9, "grade-9")) == 4, "all four announce the lesson"
    assert mf.staged(G9, "grade-9"), "one scripts a discussion and invents the replies"
    assert len(mf.unexercised(G9, "grade-9")) == 2, "neither lesson has practice"


def test_the_same_material_is_fine_for_pre_primary() -> None:
    """A teacher greeting a class of five-year-olds is not a defect. These
    checks must be band-specific or they become noise."""
    assert mf.announced(G9, "grade-pp1") == []
    assert mf.staged(G9, "grade-pp1") == []
    assert mf.unexercised(G9, "grade-pp1") == []


def test_a_textbook_page_with_exercises_passes() -> None:
    assert mf.announced(TEXTBOOK, "grade-9") == []
    assert mf.unexercised(TEXTBOOK, "grade-9") == []


def test_nothing_is_asserted_when_the_band_is_unknown() -> None:
    """`form_for` defaults to EXPOSITION so a prompt still says something
    useful. A FINDING on a guess is different, and would report "no exercises"
    for content whose grade simply was not passed."""
    assert not mf.band_known("")
    assert not mf.band_known("grade-42")
    for grade in ("", None, "grade-42"):
        assert mf.announced(G9, grade) == []
        assert mf.unexercised(G9, grade) == []


@pytest.mark.parametrize("grade", ["grade-pp1", "grade-5", "grade-9"])
def test_the_prompt_block_states_the_form_and_forbids_sameness(grade: str) -> None:
    block = mf.block_for(grade)
    form = mf.form_for(grade)

    assert form.band in block
    assert form.artifact in block
    assert "DO NOT WRITE EVERY PIECE THE SAME WAY" in block
    for rule in form.forbidden:
        assert rule in block


def test_the_exposition_block_names_the_exact_failure() -> None:
    block = mf.block_for("grade-9")
    assert "Today, we are going to explore" in block
    assert "EXERCISE SET" in block
