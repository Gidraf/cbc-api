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


def test_a_design_this_system_has_not_read_blames_no_piece() -> None:
    """No piece is at fault for a design nobody extracted — but it is not clean.

    This used to return `[]`, which is also what "every piece cites the design"
    returns. The gate read the empty list, scored 1.0 and printed "every piece
    names the design element it serves" about a guide that had never been
    checked against anything, under a footer claiming KICD provenance.
    """
    with mock.patch.object(lm, "_design_row", return_value={}):
        try:
            lm.check_provenance({"material": [_piece(1)]},
                                "grade-9", "Mathematics", "Integers")
        except lm.UncheckableProvenance as exc:
            assert "curriculum_substrands" in str(exc)
        else:
            raise AssertionError("an unread design must not report clean")


def test_an_unread_design_is_reported_as_unchecked_not_passed() -> None:
    report = lm.MaterialReport(total=1, written=1)
    report.provenance_blocked = "no row in curriculum_substrands for grade-9"
    gate = lm.gate_of(report)

    assert not gate["passed"]
    aspect = next(a for a in gate["reviewer"]["feedback"]
                  if a["aspect"] == "every_piece_names_what_it_serves")
    assert aspect["status"] == "unchecked"
    assert aspect["score"] == 0.0
    assert "could not be checked" in aspect["comment"]
    assert any("unverifiable" in a for a in gate["next_actions"])


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


def test_a_lesson_cloned_with_new_numbers_is_caught() -> None:
    """`redundancy_check` compares prose and the task pass compares arithmetic,
    and a renumbered clone slips between them: the words differ enough to score
    as distinct, and every sum in it is genuinely new. One guide taught "the
    temperature rises from -5°C to 3°C" in lesson 3 and "rises from -3°C to
    2°C" in lesson 6, same apparatus, and spent two of six periods reading a
    thermometer."""
    three = ("Integers are often used to represent temperature changes. For "
             "example, if the temperature rises from -5C to 3C, we represent "
             "this change as +8C. Conversely, if it drops from 2C to -4C, the "
             "change is -6C. Let us discuss examples of tracking temperature "
             "changes in our environment.")
    six = ("Integers are often used to represent temperature changes. For "
           "instance, if the temperature rises from -3C to 2C, we represent "
           "this change as +5C. Conversely, if it drops from 1C to -4C, the "
           "change is -5C. Let us practice reading temperature changes in our "
           "environment.")
    other = ("In financial contexts, integers represent profits and losses. If "
             "a business earns KSh 5000 and incurs a loss of KSh 2000, we "
             "write 5000 + (-2000) = 3000. Understanding this is crucial for "
             "managing money effectively over a long period of time.")

    found = lm.check_repetition({"material": [
        {"module_number": 3, "say": three},
        {"module_number": 4, "say": other},
        {"module_number": 6, "say": six}]})

    clones = [f for f in found if f["kind"] == "lesson"]
    assert clones
    assert clones[0]["first_seen"] == "lesson 3" and clones[0]["where"] == "lesson 6"


def test_two_genuinely_different_lessons_are_not_clones() -> None:
    a = ("Integers are used to represent temperature changes above and below "
         "freezing, and a thermometer is the instrument that reads them off a "
         "scale marked in degrees Celsius on both sides of zero.")
    b = ("Multiplying two integers with the same sign gives a positive result, "
         "and multiplying two with different signs gives a negative one. The "
         "same rule governs division of directed numbers throughout.")

    found = lm.check_repetition({"material": [
        {"module_number": 1, "say": a}, {"module_number": 2, "say": b}]})

    assert not [f for f in found if f["kind"] == "lesson"]


# ── each piece is told what the earlier pieces used ─────────────────────────


def test_the_ledger_names_what_earlier_pieces_already_used() -> None:
    """The material station generates one call per directive — the finer
    granularity it looks like it should be — and every call was blind to the
    others. That is twenty-one authors writing one book without reading each
    other, and it produced what that produces: one expression in sixteen
    examples, three exercises in six lessons, lesson 6 a copy of lesson 3."""
    block = lm.already_taught([
        {"module_number": 1, "title": "Addition",
         "worked_examples": [{"statement": "Evaluate -15 ÷ 3 - (-2) × (-4) + 6",
                              "steps": [{"working": "-5 - 8 + 6 = -7"}],
                              "answer": "7/10"}],
         "exercises": [{"question": "5 + (-3)"}]},
        {"module_number": 2, "title": "Temperature",
         "exercises": [{"question": "The temperature rises from -5C to 3C."}]},
    ])

    assert "Lesson 1 — Addition" in block and "Lesson 2 — Temperature" in block
    assert "5 + (-3)" in block
    assert "with the numbers changed" in block, "the renumbered clone is named"


def test_the_first_piece_gets_no_ledger() -> None:
    """There is nothing to repeat yet, and an empty heading is noise."""
    assert lm.already_taught([]) == ""


def test_the_ledger_is_bounded() -> None:
    """It must not become the prompt."""
    many = [{"module_number": n, "title": f"Topic {n}",
             "exercises": [{"question": f"question {n}.{i}"} for i in range(20)]}
            for n in range(40)]

    block = lm.already_taught(many)
    listed = [ln for ln in block.split("\n") if ln.startswith("  Lesson ")]

    assert len(listed) == lm.LEDGER_PIECES
    assert "question 0.9" not in block, "only the first few items of each piece"


def test_every_piece_after_the_first_is_given_it() -> None:
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_material)
    assert "written_already=lesson_material.already_taught(written)" in source


def test_the_slot_exists_in_the_prompt() -> None:
    """A binding whose template never mentions the slot replaces nothing."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    assert "{{ already_taught }}" in SEED_AGENT_PROMPTS["material-generator"]


# ── the prompt promises this check; it has to actually run ──────────────────


def test_lessons_sharing_an_outcome_are_caught_even_with_no_citations() -> None:
    """The prompt tells the model that repeating an outcome "is detected
    mechanically after you write — by comparing each module's `slos_covered`,
    `citations` and `learning_experiences_used`".

    It was not. The check required a citation as well as an outcome, so a guide
    that gave three of its six lessons to one outcome and cited the design
    nowhere skipped every one of them. A promise in a prompt that nothing keeps
    is worse than no promise.
    """
    from app.services.redundancy_check import _same_outcome_same_source

    same = "work out combined operations of integers in the correct order"
    uncited = [{"module_number": n, "title": f"Lesson {n}",
                "slos_covered": [same], "citations": [],
                "learning_experiences_used": ["work out combined operations"]}
               for n in (2, 3, 4)]

    found = _same_outcome_same_source(uncited)

    assert len(found) == 1
    assert found[0]["lessons"] == ["Lesson 2", "Lesson 3", "Lesson 4"]
    assert found[0]["uncited"] is True


def test_it_still_works_when_the_guide_does_cite() -> None:
    from app.services.redundancy_check import _same_outcome_same_source

    same = "work out combined operations of integers in the correct order"
    cited = [{"module_number": n, "title": f"Lesson {n}",
              "slos_covered": [same], "citations": [{"ref": "13:4"}],
              "learning_experiences_used": ["x"]} for n in (2, 3, 4)]

    found = _same_outcome_same_source(cited)

    assert len(found) == 1 and found[0]["ref"] == "13:4"
    assert found[0]["uncited"] is False


def test_lessons_on_different_outcomes_are_not_grouped() -> None:
    from app.services.redundancy_check import _same_outcome_same_source

    different = [
        {"module_number": 1, "title": "L1", "slos_covered": ["perform basic operations"],
         "citations": [], "learning_experiences_used": ["cards"]},
        {"module_number": 2, "title": "L2", "slos_covered": ["apply integers to real life"],
         "citations": [], "learning_experiences_used": ["thermometer"]},
    ]

    assert _same_outcome_same_source(different) == []


def test_the_finding_reads_properly_with_no_citation() -> None:
    """"from the same line ()" is what an empty citation printed."""
    from app.services import redundancy_check

    same = "work out combined operations of integers in the correct order"
    report = redundancy_check.inspect({"modules": [
        {"module_number": n, "title": f"Lesson {n}", "slos_covered": [same],
         "citations": [], "learning_experiences_used": ["combined operations"]}
        for n in (2, 3, 4)]})

    text = " ".join(report.get("findings") or [])
    assert "none of them cites the design" in text
    assert "same line ()" not in text
