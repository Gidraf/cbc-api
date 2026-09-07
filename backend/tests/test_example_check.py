"""Whether a worked example's arithmetic models what it describes.

A reviewer found three faults in one Grade 9 guide, and the maths engine
verified all three sums as correct:

    "temperature drops from 5°C to -3°C, so 5 + (-3) = 2"       5 + (-3) IS 2
    "a hiker climbs from 200 m to 50 m, so 200 + (-50) = 150"   200 + (-50) IS 150
    "-7 + 3 = -4, so adding a positive moves you closer to 0"   -7 + 3 IS -4

The change from 5 to -3 is a fall of 8. A hiker going from 200 m to 50 m has
descended. And -2 + 10 = 8 is further from zero, not closer. The arithmetic was
never the problem — the sentence saying what it represents was, and a solver
cannot see that because there is nothing wrong with the sum.
"""
from __future__ import annotations

import pytest

from app.services import example_check


def _kinds(example: dict, grade: str = "grade-9") -> list[str]:
    return [f.kind for f in example_check.check([example], grade=grade).findings]


# ── the three the reviewer found ────────────────────────────────────────────


def test_an_example_that_computes_a_different_question_is_caught() -> None:
    kinds = _kinds({
        "statement": "Calculate the temperature change when it drops from 5°C to -3°C.",
        "steps": [{"working": "5 + (-3) = 2"}], "answer": "2"})

    assert "models_the_wrong_thing" in kinds

    finding = example_check.check([{
        "statement": "Calculate the temperature change when it drops from 5°C to -3°C.",
        "steps": [{"working": "5 + (-3) = 2"}], "answer": "2"}],
        grade="grade-9").findings[0]
    assert "the change is -8" in finding.says
    assert "answers 2" in finding.says
    assert "final minus initial" in finding.fix


def test_a_story_going_the_other_way_from_its_numbers_is_caught() -> None:
    """"from an elevation of 200 metres to 50 metres" — words sit between
    "from" and its number, and a pattern demanding the number immediately
    after walked straight past it."""
    kinds = _kinds({
        "statement": "A hiker climbs from an elevation of 200 metres to 50 metres. "
                     "What is the change in elevation?",
        "steps": [{"working": "200 + (-50) = 150"}], "answer": "150"})

    assert "direction" in kinds


def test_a_rule_that_fails_on_the_second_case_is_caught() -> None:
    kinds = _kinds({
        "statement": "Work out -7 + 3",
        "steps": [{"working": "-7 + 3 = -4",
                   "because": "Adding a positive integer to a negative integer "
                              "always results in a value closer to zero."}],
        "answer": "-4"})

    assert "false_generalisation" in kinds
    finding = example_check.check([{
        "statement": "x", "steps": [{"because": "Adding a positive to a negative "
                                     "always results in a value closer to zero."}]}],
        grade="grade-9").findings[0]
    assert "-2 + 10 = 8" in finding.fix


# ── pitched for the grade ───────────────────────────────────────────────────


def test_single_digit_arithmetic_is_flagged_above_upper_primary() -> None:
    """Grade 9 is fourteen and fifteen years old. "7 - 4 = 3" is the reason a
    parent puts the booklet down."""
    assert _kinds({"statement": "Work out 7 - 4",
                   "steps": [{"working": "7 - 4 = 3"}], "answer": "3"}) == \
        ["below_the_grade"]


def test_the_same_sum_is_fine_lower_down() -> None:
    assert _kinds({"statement": "Work out 7 - 4",
                   "steps": [{"working": "7 - 4 = 3"}]}, grade="grade-3") == []


def test_a_multi_step_expression_is_not_read_as_a_single_digit_sum() -> None:
    """"-5 - 8 + 6 = -7" contains "8 + 6 = -7". Reading that as a single-digit
    sum condemned the one example pitched correctly for the grade."""
    assert _kinds({"statement": "Evaluate (-15 ÷ 3) - (-2 × -4) + 6",
                   "steps": [{"working": "-5 - 8 + 6 = -7"}], "answer": "-7"}) == []


def test_a_negative_number_is_not_a_single_digit() -> None:
    """`-7 + 3` is not a misread of `7 + 3`, and lower down it is fine as it is."""
    example = {"statement": "Work out -7 + 3",
               "steps": [{"working": "-7 + 3 = -4"}], "answer": "-4"}
    assert _kinds(example, grade="grade-3") == []
    # At Grade 9 the only complaint is that one addition is not the grade —
    # never that the arithmetic or the modelling is wrong, because neither is.
    assert _kinds(example) == ["below_the_grade"]


# ── it must not cry wolf ────────────────────────────────────────────────────


@pytest.mark.parametrize("example", [
    {"statement": "Evaluate -15 ÷ 3 - (-2) × (-4) + 6",
     "steps": [{"working": "-5 - 8 + 6 = -7"}], "answer": "-7"},
    {"statement": "A freezer at 18°C drops 3°C every 12 minutes. Find its "
                  "temperature after 2 hours.",
     "steps": [{"working": "18 - (10 × 3) = -12"}], "answer": "-12°C"},
])
def test_a_sound_grade_nine_example_passes(example: dict) -> None:
    assert _kinds(example) == [], example["statement"]


def test_the_one_simple_example_a_lesson_needs_is_not_condemned() -> None:
    """A guide teaching the sign rule NEEDS `-4 × 6 = -24` in it.

    Difficulty is a property of the SET. Failing the introductory example on
    its own is how a gate gets switched off, and then it catches nothing.
    """
    findings = example_check.check([
        {"statement": "Work out the product of -4 and 6",
         "steps": [{"working": "-4 × 6 = -24"}], "answer": "-24"},
        {"statement": "Evaluate -15 ÷ 3 - (-2) × (-4) + 6",
         "steps": [{"working": "-5 - 8 + 6 = -7"}], "answer": "-7"},
    ], grade="grade-9").findings

    assert [f.kind for f in findings] == []


def test_a_set_whose_hardest_item_is_one_addition_is_below_the_grade() -> None:
    """The reviewer's actual complaint: not one easy example, but a whole
    booklet whose hardest line was single-step arithmetic."""
    report = example_check.check([
        {"statement": "Work out 5 + (-3)", "steps": [{"working": "5 + (-3) = 2"}]},
        {"statement": "Work out -7 + 3", "steps": [{"working": "-7 + 3 = -4"}]},
        {"statement": "Work out 4 + (-9)", "steps": [{"working": "4 + (-9) = -5"}]},
    ], grade="grade-9")

    below = [f for f in report.findings if f.kind == "below_the_grade"]
    assert len(below) == 1
    assert "Nothing in these 3 items reaches Junior School" in below[0].says
    assert "\\dfrac" in below[0].fix


def test_a_change_correctly_worked_is_not_flagged() -> None:
    """The modelling is right, so nothing about the modelling is reported.
    One subtraction is still not Grade 9, and that is a separate finding."""
    kinds = _kinds({
        "statement": "Find the change in temperature from 5°C to -3°C.",
        "steps": [{"working": "-3 - 5 = -8"}], "answer": "-8"})
    assert "models_the_wrong_thing" not in kinds and "direction" not in kinds


def test_nothing_to_check_is_not_a_failure() -> None:
    report = example_check.check([], grade="grade-9")

    assert report.checked == 0 and report.clean


# ── the gate ────────────────────────────────────────────────────────────────


def test_a_miscast_example_fails_the_material_gate() -> None:
    """Not a score penalty. Printing a correct sum that answers a different
    question is the one defect a buyer notices and cannot forgive."""
    from app.services import lesson_material

    report = lesson_material.MaterialReport(total=1, written=1)
    report.miscast = [{"says": "The change is -8. This example answers 2.",
                       "fix": "Write it as final minus initial."}]

    gate = lesson_material.gate_of(report)

    assert gate["passed"] is False
    measure = next(f for f in gate["reviewer"]["feedback"]
                   if f["aspect"] == "examples_model_what_they_describe")
    assert measure["status"] == "fail"
    # And it is named first, with the fix attached.
    assert "answers 2" in gate["next_actions"][0]
    assert "final minus initial" in gate["next_actions"][0]


def test_a_clean_set_reports_the_measure_as_passing() -> None:
    from app.services import lesson_material

    gate = lesson_material.gate_of(
        lesson_material.MaterialReport(total=1, written=1))

    measure = next(f for f in gate["reviewer"]["feedback"]
                   if f["aspect"] == "examples_model_what_they_describe")
    assert measure["status"] == "pass"


def test_a_worked_example_is_not_judged_on_its_command_word() -> None:
    """A worked example demands nothing of the learner — it is the teacher
    showing a method. "Find its temperature after 2 hours" is a demonstration,
    and failing it for not saying "evaluate" would fail every worked example in
    every guide in the system.

    That half of the measure belongs on questions, activities and experiments,
    which do ask the learner something.
    """
    demonstration = {
        "statement": "A freezer at 18°C drops 3°C every 12 minutes. Find its "
                     "temperature after 2 hours.",
        "steps": [{"working": "18 - (10 × 3) = -12"}], "answer": "-12°C"}

    assert _kinds(demonstration) == []

    from app.services import command_words

    assert command_words.check_set([{"stem": demonstration["statement"]}],
                                   "grade-9").below, \
        "the same sentence IS below the bar as a question"
