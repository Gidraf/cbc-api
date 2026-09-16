"""A marking scheme a learner can read.

The engine writes LaTeX. Handed to the page unmarked, the renderer treated
each `\\times` as a loose fragment and typeset "(2 \\times" and "150) \\div"
as separate spans, so a printed step read

    5^3 - (120 + (5) = 5^3 - (5)

— brackets unclosed, operands out of order, the power a caret.
"""
from __future__ import annotations

import re

from app.services import solution_builder
from app.services.notes_renderer import _math


def _mcq(stem: str, key: str = "14") -> dict:
    return {"question_text": stem, "question_type": "multiple_choice",
            "options": [{"id": "A", "text": key, "is_correct": True},
                        {"id": "B", "text": "-4"}]}


def test_each_engine_step_is_one_math_span():
    worked = solution_builder.build(_mcq(r"Work out $(2 \times 5^3 - (40 \times 3 + 30)) \div 5$", "20"))
    assert worked.steps, "the engine must work this"
    for step in worked.steps:
        html = _math(step.text)
        spans = re.findall(r"<span class='math'[^>]*>(.*?)</span>", html)
        assert len(spans) == 1, f"one span per step, got {len(spans)}: {html}"
        # Nothing of the step is left outside the span to print as raw text.
        assert re.sub(r"<[^>]+>", "", html).strip() == spans[0].strip()
        assert "^" not in re.sub(r"<span class='math'.*?</span>", "", html), "no bare caret on the page"
        assert spans[0].count("(") == spans[0].count(")"), f"unbalanced: {spans[0]}"


def test_the_engine_reaches_the_documented_answer():
    worked = solution_builder.build(_mcq(r"Work out $-16 + (-28) \div 4 \times (-3) - (-9)$"))
    assert worked.answer == "14" or worked.steps[-1].text.rstrip("$").endswith("14")


def test_the_sign_rule_describes_the_numbers_on_the_line():
    """(−28) ÷ 4 is a negative divided by a positive. The scheme said
    "A positive divided by a negative", which is a different sum."""
    worked = solution_builder.build(_mcq(r"Work out $-16 + (-28) \div 4 \times (-3) - (-9)$"))
    division = next(s for s in worked.steps if "div" in s.text)
    assert division.why == "A negative divided by a positive gives a negative."

    times = next(s for s in worked.steps if "times" in s.text and "div" not in s.text)
    assert times.why == "A negative multiplied by a negative gives a positive."


def test_a_positive_times_a_negative_is_not_called_a_negative_times_a_positive():
    from fractions import Fraction

    from app.services.math_engine.solvers.integers import _reason

    f = Fraction
    assert _reason(f(6), "*", f(-3), f(-18)) == "A positive multiplied by a negative gives a negative."
    assert _reason(f(-6), "*", f(3), f(-18)) == "A negative multiplied by a positive gives a negative."
    assert _reason(f(-28), "/", f(4), f(-7)) == "A negative divided by a positive gives a negative."
    assert _reason(f(28), "/", f(-4), f(-7)) == "A positive divided by a negative gives a negative."


def test_the_scheme_is_not_printed_twice_when_it_became_the_working():
    """"M1 for setting up −18 + 12 − 5 + 8; A1 for final position −3 m"
    appeared as step one and again underneath it, word for word."""
    from app.services.question_paper import _scheme_item

    scheme = "M1 for setting up -18 + 12 - 5 + 8; A1 for final position -3 m"
    html = _scheme_item({
        "question_text": "A diver descends. Where does she end up?",
        "question_type": "multiple_choice",
        "marking_scheme": scheme,
        "model_answer": scheme + ".",
        "options": [{"id": "A", "text": "-3 m", "is_correct": True},
                    {"id": "B", "text": "-6 m"}],
    }, 8)
    assert html.count("A1 for final position") == 1, html
