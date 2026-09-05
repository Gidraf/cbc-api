"""Worked solutions computed by the engine, for a booklet a mathematician reads.

The engine could solve fractions, equations, areas and percentages, and could
not solve `-3 + 5`. So a Grade 9 sub-strand called Integers — every exercise in
it a signed-number calculation — got no worked solutions at all.
"""
from __future__ import annotations

import pytest

from app.services import worked_solutions
from app.services.math_engine import solve_math_problem
from app.services.math_engine.solvers.integers import (
    NotArithmetic,
    arithmetic_in,
    solve_integer_expression,
)


# ── the arithmetic the whole sub-strand is made of ──────────────────────────

@pytest.mark.parametrize("expression, answer", [
    ("-3 + 5", "2"),
    ("7 + (-2)", "5"),
    ("-6 - (-2)", "-4"),
    ("8 + (-2) + (-5)", "1"),
    ("(-3) * (-4) + 10", "22"),
    ("3 + 5 - 2 * 4", "0"),          # BODMAS: not 12
    ("-12 / -4", "3"),
    ("(-3) * 4", "-12"),
    ("10 - 4 + 2", "8"),             # left to right, not 4
])
def test_a_signed_calculation_is_worked_correctly(expression: str, answer: str) -> None:
    trace = solve_integer_expression(expression)

    assert trace.final_answer == answer, trace.final_answer
    assert trace.steps, "a worked solution shows its working"


def test_every_step_carries_the_rule_that_produced_it() -> None:
    """"now we multiply" does not teach a sign rule, and sign rules are exactly
    what a learner gets wrong."""
    trace = solve_integer_expression("(-3) * (-4) + 10")

    assert all(step.explanation for step in trace.steps)
    assert "negative" in trace.steps[0].explanation.lower()


@pytest.mark.parametrize("expression, phrase", [
    ("7 + (-2)", "adding a negative"),
    ("-6 - (-2)", "subtracting a negative"),
    ("(-3) * (-4)", "negative multiplied by a negative"),
])
def test_the_reason_names_the_actual_rule(expression: str, phrase: str) -> None:
    trace = solve_integer_expression(expression)
    assert any(phrase in s.explanation.lower() for s in trace.steps), \
        [s.explanation for s in trace.steps]


def test_a_negative_after_an_operator_is_bracketed_not_bare() -> None:
    """`6 + -5` is not how anyone writes it."""
    trace = solve_integer_expression("8 + (-2) + (-5)")
    written = " ".join(step.latex for step in trace.steps)

    assert "+ (-5)" in written
    assert "+ -" not in written


@pytest.mark.parametrize("text", ["hello there", "x + y", "", "   "])
def test_text_that_is_not_a_calculation_is_refused(text: str) -> None:
    with pytest.raises((NotArithmetic, ValueError)):
        solve_integer_expression(text)


# ── finding the calculation inside a sentence ───────────────────────────────

@pytest.mark.parametrize("sentence, expected", [
    ("Determine (-3) * (-4) + 10.", "(-3) * (-4) + 10"),
    ("What is the result of 7 + (-2)?", "7 + (-2)"),
    ("Calculate the sum of -3 and 5.", "-3 + 5"),
    ("Find the difference between -4 and 3.", "-4 - 3"),
    ("Subtract 5 from 12.", "12 - 5"),
    ("Multiply -6 by 3.", "-6 * 3"),
])
def test_the_calculation_is_found_however_it_is_phrased(sentence: str, expected: str) -> None:
    """CBC exercises are full of "the sum of -3 and 5" — a calculation carrying
    no operator at all, which no expression scanner would ever find."""
    assert arithmetic_in(sentence) == expected


def test_prose_with_no_calculation_yields_nothing() -> None:
    assert arithmetic_in("List three real-life uses of integers.") == ""


# ── through the dispatcher ──────────────────────────────────────────────────

@pytest.mark.parametrize("question, answer", [
    (r"Calculate the sum of $-3$ and $5$.", "2"),
    (r"What is the result of $7 + (-2)$?", "5"),
    (r"Determine $(-3) \times (-4) + 10$.", "22"),
])
def test_the_console_shapes_reach_the_new_solver(question: str, answer: str) -> None:
    trace = solve_math_problem(question)

    assert not trace.unsolved, question
    assert trace.final_answer == answer


def test_a_fraction_still_goes_to_the_solver_that_knows_fractions() -> None:
    """The arithmetic solver runs LAST, so it takes only what nothing else
    claimed — otherwise it would strip the fractions and work the digits."""
    trace = solve_math_problem(r"Work out $\frac{2}{3} + \frac{1}{4}$.")

    assert trace.final_answer == r"\frac{11}{12}"
    assert any("common" in s.explanation.lower() for s in trace.steps)


# ── what the booklet gets ───────────────────────────────────────────────────

def test_a_solved_exercise_comes_back_with_working_and_a_check() -> None:
    solution = worked_solutions.solve(r"Determine $(-3) \times (-4) + 10$.")

    assert solution.solved and solution.verified
    assert solution.answer == "22"
    assert len(solution.lines) == 2
    assert all(line.latex for line in solution.lines)
    assert solution.lines[0].because


def test_an_exercise_the_engine_cannot_work_returns_nothing_invented() -> None:
    """A booklet with eight of eleven solutions, honestly marked, is worth more
    than one with eleven of eleven and three of them wrong."""
    solution = worked_solutions.solve("List three real-life uses of integers.")

    assert not solution.solved
    assert solution.lines == []
    assert solution.answer == ""
    assert solution.why_not


def test_the_service_never_raises_on_rubbish() -> None:
    for text in ("", "   ", "?!?!", "\\frac{"):
        assert worked_solutions.solve(text).solved is False


def test_an_answer_somebody_else_wrote_can_be_checked() -> None:
    agreed = worked_solutions.check(r"$7 + (-2)$", "5")
    assert agreed["checked"] and agreed["agrees"] is True

    wrong = worked_solutions.check(r"$7 + (-2)$", "9")
    assert wrong["checked"] and wrong["agrees"] is False


# ── the page ────────────────────────────────────────────────────────────────

def _booklet(monkeypatch, questions: list[str]) -> str:
    from app.services import question_dna
    from app.services.notes_renderer import render_html

    monkeypatch.setattr(
        question_dna.question_dna_service, "list_questions",
        lambda **kw: [{"content": {"question_text": q, "max_marks": 2}} for q in questions],
    )
    return render_html({"title": "Integers", "modules": [
        {"title": "Lesson 1", "teacher_exposition": "Integers include zero."}]},
        grade="grade-9", subject="Mathematics", sub_strand="Integers")


def test_the_booklet_prints_the_working_not_just_the_answers(monkeypatch) -> None:
    html = _booklet(monkeypatch, [r"Determine $(-3) \times (-4) + 10$.",
                                  r"What is $7 + (-2)$?"])

    assert "Worked solutions" in html
    assert html.count("class='solution'") == 2
    assert "negative multiplied by a negative" in html
    assert "class='ok'" in html, "and says which were checked"


def test_an_unworked_question_is_numbered_rather_than_skipped(monkeypatch) -> None:
    """A gap in a numbered solutions section sends a learner hunting for a page
    that is not there."""
    html = _booklet(monkeypatch, [r"What is $7 + (-2)$?",
                                  "List three uses of integers."])

    assert "Question 2 is not a calculation this engine works" in html


def test_no_solutions_section_when_nothing_could_be_worked(monkeypatch) -> None:
    html = _booklet(monkeypatch, ["Describe two uses of a magnet.",
                                  "Explain why the sky is blue."])

    assert "class='solutions'" not in html


def test_the_solutions_are_set_in_columns(monkeypatch) -> None:
    html = _booklet(monkeypatch, [r"What is $7 + (-2)$?"])
    assert ".solutions, .exercise > ol { column-count: 2;" in html
