r"""LaTeX inside JSON, which the parser used to silently corrupt.

`"$3 \times 4$"` is VALID JSON. It means `$3 <TAB>imes 4$`, and that is what
was printed in a Grade 9 mathematics lesson: "3 imes (-4) = -12".
"""
from __future__ import annotations

import json

import pytest

from app.services.json_latex import repair


@pytest.mark.parametrize("command", [
    "times", "text", "frac", "neq", "right", "begin", "underline", "bar",
    "theta", "forall", "nabla", "binom", "uparrow",
])
def test_a_latex_command_survives_the_round_trip(command: str) -> None:
    raw = '{"a": "$\\%s{x}$"}' % command
    assert json.loads(repair(raw))["a"] == "$\\%s{x}$" % command


@pytest.mark.parametrize("raw, expected", [
    (r'{"a": "$3 \times (-4) = -12$"}', r"$3 \times (-4) = -12$"),
    (r'{"a": "$A = \frac{1}{2}bh$"}', r"$A = \frac{1}{2}bh$"),
    (r'{"a": "$5^\text{°C}$"}', r"$5^\text{°C}$"),
    (r'{"a": "$\alpha + \pi$"}', r"$\alpha + \pi$"),
    (r'{"a": "$\left(\frac{a}{b}\right)$"}', r"$\left(\frac{a}{b}\right)$"),
])
def test_the_exact_shapes_that_reached_a_class(raw: str, expected: str) -> None:
    assert json.loads(repair(raw))["a"] == expected


def test_the_silent_corruption_is_what_this_is_for() -> None:
    """These parse WITHOUT the repair, which is why nothing caught them."""
    raw = r'{"a": "$3 \times 4$", "b": "$\frac{1}{2}$"}'

    broken = json.loads(raw)
    assert "\times" in broken["a"], "a tab, not a backslash"
    assert broken["b"].startswith("$\x0crac"), "a formfeed, not a backslash"

    fixed = json.loads(repair(raw))
    assert fixed["a"] == r"$3 \times 4$"
    assert fixed["b"] == r"$\frac{1}{2}$"


@pytest.mark.parametrize("raw", [
    r'{"a": "line\nbreak"}',
    r'{"a": "tab\there"}',
    r'{"a": "quote\"inside"}',
    r'{"a": "slash\/escaped"}',
    r'{"a": "back\\slash"}',
    r'{"a": "$3 \\times 4$"}',
    r'{"a": "é"}',
    '{"a": "plain text with no backslash"}',
])
def test_correct_json_is_returned_unchanged(raw: str) -> None:
    """The repair only ever ADDS backslashes where JSON has no escape. A model
    that got it right must not be punished for it."""
    assert json.loads(repair(raw)) == json.loads(raw)


def test_the_parser_uses_it_before_it_parses() -> None:
    """Not as a fallback on JSONDecodeError — the corrupting cases parse fine,
    so a repair that only ran after a failure would never fire for them."""
    from app.services.llm_client import llm_client

    out = llm_client._extract_and_parse_json(
        r'{"say": "For example, $3 \times (-4) = -12$ and $A = \frac{1}{2}bh$."}'
    )
    assert out["say"] == r"For example, $3 \times (-4) = -12$ and $A = \frac{1}{2}bh$."


def test_it_still_survives_fences_and_thinking() -> None:
    from app.services.llm_client import llm_client

    fenced = '```json\n{"a": "$\\times$"}\n```'
    assert llm_client._extract_and_parse_json(fenced)["a"] == r"$\times$"
