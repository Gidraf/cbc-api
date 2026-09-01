"""What the lesson plan says it needs a picture, a recording or a video OF.

The plan already names its assets. Lesson 1 asks for "an audio clip of a song
about God" and "visual aids for gestures"; a segment says "observe pictures of
Adam and Eve" because the design said so.

The asset stations were not reading any of it. Each was given the sub-strand's
title and outcomes and asked to plan from scratch — which is why one came back
with a soil-profile schematic for a lesson about God, and why nothing the plan
actually asked for was guaranteed to exist.
"""
from __future__ import annotations

import pathlib

from app.services import asset_requirements as ar

PLAN = {
    "modules": [
        {"module_number": 1, "title": "Lesson 1: Introducing God",
         "resources_needed": [
             "audio clip of a song about God",
             "visual aids for gestures",
             "space for group singing",
         ],
         "exposition_segments": [
             {"topic": "Using Gestures",
              "body": "Introduce the phrase. Hold up a picture of a family at "
                      "home. Play a recorded clip of the phrase."},
         ]},
        {"module_number": 2, "title": "Lesson 2: God as Creator",
         "resources_needed": ["pictures of creation", "nature walk materials"],
         "exposition_segments": [
             {"topic": "Creation",
              "body": "Watch a video clip about plants growing."},
         ]},
    ]
}


# ── what counts as a requirement ────────────────────────────────────────────


def test_the_plans_own_resource_list_is_read():
    what = {i.what for i in ar.read(PLAN).items}

    assert "audio clip of a song about God" in what
    assert "pictures of creation" in what


def test_what_the_teaching_itself_asks_to_be_shown_is_read_too():
    """A segment saying "hold up a picture of a family" is asking for a
    picture whether or not anyone wrote it under resources."""
    items = ar.read(PLAN).items
    from_teaching = [i for i in items if i.source == "exposition"]

    assert any("picture of a family" in i.what for i in from_teaching)
    assert all(i.topic for i in from_teaching), "it should say which topic"


def test_a_thing_to_bring_is_not_a_thing_to_generate():
    """"Space for group singing" is a room, and a station that produced a brief
    for a room would be producing nothing."""
    items = {i.what: i for i in ar.read(PLAN).items}

    assert items["space for group singing"].kind == "object"
    assert items["space for group singing"].station == ""
    assert items["nature walk materials"].station == ""


def test_each_kind_goes_to_the_station_that_makes_it():
    items = {i.what: i for i in ar.read(PLAN).items}

    assert items["audio clip of a song about God"].kind == "audio"
    assert items["audio clip of a song about God"].station == "media"
    assert items["pictures of creation"].station == "media"


def test_a_plural_is_still_the_thing_it_is_the_plural_of():
    """"visual aid" with a trailing word boundary does not match "visual aids",
    which is how every plan writes it — and the requirement was then filed as
    an object to bring."""
    assert ar._classify("visual aids for gestures") == "image"
    assert ar._classify("wall charts of church activities") == "image"
    assert ar._classify("flash cards of letter sounds") == "image"


def test_a_wall_chart_is_a_picture_and_a_water_cycle_chart_is_a_diagram():
    assert ar._classify("wall charts of church activities") == "image"
    assert ar._classify("a chart of the water cycle") == "diagram"


def test_the_same_thing_named_twice_in_one_lesson_is_one_requirement():
    plan = {"modules": [{"module_number": 1, "title": "L1",
                         "resources_needed": ["pictures of creation",
                                              "Pictures of creation"]}]}

    assert len(ar.read(plan).items) == 1


def test_an_empty_plan_asks_for_nothing_rather_than_failing():
    assert ar.read({}).items == []
    assert ar.read("not a plan").items == []


# ── what the station is told ────────────────────────────────────────────────


def test_the_station_is_told_what_to_produce_lesson_by_lesson():
    rendered = ar.render(ar.read(PLAN), "media")

    assert "=== WHAT THE LESSON PLAN ASKS FOR ===" in rendered
    assert "Lesson 1: Introducing God" in rendered
    assert "[audio] audio clip of a song about God" in rendered


def test_the_station_is_told_not_to_add_what_nothing_asked_for():
    rendered = ar.render(ar.read(PLAN))

    assert "Do NOT add assets the plan does not ask for" in rendered
    assert "printed beside a lesson it illustrates nothing in" in rendered


def test_objects_are_not_put_on_a_stations_list():
    rendered = ar.render(ar.read(PLAN), "media")

    assert "space for group singing" not in rendered


def test_a_station_nothing_asked_gets_no_block_rather_than_an_empty_one():
    assert ar.render(ar.read(PLAN), "simulation") == ""


# ── the prompt that caused the soil-profile diagram ─────────────────────────


def test_the_visuals_prompt_no_longer_names_a_soil_lesson_for_every_subject():
    """It named "Soil Erosion types, Contour Bunds, Gabions" and "Soil Profile
    Horizon Strata O-A-B-C, pH Titration" as its examples — for every subject,
    including a PP1 lesson about God. A reviewer later flagged a soil-profile
    schematic on that lesson as an invention. It was not an invention; it was
    the prompt's own example, followed faithfully."""
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "app/routes/curriculum.py").read_text()
    code = "\n".join(l for l in source.splitlines()
                     if not l.lstrip().startswith("#"))

    assert "Contour Bunds" not in code
    assert "pH Titration & Buffer Capacity" not in code
    assert "Soil Erosion types" not in code


def test_the_visuals_station_is_given_what_the_plan_asked_for():
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_plan_visuals)
    assert "asset_requirements.read(" in source
    assert "{asset_brief}" in source


def test_a_lesson_the_plan_asks_nothing_for_still_gets_visuals():
    """A plan that names no assets is not a plan that wants none."""
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_plan_visuals)
    assert "WHERE THE PLAN ASKS FOR NOTHING" in source


# ── seeing it on the board ──────────────────────────────────────────────────


def test_the_board_can_show_what_the_plans_ask_a_station_for():
    import inspect

    from app.routes import pipelines

    source = inspect.getsource(pipelines.stage_requirements)
    assert "asset_requirements.read(plan)" in source

    view = (pathlib.Path(__file__).resolve().parents[2]
            / "frontend-web/src/views/Pipelines.tsx").read_text()
    assert "function StageRequirements(" in view
    assert "What the plan asks for" in view


def test_only_the_stations_that_build_from_the_plan_offer_it():
    view = (pathlib.Path(__file__).resolve().parents[2]
            / "frontend-web/src/views/Pipelines.tsx").read_text()

    assert 'STATION_STAGES = new Set(["diagram", "media", "simulation", "activity"])' in view


def test_with_no_plan_filed_the_board_says_that_rather_than_nothing():
    view = (pathlib.Path(__file__).resolve().parents[2]
            / "frontend-web/src/views/Pipelines.tsx").read_text()

    assert "station plans from the plan." in view
