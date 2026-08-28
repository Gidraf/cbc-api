"""An essence statement is a paragraph, not the rest of the design.

The compiled note-generator prompt ran to 114,703 characters — 28,675 tokens —
for a 31,689-character design. The design was in there three times: once as the
source excerpt, and twice more because the stored "essence statement" WAS the
whole document, injected by the template and again by the appended directive.

This is the context-duplication defect the chunker was built to prevent,
arriving through a field nobody suspected.
"""
from __future__ import annotations

import re

import pytest

from app.services.curriculum_extractor import MAX_ESSENCE_CHARS, _extract_essence_statement

_RENDERED = (
    "200:10  Essence Statement\n"
    "200:12  Christian Religious Education at Pre-Primary level aims at teaching\n"
    "200:13  children about God. This is based on Proverbs 22:6.\n"
    "200:19  foundation for learning CRE at Pre-primary 2.\n"
    "[PAGE 201]\n"
    "201:2  Subject General Learning Outcomes\n"
    "201:4  a) Demonstrate an awareness of the love of God.\n"
    + "".join(f"2{2+i:02d}:1  a further page of design text, line {i}\n" for i in range(40))
)


def test_the_statement_stops_at_the_next_heading() -> None:
    essence = _extract_essence_statement(_RENDERED)

    assert "Proverbs 22:6" in essence
    assert "Pre-primary 2" in essence
    assert "General Learning Outcomes" not in essence
    assert "further page of design text" not in essence


def test_the_old_pattern_really_did_swallow_the_document() -> None:
    """Every line of a rendered design starts with its "200:12  " address, so
    the old lookahead — a line of four or more capitals — never matched, and the
    capture ran to the end."""
    old = re.search(
        r"ESSENCE STATEMENT\s*\n+(.*?)(?=\n+[A-Z\s]{4,}\n|\Z)",
        _RENDERED, re.DOTALL | re.IGNORECASE,
    )

    assert old is not None
    assert len(old.group(1)) > len(_extract_essence_statement(_RENDERED)) * 5
    assert "line 39" in old.group(1), "the old pattern reached the last line"


def test_a_heading_it_does_not_know_cannot_swallow_the_document() -> None:
    """A hard ceiling, because the list of headings will never be complete."""
    runaway = "200:10  Essence Statement\n" + "".join(
        f"2{i:03d}:1  {'x' * 200}\n" for i in range(300)
    )

    assert len(_extract_essence_statement(runaway)) <= MAX_ESSENCE_CHARS


def test_a_page_break_inside_the_paragraph_does_not_end_it() -> None:
    across = (
        "200:10  Essence Statement\n"
        "200:12  The first half of the statement.\n"
        "[PAGE 201]\n"
        "201:1  The second half of the statement.\n"
        "201:2  Summary of Strands and Sub-Strands\n"
    )

    essence = _extract_essence_statement(across)

    assert "first half" in essence and "second half" in essence
    assert "Summary of Strands" not in essence


def test_a_design_with_no_essence_statement_returns_nothing() -> None:
    assert _extract_essence_statement("200:1  Summary of Strands\n") == ""


@pytest.mark.parametrize("heading", [
    "Subject General Learning Outcomes",
    "Summary of Strands and Sub-Strands",
    "STRAND 1.0: CREATION",
    "LESSON ALLOCATION FOR PRE-PRIMARY",
    "Suggested Assessment Rubric",
])
def test_each_known_heading_ends_the_statement(heading) -> None:
    text = f"200:10  Essence Statement\n200:12  The statement itself.\n201:1  {heading}\n201:2  after\n"

    essence = _extract_essence_statement(text)

    assert "The statement itself." in essence
    assert heading not in essence


# ── The contradictions in the same prompt ───────────────────────────────────

def _profile(insights):
    from app.services.content_type_classifier import ContentTypeProfile

    return ContentTypeProfile(
        content_type="cre", persona="A CRE teacher educator.",
        note_style="Structured lesson plans.", diagram_type="Pictures.",
        activity_type="Songs and role-play.", question_type="Oral questions.",
        safety_focus="Supervise nature walks.",
        subject="Christian Religious Education", grade="grade-pp1",
        empirical_insights=insights,
    )

def test_profile_figures_are_not_headed_verified() -> None:
    """The profile block said "Verified Subject Data (use these, do not invent
    statistics)" for the same numbers the research dossier calls unverified and
    forbids. Two blocks in one prompt giving opposite instructions about one set
    of numbers is worse than either alone."""
    from app.services.content_type_classifier import ContentTypeProfile

    profile = _profile([{"metric": "children who can identify qualities of God",
                         "value": "85%", "source": "KICD 2022 Report"}])
    block = profile.format_for_prompt()

    assert "Verified Subject Data" not in block
    assert "NOT VERIFIED" in block
    assert "unverified, claimed: KICD 2022 Report" in block


def test_an_invented_source_does_not_become_a_permitted_one() -> None:
    """The permitted list was DERIVED from those figures, so a source a model
    invented arrived stamped "permitted" — which laundered the fabrication."""
    from app.services.content_type_classifier import ContentTypeProfile

    profile = _profile([{"metric": "x", "value": "85%", "source": "KICD 2022 Report"}])
    block = profile.format_for_prompt()

    assert "Permitted Citation Sources: KICD 2022 Report" not in block
    assert "never one named above" in block
    assert "cite the KICD curriculum design, by page and line" in block
