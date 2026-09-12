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
