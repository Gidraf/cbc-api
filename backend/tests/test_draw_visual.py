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


def _flowed() -> str:
    """The brief with its line wrapping collapsed. A rule spanning two lines
    is the same rule, and an assertion that breaks when a sentence rewraps is
    testing the margin rather than the instruction."""
    return " ".join(_brief().split())


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


# ── the brief has to describe the page, not "a diagram" ─────────────────────


def test_the_brief_carries_the_column_the_figure_actually_lands_in() -> None:
    """The first drawing came back 800×600 with 20-unit labels, because the
    brief said "scales to the page" and left the model to guess what the page
    was. The page is not a guess: the sheet is 210mm with 16mm margins and two
    columns 8mm apart, so a figure is 85mm wide, and the plate reserves the
    50mm that a 340 × 200 drawing occupies at that width."""
    brief = _flowed()

    assert "85mm" in brief
    assert "50mm" in brief
    assert 'viewBox="0 0 340 200"' in brief
    assert "NO width or height attribute" in brief


def test_it_gives_the_sizes_in_the_units_it_asked_the_model_to_work_in() -> None:
    """"Large enough to survive a photocopy" is not a number, and produced
    font-size 20 in an 800-wide viewBox — 2.1mm on paper."""
    brief = _flowed()

    assert 'font-size="13"' in brief
    assert "0.55" in brief, "the model needs the advance width to place labels"
    assert "44 characters" in brief
    assert "<tspan>" in brief


def test_it_forbids_the_overlap_in_the_terms_the_model_can_check() -> None:
    brief = _flowed()

    assert "NOTHING MAY OVERLAP ANYTHING" in brief
    assert "leader line" in brief
    assert "the box it occupies" in brief


def test_it_asks_for_a_picture_that_means_something_without_its_labels() -> None:
    """Four operations drawn as four identical circle-line-circle motifs is a
    list with a caption, and a question that hides one part tests nothing."""
    brief = _flowed()

    assert "CARRY THE MEANING" in brief
    assert "look different from" in brief


def test_colour_is_allowed_but_never_load_bearing() -> None:
    """The plan asks for colour; the page is photocopied in grey. Both are
    true, so colour may decorate and may not distinguish."""
    brief = _flowed()

    assert "One accent colour plus black on white" in brief
    assert "photocopied in grey" in brief
    assert "never as the only thing distinguishing" in brief


def test_the_occlusion_contract_survived_the_rewrite() -> None:
    """Every diagram question depends on this attribute. Rewriting the brief
    around it is exactly when it gets dropped."""
    brief = _flowed()

    assert 'data-part-id="part-<label in lower case with hyphens>"' in brief
    assert "the same value as `id`" in brief


def test_a_drawing_is_measured_and_redrawn_against_what_was_measured() -> None:
    """A model told "labels must not overlap" writes overlapping labels
    anyway. A model told which four labels overlap moves them."""
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_draw_visual)

    assert "diagram_layout.measure(candidate)" in source
    assert "diagram_layout.corrections(measured)" in source
    assert "for pass_no in range(2)" in source, "one redraw, not a loop"
    # And the better of the two is kept, not the later one.
    assert "len(measured.findings) < len(fit.findings)" in source


def test_the_operator_is_told_what_the_drawing_does_on_the_page() -> None:
    """A thumbnail cannot show that a label prints at 2mm."""
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_draw_visual)

    assert '"layout": {' in source
    assert '"overlapping_labels"' in source
    assert '"findings"' in source
