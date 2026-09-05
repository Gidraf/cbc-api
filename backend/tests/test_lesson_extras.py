"""The book showing what the other stations actually made.

A guide was rendered from the lesson plan alone. Meanwhile the diagram station
had drawn diagrams, the activity station had written the practical work, and
the media station had briefed photographs and clips — and none of it appeared
on the page a teacher prints. Each station's output was reachable only from its
own panel in the console, so the activity KICD funded, written and reviewed and
filed, was not in the book.
"""
from __future__ import annotations

import pytest

from app.services import lesson_extras
from app.services.notes_renderer import render_html

SVG = "<svg viewBox='0 0 10 10'><line x1='0' y1='5' x2='10' y2='5'/></svg>"

ACTIVITY = {
    "module_number": 1,
    "activity_name": "Walking the number line",
    "objective": "Order integers by standing on a number line.",
    "materials": ["chalk", "number cards"],
    "hazard_level": "low",
    "procedure_steps": ["Draw the line.", "Walk five steps right from -3."],
    "assessment_observables": ["Counts in the right direction from a negative."],
    "inclusion_adaptations": {"sne": "Move a counter instead of walking."},
}


@pytest.fixture()
def stations(monkeypatch):
    """The stations, each having produced something."""
    from app.services import artifact_registry, asset_uploads, media_registry

    def search(**kw):
        if kw.get("kind") == "diagram":
            return [{"content": {"visuals": [
                {"diagram_title": "a number line from -6 to +6",
                 "diagram_svg": SVG, "alt_text": "a number line"}]}}]
        if kw.get("kind") == "activity":
            return [{"content": {"activities": [ACTIVITY]}}]
        return []

    monkeypatch.setattr(artifact_registry, "search", search)
    monkeypatch.setattr(asset_uploads, "list_for", lambda *a, **k: [])
    monkeypatch.setattr(media_registry, "list_for", lambda *a, **k: [
        {"kind": "video", "title": "temperature falling below zero",
         "purpose": "A negative reading in the real world.",
         "storage_url": "", "module_number": 1}])
    from app.services import question_dna
    monkeypatch.setattr(question_dna.question_dna_service, "list_questions",
                        lambda **kw: [])


NOTES = {"title": "Integers", "modules": [{
    "module_number": 1, "title": "Introduction to Integers",
    "lesson_flow": [{"phase": "The number line", "minutes": 15,
                     "what_the_teacher_does": "Shown on a number line below."}],
    "resources_needed": ["a number line from -6 to +6"],
}]}


def _book(**kw) -> str:
    from app.services import lesson_assets

    assets = lesson_assets.for_notes(NOTES, "Grade 9", "Mathematics", "Integers")
    return render_html(NOTES, grade="Grade 9", subject="Mathematics",
                       strand="Numbers", sub_strand="Integers",
                       assets=assets, **kw)


# ── the diagram the station actually filed ──────────────────────────────────

def test_a_generated_diagram_reaches_the_page(stations) -> None:
    """The station files `visuals`; the collector read `diagrams`. So every
    diagram it produced was invisible and the plate stayed hatched next to a
    diagram that existed."""
    html = _book()

    assert "<svg" in html, "the station's own diagram is on the page"
    # The lesson text asks for a second figure of its own ("shown on a number
    # line below"), and that one has nothing filed — so a plate for it is
    # correct. What matters is that the DRAWN one is not also a plate.
    assert html.count("<figure") > html.count("class='plate'")


def test_both_shapes_are_read(stations) -> None:
    from app.services import artifact_registry, lesson_assets

    for key in ("visuals", "diagrams"):
        artifact_registry.search = lambda **kw: (
            [{"content": {key: [{"diagram_title": "x", "diagram_svg": SVG}]}}]
            if kw.get("kind") == "diagram" else [])
        found = lesson_assets.collect("Grade 9", "Mathematics", "Integers")
        assert any(f["svg"] for f in found), key


# ── the practical work ──────────────────────────────────────────────────────

def test_the_activity_is_in_the_book(stations) -> None:
    html = _book()

    assert "Walking the number line" in html
    assert "Draw the line." in html
    assert "chalk" in html


def test_an_activity_shows_what_to_watch_for_and_who_it_adapts_for(stations) -> None:
    html = _book()

    assert "What to watch for" in html
    assert "So everyone can do it" in html
    assert "Move a counter instead" in html


def test_safety_comes_before_the_procedure(stations) -> None:
    """A safety line under the procedure is a safety line read after the thing
    it was meant to prevent."""
    from app.services.notes_renderer import _activity

    rendered = _activity({**ACTIVITY, "hazard_level": "high",
                          "hazard_warnings": ["Tape the cards down."]}, "1.1")

    assert rendered.index("Before you start") < rendered.index("ol class='procedure'")


# ── where each thing lands ──────────────────────────────────────────────────

def test_everything_sits_in_the_lesson_it_belongs_to(stations) -> None:
    """A clip filed against lesson 1 belongs beside lesson 1's teaching, not in
    a pile at the end of the book."""
    html = _book()

    assert "For this sub-strand" not in html, "nothing fell into the loose pile"
    assert "temperature falling below zero" in html


def test_the_lesson_number_survives_being_reshaped() -> None:
    """`media()` rebuilt each row into a tidier shape and dropped the lesson it
    belonged to, so every clip fell to the end of the book."""
    grouped = lesson_extras.by_lesson([
        {"module_number": 1}, {"hour_number": 1}, {"lesson": 2}, {},
    ])

    assert sorted(grouped) == [0, 1, 2]
    assert len(grouped[1]) == 2


def test_anything_with_no_lesson_still_reaches_the_book(monkeypatch, stations) -> None:
    from app.services import media_registry

    monkeypatch.setattr(media_registry, "list_for", lambda *a, **k: [
        {"kind": "photo", "title": "a Nairobi market stall", "storage_url": ""}])

    html = _book()
    assert "For this sub-strand" in html
    assert "a Nairobi market stall" in html


# ── it must never take the book down ────────────────────────────────────────

def test_a_station_that_cannot_be_read_does_not_break_the_page(monkeypatch) -> None:
    """A guide that renders without its activities is worth more than a guide
    that will not render."""
    from app.services import artifact_registry, media_registry

    def boom(*a, **k):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(artifact_registry, "search", boom)
    monkeypatch.setattr(media_registry, "list_for", boom)

    assert lesson_extras.gather("Grade 9", "Mathematics", "Integers")["counts"] == {
        "activities": 0, "media": 0}


def test_only_the_newest_version_of_an_activity_is_used(monkeypatch) -> None:
    """Two versions of the same activity in one guide reads as two."""
    from app.services import artifact_registry

    monkeypatch.setattr(artifact_registry, "search", lambda **kw: (
        [{"content": {"activities": [{"activity_name": "newest"}]}},
         {"content": {"activities": [{"activity_name": "older"}]}}]
        if kw.get("kind") == "activity" else []))

    found = lesson_extras.activities("Grade 9", "Mathematics", "Integers")
    assert [a["activity_name"] for a in found] == ["newest"]


# ── the figures a mathematics lesson asks for by name ───────────────────────

@pytest.mark.parametrize("wanted", [
    "a number line from -6 to +6",
    "a coordinate grid",
    "a clock face",
    "a net of a cube",
    "a hundred square",
    "a pictogram of fruit sold",
])
def test_a_maths_figure_is_a_figure_even_without_the_word_diagram(wanted: str) -> None:
    """"A number line from -6 to +6" is a drawing the page must keep space for.
    It matched no keyword, so it was filed as an object to bring — like chalk —
    and no plate was ever reserved for it."""
    from app.services.asset_requirements import _classify

    assert _classify(wanted) == "diagram", wanted


@pytest.mark.parametrize("wanted", [
    "a set of counters",
    "number cards, charts, worksheets",
    "chalk and a ruler",
])
def test_things_carried_into_the_room_are_still_objects(wanted: str) -> None:
    """Counters and cards really are brought in. Reserving a printed rectangle
    for them puts a hatched box in the book asking somebody to draw stationery."""
    from app.services.asset_requirements import _classify

    assert _classify(wanted) == "object", wanted
