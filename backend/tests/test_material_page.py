"""The material page, from a Grade 9 Integers guide that showed every bug at once.

    temperatures can be below zero, such as -5^\\text{°C}      raw LaTeX
    if you have $50 and you spend $20  ->  "50andyouspend20"   currency eaten
    Calculate the sum of  −3−3  and  55                        MathML not hidden
    Introduction to Integers 10 min one of: explanation, ...   the schema echoed
    Where these words come from: written here for this lesson  no citation
"""
from __future__ import annotations

import pytest

from app.services.notes_renderer import _bare, _is_maths, _math, render_material_html


# ── what counts as mathematics ──────────────────────────────────────────────

@pytest.mark.parametrize("body", ["5 + (-3)", r"\frac{11}{12}", "-3", "x", "x^2", "a < b"])
def test_real_mathematics_is_typeset(body: str) -> None:
    assert _is_maths(body), body


@pytest.mark.parametrize("body", [
    "50 and you spend ",          # the exact string that broke the page
    "20 for lunch and ",
    " leading space",
    "",
])
def test_prose_between_two_prices_is_not(body: str) -> None:
    assert not _is_maths(body), body


def test_two_prices_in_a_sentence_survive_intact() -> None:
    text = "if you have $50 and you spend $20, your balance is $30"
    assert _math(text) == text, "nothing was typeset, and nothing was eaten"


def test_a_latex_command_with_no_dollars_is_still_typeset() -> None:
    """The schema asks for `$…$`. Models write `-5^\\text{°C}` mid-sentence."""
    out = _math(r"below zero, such as -5^\text{°C}, or above zero")

    assert "class='math'" in out
    assert r"\text" not in out.replace(r"-5^\text{°C}", ""), "only inside the span"


def test_plain_prose_is_left_alone() -> None:
    text = "No mathematics at all in this sentence."
    assert _math(text) == text
    assert _bare(text) == text


# ── the page ────────────────────────────────────────────────────────────────

PLAN = {"modules": [{
    "module_number": 1, "title": "Lesson 1: Basic Operations on Integers",
    "resources_needed": ["a number line diagram from -6 to +6",
                         "a short video clip showing temperature below zero"],
}]}

MATERIAL = {"material": [{
    "module_number": 1, "module_title": "Lesson 1: Basic Operations on Integers",
    "topic": "Introduction to Integers", "minutes": 10, "form": "explanation",
    "instruction": "Define integers and give examples.",
    "say": r"An integer is a whole number. Thus $-2 < -1$.",
    "learner_does": "Learners listen.",
    "citation": {"ref": "202:14", "quote": "carry out operations on integers"},
}]}


def _page(**kw) -> str:
    return render_material_html(
        MATERIAL, grade="grade-9", subject="Mathematics", strand="Numbers",
        sub_strand="Integers", version=3, **kw)


def test_the_mathml_copy_is_hidden_even_with_no_network() -> None:
    """KaTeX writes the expression twice and hides one with its stylesheet. On
    a server with no route to the CDN both showed, and every expression read
    "−3−3". The hiding rule is inlined so the page is right offline."""
    html = _page()

    assert ".katex-mathml" in html
    assert "clip: rect(1px, 1px, 1px, 1px)" in html
    assert "katex.min.css" in html, "the full sheet is still linked when reachable"


def test_the_page_is_set_in_columns() -> None:
    assert "column-count: 2" in _page()


def test_a_figure_the_plan_names_gets_its_place_and_its_prompt() -> None:
    """The material is what a teacher reads while holding up the picture."""
    html = _page(plan=PLAN)

    assert "<figure" in html
    assert "copy-brief" in html, "an unmade figure carries the prompt to make it"
    assert "pitched at grade-9" in html, "and the prompt names the grade"


def test_a_figure_that_exists_is_shown_instead_of_a_plate() -> None:
    filled = _page(plan=PLAN, assets={
        "a number line diagram from -6 to +6": {
            "kind": "diagram", "title": "Number line", "url": "", "alt": "n",
            "svg": "<svg viewBox='0 0 10 10'><line x1='0' y1='5' x2='10' y2='5'/></svg>"}})

    assert "<svg" in filled
    # The video is still outstanding, so one plate remains.
    assert filled.count("class='plate'") == 1


def test_the_plan_parameter_is_not_clobbered_by_the_page_metadata() -> None:
    """`plan = material.get("from_plan")` overwrote the parameter holding the
    plan's content, and every figure silently vanished."""
    html = render_material_html(
        {**MATERIAL, "from_plan": {"artifact_id": "art_x", "version": 1}},
        grade="grade-9", subject="Mathematics", sub_strand="Integers",
        plan=PLAN,
    )

    assert "<figure" in html, "the figures survived the metadata line"
    assert "from plan version 1" in html, "and the metadata still renders"


def test_a_citation_says_which_page_of_which_design() -> None:
    html = _page()

    assert "grade-9 · Mathematics · Numbers · Integers" in html
    assert "page 202" in html and "line 14" in html
    assert "carry out operations on integers" in html


def test_words_of_our_own_are_not_dressed_up_as_the_design() -> None:
    html = render_material_html(
        {"material": [{"module_number": 1, "topic": "x", "say": "words",
                       "attribution": "written here for this lesson"}]},
        grade="grade-9", subject="Mathematics",
    )

    assert "Not quoted from the design" in html


# ── the prompt that produced the mess ───────────────────────────────────────

def test_the_schema_no_longer_offers_its_own_menu_as_a_value() -> None:
    """`"form": "one of: {{ forms }}"` came back verbatim and printed on the
    page: "10 min one of: explanation, story, song, prayer, ...".
    """
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    prompt = SEED_AGENT_PROMPTS["material-generator"]

    assert '"form": "one of: {{ forms }}"' not in prompt
    assert '"form": "explanation"' in prompt
    assert "form` IS ONE WORD" in prompt
    assert "{{ forms }}" in prompt, "the list is still given, as instruction"


def test_the_prompt_asks_for_shillings_and_a_real_citation() -> None:
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    prompt = SEED_AGENT_PROMPTS["material-generator"]

    assert "MONEY IS IN SHILLINGS" in prompt
    assert '"citation"' in prompt and '"ref"' in prompt and '"quote"' in prompt
    assert "NAME YOUR OWN LESSON" in prompt
