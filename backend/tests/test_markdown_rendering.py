"""Markdown the model writes, rendered rather than printed.

A Grade 9 Integers page came back reading

    **Addition**: To add integers, combine their values.
    **Example**:
    -2 + 3 = 1.

with the asterisks on the page. Models write Markdown because that is how
models write emphasis and structure, and nothing here converted any of it.
"""
from __future__ import annotations

import re

import pytest

from app.services.notes_renderer import _is_a_calculation, _math, _spoken


# ── inline ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("source, expected", [
    ("**Addition**: combine their values.", "<strong>Addition</strong>"),
    ("**Example**:", "<strong>Example</strong>"),
    ("__also bold__ here", "<strong>also bold</strong>"),
    ("This is *important* to know.", "<em>important</em>"),
    ("This is _important_ too.", "<em>important</em>"),
    ("Enter `5 + (-3)` and press equals.", "<code>5 + (-3)</code>"),
])
def test_inline_markdown_is_rendered(source: str, expected: str) -> None:
    assert expected in _math(source)


def test_no_asterisks_survive_to_the_page() -> None:
    assert "*" not in _math("**Addition**: To add integers, combine values.")


@pytest.mark.parametrize("source", [
    "Work out 3 * 4 and then 5 * 2.",       # multiplication, not emphasis
    "snake_case_name stays intact",         # an underscore inside a word
    "5 * 3 = 15",
])
def test_what_is_not_emphasis_is_left_alone(source: str) -> None:
    out = _math(source)
    assert "<em>" not in out and "<strong>" not in out, out


def test_markup_a_model_writes_cannot_become_markup() -> None:
    """Escaping happens BEFORE the Markdown pass, so a tag stays a tag's worth
    of text no matter how it is wrapped."""
    out = _math("**<script>alert(1)</script>**")

    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "<strong>" in out, "the emphasis still renders around it"


def test_code_spans_keep_their_contents_literal() -> None:
    out = _math("Type `**not bold**` exactly.")
    assert "<code>**not bold**</code>" in out


# ── block ───────────────────────────────────────────────────────────────────

def test_a_heading_becomes_a_heading() -> None:
    out = _spoken("### Rules for signs")
    assert "class='mdh'" in out
    assert "Rules for signs" in out
    assert "#" not in out


def test_headings_never_outrank_the_page() -> None:
    """The page owns h1-h3. A model's `#` must not compete with the lesson."""
    for hashes in ("#", "##", "###"):
        out = _spoken(f"{hashes} A heading")
        assert re.search(r"<h[456]", out), out


def test_a_bullet_list_becomes_a_list() -> None:
    out = _spoken("- A negative times a negative is positive.\n"
                  "- A positive times a negative is negative.")

    assert out.count("<li>") == 2
    assert "ul class='points'" in out
    assert "- A negative" not in out


def test_consecutive_bullets_are_one_list() -> None:
    out = _spoken("- one\n- two\n- three")
    assert out.count("<ul") == 1 and out.count("<li>") == 3


def test_a_blank_line_closes_the_list() -> None:
    out = _spoken("- one\n- two\n\nSome prose.\n\n- three")
    assert out.count("<ul") == 2


def test_a_horizontal_rule_is_a_rule() -> None:
    assert "<hr" in _spoken("Before\n---\nAfter")


# ── the bare calculations the model wrote as prose ──────────────────────────

@pytest.mark.parametrize("line", [
    "-2 + 3 = 1.", "5 - 3 = 2.", "-4 × 2 = -8.", "12 ÷ (-3) = -4",
])
def test_a_line_that_is_only_a_calculation_is_typeset(line: str) -> None:
    assert _is_a_calculation(line), line
    assert "data-display='true'" in _spoken(line)


@pytest.mark.parametrize("line", [
    "1.",                                   # a list marker, not a sum
    "2024.",                                # a year
    "This results in 1.",                   # prose that ends in a number
    "Integers include 2, -3, 5, 0, and 7.", # a list of examples
    "Page 13.",
])
def test_prose_is_not_mistaken_for_a_calculation(line: str) -> None:
    assert not _is_a_calculation(line), line


def test_the_page_from_the_report_renders_clean() -> None:
    """The exact content that prompted this, end to end."""
    from app.services.notes_renderer import render_material_html

    say = ("**Addition**: To add integers, combine their values.\n"
           "**Example**:\n-2 + 3 = 1.\n"
           "### Rules for signs\n"
           "- A negative times a negative is *positive*.\n"
           "**Example**:\n-4 × 2 = -8.")

    html = render_material_html(
        {"material": [{"module_number": 1, "topic": "Integers", "say": say}]},
        grade="grade-9", subject="Mathematics", sub_strand="Integers")

    body = re.search(r"<div class='say'>(.*?)</div>\s*(?:<details|<div class='aside)",
                     html, re.S)
    rendered = body.group(1) if body else html

    assert "**" not in rendered
    assert "###" not in rendered
    assert rendered.count("<strong>") == 3
    assert "<em>positive</em>" in rendered
    assert "class='mdh'" in rendered
    assert "ul class='points'" in rendered
