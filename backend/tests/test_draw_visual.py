"""Turning a planned visual into an actual drawing.

The diagram station PLANS: a title, a vivid prompt, and a scene of addressable
parts so a question can point at one region. Nothing turned that into a
picture — so every brief sat in an artifact and the book printed a hatched
rectangle beside it, while the station panel showed JSON.
"""
from __future__ import annotations

import inspect

import pytest

from app.routes.curriculum import _svg_brief

VISUAL = {
    "diagram_title": "Number line from -10 to 10",
    "vivid_prompt": "A horizontal number line marked at every integer from -10 to 10.",
    "accessibility": {"alt_text": "A number line from minus ten to ten."},
    "scene": {"parts": [
        {"label": "Number Line", "function": "represents the integers from -10 to 10",
         "assessable": True, "occludable": False},
        {"label": "Zero", "function": "the origin", "assessable": True},
    ]},
}


def _brief() -> str:
    return _svg_brief(VISUAL, grade="grade-9", subject="Mathematics",
                      strand="Numbers", sub_strand="Integers")


def test_the_brief_is_built_from_the_plan_not_the_substrand_name() -> None:
    brief = _brief()

    assert "Number line from -10 to 10" in brief
    assert "marked at every integer" in brief
    assert "grade-9 · Mathematics · Numbers · Integers" in brief


def test_every_addressable_part_must_be_labelled() -> None:
    """This station exists so a question can say "the part labelled A". A
    drawing whose labels differ breaks every question written against it."""
    brief = _brief()

    assert "Number Line" in brief and "Zero" in brief
    assert "spelled exactly as written" in brief
    assert "breaks the question that points at it" in brief


def test_the_parts_get_addressable_ids() -> None:
    assert 'id="part-' in _brief()


def test_it_asks_for_something_printable_and_offline() -> None:
    brief = _brief()

    assert "viewBox" in brief
    assert "photocopy" in brief
    assert "external fonts" in brief and "offline" in brief
    assert "Return ONLY the <svg> element" in brief


def test_a_visual_with_no_parts_still_gets_a_brief() -> None:
    brief = _svg_brief({"diagram_title": "A bar chart",
                        "vivid_prompt": "Rainfall by month."},
                       grade="grade-9", subject="Mathematics",
                       strand="", sub_strand="Integers")

    assert "A bar chart" in brief and "Rainfall by month." in brief


def test_the_drawing_is_filed_where_the_book_looks() -> None:
    """Against the visual's own title, which is what `lesson_assets` matches a
    requirement on — so the plate fills on the next render."""
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_draw_visual)

    assert "asset_uploads.record(" in source
    assert 'kind="diagram"' in source
    assert "what=title" in source


def test_the_svg_is_sanitised_before_it_is_stored() -> None:
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_draw_visual)
    assert "extract_and_sanitize_svg" in source


def test_it_is_written_back_onto_the_plan_too() -> None:
    """So the station panel shows what it drew, and the gate can see the visual
    is no longer only a brief."""
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_draw_visual)
    assert '"diagram_svg"] = svg' in source
    assert "diagram_gate.gate_of" in source


def test_only_a_diagram_plan_can_be_drawn_from() -> None:
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_draw_visual)
    assert 'artifact.kind != "diagram"' in source


def test_an_index_that_does_not_exist_says_how_many_do() -> None:
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_draw_visual)
    assert "there is no" in source and "plans {len(visuals)}" in source


def test_a_storage_failure_does_not_lose_the_drawing() -> None:
    """The SVG is inlined on the page, so losing the stored copy costs the
    download and not the figure."""
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_draw_visual)
    stored = source.split("object_storage.save_bytes")[1]
    assert "except Exception" in stored
    assert "asset_uploads.record" in stored, "recorded regardless"


def test_the_route_exists() -> None:
    from app.routes.curriculum import router

    paths = {(tuple(sorted(r.methods)), r.path) for r in router.routes}
    assert (("POST",), "/api/v1/curriculum/factory/visuals/draw") in paths


def test_the_console_offers_it_on_a_diagram_version() -> None:
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "frontend-web/src"
    panel = (root / "views/VersionReview.tsx").read_text()
    button = (root / "ui/DrawVisuals.tsx").read_text()

    assert 'data.kind === "diagram"' in panel
    assert "<DrawVisuals" in panel
    assert "Draw it" in button and "Draw again" in button
    assert "brief only" in button, "and says which are still only a brief"
