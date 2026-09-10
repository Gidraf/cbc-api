"""A blank badge read as approval.

`worked_solutions.check` solves the STATEMENT. A word problem has no
expression in its statement, so it declined — and the page rendered no badge
at all, which is the same thing an example with no mathematics in it shows.

Example 3.1 of a Grade 9 Integers guide was published under that blank:

    Calculate the final temperature if it drops from 10°C to -5°C and then
    rises by 12°C.
      10 - 5 + 12 = 7

The step is worth 17. The answer 7 happened to be right — the drop is 15, not
5 — so the only wrong thing on the page was the method, which is the part a
learner copies. `_arithmetic_faults` had caught it in the console all along;
nothing carried it to the page.
"""
from __future__ import annotations

import re

from app.services import worked_solutions
from app.services.notes_renderer import _worked_examples

_TEMPERATURE = {
    "statement": "Calculate the final temperature if it drops from 10°C to "
                 "-5°C and then rises by 12°C.",
    "steps": [{"working": "10 - 5 + 12 = 7", "because": "drop, then rise"}],
    "answer": "7°C",
}
_MONEY = {
    "statement": "If you have KSh 300, spend KSh 120, and then earn KSh 80, "
                 "what is your final amount?",
    "steps": [{"working": "300 - 120 + 80 = 260", "because": "spend, earn"}],
    "answer": "KSh 260",
}
_NO_MATHS = {
    "statement": "Discuss why integers matter in daily life.",
    "steps": [{"working": "no mathematics here"}],
    "answer": "many reasons",
}


def _badges(module: dict) -> list[str]:
    html = _worked_examples(module, 3)
    return [re.sub(r"<[^>]+>", " ", m).strip()
            for m in re.findall(r"<h4>(.*?)</h4>", html)]


def test_a_word_problem_is_checked_through_its_steps() -> None:
    verdict = worked_solutions.check_working(
        _TEMPERATURE["statement"], _TEMPERATURE["answer"],
        _TEMPERATURE["steps"])

    assert verdict["checked"], "the statement is prose; the steps are not"
    assert verdict["agrees"] is False
    assert verdict["step"] == 1
    assert verdict["engine_answer"] == "17"
    assert verdict["claimed"] == "7"


def test_a_word_problem_whose_steps_are_true_is_passed() -> None:
    verdict = worked_solutions.check_working(
        _MONEY["statement"], _MONEY["answer"], _MONEY["steps"])

    assert verdict["checked"] and verdict["agrees"] is True


def test_an_example_with_no_mathematics_is_not_silently_approved() -> None:
    verdict = worked_solutions.check_working(
        _NO_MATHS["statement"], _NO_MATHS["answer"], _NO_MATHS["steps"])

    assert not verdict["checked"]


def test_the_page_says_which_step_is_wrong() -> None:
    badges = _badges({"worked_examples": [_TEMPERATURE]})

    assert "step 1 does not reach" in badges[0], badges
    assert "checked</span>" not in badges[0]


def test_the_page_never_leaves_a_badge_blank() -> None:
    """Silence is what got read as approval. Every example says something."""
    badges = _badges({"worked_examples": [_TEMPERATURE, _MONEY, _NO_MATHS]})

    assert len(badges) == 3
    for badge in badges:
        assert re.sub(r"Example \d+\.\d+", "", badge).strip(), badge
    assert "not checked" in badges[2]


def test_the_wrong_method_is_explained_under_the_example() -> None:
    html = _worked_examples({"worked_examples": [_TEMPERATURE]}, 3)

    assert "Step 1 is wrong" in html
    assert "the method is what a learner copies" in html.lower()


def test_a_statement_that_can_be_read_is_still_preferred() -> None:
    """The statement check is the stronger one; steps are the fallback."""
    bare = {"statement": "Calculate 7 + (-4) - 2",
            "steps": [{"working": "7 + (-4) = 3"}, {"working": "3 - 2 = 1"}],
            "answer": "1"}

    verdict = worked_solutions.check_working(
        bare["statement"], bare["answer"], bare["steps"])

    assert verdict["checked"] and verdict["agrees"] is True
    assert verdict["step"] == 0, "the statement answered it; no step blamed"
