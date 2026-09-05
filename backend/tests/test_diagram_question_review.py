"""Reviewing a diagram question by doing to the diagram what the question does.

"Name the part labelled A" is a claim about a PICTURE that has had something
taken out of it. Reading the question and the diagram separately — all a text
reviewer can do — cannot see that the answer is printed elsewhere on the page,
or that nothing was removed at all.
"""
from __future__ import annotations

import pytest

from app.services import diagram_question_review as dqr

SVG = ('<svg viewBox="0 0 200 100" xmlns="http://www.w3.org/2000/svg">'
       '<g data-part-id="part-stigma" id="part-stigma">'
       '<circle cx="50" cy="30" r="8"/><text x="50" y="20">Stigma</text></g>'
       '<g data-part-id="part-style" id="part-style">'
       '<line x1="50" y1="38" x2="50" y2="70"/><text x="62" y="55">Style</text></g>'
       '<text x="120" y="90">The Stigma receives pollen</text></svg>')

SCENE = {"parts": [{"id": "part-stigma", "label": "Stigma", "occludable": True},
                   {"id": "part-style", "label": "Style", "occludable": True}]}
DIAGRAM = {"diagram_svg": SVG, "scene_document": SCENE}


def test_a_sound_question_survives_its_own_manipulation() -> None:
    verdict = dqr.review(DIAGRAM, {"hide_part_ids": ["part-style"]}, answer="Style")

    assert verdict.checked and verdict.sound
    assert verdict.hidden_labels == ["Style"]
    assert "Style" not in " ".join(dqr.visible_text(verdict.learner_view))
    assert "Style" in " ".join(dqr.visible_text(verdict.marking_view))


def test_an_answer_printed_elsewhere_is_caught() -> None:
    """The label is hidden and the caption still says it. Only manipulating the
    diagram shows that the question is free marks."""
    verdict = dqr.review(DIAGRAM, {"hide_part_ids": ["part-stigma"]}, answer="Stigma")

    assert not verdict.sound
    assert dqr.LEAK in [f.code for f in verdict.findings]
    assert "receives pollen" in verdict.findings[0].detail


def test_a_question_that_hides_nothing_is_caught() -> None:
    verdict = dqr.review(DIAGRAM, {"hide_part_ids": []}, answer="Stigma")

    assert not verdict.sound
    assert dqr.LEAK in [f.code for f in verdict.findings]


def test_hiding_two_parts_leaves_no_single_answer() -> None:
    verdict = dqr.review(
        DIAGRAM, {"hide_part_ids": ["part-stigma", "part-style"]}, answer="Stigma")

    assert dqr.AMBIGUOUS in [f.code for f in verdict.findings]


def test_pointing_at_a_region_the_diagram_lacks_is_caught() -> None:
    verdict = dqr.review(
        DIAGRAM, {"hide_part_ids": ["part-style"], "region_id": "part-ovary"},
        answer="Style")

    assert dqr.OFF_CANVAS in [f.code for f in verdict.findings]


def test_a_question_about_a_diagram_nobody_drew_is_caught() -> None:
    """The plan was written and nothing was drawn from it, so the question
    points at a blank space."""
    verdict = dqr.review({"diagram_svg": "", "scene_document": SCENE},
                         {"hide_part_ids": []}, answer="Stigma")

    assert not verdict.checked
    assert dqr.NO_DIAGRAM in [f.code for f in verdict.findings]


# ── the leak check must not cry wolf ────────────────────────────────────────

@pytest.mark.parametrize("answer", ["A", "B", "12"])
def test_a_one_or_two_character_answer_is_not_leak_checked(answer: str) -> None:
    """"A" appears in half the labels on any diagram. Flagging that would train
    a reviewer to ignore this check."""
    assert dqr._leaks(answer, ["A label", "Part A"]) == ""


def test_a_substring_is_not_a_leak() -> None:
    """"Zero" must not be reported because the picture prints "-10"."""
    assert dqr._leaks("Zero", ["-10", "10", "0"]) == ""
    assert dqr._leaks("Style", ["Stylet"]) == ""


def test_a_whole_word_or_phrase_is_a_leak() -> None:
    assert dqr._leaks("Stigma", ["The Stigma receives pollen"])
    assert dqr._leaks("number line", ["This number line shows integers"])


# ── the engine finds parts however the drawing marked them ──────────────────

def test_a_model_drawn_svg_can_still_be_occluded() -> None:
    """The engine hid by `data-part-id`; a model asked for an SVG writes
    `id="part-stigma"`, because that is ordinary SVG. A drawing whose parts
    cannot be found is one no question can occlude — so every question against
    it silently showed the learner the marking copy."""
    model_drawn = SVG.replace(' data-part-id="part-stigma"', "").replace(
        ' data-part-id="part-style"', "")
    verdict = dqr.review({"diagram_svg": model_drawn, "scene_document": SCENE},
                         {"hide_part_ids": ["part-style"]}, answer="Style")

    assert verdict.checked
    assert "Style" not in " ".join(dqr.visible_text(verdict.learner_view))


def test_the_drawing_brief_asks_for_the_marker_the_engine_reads() -> None:
    import inspect

    from app.routes import curriculum

    brief = inspect.getsource(curriculum._svg_brief)
    assert "data-part-id" in brief
    assert "cannot be hidden" in brief


# ── the gate ────────────────────────────────────────────────────────────────

def test_the_gate_names_what_to_fix() -> None:
    verdicts = [
        dqr.review(DIAGRAM, {"hide_part_ids": ["part-style"]}, "Style"),
        dqr.review(DIAGRAM, {"hide_part_ids": ["part-stigma"]}, "Stigma"),
        dqr.review({"diagram_svg": "", "scene_document": SCENE}, {}, "Stigma"),
    ]
    gate = dqr.gate_of(verdicts)

    assert not gate["passed"]
    assert "1 of 3" in gate["summary_message"]
    actions = " ".join(gate["next_actions"])
    assert "print their own answer" in actions
    assert "never drawn" in actions


def test_all_sound_passes() -> None:
    gate = dqr.gate_of([dqr.review(DIAGRAM, {"hide_part_ids": ["part-style"]}, "Style")])

    assert gate["passed"]
    assert gate["overall_score"] == 100


def test_the_views_are_returned_so_a_person_can_look() -> None:
    """A reviewer should be able to SEE what the learner will see rather than
    take this on trust."""
    out = dqr.review(DIAGRAM, {"hide_part_ids": ["part-style"]}, "Style").to_dict()

    assert out["learner_view"].startswith("<svg") or "<svg" in out["learner_view"]
    assert out["marking_view"]
    assert out["learner_view"] != out["marking_view"]
