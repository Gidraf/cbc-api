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


# Layout is checked separately, below. The fixtures in this file are cut down
# to the one fault each test is about — a two-line example with no `because`
# is a shape defect in a real guide and is noise in a test about sign errors.
def _kinds(example: dict, grade: str = "grade-9",
           subject: str = "Mathematics") -> list[str]:
    return [f.kind for f in
            example_check.check([example], grade=grade, subject=subject).findings
            if f.kind != "solution_not_uniform"]


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
         "steps": [{"working": "-4 × 6 = -24",
                    "because": "a negative times a positive is negative"}],
         "answer": "-24"},
        {"statement": "Evaluate -15 ÷ 3 - (-2) × (-4) + 6",
         "steps": [{"working": "-5 - 8 + 6 = -7",
                    "because": "divide and multiply before adding"}],
         "answer": "-7"},
    ], grade="grade-9", subject="Mathematics").findings

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
    assert "Only 0 of 3 items reach Junior School" in below[0].says
    assert "a learner reads all of them" in below[0].says
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


# ── the set is judged on its typical example, not its hardest ───────────────


def test_a_guide_whose_typical_example_is_trivial_is_caught() -> None:
    """The rule was "does anything reach the grade", and it passed a Grade 9
    integers guide whose examples were 5 + 3, 3 - 5, 3 + 5 x 2, -4 + 6 x (-2),
    -300 + 300, 3 + 5 x 2 again, and -4 + 6 x (-2) - 3. It passed on the last
    one. A learner reads all seven."""
    report = example_check.check([
        {"statement": "5 + 3", "steps": [{"working": "5 + 3 = 8"}]},
        {"statement": "3 - 5", "steps": [{"working": "3 - 5 = -2"}]},
        {"statement": "Evaluate: 3 + 5 × 2",
         "steps": [{"working": "5 × 2 = 10"}, {"working": "3 + 10 = 13"}]},
        {"statement": "-4 + 6 × (-2) - 3",
         "steps": [{"working": "-16 - 3"}, {"working": "-19"}]},
    ], grade="grade-9", subject="Mathematics")

    said = next(f.says for f in report.findings if f.kind == "below_the_grade")
    assert "5 + 3" in said and "3 - 5" in said
    assert "primary-school work" in said


def test_single_digit_arithmetic_is_never_excused_by_a_harder_example() -> None:
    """`-4 x 6 = -24` is one operation and does a job. `5 + 3` is Grade 2 work
    six years down, and nothing at this grade reaches for it."""
    from app.services import task_demand

    report = task_demand.check_set([
        {"statement": "5 + 3", "steps": [{"working": "5 + 3 = 8"}]},
        {"statement": "Evaluate -15 ÷ 3 - (-2) × (-4) + 6",
         "steps": [{"working": "-5 - 8 + 6 = -7"}]},
        {"statement": "Evaluate -8 + 3 × (-4) - (-6) ÷ 2",
         "steps": [{"working": "-8 - 12 + 3 = -17"}]},
    ], "grade-9", "Mathematics")

    assert report.below and report.far_below == ["5 + 3"]
    assert not report.typical_below, "two of three DO reach the grade"


def test_an_expression_typed_on_two_lines_is_not_a_word_problem() -> None:
    """The multi-step escape exists for word problems. Writing the
    multiplication on one line and the addition on the next made a two-step
    item out of `3 + 5 x 2` — no brackets, no negative number, Grade 5 work
    counted as Grade 9 because it was typed on two lines."""
    from app.services import task_demand

    assert task_demand.check_item(
        {"statement": "Evaluate: 3 + 5 × 2",
         "steps": [{"working": "5 × 2 = 10"}, {"working": "3 + 10 = 13"}]},
        "grade-9", "Mathematics").below

    assert not task_demand.check_item(
        {"statement": "A trader buys 3 crates at KSh 450 each and sells each "
                      "crate at KSh 620. Find the profit.",
         "steps": [{"working": "3 × 450 = 1350"}, {"working": "3 × 620 = 1860"},
                   {"working": "1860 - 1350 = 510"}]},
        "grade-9", "Mathematics").below


# ── the same example twice ──────────────────────────────────────────────────


def test_the_same_example_worked_twice_is_reported() -> None:
    """A guide taught 3 + 5 x 2 in Lesson 2 and taught it again in Lesson 5.
    Each copy is full length and correct, so a check that reads forwards sees
    two good lessons."""
    report = example_check.check([
        {"statement": "Evaluate: 3 + 5 × 2", "steps": [{"working": "3 + 10 = 13"}]},
        {"statement": "Work out 3 + 5 × 2", "steps": [{"working": "3 + 10 = 13"}]},
    ], grade="grade-9", subject="Mathematics")

    repeats = [f for f in report.findings if f.kind == "repeated_example"]
    assert len(repeats) == 1
    assert "example 1 has already worked out" in repeats[0].says


def test_two_different_examples_are_not_a_repeat() -> None:
    report = example_check.check([
        {"statement": "Evaluate -15 ÷ 3 - (-2) × (-4) + 6",
         "steps": [{"working": "-5 - 8 + 6 = -7"}]},
        {"statement": "Evaluate -8 + 3 × (-4) - (-6) ÷ 2",
         "steps": [{"working": "-8 - 12 + 3 = -17"}]},
    ], grade="grade-9", subject="Mathematics")

    assert not [f for f in report.findings if f.kind == "repeated_example"]


# ── notation that prints as nonsense ────────────────────────────────────────


def test_an_unclosed_dollar_is_caught_before_it_reaches_a_page() -> None:
    report = example_check.check(
        [{"statement": r"Evaluate $(6 + 4) \times 2",
          "steps": [{"working": "20"}]}],
        grade="grade-9", subject="Mathematics")

    assert any(f.kind == "mangled_notation" for f in report.findings)


def test_two_operators_in_a_row_are_caught() -> None:
    report = example_check.check(
        [{"statement": r"$12 \times \times 2 - 3 + 1$", "steps": []}],
        grade="grade-9", subject="Mathematics")

    assert any("two operators in a row" in f.says for f in report.findings)


def test_sound_notation_is_not_reported() -> None:
    report = example_check.check(
        [{"statement": r"Evaluate $\dfrac{-15 \div 3 - (-2) \times (-4) + 6}"
                       r"{-2 \times 3 + (-4)}$",
          "steps": [{"working": r"$-5 - 8 + 6 = -7$"}]}],
        grade="grade-9", subject="Mathematics")

    assert not [f for f in report.findings if f.kind == "mangled_notation"]


# ── a negative on a quantity that cannot be negative ────────────────────────


def test_negative_survey_counts_are_caught() -> None:
    """There is no such thing as -15 people preferring coffee. A category is
    not a sign, and a learner told otherwise writes negative frequencies in a
    data-handling paper."""
    report = example_check.check([{
        "statement": "Survey preferences",
        "steps": [{"because": "In a survey, if more people prefer tea over "
                              "coffee, we represent tea as a positive integer "
                              "and coffee as a negative."}]}],
        grade="grade-9", subject="Mathematics")

    assert any(f.kind == "impossible_negative" for f in report.findings)


def test_shillings_in_a_recipe_are_caught() -> None:
    report = example_check.check([{
        "statement": "Cooking",
        "steps": [{"because": "When cooking, if a recipe requires you to "
                              "subtract KES 20 for ingredients you already "
                              "have, you are using integers."}]}],
        grade="grade-9", subject="Mathematics")

    assert any(f.kind == "impossible_negative" for f in report.findings)


@pytest.mark.parametrize("example", [
    {"statement": "The temperature falls from 5°C to -3°C",
     "steps": [{"working": "-3 - 5 = -8"}]},
    {"statement": "A diver descends to -30 m below sea level",
     "steps": [{"working": "-30 + 12 = -18"}]},
    {"statement": "An account is overdrawn by KSh 400",
     "steps": [{"working": "-400 + 950 = 550"}]},
])
def test_a_genuinely_signed_context_is_left_alone(example: dict) -> None:
    """Temperature, altitude and money owed are the contexts this sub-strand
    exists to teach. Flagging them would empty the lesson."""
    report = example_check.check([example], grade="grade-9",
                                 subject="Mathematics")

    assert not [f for f in report.findings if f.kind == "impossible_negative"]


# ── every worked example checked, step by step, against the engine ──────────


def test_a_wrong_step_is_named_where_it_happens() -> None:
    """A Grade 9 guide wrote "-(-2) x (-4) = 2 x 4 = 8". The term is -8: the
    minus was distributed onto one factor and the sign flipped twice. Every
    step after it inherited the error, so naming the total is not enough."""
    report = example_check.check([{
        "statement": "(-15 / 3 - (-2) * (-4) + 6) / (-2 * 3 + (-4))",
        "steps": [{"working": "-15 / 3 = -5", "because": "a negative over a positive"},
                  {"working": "-((-2) * (-4)) = 8", "because": "two negatives"},
                  {"working": "-5 + 8 + 6 = 9", "because": "adding the results"}],
        "answer": "-9/10"}], grade="grade-9", subject="Mathematics")

    wrong = [f for f in report.findings if f.kind == "step_is_wrong"]
    assert wrong and "step 2" in wrong[0].says
    assert "is -8" in wrong[0].says


def test_an_answer_that_stops_at_the_numerator_is_caught() -> None:
    """The same expression in another lesson worked the numerator correctly to
    -7, wrote the denominator down, and reported -7 as the value of the
    fraction. Every step was right and the answer was wrong."""
    report = example_check.check([{
        "statement": "(-15 / 3 - (-2) * (-4) + 6) / (-2 * 3 + (-4))",
        "steps": [{"working": "-15 / 3 = -5", "because": "divide"},
                  {"working": "(-2) * (-4) = 8", "because": "two negatives"},
                  {"working": "-5 - 8 = -13", "because": "subtract"},
                  {"working": "-13 + 6 = -7", "because": "add"}],
        "answer": "-7"}], grade="grade-9", subject="Mathematics")

    assert [f.kind for f in report.findings if f.kind == "answer_disagrees"]


def test_a_correct_example_is_left_alone() -> None:
    report = example_check.check([{
        "statement": "(-15 / 3 - (-2) * (-4) + 6) / (-2 * 3 + (-4))",
        "steps": [{"working": "-15 / 3 = -5", "because": "divide first"},
                  {"working": "(-2) * (-4) = 8", "because": "two negatives give a positive"},
                  {"working": "-5 - 8 + 6 = -7", "because": "combine the numerator"},
                  {"working": "-2 * 3 + (-4) = -10", "because": "the denominator"}],
        "answer": "7/10"}], grade="grade-9", subject="Mathematics")

    assert not [f for f in report.findings
                if f.kind in ("step_is_wrong", "answer_disagrees")]


# ── one shape, every example ────────────────────────────────────────────────


def test_an_example_with_no_answer_is_reported() -> None:
    report = example_check.check(
        [{"statement": "Evaluate -15 ÷ 3 - (-2) × (-4) + 6",
          "steps": [{"working": "-5 - 8 + 6 = -7", "because": "combine"}]}],
        grade="grade-9", subject="Mathematics")

    said = [f.says for f in report.findings if f.kind == "solution_not_uniform"]
    assert said and "final answer" in said[0]


def test_a_step_with_no_reason_is_reported() -> None:
    report = example_check.check(
        [{"statement": "Evaluate -15 ÷ 3 - (-2) × (-4) + 6",
          "steps": [{"working": "-5 - 8 + 6 = -7"}], "answer": "-7"}],
        grade="grade-9", subject="Mathematics")

    assert any("no reason given" in f.says for f in report.findings)


def test_display_maths_inside_a_sentence_is_reported() -> None:
    """"First, adding $$-5$$ and $$8$$ gives $$3$$" prints as prose and centred
    numbers alternating down the page, one line each."""
    report = example_check.check(
        [{"statement": "Evaluate -15 ÷ 3 + 6",
          "steps": [{"working": "-5 + 6 = 1",
                     "because": "First, adding $$-5$$ and $$6$$ gives $$1$$."}],
          "answer": "1"}], grade="grade-9", subject="Mathematics")

    assert any("staircase" in f.says for f in report.findings)


def test_the_renderer_will_not_build_a_staircase_even_if_one_is_authored() -> None:
    from app.services.notes_renderer import _inline_math, _math

    sentence = "First, adding $$-5$$ and $$8$$ gives $$3$$."

    assert _math(sentence).count("data-display='true'") == 3
    assert _inline_math(sentence).count("data-display='true'") == 0
