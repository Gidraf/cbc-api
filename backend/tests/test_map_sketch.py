"""A sketch map drawn from data, with every feature where it actually is.

The diagram station asked a model for the SVG of Kenya and got Kenya as a
person draws it from memory in the dark. A map whose towns are in the wrong
places cannot be asked a question about.
"""
from __future__ import annotations

import re

from app.services import map_sketch
from app.services.diagram_scene import build_scene_from_svg, occludable_parts, plan_occlusion


def _kenya() -> dict:
    return {"diagram_title": "Kenya", "map": {"extent": "Kenya", "title": "Physical features of Kenya",
            "features": [
                {"kind": "capital", "name": "Nairobi"},
                {"kind": "town", "name": "Mombasa"},
                {"kind": "town", "name": "Kisumu"},
                {"kind": "mountain", "name": "Mt Kenya", "note": "the highest mountain in Kenya"},
                {"kind": "lake", "name": "Lake Victoria"},
                {"kind": "lake", "name": "Lake Turkana"},
                {"kind": "river", "name": "Tana", "note": "Kenya's longest river"},
            ]}}


def _label_xy(svg: str, label: str) -> tuple[float, float]:
    match = re.search(rf"<text x='([\d.]+)' y='([\d.]+)'[^>]*>{re.escape(label)}</text>", svg)
    assert match, f"{label} is not on the map"
    return float(match.group(1)), float(match.group(2))


def test_the_features_are_where_they_are_not_where_the_model_says() -> None:
    content = _kenya()
    # The model puts Mombasa in the north-west; the gazetteer knows better.
    content["map"]["features"][1].update({"lat": 3.0, "lon": 34.5})

    out = map_sketch.render_from_model(content)
    svg = out["svg"]

    nairobi, mombasa, kisumu = (_label_xy(svg, n) for n in ("Nairobi", "Mombasa", "Kisumu"))
    turkana = _label_xy(svg, "L. Turkana")
    assert mombasa[0] > nairobi[0] > kisumu[0], "west to east: Kisumu, Nairobi, Mombasa"
    assert mombasa[1] > nairobi[1], "Mombasa is south of Nairobi"
    assert turkana[1] < nairobi[1], "Lake Turkana is in the north"
    assert out["scene"]["map"]["placed_by_gazetteer"] == [
        "Nairobi", "Mombasa", "Kisumu", "Mt Kenya", "Lake Victoria", "Lake Turkana", "Tana"]


def test_every_map_carries_title_north_scale_key_and_graticule() -> None:
    out = map_sketch.render_from_model(_kenya())
    svg = out["svg"]

    assert ">Physical features of Kenya<" in svg
    assert ">N<" in svg
    assert "Scale: 1 :" in svg and ">km<" in svg
    assert ">Key<" in svg and ">Capital city<" in svg and ">River<" in svg and ">Lake<" in svg
    assert ">Town<" not in svg or "Mombasa" in svg
    assert ">0° (Equator)<" in svg and ">36°E<" in svg
    assert out["key"] == ["boundary", "capital", "town", "mountain", "lake", "river"]


def test_the_key_names_only_the_symbols_used() -> None:
    content = _kenya()
    content["map"]["features"] = [{"kind": "town", "name": "Nakuru"}]

    out = map_sketch.render_from_model(content)

    assert ">River<" not in out["svg"] and ">Lake<" not in out["svg"]
    assert ">Town<" in out["svg"]


def test_feature_labels_are_the_only_occludable_parts() -> None:
    """A question can blank Nairobi; it must never blank the title, the key
    or the Equator."""
    out = map_sketch.render_from_model(_kenya())
    scene = build_scene_from_svg(out["svg"], out["title"], out["scene"])

    blankable = {p["label"] for p in occludable_parts(scene, "label_blanks")}
    assert blankable == {"Nairobi", "Mombasa", "Kisumu", "Mt Kenya", "L. Victoria", "L. Turkana", "R. Tana"}
    functions = {p["label"]: p["function"] for p in scene["parts"] if p.get("assessable")}
    assert functions["Nairobi"] == "the capital city"
    assert "longest river" in functions["R. Tana"]
    assert "highest mountain" in functions["Mt Kenya"]


def test_an_occlusion_plan_can_be_made_from_the_map() -> None:
    out = map_sketch.render_from_model(_kenya())
    scene = build_scene_from_svg(out["svg"], out["title"], out["scene"])

    plan = plan_occlusion(scene, "label_blanks", max_blanks=3)

    assert len(plan["removed_facts"]) == 3
    assert all(f["label"] in {"Nairobi", "Mombasa", "Kisumu", "Mt Kenya", "L. Victoria",
                              "L. Turkana", "R. Tana"} for f in plan["removed_facts"])


def test_spellings_the_lesson_uses_are_understood() -> None:
    content = _kenya()
    content["map"]["features"] = [
        {"kind": "river", "name": "River Tana"}, {"kind": "river", "name": "Ewaso Nyiro"},
        {"kind": "mountain", "name": "The Aberdares"}, {"kind": "mountain", "name": "Mt. Elgon"},
        {"kind": "lake", "name": "Naivasha"}, {"kind": "feature", "name": "Eldoret"},
    ]

    out = map_sketch.render_from_model(content)

    assert out["unplaced"] == []
    assert "R. Ewaso Ng'iro" in out["svg"] and "Aberdare Range" in out["svg"] and "Eldoret" in out["svg"]


def test_a_feature_nobody_can_place_is_reported_not_invented() -> None:
    content = _kenya()
    content["map"]["features"].append({"kind": "town", "name": "Nowhere"})
    content["map"]["features"].append({"kind": "town", "name": "Somewhere", "lat": 1.0, "lon": 38.0})

    out = map_sketch.render_from_model(content)

    assert out["unplaced"] == ["Nowhere"]
    assert "Nowhere" not in out["svg"]
    assert "Somewhere" in out["svg"]
    assert out["scene"]["map"]["placed_by_model"] == ["Somewhere"]


def test_a_school_compound_is_drawn_from_the_models_own_grid() -> None:
    content = {"map": {"extent": "the school compound", "title": "Sketch map of Tumaini School",
               "features": [
                   {"kind": "building", "name": "Administration block", "x": 50, "y": 20},
                   {"kind": "building", "name": "Library", "x": 80, "y": 50},
                   {"kind": "road", "name": "Main path", "path": [[50, 0], [50, 100]]},
                   {"kind": "feature", "name": "Main gate", "x": 50, "y": 96},
               ]}}

    out = map_sketch.render_from_model(content)
    svg = out["svg"]

    admin, library, gate = (_label_xy(svg, n) for n in ("Administration block", "Library", "Main gate"))
    assert library[0] > admin[0] and gate[1] > admin[1]
    assert ">N<" in svg and ">Key<" in svg and ">Building<" in svg
    assert "°E" not in svg, "no graticule on a plan"
    assert "not to projection" in svg


def test_nothing_is_drawn_when_the_model_sent_no_map() -> None:
    assert map_sketch.render_from_model({"diagram_svg": "<svg/>"}) is None
    assert map_sketch.render_from_model({"map": {"features": []}}) is None
    assert map_sketch.render_from_model("x") is None


def test_the_diagram_routes_draw_maps_here() -> None:
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum)
    assert source.count("map_sketch.render_from_model(resp.content)") == 2
    assert source.count('"sub_strand": payload.sub_strand, "map": bool(drawn_map)') == 2


def test_the_questions_station_reads_the_drawn_figures_with_their_parts() -> None:
    import inspect

    from app.routes import questions
    from app.services import occlusion_questions

    body = inspect.getsource(questions.factory_generate_questions_batch)
    assert "_occlusion.filed_for_sub_strand(" in body
    assert "_occlusion.merge_figures(" in body

    bundle = [{"title": "The cell", "description": "brief only"}]
    filed = [{"diagram_id": "d1", "title": "The cell", "svg_markup": "<svg/>",
              "scene_document": {"parts": [{"part_id": "p"}]}},
             {"diagram_id": "d2", "title": "Another", "svg_markup": "<svg/>", "scene_document": {}}]
    merged = occlusion_questions.merge_figures(bundle, filed)

    assert merged[0]["scene_document"] == {"parts": [{"part_id": "p"}]}
    assert merged[0]["diagram_id"] == "d1"
    assert [m["diagram_id"] for m in merged] == ["d1", "d2"]
