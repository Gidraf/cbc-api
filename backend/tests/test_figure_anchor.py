"""Figures go where the text promises them, and carry their own brief.

Written from a page that read "Integers can be illustrated on a number line as
shown below" while the number line sat three hundred words earlier, beside a
different paragraph — and from empty plates that said "diagram to be placed
here" and nothing more.
"""
from __future__ import annotations

from app.services.asset_requirements import Requirement
from app.services.figure_anchor import anchor, brief_for, by_segment

SEGMENTS = [
    {"topic": "What is an integer?",
     "body": "An integer is a positive whole number, a negative whole number, "
             "or zero. Examples: 2, -3, 5, 0, 7."},
    {"topic": "The number line",
     "body": "A number line is a pictorial representation of numbers on a "
             "straight line. Integers can be illustrated on a number line as "
             "shown below. Any integer is less than every integer to the right."},
    {"topic": "Comparing integers",
     "body": "The symbols < and > denote less than and greater than."},
]


def _req(what: str, kind: str = "diagram", topic: str = "") -> Requirement:
    return Requirement(kind=kind, what=what, module_number=1,
                       module_title="Integers", topic=topic)


def test_a_figure_lands_on_the_paragraph_that_promises_it() -> None:
    placed = anchor([_req("a number line from -6 to +6 marked at every integer")],
                    SEGMENTS)

    assert placed[0].segment_index == 2, "the 'as shown below' paragraph"
    assert placed[0].explicit


def test_plurals_do_not_break_the_match() -> None:
    """The requirement says "number line", the paragraph says "numbers" and
    "integers". Without stemming this landed on the wrong paragraph."""
    placed = anchor([_req("number line showing integers")], SEGMENTS)
    assert placed[0].segment_index == 2


def test_figures_spread_out_before_they_stack() -> None:
    """Four diagrams must not all pile onto the one paragraph that happens to
    say "diagram"."""
    reqs = [_req("a number line from -6 to +6"),
            _req("integers shown as positive and negative whole numbers"),
            _req("the symbols for less than and greater than")]
    grouped = by_segment(anchor(reqs, SEGMENTS))

    assert len(grouped) >= 2, f"all three landed together: {grouped}"


def test_a_figure_nothing_names_leads_the_lesson() -> None:
    placed = anchor([_req("a photograph of a Nairobi street market", kind="image")],
                    SEGMENTS)

    assert placed[0].segment_index == 0
    assert "no segment named it" in placed[0].reason


def test_an_empty_plate_carries_a_brief_somebody_can_act_on() -> None:
    brief = brief_for(
        _req("a number line from -6 to +6 marked at every integer",
             topic="The number line"),
        grade_label="Grade 9", subject="Mathematics", strand="Numbers",
        sub_strand="Integers", lesson_title="Introduction to Integers",
        nearby_text=SEGMENTS[1]["body"],
    )

    # Everything a person needs to commission the drawing without coming back.
    assert "Grade 9" in brief and "Mathematics" in brief
    assert "Numbers" in brief and "Integers" in brief
    assert "Introduction to Integers" in brief
    assert "-6 to +6" in brief
    assert "as shown below" in brief, "the text it must match"
    assert "photocopy" in brief, "the style constraint"
    assert "pitched at Grade 9" in brief


def test_each_kind_asks_for_the_right_thing() -> None:
    for kind, phrase in (("diagram", "labelled diagram"),
                         ("image", "photograph"),
                         ("video", "video clip"),
                         ("simulation", "interactive simulation")):
        assert phrase in brief_for(_req("something", kind=kind))


def test_the_renderer_places_and_briefs_them() -> None:
    from app.services.notes_renderer import render_html

    html = render_html(
        {"title": "Integers", "modules": [{
            "title": "Introduction to Integers",
            "exposition_segments": SEGMENTS,
            "resources_needed": [
                "a number line diagram from -6 to +6 marked at every integer"],
        }]},
        grade="Grade 9", subject="Mathematics", strand="Numbers",
        sub_strand="Integers",
    )

    assert "copy-brief" in html, "the plate offers its prompt"
    assert "pitched at Grade 9" in html, "and the prompt is complete"
    # The figure sits inside the segment that promised it, not before it.
    second = html.split("<div class='seg'>")[2]
    assert "<figure" in second


# ── what the page shows when the picture EXISTS ─────────────────────────────

def test_a_filed_diagram_replaces_the_placeholder() -> None:
    """Neither route that renders a guide ever passed `assets`, so every figure
    printed as a hatched plate — including ones already generated and filed."""
    from app.services.notes_renderer import render_html

    notes = {"title": "Integers", "modules": [{
        "title": "Introduction to Integers",
        "lesson_flow": [
            {"phase": "The number line", "minutes": 15,
             "what_the_teacher_does": "Integers can be illustrated on a number "
                                      "line as shown below."}],
        "resources_needed": ["a number line diagram from -6 to +6"],
    }]}
    assets = {"a number line diagram from -6 to +6": {
        "kind": "diagram", "title": "Number line", "url": "", "alt": "A number line",
        "svg": "<svg viewBox='0 0 10 10'><line x1='0' y1='5' x2='10' y2='5'/></svg>"}}

    filled = render_html(notes, grade="Grade 9", subject="Mathematics", assets=assets)
    empty = render_html(notes, grade="Grade 9", subject="Mathematics")

    assert "<svg" in filled and "class='plate'" not in filled
    assert "class='plate'" in empty, "and still a plate when nothing is filed"


def test_lesson_flow_is_read_as_the_teaching_text() -> None:
    """The renderer read `exposition_segments`, which the schema has never
    produced — so the segment path was dead for every real guide."""
    from app.services.notes_renderer import _segments

    segments = _segments({"lesson_flow": [
        {"phase": "Introduction", "minutes": 5,
         "what_the_teacher_does": "Recall what a whole number is.",
         "what_learners_do": "Give examples."}]})

    assert len(segments) == 1
    assert segments[0]["topic"] == "Introduction"
    assert "whole number" in segments[0]["body"]
    assert segments[0]["learners"] == "Give examples."


def test_a_guide_with_neither_still_renders_its_exposition() -> None:
    from app.services.notes_renderer import _segments

    segments = _segments({"teacher_exposition": "Integers include zero."})
    assert len(segments) == 1 and "zero" in segments[0]["body"]
