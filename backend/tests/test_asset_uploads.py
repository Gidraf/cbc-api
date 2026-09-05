"""Filling a planned figure — by generating it, or by supplying the file.

The pipeline plans every picture, clip and simulation a lesson needs, writes a
brief for each and keeps a place on the page for it. It could not accept the
thing itself: diagrams live behind the diagram station, photos and video behind
the media registry, and neither takes a file for a figure that was merely
PLANNED. So a teacher with the right photograph, or a video nobody can
generate, had nowhere to put it and the plate stayed hatched.
"""
from __future__ import annotations

import inspect

import pytest

from app.services import asset_uploads


# ── what can be made here, and what can only be received ────────────────────

def test_video_is_upload_only() -> None:
    """Nothing here makes footage. A generate button for it would be offering
    to fail, and would cost a model call to learn what this already knows."""
    assert not asset_uploads.can_generate("video")
    assert not asset_uploads.can_generate("image")
    assert not asset_uploads.can_generate("audio")


def test_what_can_be_generated_is_stated_rather_than_attempted() -> None:
    assert asset_uploads.can_generate("diagram")
    assert asset_uploads.can_generate("simulation")


def test_every_kind_a_page_reserves_space_for_accepts_something() -> None:
    from app.services.notes_renderer import _PLATE

    for kind in _PLATE:
        assert asset_uploads.ACCEPTS.get(kind), kind


@pytest.mark.parametrize("kind, content_type, allowed", [
    ("diagram", "image/svg+xml", True),
    ("diagram", "image/png", True),
    ("diagram", "video/mp4", False),
    ("video", "video/mp4", True),
    ("video", "image/png", False),
    ("image", "image/jpeg", True),
    ("audio", "audio/mpeg", True),
])
def test_a_file_must_suit_the_plate_it_fills(kind, content_type, allowed) -> None:
    """A video in a slot kept for a diagram is not a near miss: the page
    reserves a printed rectangle for one and a cue for the other."""
    assert (content_type in asset_uploads.ACCEPTS[kind]) is allowed


# ── one asset per requirement ───────────────────────────────────────────────

def test_an_asset_is_keyed_on_the_requirement_it_answers() -> None:
    """A second upload for the same figure replaces the first rather than
    leaving the renderer to choose between them."""
    first = asset_uploads.asset_id_for("grade-9", "Mathematics", "Integers",
                                       "diagram", "a number line from -6 to +6")
    again = asset_uploads.asset_id_for("grade-9", "Mathematics", "Integers",
                                       "diagram", "a number line from -6 to +6")
    other = asset_uploads.asset_id_for("grade-9", "Mathematics", "Integers",
                                       "diagram", "a bar chart of rainfall")

    assert first == again
    assert first != other


def test_the_grade_spelling_does_not_split_one_figure_into_two() -> None:
    assert (asset_uploads.asset_id_for("Grade-9", "Mathematics", "Integers",
                                       "diagram", "x")
            == asset_uploads.asset_id_for("grade-9", "mathematics", "integers",
                                          "diagram", "x"))


# ── the page finds them ─────────────────────────────────────────────────────

def test_an_uploaded_file_fills_the_plate() -> None:
    from app.services.asset_requirements import Requirement
    from app.services.lesson_assets import match

    req = Requirement(kind="diagram", what="a number line from -6 to +6",
                      module_number=1, module_title="L")
    filled = match([req], [{"kind": "diagram",
                            "title": "a number line from -6 to +6",
                            "url": "u_upload", "svg": "", "source": "upload"}])

    assert filled and list(filled.values())[0]["url"] == "u_upload"


def test_a_persons_choice_outranks_the_stations_older_attempt() -> None:
    """An upload is a decision. A station's near-match is a guess."""
    from app.services.asset_requirements import Requirement
    from app.services.lesson_assets import match

    req = Requirement(kind="diagram", what="a number line from -6 to +6",
                      module_number=1, module_title="L")
    filled = match([req], [
        {"kind": "diagram", "title": "Number line from -6 to 6",
         "url": "u_station", "svg": "", "source": "station"},
        {"kind": "diagram", "title": "a number line from -6 to +6",
         "url": "u_upload", "svg": "", "source": "upload"},
    ])

    assert list(filled.values())[0]["url"] == "u_upload"


def test_the_renderer_reads_the_upload_store() -> None:
    from app.services import lesson_assets

    source = inspect.getsource(lesson_assets.collect)
    assert "asset_uploads.list_for" in source


def test_a_store_that_is_down_still_renders_the_page(monkeypatch) -> None:
    """Placeholders beat a page that will not render."""
    import app.infra.db as db

    monkeypatch.setattr(db, "fetch_all",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert asset_uploads.list_for("grade-9", "Mathematics", "Integers") == []


# ── the routes ──────────────────────────────────────────────────────────────

def test_all_four_routes_exist() -> None:
    from app.routes.curriculum import router

    paths = {(tuple(sorted(r.methods)), r.path) for r in router.routes}
    base = "/api/v1/curriculum/factory/assets"

    assert (("GET",), f"{base}/requirements") in paths
    assert (("POST",), f"{base}/upload") in paths
    assert (("POST",), f"{base}/generate") in paths
    assert (("DELETE",), f"{base}/{{asset_id}}") in paths


def test_generating_a_video_is_refused_before_a_call_is_made() -> None:
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_asset)
    refusal = source.split("can_generate")[1].split("llm_client")[0]

    assert "raise_api_error" in refusal, "refused before the model is called"
    assert "upload the file when you have it" in source


def test_a_generated_svg_is_sanitised_before_it_is_stored() -> None:
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_asset)
    assert "extract_and_sanitize_svg" in source


def test_the_requirements_list_says_what_can_be_generated() -> None:
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_asset_requirements)
    assert "can_generate" in source
    assert "brief" in source, "and carries the brief to copy"
    assert "filled" in source


def test_the_table_exists() -> None:
    from app.infra.db import MIGRATIONS

    assert "029_uploaded_assets" in [name for name, _ in MIGRATIONS]
    sql = dict(MIGRATIONS)["029_uploaded_assets"]
    assert "uploaded_assets" in sql and "storage_url" in sql and "svg TEXT" in sql
