"""Turning a planned visual into an actual drawing.

The diagram station PLANS: a title, a vivid prompt, and a scene of addressable
parts so a question can point at one region. Nothing turned that into a
picture — so every brief sat in an artifact and the book printed a hatched
rectangle beside it, while the station panel showed JSON.
"""
from __future__ import annotations

import inspect

import pytest

from pathlib import Path

from app.routes.curriculum import _svg_brief

FRONTEND = Path(__file__).resolve().parents[2] / "frontend-web"

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
    requirement on — so the plate fills on the next render.

    Drawing and hand-editing file through the SAME function: an edit that
    filed anywhere else left the book printing the drawing from before it."""
    from app.routes import curriculum
    from app.services import asset_uploads

    assert "asset_uploads.file_drawing(" in inspect.getsource(
        curriculum.factory_draw_visual)

    filing = inspect.getsource(asset_uploads.file_drawing)
    assert 'kind="diagram"' in filing
    assert "what=title" in filing


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
    from app.services import asset_uploads

    source = inspect.getsource(asset_uploads.file_drawing)
    stored = source.split("object_storage.save_bytes")[1]
    assert "except Exception" in stored
    assert "record(" in stored, "recorded regardless"


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
    assert "A learner covering every label must still be able to work out" in brief


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
    assert "range(_DRAW_ATTEMPTS)" in source, "a bounded number, not a loop"
    # And the better of the two is kept, not the later one.
    assert "len(measured.findings) < len(fit.findings)" in source


def test_the_operator_is_told_what_the_drawing_does_on_the_page() -> None:
    """A thumbnail cannot show that a label prints at 2mm."""
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_draw_visual)

    assert '"layout": {' in source
    assert '"overlapping_labels"' in source
    assert '"findings"' in source


def test_it_names_the_failure_it_keeps_getting_back() -> None:
    """Twice now the model has returned four stacked rows, each a boxed word
    beside an equation. "Each part must look like what it is" did not stop it;
    naming the pattern might."""
    brief = _flowed()

    assert "Do not draw a stack of rows" in brief
    assert "bordered table" in brief
    assert "Show the thing HAPPENING, not the thing named" in brief


def test_it_offers_a_repertoire_rather_than_asking_for_creativity() -> None:
    """"Be creative" is not an instruction. A list of arrangements that suit
    particular ideas is."""
    brief = _flowed()

    for arrangement in ("number line", "area model", "part-whole bar",
                        "grouped counters", "cross-section", "cycle of arrows"):
        assert arrangement in brief, arrangement
    assert "Choose ONE and commit to it" in brief


def test_it_forbids_the_leader_line_through_the_equation() -> None:
    brief = _flowed()

    assert "Never route a leader line THROUGH text" in brief
    assert "between the characters of an expression" in brief


def test_it_says_that_what_falls_outside_the_viewbox_is_gone() -> None:
    """Including the second line of a wrapped label — the drawing that came
    back clipped its last row and its own left-hand captions."""
    brief = _flowed()

    assert "Nothing may fall outside the viewBox" in brief
    assert "second or third line of a wrapped label" in brief


# ── what actually reaches storage ───────────────────────────────────────────


def test_a_drawing_that_never_reached_minio_says_so() -> None:
    """`save_bytes` does not raise when MinIO is unreachable — it logs and
    returns a `local://` URL. So the route reported every drawing as stored,
    served it from the database row, and left the bucket empty."""
    from app.routes import curriculum
    from app.services import asset_uploads

    assert 'startswith("local://")' in inspect.getsource(
        asset_uploads.file_drawing)

    route = inspect.getsource(curriculum.factory_draw_visual)
    assert '"stored_in_minio": in_minio' in route
    assert '"asset_id": asset_id' in route, "so it can be deleted again"


def test_deleting_an_asset_takes_its_object_out_of_the_bucket(monkeypatch) -> None:
    """Removing the row left the SVG in MinIO for ever: nothing referred to
    it, nothing listed it, nothing would ever delete it."""
    from app.infra import db, storage
    from app.services import asset_uploads

    monkeypatch.setattr(db, "fetch_all", lambda *a, **k: [
        {"storage_url": "http://minio:9000/cbc-assets/assets/grade-9/x.svg"}])
    monkeypatch.setattr(db, "execute", lambda *a, **k: None)
    gone: list[str] = []
    monkeypatch.setattr(storage.object_storage, "remove_object",
                        lambda name: gone.append(name) or True)

    assert asset_uploads.remove("asset_abc") is True
    assert gone == ["assets/grade-9/x.svg"]


def test_a_bucket_that_will_not_delete_does_not_fail_the_delete(monkeypatch) -> None:
    """The row is the record; the object is a copy. The figure is already gone
    from every page that reads it."""
    from app.infra import db, storage
    from app.services import asset_uploads

    monkeypatch.setattr(db, "fetch_all", lambda *a, **k: [
        {"storage_url": "http://minio:9000/cbc-assets/assets/x.svg"}])
    monkeypatch.setattr(db, "execute", lambda *a, **k: None)

    def _boom(_name):
        raise RuntimeError("minio is down")

    monkeypatch.setattr(storage.object_storage, "remove_object", _boom)

    assert asset_uploads.remove("asset_abc") is True


def test_it_says_where_the_edge_labels_go() -> None:
    """A number line came back with its "10" and its right-hand caption cut
    off by the canvas edge — a label centred on the last tick is half outside
    it. The rule is an anchor and a coordinate, not "keep a margin"."""
    brief = _flowed()

    assert 'text-anchor="end" at x=328' in brief
    assert "a label at the left edge starts at x=12" in brief
    assert "first and last ticks of a scale go at x=30 and x=310" in brief


def test_editing_a_drawing_by_hand_reaches_the_book(monkeypatch) -> None:
    """An edit files a new artifact version. The book matches on the stored
    asset, which still held the drawing from before the edit — so a hand fix
    showed in the JSON and nowhere else."""
    from app.services import asset_uploads

    filed: list[tuple[str, str]] = []
    monkeypatch.setattr(asset_uploads, "file_drawing",
                        lambda **k: filed.append((k["title"], k["svg"])) or {})

    class _Version:
        content = {"visuals": [
            {"diagram_title": "Number line", "diagram_svg": "<svg>fixed</svg>"},
            {"diagram_title": "Never drawn"},
        ]}
        grade, subject = "grade-9", "Mathematics"
        strand_name, sub_strand_name = "Numbers", "Integers"

    assert asset_uploads.refile_diagram_artifact(_Version()) == 1
    assert filed == [("Number line", "<svg>fixed</svg>")]


def test_the_edit_route_refiles_only_diagrams() -> None:
    from app.routes import artifacts

    source = inspect.getsource(artifacts.edit_artifact)

    assert 'if current.kind == "diagram":' in source
    assert "refile_diagram_artifact" in source
    # An edit that saved must not report itself failed because a bucket blinked.
    assert "except Exception" in source.split("refile_diagram_artifact")[1]


def test_a_bad_drawing_gets_more_than_one_correction() -> None:
    """The second attempt fixes most of what the first got wrong; the third
    catches what the fix broke. Beyond that it is filed with its findings
    rather than retried for ever."""
    from app.routes import curriculum

    assert curriculum._DRAW_ATTEMPTS == 3
    source = inspect.getsource(curriculum.factory_draw_visual)
    assert "for pass_no in range(_DRAW_ATTEMPTS)" in source
    # Corrected against the drawing it just made, kept if it is the best one.
    assert "attempt = brief + diagram_layout.corrections(measured)" in source
    assert "len(measured.findings) < len(fit.findings)" in source


def test_the_drawing_does_not_repeat_the_caption_the_book_prints() -> None:
    brief = _flowed()

    assert "Do NOT put a title inside the drawing" in brief
    assert "takes a fifth of the canvas" in brief


# ── editing one drawing out of several ──────────────────────────────────────


def test_one_drawing_can_be_replaced_without_touching_the_others() -> None:
    """A plan with four visuals offered no way to touch the second: the only
    editor was the whole artifact as JSON, where each SVG is one enormous line
    among the briefs. So a drawing that was nearly right was redrawn from
    scratch rather than nudged."""
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_edit_visual_svg)

    assert "extract_and_sanitize_svg" in source, "a pasted SVG is not trusted"
    assert "asset_uploads.file_drawing(" in source, "so the book shows it"
    assert "_record_artifact(" in source, "an edit is a new version, not an overwrite"
    assert "diagram_layout.measure(svg)" in source, "measured like a drawn one"


def test_editing_an_index_that_does_not_exist_says_how_many_do() -> None:
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_edit_visual_svg)

    assert "there is no " in source
    assert "is not a diagram plan" in source


def test_the_console_lists_every_planned_diagram_by_its_number() -> None:
    """"I don't have a way to edit 1.2" — the row and the plate now carry the
    same number."""
    panel = " ".join((FRONTEND / "src/ui/DrawVisuals.tsx").read_text().split())

    assert "DIAGRAM 1.{index + 1}" in panel
    assert "Edit this one" in panel
    assert "useEditVisualSvg" in panel
    # And a repair the operator never asked for is reported.
    assert "Adjusted before filing" in panel
