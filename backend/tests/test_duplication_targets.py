"""A duplication finding with no lesson to rewrite was a comment.

Three of the six ways redundancy_check finds a guide repeating itself produced
a finding and no target. The remediation loop, handed findings and nothing to
rewrite, went straight to regenerating the whole guide — the one path that
drops the lesson-to-lesson hand-off, and so the path most likely to hand back
the same repeat. Six guides in a row came back with "Review of Combined
Operations" taught twice and "Complex Problem Solving" three times; the check
named it every time; every one was published.
"""
from __future__ import annotations

from app.services import notes_remediation


def _m(n: int, title: str, segs: list[tuple[str, str]]) -> dict:
    return {"module_number": n, "title": title,
            "exposition_segments": [{"topic": t, "body": b} for t, b in segs]}


_LONG = ("Begin by reviewing the rules for combined operations with integers, "
         "reminding learners of BODMAS and how the order decides the answer. ")


def test_a_lesson_sharing_an_earlier_title_is_rewritten_not_the_earlier_one() -> None:
    notes = {"modules": [
        _m(1, "Introduction", [("Understanding Integers", "An integer is a whole number.")]),
        _m(2, "Combined Operations with Integers", [("Order", "BODMAS decides.")]),
        _m(3, "Applications", [("Real life", "Temperatures and money.")]),
        _m(4, "Combined Operations with Integers", [("Working", "Work expressions.")]),
    ]}
    _, findings, targets = notes_remediation._inspect(notes, [], None)

    assert 4 in targets and 2 not in targets, "the first is the honest one"
    assert any('Lesson 4 is titled "Combined Operations with Integers"' in f
               for f in findings)


def test_every_lesson_after_the_first_to_carry_a_heading_is_rewritten() -> None:
    notes = {"modules": [
        _m(1, "Intro", [("Understanding Integers", "x")]),
        _m(2, "Ops", [("Order of Operations", "x")]),
        _m(3, "Applying", [("Review of Combined Operations", "a"),
                           ("Complex Problem Solving", "b")]),
        _m(4, "Combined", [("Working Out Combined Operations", "c")]),
        _m(5, "Complex", [("Complex Problem Solving", "d")]),
        _m(6, "Advanced", [("Review of Combined Operations", "e"),
                           ("Complex Problem Solving", "f")]),
    ]}
    _, _, targets = notes_remediation._inspect(notes, [], None)

    assert sorted(targets) == [5, 6]
    assert 3 not in targets


def test_the_same_block_of_prose_in_two_lessons_targets_the_later() -> None:
    notes = {"modules": [
        _m(1, "A", [("Review", _LONG * 2)]),
        _m(2, "B", [("Something else", "Different teaching entirely, long enough "
                                       "to be its own block of exposition here.")]),
        _m(3, "C", [("Review again", _LONG * 2)]),
    ]}
    _, findings, targets = notes_remediation._inspect(notes, [], None)

    assert 3 in targets and 1 not in targets
    assert any("same block of exposition" in f for f in findings)


def test_a_guide_that_repeats_nothing_has_no_duplication_targets() -> None:
    notes = {"modules": [
        _m(1, "Introduction to Integers", [("Understanding Integers", "Whole numbers.")]),
        _m(2, "Basic Operations", [("Adding and subtracting", "Use the number line.")]),
        _m(3, "Combined Operations", [("Order of operations", "BODMAS decides.")]),
    ]}
    _, _, targets = notes_remediation._inspect(notes, [], None)

    assert targets == []


# ── difficulty floor check ────────────────────────────────────────────────────


def _ops_module(n: int, title: str, examples: list[dict]) -> dict:
    """A module with worked examples but no other fields that could trip integrity checks."""
    return {
        "module_number": n, "title": title,
        "worked_examples": examples,
        "learning_experiences_used": ["discuss integers"],  # stop integrity flagging
    }


def test_a_lesson_with_only_addition_and_subtraction_examples_is_a_target() -> None:
    """'50 - 20 + 15' and '5 - 3 + 4' pass arithmetic checks (answers correct)
    and pass every duplication check (text differs). Nothing stopped them
    reaching the Grade 9 page — a parent reads Grade 4 arithmetic.

    The remediation loop now checks whether every worked example in a lesson
    has at least two DIFFERENT operation kinds. If none do, the lesson is a
    rewrite target and the score drops.
    """
    notes = {"modules": [_ops_module(1, "Operations", [
        {"statement": r"Calculate $50 - 20 + 15$.",
         "steps": [{"working": r"$50 - 20 = 30$", "because": "subtract first"},
                   {"working": r"$30 + 15 = 45$", "because": "then add"}],
         "answer": "45"},
        {"statement": r"Work out $5 - 3 + 4$.",
         "steps": [{"working": r"$5 - 3 = 2$", "because": "subtract"},
                   {"working": r"$2 + 4 = 6$", "because": "add"}],
         "answer": "6"},
    ])]}

    _score, findings, targets = notes_remediation._inspect(
        notes, ["discuss integers"], {})

    assert 1 in targets, "lesson 1 must be flagged for rewrite"
    assert any("operation" in f.lower() for f in findings), \
        "a finding should name the missing operation kind"


def test_a_lesson_with_a_mixed_example_is_not_flagged() -> None:
    """(-4 + 6) × 3 - 5 mixes × with + and - so BODMAS decides the answer."""
    notes = {"modules": [_ops_module(1, "Operations", [
        {"statement": r"Evaluate $(-4 + 6) \times 3 - 5$.",
         "steps": [{"working": r"$(-4+6) \times 3 - 5 = 2 \times 3 - 5$",
                    "because": "brackets first"},
                   {"working": r"$2 \times 3 - 5 = 6 - 5$",
                    "because": "multiply before subtract"},
                   {"working": r"$6 - 5 = 1$", "because": "subtract"}],
         "answer": "1"},
    ])]}

    _score, findings, targets = notes_remediation._inspect(
        notes, ["discuss integers"], {})

    diff_findings = [f for f in findings if "operation" in f.lower()]
    assert not diff_findings, \
        f"a lesson with a mixed example must not raise a difficulty finding: {diff_findings}"
