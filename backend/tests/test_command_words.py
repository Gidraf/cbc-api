"""What a task ASKS for, ranked — the difficulty measure for subjects with no
arithmetic in them.

`task_demand` measures the shape of an expression, which is the whole story in
Mathematics and no story at all in History, CRE or English. There, a question
can be long, well written, correctly cited and still ask for nothing harder
than a list. What separates a hard question from an easy one is its command
word, and the KICD designs are written in those verbs.
"""
from __future__ import annotations

import pytest

from app.services import command_words as cw


def _stems(*texts: str) -> list[dict]:
    return [{"stem": t} for t in texts]


# ── placing a task on the ladder ────────────────────────────────────────────


@pytest.mark.parametrize("stem,name", [
    ("List three causes of soil erosion.", "recall"),
    ("Describe how rain forms.", "understand"),
    ("Calculate the total cost of the goods.", "apply"),
    ("Compare farming in Nyeri with farming in Turkana.", "analyse"),
    ("Evaluate the effect of the policy on small traders.", "evaluate"),
    ("Design an experiment to test the hypothesis.", "create"),
])
def test_each_command_word_lands_on_its_rung(stem: str, name: str) -> None:
    rung = cw.rung_of(stem)

    assert rung and rung.name == name


def test_the_hardest_verb_governs_not_the_first() -> None:
    """A learner who only describes has not answered "describe and evaluate",
    and a marker marking it knows that even though the easy verb comes first."""
    rung = cw.rung_of("Describe the process and evaluate its effect.")

    assert rung and rung.name == "evaluate"


def test_a_longer_phrase_beats_the_word_inside_it() -> None:
    """"Explain why" is an analysis. Reading it as "explain" ranks a Grade 9
    question one rung below what it actually asks for."""
    assert cw.rung_of("Explain why the leaves turn yellow.").name == "analyse"


def test_a_task_with_no_command_word_is_counted_but_not_ranked() -> None:
    spread = cw.spread(_stems("The mitochondrion.", "List two organelles."))

    assert spread.measured == 2 and spread.unverbed == 1


# ── the floor ───────────────────────────────────────────────────────────────


def test_the_youngest_are_not_asked_to_evaluate() -> None:
    """Demanding a judgement of a four-year-old is the same error as demanding
    brackets of them."""
    assert cw.floor_for("grade-pp1") is None


@pytest.mark.parametrize("grade,top", [
    ("grade-2", 2), ("grade-5", 3), ("grade-9", 4), ("grade-12", 5),
])
def test_each_level_has_to_reach_its_own_rung(grade: str, top: int) -> None:
    floor = cw.floor_for(grade)

    assert floor and floor.top == top


def test_a_set_that_never_leaves_the_bottom_of_the_ladder_is_caught() -> None:
    report = cw.check_set(_stems(
        "List three uses of water.", "Name two rivers in Kenya.",
        "State the capital city of Kenya.", "Identify the largest lake."),
        "grade-9")

    assert report.below
    assert "recall" in report.says()
    assert "compare" in report.fix()


def test_one_task_at_the_top_carries_the_set() -> None:
    """A paper needs its opener. What is wrong is a set whose HARDEST task
    never leaves the bottom."""
    report = cw.check_set(_stems(
        "List three causes of soil erosion.",
        "Describe how terracing reduces it.",
        "Compare terracing with contour ploughing on a steep slope."),
        "grade-9")

    assert not report.below


def test_two_tasks_are_not_failed_for_not_spanning_three_rungs() -> None:
    """A set of two cannot spread across three. Reporting that as a defect is
    reporting arithmetic as a defect, and a gate that does it once gets turned
    off."""
    report = cw.check_set(_stems(
        "Calculate the profit made on the sale.",
        "Evaluate whether the trader should change supplier."), "grade-9")

    assert not report.below


def test_an_empty_set_is_not_below_anything() -> None:
    assert not cw.check_set([], "grade-9").below


def test_a_generated_profile_overrides_the_ladder() -> None:
    """A design says what it asks for better than a general ladder can. A
    sub-strand whose own outcomes stop at "describe" must not be failed for
    not reaching "analyse"."""
    tasks = _stems("Describe the parts of a flower.",
                   "Name the part that makes pollen.")

    assert cw.check_set(tasks, "grade-9").below
    assert not cw.check_set(tasks, "grade-9",
                            required={"top": 2, "distinct": 2}).below


def test_a_profile_cannot_raise_the_bar_off_the_ladder() -> None:
    report = cw.check_set(_stems("List two things."), "grade-9",
                          required={"top": 99})

    assert report.floor and report.floor.top == 4, "an impossible rung is ignored"


# ── the prompt says what the gate measures ──────────────────────────────────


def test_the_block_is_rendered_from_the_same_ladder_it_measures() -> None:
    """Two lists that mean to agree and are maintained apart do not stay
    agreeing."""
    block = cw.block_for("grade-9")

    for rung in cw.LADDER:
        assert rung.name.upper() in block
        assert rung.verbs[0] in block
    assert "rung 4" in block


def test_the_block_never_suggests_a_spelling_the_house_style_forbids() -> None:
    block = cw.block_for("grade-12")

    assert "analyze" not in block and "summarize" not in block
    assert "analyse" in block and "summarise" in block


def test_a_us_spelling_is_still_recognised_when_a_model_writes_one() -> None:
    """Not suggesting it and not seeing it are different things."""
    assert cw.rung_of("Analyze the data.").name == "analyse"


def test_the_youngest_get_no_block_rather_than_an_impossible_one() -> None:
    assert cw.block_for("grade-pp1") == ""
