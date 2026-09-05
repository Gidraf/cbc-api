"""A diagram question has to be able to reach the diagrams that exist.

    Q5 — diagram_based item 'q-grade-9-math-integers-…' has no diagram
    binding. A diagram question with no diagram cannot be printed.

Two reasons it could not bind, and the sub-strand had drawings the whole time.
The first is the same fault the book had: the binder was offered only the
visuals on the NEWEST diagram artifact version, and the page numbers its
figures across the whole lesson — 1.1 and 1.2 routinely live in different
versions. The second is a confidence floor applied where there was nothing to
choose between.
"""
from __future__ import annotations

import inspect

from app.services.diagram_binding import resolve_binding

LINE = {"asset_id": "ast_line", "diagram_title": "Number line from -10 to 10",
        "alt_text": "A number line."}
OPS = {"asset_id": "ast_ops", "diagram_title": "Basic operations on integers",
       "alt_text": "Four operations."}


def test_the_only_diagram_there_is_gets_the_question() -> None:
    """Refusing this threw away a written, answered question over a similarity
    score, with one diagram sitting right there on the page."""
    binding = resolve_binding(
        {"question_text": "Study the figure and state what it shows."},
        "diagram_based", [LINE])

    assert binding is not None
    assert binding.diagram_id == "ast_line"
    assert binding.binding_method == "only-one"


def test_a_choice_between_two_is_still_a_choice() -> None:
    """With more than one candidate a guess is a guess, and a question printed
    against the wrong figure is worse than one held back."""
    assert resolve_binding({"question_text": "Study the figure."},
                           "diagram_based", [LINE, OPS]) is None


def test_a_confident_match_still_wins_on_its_own_terms() -> None:
    binding = resolve_binding(
        {"question_text": "On the number line from -10 to 10, mark -4."},
        "diagram_based", [LINE, OPS])

    assert binding is not None and binding.diagram_id == "ast_line"
    assert binding.binding_method == "semantic"


def test_an_explicit_reference_beats_the_guessing() -> None:
    binding = resolve_binding({"diagram_ref": "ast_ops", "question_text": "x"},
                              "diagram_based", [LINE, OPS])

    assert binding is not None and binding.diagram_id == "ast_ops"
    assert binding.binding_method == "explicit"


def test_a_question_that_is_not_about_a_diagram_binds_nothing() -> None:
    assert resolve_binding({"question_text": "What is 5 + 3?"},
                           "short_answer", []) is None


def test_the_binder_is_offered_every_drawing_the_substrand_has() -> None:
    """Not only the visuals on the newest diagram version."""
    from app.routes import questions

    source = inspect.getsource(questions)
    generation = source.split("diagrams_list = [")[1][:1600]

    assert "lesson_assets.collect(" in generation
    assert '"asset_id": asset.get("asset_id")' in generation, "so it can bind explicitly"
    assert "known" in generation, "and the bundle's own copies are not duplicated"
    # Questions from the bundle alone beat no questions at all.
    assert "except Exception" in generation
