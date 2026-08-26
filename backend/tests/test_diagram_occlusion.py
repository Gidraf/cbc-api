"""The occlusion path: what is removed, what is asked, and what is marked."""
from __future__ import annotations

import pytest

from app.question_models import DiagramBinding
from app.services.diagram_binding import resolve_binding
from app.services.diagram_question_agent import (
    OcclusionNotPossible,
    author_questions_from_diagram,
)
from app.services.diagram_scene import (
    apply_occlusion,
    build_scene_from_svg,
    describe_scene_for_prompt,
    plan_occlusion,
    render_for_question,
)

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">
<rect x="0" y="0" width="400" height="300" fill="#ffffff"/>
<circle cx="200" cy="90" r="40"/>
<text x="200" y="40" font-size="14">Stigma</text>
<text x="200" y="150" font-size="14">Ovary</text>
<text x="120" y="220" font-size="14">Petal</text>
<text x="300" y="250" font-size="14">37 °C</text>
</svg>"""

MODEL_SCENE = {
    "parts": [
        {"label": "Stigma", "function": "receives pollen during pollination", "assessable": True},
        {"label": "Ovary", "function": "contains the ovules that become seeds", "assessable": True},
        {"label": "Petal", "function": "attracts insect pollinators", "assessable": True},
        {"label": "37 °C", "function": "incubation temperature", "assessable": True},
    ]
}


@pytest.fixture
def diagram():
    scene = build_scene_from_svg(SVG, "Parts of a flower", MODEL_SCENE)
    return {
        "asset_id": "diag_flower_01",
        "title": "Parts of a flower",
        "svg_markup": SVG,
        "scene_document": scene,
    }


def test_occlusion_hides_only_the_chosen_parts(diagram):
    plan = plan_occlusion(diagram["scene_document"], mode="label_blanks", max_blanks=2)
    out = apply_occlusion(diagram, plan)

    hidden = [f["label"] for f in plan["removed_facts"]]
    retained = [p["label"] for p in plan["retained_parts"]]

    assert len(hidden) == 2
    for label in hidden:
        assert label not in out["paper_svg"]
        assert label in out["answer_svg"]
    for label in retained:
        assert label in out["paper_svg"]


def test_every_blank_gets_a_marker(diagram):
    """A gap with no marker is a question the learner cannot see."""
    plan = plan_occlusion(diagram["scene_document"], max_blanks=3)
    out = apply_occlusion(diagram, plan)

    for fact in plan["removed_facts"]:
        assert f'data-blank-slot="{fact["slot"]}"' in out["paper_svg"]
    assert "data-blank-slot" not in out["answer_svg"]


def test_occlusion_is_deterministic(diagram):
    a = plan_occlusion(diagram["scene_document"], max_blanks=2)
    b = plan_occlusion(diagram["scene_document"], max_blanks=2)
    assert a["slots"] == b["slots"]


def test_missing_parameters_mode_targets_measurements(diagram):
    plan = plan_occlusion(diagram["scene_document"], mode="missing_parameters", max_blanks=5)
    assert [f["label"] for f in plan["removed_facts"]] == ["37 °C"]


def test_binding_rejects_a_blank_without_a_marker():
    with pytest.raises(ValueError, match="without a blank marker"):
        DiagramBinding(diagram_id="d1", hide_part_ids=["stigma"], slots={})


def test_authored_binding_beats_semantic_guessing(diagram):
    plan = plan_occlusion(diagram["scene_document"], max_blanks=2)
    raw = {
        "question_text": "Name the part labelled A.",
        "diagram_occlusion": {
            "mode": plan["mode"],
            "hidden_part_ids": plan["hidden_part_ids"],
            "slots": plan["slots"],
        },
    }
    binding = resolve_binding(raw, "diagram_based", [diagram], anchored_diagram=diagram)

    assert binding is not None
    assert binding.binding_method == "authored"
    assert binding.binding_confidence == 1.0
    assert binding.hide_part_ids == plan["hidden_part_ids"]
    assert binding.slots == plan["slots"]
    # Per-part hiding replaces the blunt whole-layer strip.
    assert binding.hide_layers == []


def test_binding_drops_part_ids_the_scene_does_not_know(diagram):
    raw = {
        "question_text": "Name the part labelled A.",
        "diagram_occlusion": {
            "mode": "label_blanks",
            "hidden_part_ids": ["stigma", "invented_part"],
            "slots": {"stigma": "A", "invented_part": "B"},
        },
    }
    binding = resolve_binding(raw, "diagram_based", [diagram], anchored_diagram=diagram)
    assert binding.hide_part_ids == ["stigma"]
    assert binding.slots == {"stigma": "A"}


def test_render_for_question_splits_paper_from_marking_scheme(diagram):
    plan = plan_occlusion(diagram["scene_document"], max_blanks=1)
    binding = {
        "hide_part_ids": plan["hidden_part_ids"],
        "slots": plan["slots"],
        "region_id": None,
    }
    label = plan["removed_facts"][0]["label"]

    paper = render_for_question(diagram, binding, with_answers=False)
    marking = render_for_question(diagram, binding, with_answers=True)

    assert label not in paper
    assert label in marking


# ── The agent ────────────────────────────────────────────────────────────────

def _stub(payload):
    return lambda _prompt: payload


def test_agent_answers_come_from_the_diagram_not_the_model(diagram):
    """A model that mislabels a part must not reach the marking scheme."""
    result = author_questions_from_diagram(
        diagram,
        generate=_stub({"questions": [{
            "question_text": "Study the flower and answer the questions.",
            "slots_tested": ["A"],
            "structured_parts": [
                {"part_id": "(a)", "sub_question": "Name the part labelled A.",
                 "marks": 1, "model_answer": "Anther"},
            ],
        }]}),
        max_blanks=1,
    )

    question = result["questions"][0]
    truth = result["removed_facts"][0]["label"]
    assert question["structured_parts"][0]["model_answer"] == truth
    assert any("used the diagram" in note for note in question["answer_corrections"])


def test_agent_answers_function_questions_with_the_function(diagram):
    result = author_questions_from_diagram(
        diagram,
        generate=_stub({"questions": [{
            "question_text": "Study the diagram.",
            "slots_tested": ["A"],
            "structured_parts": [
                {"part_id": "(a)", "sub_question": "State the function of the part labelled A.", "marks": 2},
            ],
        }]}),
        max_blanks=1,
    )
    fact = result["removed_facts"][0]
    assert result["questions"][0]["structured_parts"][0]["model_answer"] == fact["function"]


def test_agent_drops_a_question_that_gives_the_answer_away(diagram):
    plan = plan_occlusion(diagram["scene_document"], max_blanks=1)
    hidden_label = plan["removed_facts"][0]["label"]

    result = author_questions_from_diagram(
        diagram,
        generate=_stub({"questions": [{
            "question_text": f"Where is the {hidden_label} found? It is labelled A.",
            "slots_tested": ["A"],
            "structured_parts": [
                {"part_id": "(a)", "sub_question": "Name the part labelled A.", "marks": 1},
            ],
        }]}),
        max_blanks=1,
    )

    assert result["questions"] == []
    assert "revealed the hidden label" in result["rejected"][0]["reasons"][0]


def test_agent_drops_a_question_about_a_slot_that_was_never_blanked(diagram):
    result = author_questions_from_diagram(
        diagram,
        generate=_stub({"questions": [{
            "question_text": "Name the part labelled Z.",
            "slots_tested": ["Z"],
            "structured_parts": [
                {"part_id": "(a)", "sub_question": "Name the part labelled Z.", "marks": 1},
            ],
        }]}),
        max_blanks=1,
    )
    assert result["questions"] == []
    assert "unknown slot" in result["rejected"][0]["reasons"][0]


def test_agent_marks_total_the_sub_questions(diagram):
    result = author_questions_from_diagram(
        diagram,
        generate=_stub({"questions": [{
            "question_text": "Study the diagram.",
            "slots_tested": ["A", "B"],
            "structured_parts": [
                {"part_id": "(a)", "sub_question": "Name the part labelled A.", "marks": 1},
                {"part_id": "(b)", "sub_question": "State the function of the part labelled B.", "marks": 3},
            ],
        }]}),
        max_blanks=2,
    )
    assert result["questions"][0]["max_marks"] == 4


def test_agent_refuses_a_diagram_with_nothing_to_blank():
    bare = {"asset_id": "d", "svg_markup": "<svg/>", "scene_document": {"parts": []}}
    with pytest.raises(OcclusionNotPossible):
        author_questions_from_diagram(bare, generate=_stub({"questions": []}))


def test_prompt_lists_parts_instead_of_raw_svg(diagram):
    catalogue = describe_scene_for_prompt(diagram["scene_document"])
    assert "part_id=stigma" in catalogue
    assert "receives pollen" in catalogue
    assert "<svg" not in catalogue
