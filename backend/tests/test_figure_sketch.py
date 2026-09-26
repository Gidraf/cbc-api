"""The figure a question needs, drawn from the question's own numbers."""
from __future__ import annotations

import re

from app.services import figure_sketch
from app.services.diagram_scene import build_scene_from_svg, occludable_parts


def _labels(svg: str) -> list[str]:
    return re.findall(r"<text[^>]*>([^<]+)</text>", svg)


def test_every_kind_draws() -> None:
    specs = [
        {"kind": "number_line", "min": -10, "max": 10, "step": 2, "marks": [{"value": -4, "label": "P"}]},
        {"kind": "bar_chart", "title": "Rainfall", "categories": ["Jan", "Feb"], "values": [60, 45], "unit": "mm"},
        {"kind": "pie_chart", "slices": [{"label": "Walk", "value": 20}, {"label": "Bus", "value": 20}]},
        {"kind": "line_graph", "points": [[1, 18], [2, 21], [3, 19]]},
        {"kind": "table", "columns": ["Item", "Price"], "rows": [["Bread", "65"]]},
        {"kind": "clock", "hour": 7, "minute": 45},
        {"kind": "thermometer", "min": -20, "max": 50, "reading": -5},
        {"kind": "shape", "shape": "rectangle", "dimensions": {"length": 12, "width": 5}, "unit": "cm"},
        {"kind": "shape", "shape": "right_triangle", "dimensions": {"base": 8, "height": 6, "hypotenuse": 10}},
        {"kind": "shape", "shape": "circle", "dimensions": {"radius": 7}},
        {"kind": "shape", "shape": "trapezium", "dimensions": {"bottom": 12, "top": 8, "height": 5}, "shaded": True},
        {"kind": "fraction", "parts": 8, "shaded": 3},
        {"kind": "angle", "degrees": 135, "label": "x"},
    ]
    for spec in specs:
        out = figure_sketch.render(spec)
        assert out and out["svg"].startswith("<svg"), spec["kind"]


def test_the_figure_carries_the_questions_numbers_and_nothing_else() -> None:
    out = figure_sketch.render({"kind": "shape", "shape": "rectangle",
                                "dimensions": {"length": 12, "width": 5}, "unit": "cm",
                                "labels": {"vertices": ["A", "B", "C", "D"]}})
    labels = _labels(out["svg"])

    assert "12 cm" in labels and "5 cm" in labels
    assert {"A", "B", "C", "D"} <= set(labels)
    assert not any("area" in lb.lower() for lb in labels)


def test_the_geometry_follows_the_numbers() -> None:
    """A 12 by 5 rectangle is wider than it is tall; a 50% slice is half."""
    out = figure_sketch.render({"kind": "shape", "shape": "rectangle", "dimensions": {"length": 12, "width": 5}})
    w, h = map(float, re.search(r"<rect x='[\d.]+' y='[\d.]+' width='([\d.]+)' height='([\d.]+)'", out["svg"]).groups())
    assert abs(w / h - 12 / 5) < 0.01

    pie = figure_sketch.render({"kind": "pie_chart", "slices": [{"label": "a", "value": 1}, {"label": "b", "value": 1}]})
    assert "50%" in _labels(pie["svg"])


def test_a_figure_that_cannot_be_drawn_is_none_not_an_error() -> None:
    assert figure_sketch.render({"kind": "hologram"}) is None
    assert figure_sketch.render({"kind": "bar_chart"}) is None
    assert figure_sketch.render("x") is None


def test_a_question_figures_labels_are_givens_and_never_blanked() -> None:
    out = figure_sketch.render({"kind": "bar_chart", "categories": ["Jan", "Feb"], "values": [60, 45]})
    scene = build_scene_from_svg(out["svg"], out["title"], out["scene"])

    assert scene["parts"], "the labels are addressable"
    assert occludable_parts(scene, "label_blanks") == []


def test_the_questions_station_draws_files_and_binds_figures() -> None:
    import inspect

    from app.routes import questions

    source = inspect.getsource(questions)
    assert "figure_sketch.prompt_block(payload.subject)" in source, "the writer is told how to ask for a figure"
    assert "_draw_question_figures(" in source and "_bind_figure(raw_q) or resolve_binding(" in source
    binding = questions._bind_figure({"_figure": {"diagram_id": "diag-1", "diagram_title": "T"}})
    assert binding.variant_mode == "full" and binding.hide_layers == [] and binding.binding_method == "explicit"
    assert questions._bind_figure({}) is None


def test_the_queued_diagram_station_draws_what_it_planned() -> None:
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum._run_queued)
    assert '_draw_planned_visuals(result)' in source
    draw = inspect.getsource(curriculum._draw_planned_visuals)
    assert "factory_draw_visual(DrawVisualRequest(artifact_id=artifact_id, index=index), None)" in draw
    assert "failed.append" in draw, "one failed drawing must not fail the station"
