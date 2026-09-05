"""A diagram that has been drawn belongs in the book.

The station planned it, drew it, sanitised it, stored the SVG in MinIO and
scored it 100/100 — and the page printed a hatched rectangle captioned
`DIAGRAM 1.1 · charts`, because a plate is reserved for what the PLAN asks
for and the plan had asked for "charts". Nothing binds "charts" to "Basic
Operations on Integers", so the drawing had nowhere to go and the requirement
had nothing to fill it.
"""
from __future__ import annotations

import pytest

from app.services import asset_requirements, lesson_assets, notes_renderer

PLAN = {"modules": [
    {"title": "Basic Operations on Integers", "module_number": 1,
     "topic": "Integers", "resources_needed": ["charts"],
     "teacher_exposition": "Integers are whole numbers.",
     "exposition_segments": [
         {"topic": "Integers", "body": "Integers are whole numbers."}]},
    {"title": "Ordering Integers", "module_number": 2, "topic": "Ordering",
     "teacher_exposition": "Compare integers on a number line."},
]}

DRAWN = [{"kind": "diagram", "title": "Basic Operations on Integers",
          "url": "http://minio/assets/x.svg",
          "svg": '<svg viewBox="0 0 340 200">'
                 '<text x="12" y="100" font-size="14">Counters</text></svg>',
          "alt": "The four operations."}]

PAGE = dict(grade="grade-9", subject="Mathematics", strand="Numbers",
            sub_strand="Integers", version=1)


@pytest.fixture
def drawn(monkeypatch):
    monkeypatch.setattr(lesson_assets, "collect", lambda *a, **k: list(DRAWN))


def test_charts_is_not_a_figure_anyone_can_produce() -> None:
    """It reserved a plate, captioned it "charts", and told whoever had to
    make it nothing whatsoever."""
    assert asset_requirements.read(PLAN).items == []


def test_a_drawing_the_plan_never_asked_for_still_reaches_the_page(drawn) -> None:
    plan = lesson_assets.with_drawn(PLAN, **{k: PAGE[k] for k in
                                             ("grade", "subject", "sub_strand")})
    wanted = asset_requirements.read(plan).items

    assert [(r.kind, r.what) for r in wanted] == [
        ("diagram", "Basic Operations on Integers")]

    assets = lesson_assets.for_notes(plan, "grade-9", "Mathematics", "Integers")
    html = notes_renderer.render_html(plan, assets=assets, **PAGE)

    assert "Counters" in html, "the SVG, inlined so the page prints offline"
    assert "<div class='plate'>" not in html, "no hatched box beside a drawing"


def test_it_lands_beside_the_lesson_it_is_about(drawn) -> None:
    """Two lessons, one drawing. Printing it against the wrong one is a page
    that shows integers being multiplied while the teacher talks about
    ordering them."""
    plan = lesson_assets.with_drawn(PLAN, "grade-9", "Mathematics", "Integers")

    assert [v["diagram_title"] for v in plan["modules"][0]["visuals"]] == [
        "Basic Operations on Integers"]
    assert not plan["modules"][1].get("visuals")


def test_a_drawing_the_plan_already_names_is_not_printed_twice(drawn) -> None:
    already = {"modules": [{**PLAN["modules"][0],
                            "visuals": [{"diagram_title":
                                         "Basic Operations on Integers"}]}]}
    plan = lesson_assets.with_drawn(already, "grade-9", "Mathematics", "Integers")

    assert len(plan["modules"][0]["visuals"]) == 1


def test_deleting_the_drawing_empties_its_plate_on_the_next_render(monkeypatch) -> None:
    """The book is rendered from what is filed at the moment it is asked for,
    so generate, redraw and delete all show on a refresh."""
    monkeypatch.setattr(lesson_assets, "collect", lambda *a, **k: [])
    plan = lesson_assets.with_drawn(PLAN, "grade-9", "Mathematics", "Integers")

    assert plan is PLAN, "nothing drawn, nothing attached"
    html = notes_renderer.render_html(plan, assets={}, **PAGE)
    assert "Counters" not in html


def test_redrawing_shows_the_new_one(monkeypatch) -> None:
    monkeypatch.setattr(lesson_assets, "collect", lambda *a, **k: [
        {**DRAWN[0], "svg": '<svg viewBox="0 0 340 200">'
                            '<text x="12" y="100" font-size="14">Redrawn</text></svg>'}])
    plan = lesson_assets.with_drawn(PLAN, "grade-9", "Mathematics", "Integers")
    assets = lesson_assets.for_notes(plan, "grade-9", "Mathematics", "Integers")

    assert "Redrawn" in notes_renderer.render_html(plan, assets=assets, **PAGE)


def test_a_plan_with_no_lessons_is_left_alone(drawn) -> None:
    for empty in ({}, {"modules": []}, {"modules": "no"}):
        assert lesson_assets.with_drawn(empty, "g", "s", "ss") == empty


def test_a_storage_failure_does_not_take_the_page_down(monkeypatch) -> None:
    """A guide that renders with placeholders beats a guide that will not
    render."""
    def _boom(*a, **k):
        raise RuntimeError("minio is down")

    monkeypatch.setattr(lesson_assets, "collect", _boom)

    assert lesson_assets.with_drawn(PLAN, "g", "s", "ss") is PLAN
