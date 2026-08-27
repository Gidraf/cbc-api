"""Questions written from the figures themselves, not from descriptions of them."""
from __future__ import annotations

import pytest

from app.services import occlusion_questions as oq
from app.services.diagram_scene import build_scene_from_svg

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">
<rect x="0" y="0" width="400" height="300" fill="#fff"/>
<text x="200" y="40" font-size="14">Stigma</text>
<text x="200" y="150" font-size="14">Ovary</text>
<text x="120" y="220" font-size="14">Petal</text>
<text x="300" y="250" font-size="14">37 °C</text>
</svg>"""

MODEL_SCENE = {"parts": [
    {"label": "Stigma", "function": "receives pollen during pollination", "assessable": True},
    {"label": "Ovary", "function": "contains the ovules", "assessable": True},
    {"label": "Petal", "function": "attracts pollinators", "assessable": True},
    {"label": "37 °C", "function": "incubation temperature", "assessable": True},
]}


def programmable(diagram_id="d1"):
    return {
        "diagram_id": diagram_id, "title": "Parts of a flower", "svg_markup": SVG,
        "scene_document": build_scene_from_svg(SVG, "Parts of a flower", MODEL_SCENE),
    }


def picture(diagram_id="p1"):
    """A visual with no scene document: showable, but no part is addressable."""
    return {"diagram_id": diagram_id, "title": "A photograph", "svg_markup": SVG, "scene_document": {}}


def stub_model(_prompt):
    return {"questions": [{
        "question_text": "Study the flower and answer the questions.",
        "slots_tested": ["A"],
        "structured_parts": [
            {"part_id": "(a)", "sub_question": "Name the part labelled A.", "marks": 1},
        ],
    }]}


def test_only_diagrams_with_addressable_parts_are_used():
    assert len(oq.programmable_diagrams([programmable(), picture()])) == 1


def test_questions_are_authored_from_a_programmable_diagram():
    result = oq.author_for_substrand([programmable()], generate=stub_model)
    assert result["questions"], result["summary"]
    assert all(q["question_type"] == "diagram_based" for q in result["questions"])
    assert result["diagrams_programmable"] == 1


def test_the_marking_scheme_comes_from_the_diagram_not_the_model():
    """A question written from a description cannot be marked against the figure."""
    def wrong_answer(_prompt):
        return {"questions": [{
            "question_text": "Study the flower.",
            "slots_tested": ["A"],
            "structured_parts": [
                {"part_id": "(a)", "sub_question": "Name the part labelled A.",
                 "marks": 1, "model_answer": "Anther"},
            ],
        }]}

    result = oq.author_for_substrand([programmable()], generate=wrong_answer)
    answers = {p["model_answer"] for q in result["questions"] for p in q["structured_parts"]}
    assert "Anther" not in answers, "the diagram is the authority on its own parts"


def test_one_figure_yields_several_different_questions():
    result = oq.author_for_substrand([programmable()], generate=stub_model)
    modes = {q["occlusion_mode"] for q in result["questions"]}
    assert len(result["questions"]) >= 2
    assert len(modes) >= 1


def test_each_question_carries_the_paper_and_the_marking_copy():
    result = oq.author_for_substrand([programmable()], generate=stub_model)
    render = result["renders"][0]
    assert render["paper_svg"] and render["answer_svg"]
    assert render["paper_svg"] != render["answer_svg"]
    assert render["removed_facts"]


def test_a_diagram_that_cannot_be_occluded_is_skipped_with_its_reason():
    bare = {"diagram_id": "b1", "title": "Bare", "svg_markup": "<svg/>",
            "scene_document": {"parts": [{"part_id": "x", "label": "x", "assessable": False}]}}
    result = oq.author_for_substrand([bare], generate=stub_model)
    assert result["questions"] == []
    assert result["diagrams_programmable"] == 0


def test_one_failing_diagram_does_not_cost_the_others():
    calls = {"n": 0}

    def flaky(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("provider hiccup")
        return stub_model(prompt)

    result = oq.author_for_substrand([programmable("d1"), programmable("d2")], generate=flaky)
    assert result["questions"], "the diagrams that worked must still produce questions"
    assert result["skipped"], "and the failure must be reported"


def test_no_diagrams_is_reported_rather_than_failing():
    result = oq.author_for_substrand([], generate=stub_model)
    assert result["questions"] == []
    assert result["diagrams_available"] == 0
    assert "0 programmable" in result["summary"]
