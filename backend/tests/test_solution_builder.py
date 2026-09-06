"""A worked solution, not an answer key.

A marking scheme that says "B" teaches nobody anything, and a teacher marking
thirty scripts with it cannot award part marks.
"""
from __future__ import annotations

from app.services import solution_builder


def test_the_engine_derives_the_working_rather_than_a_model_guessing_it() -> None:
    """The engine's dispatcher reads plain text and questions arrive carrying
    LaTeX, which is the whole reason it ever solves anything asked this way."""
    worked = solution_builder.build(
        {"question_text": "What is -3 + 5?", "question_type": "short_answer"})

    assert worked.source == "engine"
    assert worked.verified is True, "checked, not asserted"
    assert worked.answer == "2"
    assert worked.steps[0].kind == solution_builder.CALCULATION
    assert "-3 + 5 = 2" in worked.steps[0].text
    assert worked.steps[0].why, "and why the step is allowed"


def test_the_sign_rule_is_carried_as_the_reason() -> None:
    worked = solution_builder.build(
        {"question_text": "Find the product of -4 and 6",
         "question_type": "short_answer"})

    assert worked.source == "engine"
    assert worked.answer == "-24"
    assert "negative" in " ".join(s.why.lower() for s in worked.steps)


def test_an_engine_that_did_not_solve_it_does_not_claim_to() -> None:
    """A stub that returns "Solved" with `verified: True` is how a maths engine
    stops being worth having."""
    worked = solution_builder.build(
        {"question_text": "Discuss the role of the mitochondrion.",
         "question_type": "essay",
         "model_answer": "It releases energy from food.",
         "marking_scheme": "Names respiration (1 mark). States ATP (1 mark)."})

    assert worked.source == "authored"
    assert worked.verified is False
    assert [s.marks for s in worked.steps] == [1.0, 1.0]


def test_the_authors_marks_survive_onto_an_engine_solution() -> None:
    """The engine derives the route; it does not award marks. Both belong on
    the page."""
    worked = solution_builder.build({
        "question_text": "What is -3 + 5?", "question_type": "short_answer",
        "marking_scheme": "Correct sign reasoning (1 mark)\nCorrect value (1 mark)"})

    assert worked.source == "engine"
    assert sum(s.marks for s in worked.steps) == 2.0


def test_authored_working_is_split_from_its_justification() -> None:
    worked = solution_builder.build({
        "question_text": "Discuss.", "question_type": "essay",
        "marking_scheme": "3 x 4 = 12 (a positive times a positive is positive)"})

    assert worked.steps[0].text == "3 x 4 = 12"
    assert worked.steps[0].why == "a positive times a positive is positive"
    assert worked.steps[0].kind == solution_builder.CALCULATION


def test_multiple_choice_names_the_option_and_the_traps() -> None:
    worked = solution_builder.build({
        "question_type": "multiple_choice", "question_text": "Pick one.",
        "correct_answer": "B",
        "options": [{"id": "A", "text": "-8", "rationale": "Subtracts instead."},
                    {"id": "B", "text": "2", "is_correct": True},
                    {"id": "C", "text": "8"}],
        "marking_scheme": "B. 2 (1 mark)"})

    assert worked.chosen == "B. 2"
    assert [d["option"] for d in worked.distractors] == ["A"], \
        "an option with no rationale is not invented one"


def test_a_question_with_no_answer_is_reported_not_filled_in() -> None:
    """A marking scheme that quietly makes an answer up is worse than a blank."""
    worked = solution_builder.build(
        {"question_text": "Discuss photosynthesis.", "question_type": "essay"})

    assert worked.source == "none"
    assert not worked.complete
    assert "cannot be marked" in worked.note


def test_an_option_with_no_working_is_flagged_as_teaching_nothing() -> None:
    worked = solution_builder.build({
        "question_type": "multiple_choice", "question_text": "Pick one.",
        "correct_answer": "B",
        "options": [{"id": "B", "text": "2", "is_correct": True}]})

    assert worked.chosen == "B. 2"
    assert "told nothing by this" in worked.note


def test_marks_written_in_the_scheme_are_read_off_it() -> None:
    for text, expected in (("Names the organ (2 marks)", 2.0),
                           ("States the rule [3 mks]", 3.0),
                           ("Correct value (1 mark)", 1.0)):
        worked = solution_builder.build(
            {"question_text": "Discuss.", "question_type": "essay",
             "marking_scheme": text})
        assert worked.steps[0].marks == expected, text
        assert "mark" not in worked.steps[0].text.lower()


def test_nothing_at_all_does_not_raise() -> None:
    assert solution_builder.build({}).source == "none"
    assert solution_builder.build_all([None, {}, 5]) is not None
