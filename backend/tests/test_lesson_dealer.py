"""Which outcome and which experience each lesson is for, decided before a
word is written.

Each per-lesson call was told "you are writing lesson 4 of 6" and never which
outcome lesson 4 was for. The model chose "work out combined operations" three
times out of six and "appreciate the use of integers" never; the cloned worked
examples followed from the cloned topics.
"""
from __future__ import annotations

from app.services import lesson_dealer as ld
from app.services import notes_remediation

ROW = {
    "slos": [
        {"id": "grade-9-Mat-1.1-1", "text": "perform basic operations on Integers in different situations"},
        {"id": "grade-9-Mat-1.1-2", "text": "work out combined operations of integers in the correct order"},
        {"id": "grade-9-Mat-1.1-3", "text": "apply Integers to real-life situations"},
        {"id": "grade-9-Mat-1.1-4", "text": "appreciate the use of integers in real-life situations"},
    ],
    "learning_experiences": [
        "discuss with peers and work out basic operations on integers using number cards and charts",
        "play games involving numbers and operations by picking integers and performing all basic operations",
        "work out combined operations of integers in the correct order",
        "carry out activities such as reading temperature changes in a thermometer and discussing "
        "with peers how to record it. Consider temperatures below zero points",
        "use IT tools and other resources such as print to carry out operations on integers",
        "play creative games that involve integers",
    ],
}


def test_every_outcome_is_somebodys_lesson_and_every_experience_is_used_once() -> None:
    briefs = ld.deal(ROW, 6)

    assert [b.outcome_ref for b in briefs] == [
        "grade-9-Mat-1.1-1", "grade-9-Mat-1.1-1", "grade-9-Mat-1.1-1",
        "grade-9-Mat-1.1-2", "grade-9-Mat-1.1-3", "grade-9-Mat-1.1-4"]
    used = [ref for b in briefs for ref in b.experience_refs]
    assert sorted(used) == [f"experience {n}" for n in range(1, 7)]
    assert briefs[3].experience_refs == ["experience 3"], "combined ops via its own experience"
    assert briefs[4].experience_refs == ["experience 4"], "real life via the thermometer"


def test_an_outcome_nobodys_experience_matched_still_gets_a_lesson() -> None:
    """'appreciate the use of integers' shares no content word with any
    experience; without this it would have been nobody's lesson."""
    briefs = ld.deal(ROW, 6)
    assert any(b.outcome_ref == "grade-9-Mat-1.1-4" for b in briefs)


def test_the_deal_fits_the_funded_count() -> None:
    four = ld.deal(ROW, 4)
    assert len(four) == 4 and {b.outcome_ref for b in four} == {b.outcome_ref for b in ld.deal(ROW, 6)}
    eight = ld.deal(ROW, 8)
    assert len(eight) == 8
    assert sum(1 for b in eight if not b.experience_refs) == 2, "two practice lessons"


def test_the_deal_is_the_same_every_time() -> None:
    assert [b.to_dict() for b in ld.deal(ROW, 6)] == [b.to_dict() for b in ld.deal(ROW, 6)]


def test_a_lesson_is_told_what_it_is_for_in_fixed_terms() -> None:
    block = ld.block(ld.deal(ROW, 6)[5])
    assert "grade-9-Mat-1.1-4" in block
    assert "play creative games that involve integers" in block
    assert "not yours to choose" in block
    assert ld.block(None) == ""


def test_a_design_with_no_outcomes_deals_nothing() -> None:
    assert ld.deal({}, 6) == []
    assert ld.deal({"slos": []}, 3) == []


# ── the checks hold a lesson to its brief ────────────────────────────────────


def _lesson(n: int, brief: ld.Brief, slo: str, used: list[str]) -> dict:
    return {"module_number": n, "title": f"Lesson {n}", "brief": brief.to_dict(),
            "slos_covered": [slo], "learning_experiences_used": used,
            "teacher_exposition": "Learners play creative games that involve integers. " * 8}


def test_a_lesson_written_to_a_different_plan_is_a_target() -> None:
    brief = ld.deal(ROW, 6)[5]  # outcome 4 via experience 6
    notes = {"modules": [_lesson(
        6, brief, "work out combined operations of integers in the correct order",
        ["work out combined operations of integers in the correct order"])]}

    _s, findings, targets = notes_remediation._inspect(notes, [], {})

    assert 6 in targets
    wrong = [f for f in findings if "written to the wrong plan" in f]
    assert wrong and "grade-9-Mat-1.1-4" in wrong[0] and "experience 6" in wrong[0]


def test_a_lesson_written_to_its_plan_is_left_alone() -> None:
    brief = ld.deal(ROW, 6)[5]
    notes = {"modules": [_lesson(
        6, brief, "appreciate the use of integers in real-life situations",
        ["play creative games that involve integers"])]}

    _s, findings, _t = notes_remediation._inspect(notes, [], {})

    assert not any("wrong plan" in f for f in findings), findings


def test_the_rewrite_instruction_restates_the_targets_plan() -> None:
    briefs = ld.deal(ROW, 6)
    notes = {"modules": [_lesson(n, briefs[n - 1], "x", []) for n in range(1, 7)]}

    text = notes_remediation._instruction(["Lesson 6 is wrong."], [6], "Integers", "6 lessons", notes)

    assert "LESSON 6:" in text and "experience 6" in text
    assert "LESSON 4:" not in text, "only the lessons being rewritten"

    whole = notes_remediation._whole_guide_instruction(["x"], "Integers", "6 lessons", 6, notes)
    assert "LESSON 1:" in whole and "LESSON 6:" in whole and "THE PLAN ABOVE IS FIXED" in whole
