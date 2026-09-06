"""A question set as two documents, and the answers on exactly one of them.

Questions lived in the console as JSON: judging an item meant reading a field
at a time, and nobody ever saw what a learner would be handed — where the LaTeX
typesets or prints its own backslashes, where a diagram question has its figure
beside it, where three of five items ask the same thing.
"""
from __future__ import annotations

from app.services import question_paper, solution_builder

MCQ = {
    "question_type": "multiple_choice",
    "question_text": r"What is $-3 + 5$?",
    "correct_answer": "B",
    "options": [
        {"id": "A", "text": "-8"},
        {"id": "B", "text": "2", "is_correct": True},
        {"id": "C", "text": "8",
         "rationale": "Adds the sizes and ignores the signs."},
    ],
    "pedagogy": {"max_marks": 1},
    "marking_scheme": "B. 2, because -3 + 5 = 2 (1 mark)",
}

STRUCTURED = {
    "question_type": "structured",
    "question_text": "Work out the following.",
    "pedagogy": {"max_marks": 4},
    "structured_parts": [
        {"part_id": "(a)", "sub_question": r"$-4 \times 6$", "marks": 2},
        {"part_id": "(b)", "sub_question": "Explain the sign rule.", "marks": 2},
    ],
    "marking_scheme": "-4 x 6 = -24 (2 marks)\nA negative times a positive is negative (2 marks)",
    "model_answer": "-24",
}

PAGE = dict(grade="grade-9", subject="Mathematics", sub_strand="Integers")


def test_the_paper_carries_no_answer_anywhere() -> None:
    """The one thing worse than no marking scheme is a paper that turns out to
    have been one."""
    paper = question_paper.render_html([MCQ, STRUCTURED], answers=False, **PAGE)

    assert "Correct option" not in paper
    assert "Working" not in paper
    assert "-24" not in paper, "the model answer is not on the learner's copy"
    assert "Adds the sizes" not in paper, "nor the distractor rationale"
    assert "A negative times a positive" not in paper
    # But the questions themselves are all there.
    assert "What is" in paper and "Work out the following" in paper
    assert ">A.</span>" in paper.replace("'", '"') or "A." in paper


def test_a_written_question_gets_space_to_write_in() -> None:
    """A paper with nowhere to answer gets answered in the margin, and then it
    cannot be marked."""
    paper = question_paper.render_html([STRUCTURED], answers=False, **PAGE)
    scheme = question_paper.render_html([STRUCTURED], answers=True, **PAGE)

    assert "class='ruled'" in paper
    assert "class='ruled'" not in scheme, "the scheme is read, not written on"


def test_multiple_choice_is_not_given_ruled_lines() -> None:
    assert "class='ruled'" not in question_paper.render_html(
        [MCQ], answers=False, **PAGE)


def test_the_scheme_names_the_option_and_shows_why() -> None:
    """"B" is the answer and it is never the whole answer. A learner who chose
    C needs to know what C would have been the answer to."""
    scheme = question_paper.render_html([MCQ], answers=True, **PAGE)

    assert "Correct option" in scheme
    assert "Adds the sizes and ignores the signs" in scheme
    assert "class='steps'" in scheme


def test_latex_is_typeset_on_both_documents() -> None:
    """It is authored with `$-4 \\times 6$` in it, and printing the dollars and
    backslashes is what the guides used to do."""
    for answers in (False, True):
        html = question_paper.render_html([STRUCTURED], answers=answers, **PAGE)
        assert "katex" in html
        assert "class='math'" in html
        assert r"\times" in html, "handed to KaTeX, not escaped away"


def test_marks_are_printed_where_a_marker_needs_them() -> None:
    paper = question_paper.render_html([STRUCTURED], answers=False, **PAGE)

    assert "(4 marks)" in paper, "the question total"
    assert "(2 marks)" in paper, "and per part"
    assert "(1 mark)" in question_paper.render_html([MCQ], answers=False, **PAGE)


def test_a_diagram_question_prints_its_figure_beside_it() -> None:
    """A diagram question whose figure is on another page cannot be answered."""
    with_figure = {
        "question_type": "diagram_based",
        "question_text": "Name the part labelled A.",
        "pedagogy": {"max_marks": 1},
        "model_answer": "The numerator",
        "diagram": {"diagram_id": "ast_x", "diagram_title": "Fraction bar",
                    "svg_markup": "<svg viewBox='0 0 340 200'><text>A</text></svg>"},
    }
    paper = question_paper.render_html([with_figure], answers=False, **PAGE)

    assert "<svg" in paper, "inlined, so the paper works with no network"
    assert "figure-inline" in paper


def test_a_diagram_question_with_no_figure_says_so_rather_than_pretending() -> None:
    paper = question_paper.render_html([{
        "question_type": "diagram_based", "question_text": "Name part A.",
        "diagram": {"diagram_title": "Fraction bar"}}], answers=False, **PAGE)

    assert "Refer to Fraction bar" in paper


def test_an_empty_set_says_it_is_empty() -> None:
    assert "no questions in it" in question_paper.render_html([], **PAGE)


def test_the_header_counts_the_questions_and_the_marks() -> None:
    paper = question_paper.render_html([MCQ, STRUCTURED], answers=False, **PAGE)

    assert "2 questions" in paper
    assert "5 marks" in paper


def test_the_scheme_is_titled_as_one() -> None:
    assert "marking scheme" in question_paper.render_html(
        [MCQ], answers=True, **PAGE)


# ── the routes and the console ──────────────────────────────────────────────

import inspect  # noqa: E402
from pathlib import Path  # noqa: E402

FRONTEND = Path(__file__).resolve().parents[2] / "frontend-web"


def test_the_paper_and_the_scheme_are_separate_requests() -> None:
    from app.routes import questions

    source = inspect.getsource(questions.questions_paper_html)

    assert "answers: bool" in source
    assert "question_paper.render_html" in source
    assert "carries no answer anywhere" in source


def test_it_can_be_taken_away_as_a_file() -> None:
    """A classroom with no screen in it."""
    from app.routes import questions

    source = inspect.getsource(questions.questions_paper_pdf)

    assert "pdf.from_html" in source
    assert "marking-scheme" in source, "the filename says which document it is"


def test_the_station_offers_both_documents() -> None:
    factory = " ".join((FRONTEND / "src/views/ContentFactory.tsx").read_text().split())

    assert "Read the paper" in factory
    assert "Read the marking scheme" in factory
    assert 'station.id === "questions"' in factory
