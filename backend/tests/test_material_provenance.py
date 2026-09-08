"""Nothing taught twice, and every piece naming what it serves in KICD.

Two faults from one Grade 9 guide, both of which read as normal on the page:

  * the same three exercises set in six lessons, the same BODMAS paragraph
    written in two, and one expression worked sixteen times;
  * every piece captioned "Not quoted from the design — written here for this
    lesson", which tells a head of department nothing and is not what a
    curriculum guide is.

These notes are not written from open ground. The design asks for something and
the piece realises it; naming which thing is what makes the page findable in
the Grade design and in the BECF a term later.
"""
from __future__ import annotations

import unittest.mock as mock

import pytest

from app.services import lesson_material as lm

DESIGN = {
    "slos": [{"slo_id": "g9-mat-01",
              "slo": "perform combined operations on integers"}],
    "key_inquiry_questions": ["How do we use negative numbers in daily life?"],
}


def _piece(n, **over):
    # Distinct prose per piece, so a test about repeated TASKS is not also
    # tripping the repeated-lesson check.
    return {"module_number": n, "title": f"Lesson {n}",
            "say": f"Lesson {n} teaches its own distinct thing, at length, "
                   f"in words that are not lesson {n + 1}'s words.", **over}


def _tasks(found):
    return [f for f in found if f["kind"] != "lesson"]


# ── nothing is taught twice ─────────────────────────────────────────────────


def test_the_same_exercise_set_in_two_lessons_is_caught() -> None:
    """One guide set the identical three exercises in all six lessons. Each
    copy is a full, correct exercise set, so a reader going forwards sees six
    good lessons."""
    exercises = [{"question": "5+3*2-4", "answer": "7"},
                 {"question": "5-2*3-4", "answer": "-5"}]
    found = lm.check_repetition({"material": [
        _piece(1, exercises=exercises), _piece(2, exercises=exercises)]})

    tasks = _tasks(found)
    assert [f["kind"] for f in tasks] == ["exercise", "exercise"]
    assert tasks[0]["first_seen"] == "lesson 1" and tasks[0]["where"] == "lesson 2"


def test_the_same_worked_example_in_two_lessons_is_caught() -> None:
    example = [{"statement": "Evaluate (-15/3 - (-2)*(-4) + 6)/(-2*3 + (-4))",
                "answer": "7/10"}]
    found = lm.check_repetition({"material": [
        _piece(1, worked_examples=example), _piece(5, worked_examples=example)]})

    assert _tasks(found) and _tasks(found)[0]["kind"] == "worked example"


def test_a_reworded_copy_of_the_same_task_still_matches() -> None:
    """A guide can vary its wording in every lesson and still set the identical
    arithmetic, so tasks are compared on their arithmetic."""
    found = lm.check_repetition({"material": [
        _piece(1, exercises=[{"question": "Evaluate 5 + 3 × 2 - 4"}]),
        _piece(2, exercises=[{"question": "Work out: 5+3*2-4."}])]})

    assert _tasks(found), "the same sum, differently worded, is the same task"


def test_two_lessons_that_are_substantially_one_lesson_are_caught() -> None:
    same = ("The order of operations is crucial. We use BODMAS: Brackets, "
            "Orders, Division and Multiplication, Addition and Subtraction. "
            "In 3+5x2 we first multiply 5x2=10, then add 3+10=13.")
    found = lm.check_repetition({"material": [
        _piece(2, say=same), _piece(3, say=same), _piece(4, say="something else")]})

    assert any(f["kind"] == "lesson" for f in found)


def test_different_tasks_in_different_lessons_are_not_a_repeat() -> None:
    found = lm.check_repetition({"material": [
        _piece(1, exercises=[{"question": "-15 ÷ 3 - (-2) × (-4) + 6"}]),
        _piece(2, exercises=[{"question": "-8 + 3 × (-4) - (-6) ÷ 2"}])]})

    assert _tasks(found) == []


def test_repetition_fails_the_gate_and_names_what_to_do() -> None:
    report = lm.MaterialReport(total=1, written=1)
    report.repeated = [{"kind": "exercise", "where": "lesson 4",
                        "first_seen": "lesson 1", "task": "5+3*2-4"}]
    gate = lm.gate_of(report)

    assert not gate["passed"]
    assert any("already set in lesson 1" in a for a in gate["next_actions"])


# ── every piece names what it serves ────────────────────────────────────────


def _provenance(material):
    with mock.patch.object(lm, "_design_row", return_value=DESIGN):
        return lm.check_provenance(material, "grade-9", "Mathematics", "Integers")


def test_a_piece_that_names_no_design_element_is_caught() -> None:
    found = _provenance({"material": [_piece(2, serves=[])]})

    assert len(found) == 1 and found[0]["lesson"] == 2
    assert "g9-mat-01" in found[0]["available"], "it says what was available"


def test_an_invented_ref_is_not_provenance() -> None:
    """An invented provenance reads exactly like a real one, and is worse than
    none."""
    found = _provenance({"material": [_piece(3, serves=["made up ref"])]})

    assert found and found[0]["invented"] == ["made up ref"]


def test_a_piece_that_names_a_real_element_passes() -> None:
    assert _provenance({"material": [_piece(1, serves=["g9-mat-01"])]}) == []


def test_a_design_this_system_has_not_read_fails_nothing() -> None:
    """Silence rather than failing every piece for a design nobody extracted."""
    with mock.patch.object(lm, "_design_row", return_value={}):
        assert lm.check_provenance({"material": [_piece(1)]},
                                   "grade-9", "Mathematics", "Integers") == []


def test_missing_provenance_fails_the_gate() -> None:
    report = lm.MaterialReport(total=1, written=1)
    report.unsourced = [{"lesson": 2, "topic": "Games", "invented": [],
                         "available": "g9-mat-01"}]
    gate = lm.gate_of(report)

    assert not gate["passed"]
    assert any("names no design element" in a for a in gate["next_actions"])


# ── and it reaches the page in the design's own words ───────────────────────


def test_the_page_shows_the_design_s_words_not_a_bare_ref() -> None:
    """A ref on its own is an address nobody can read. Resolved, it is a phrase
    a head of department can find in the design and in the BECF."""
    import re

    from app.services import notes_renderer

    material = {"material": [_piece(1, serves=["g9-mat-01", "inquiry 1"],
                                    attribution="written here for this lesson")]}
    with mock.patch.object(lm, "_design_row", return_value=DESIGN):
        html = notes_renderer.render_material_html(
            material, grade="grade-9", subject="Mathematics",
            strand="Numbers", sub_strand="Integers")

    shown = [re.sub(r"<[^>]+>", "", x)
             for x in re.findall(r"<p class='serves'>(.*?)</p>", html)]
    assert "g9-mat-01 perform combined operations on integers" in shown
    assert "inquiry 1 How do we use negative numbers in daily life?" in shown


def test_a_ref_the_design_does_not_carry_is_not_printed() -> None:
    import re

    from app.services import notes_renderer

    material = {"material": [_piece(1, serves=["invented 9"],
                                    attribution="written here")]}
    with mock.patch.object(lm, "_design_row", return_value=DESIGN):
        html = notes_renderer.render_material_html(
            material, grade="grade-9", subject="Mathematics",
            sub_strand="Integers")

    assert not re.findall(r"<p class='serves'>", html)


def test_the_generator_is_told_to_name_what_each_piece_serves() -> None:
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    prompt = SEED_AGENT_PROMPTS["material-generator"]

    assert "{{ design_elements }}" in prompt
    assert '"serves"' in prompt
    assert "written from open ground" in prompt
