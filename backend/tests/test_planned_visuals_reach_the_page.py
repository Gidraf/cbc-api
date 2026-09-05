"""A diagram that exists has to have somewhere on the page to go.

The diagram station scored 100/100, the drawing was filed, and the book showed
nothing — because the page reserves a plate only for something the plan ASKED
for, and requirements were read from `resources_needed` and from the teaching
text only. A lesson that planned its visual in the field built for planning
visuals promised nothing at all.

The second half of the same bug: the title that did get through was classified
by its wording, and "Basic Operations on Integers" reads as an object to bring
to class rather than a picture to print.
"""
from __future__ import annotations

from app.services import asset_requirements, lesson_assets, notes_renderer

PLAN = {"modules": [{
    "title": "Lesson 1", "topic": "Integers", "module_number": 1,
    "teacher_exposition": "An integer is a whole number.",
    "exposition_segments": [
        {"topic": "Integers", "body": "An integer is a whole number."}],
    "visuals": [{"diagram_title": "Basic Operations on Integers",
                 "accessibility": {"alt_text": "Four operations on integers."}}],
}]}

MATERIAL = {"material": [{"module_number": 1, "module_title": "Lesson 1",
                          "topic": "Integers",
                          "say": "An integer is a whole number."}]}

DRAWN = [{"kind": "diagram", "title": "Basic Operations on Integers", "url": "",
          "svg": '<svg viewBox="0 0 340 200">'
                 '<text x="12" y="100" font-size="14">Counters</text></svg>',
          "alt": "Four operations on integers."}]

PAGE = dict(grade="grade-9", subject="Mathematics", strand="Numbers",
            sub_strand="Integers", version=1)


def test_a_visual_the_plan_names_is_a_requirement() -> None:
    wanted = asset_requirements.read(PLAN).items

    assert [(r.kind, r.what) for r in wanted] == [
        ("diagram", "Basic Operations on Integers")]
    assert wanted[0].source == "visuals"


def test_the_plan_s_own_structure_beats_guessing_from_the_wording() -> None:
    """`_classify` reads the words, and these words read as an object to bring
    to class — which reserves no plate, so the drawing had nowhere to go."""
    assert asset_requirements._classify("Basic Operations on Integers") != "diagram"
    assert asset_requirements.read(PLAN).items[0].kind == "diagram"


def test_a_visual_given_as_a_bare_string_still_counts() -> None:
    plan = {"modules": [{"title": "Lesson 1", "module_number": 1,
                         "visuals": ["Number line from -10 to 10"]}]}
    wanted = asset_requirements.read(plan).items

    assert [(r.kind, r.what) for r in wanted] == [
        ("diagram", "Number line from -10 to 10")]


def test_the_drawing_lands_on_the_material_page() -> None:
    """What the operator opens with "Read it as a book"."""
    assets = lesson_assets.match(asset_requirements.read(PLAN).items, DRAWN)
    assert list(assets) == ["basic operations on integers"]

    html = notes_renderer.render_material_html(MATERIAL, plan=PLAN,
                                               assets=assets, **PAGE)

    assert "Counters" in html, "the SVG itself, inlined so it prints offline"
    # The stylesheet always defines `.plate`; what must not appear is one.
    assert "<div class='plate'>" not in html, "no hatched box beside a drawing"


def test_the_drawing_lands_on_the_plan_page_too() -> None:
    assets = lesson_assets.match(asset_requirements.read(PLAN).items, DRAWN)

    assert "Counters" in notes_renderer.render_html(PLAN, assets=assets, **PAGE)


def test_a_planned_visual_nobody_has_drawn_still_reserves_its_plate() -> None:
    """The plate is the production list. An empty one is the point."""
    html = notes_renderer.render_material_html(MATERIAL, plan=PLAN, assets={},
                                               **PAGE)

    assert "<div class='plate'>" in html
    assert "Basic Operations on Integers" in html


def test_a_lesson_that_plans_no_visual_promises_none() -> None:
    """Not every lesson has a picture, and inventing a plate for one that was
    never planned prints a hole in the page."""
    plain = {"modules": [{"title": "Lesson 1", "module_number": 1,
                          "teacher_exposition": "An integer is a whole number."}]}

    assert asset_requirements.read(plain).items == []
