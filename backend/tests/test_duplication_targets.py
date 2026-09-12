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


# ── cross-lesson expression deduplication ─────────────────────────────────────


def _mixed_example(stmt: str, answer: str) -> dict:
    """A mixed-operation worked example that passes the difficulty floor check."""
    return {
        "statement": stmt,
        "steps": [{"working": f"${stmt.strip('$')} = {answer}$", "because": "compute"}],
        "answer": answer,
    }


def test_the_same_expression_in_two_lessons_targets_the_later_one() -> None:
    """(-3+5)×4-6 in lesson 3 and again in lesson 4 is the loop that produced
    six guides with duplicate examples. redundancy_check never saw it — the
    statements are too short for its minimum-length threshold.

    The remediation loop now normalises example statements and flags any later
    lesson that repeats an expression worked in an earlier one. The finding names
    the later lesson (4) and the earlier lesson (3) — not the other way around.
    """
    expr = r"$(-3 + 5) \times 4 - 6$"
    notes = {"modules": [
        _ops_module(1, "Intro", [_mixed_example(r"$(-4 + 6) \times 3 - 5$", "1")]),
        _ops_module(2, "Practice", [_mixed_example(r"$(-2 + 8) \times 2 - 3$", "9")]),
        _ops_module(3, "Review", [_mixed_example(expr, "2")]),
        _ops_module(4, "Advanced", [_mixed_example(expr, "2")]),
    ]}

    _score, findings, targets = notes_remediation._inspect(
        notes, ["discuss integers"], {})

    assert 4 in targets, "the later lesson must be a rewrite target"
    # The finding names 'Lesson 4' as the repeat and 'Lesson 3' as the original.
    # Any finding that names lesson 4 and lesson 3 in that relationship is enough.
    repeat_findings = [f for f in findings if "repeat" in f.lower()]
    assert repeat_findings, "a 'repeat' finding must be generated"
    assert any("Lesson 4" in f and "Lesson 3" in f for f in repeat_findings), (
        f"the finding must name lesson 4 (repeat) and lesson 3 (original): {repeat_findings}"
    )


def test_a_guide_with_all_distinct_expressions_has_no_dedup_findings() -> None:
    notes = {"modules": [
        _ops_module(1, "A", [_mixed_example(r"$(-4 + 6) \times 3 - 5$", "1")]),
        _ops_module(2, "B", [_mixed_example(r"$(-3 + 5) \times 4 - 6$", "2")]),
        _ops_module(3, "C", [_mixed_example(r"$(-2 + 8) \times 2 - 3$", "9")]),
    ]}

    _score, findings, targets = notes_remediation._inspect(
        notes, ["discuss integers"], {})

    repeat_findings = [f for f in findings if "repeat" in f.lower()]
    assert not repeat_findings, f"no expressions repeated: {repeat_findings}"


# ── arithmetic error detection ────────────────────────────────────────────────


def test_a_lesson_with_a_wrong_step_equation_is_a_target() -> None:
    """Step 1 claims 10 - 5 + 12 = 7 but 10-5+12 = 17.

    check_steps produces a badge for the page; before this fix the badge result
    never reached _inspect so the lesson was published with the error inside it.
    """
    notes = {"modules": [_ops_module(1, "Temperatures", [
        {"statement": "The temperature was 10°C. It fell 5°C then rose 12°C.",
         "steps": [{"working": "$10 - 5 + 12 = 7$", "because": "combine changes"}],
         "answer": "7"},
    ])]}

    _score, findings, targets = notes_remediation._inspect(
        notes, ["discuss integers"], {})

    assert 1 in targets, "a wrong step must target the lesson for rewrite"
    assert any("arithmetic" in f.lower() for f in findings)


def test_a_lesson_with_correct_arithmetic_is_not_flagged_for_errors() -> None:
    notes = {"modules": [_ops_module(1, "Correct", [
        {"statement": r"Calculate $(-3) \times (-4) + 10$.",
         "steps": [{"working": r"$(-3) \times (-4) + 10 = 12 + 10$",
                    "because": "negative × negative = positive"},
                   {"working": r"$12 + 10 = 22$", "because": "add"}],
         "answer": "22"},
    ])]}

    _score, findings, targets = notes_remediation._inspect(
        notes, ["discuss integers"], {})

    arith_findings = [f for f in findings if "arithmetic" in f.lower()]
    assert not arith_findings, f"correct arithmetic must not be flagged: {arith_findings}"


# ── a mathematics lesson with no worked example at all ───────────────────────


def test_a_mathematics_lesson_with_no_worked_examples_is_a_target() -> None:
    """The first guide generated after the difficulty floor, the duplicate check
    and the arithmetic check landed had no worked examples in any lesson. All
    three checks run over the list a lesson supplies; an empty list passed
    every one of them."""
    notes = {"modules": [_ops_module(1, "Operations", [])]}

    _score, findings, targets = notes_remediation._inspect(
        notes, ["discuss integers"], {"subject": "Mathematics"})

    assert 1 in targets
    assert any("no worked example" in f for f in findings)


def test_a_non_mathematics_lesson_needs_no_worked_example() -> None:
    notes = {"modules": [_ops_module(1, "Our God", [])]}

    _score, findings, _targets = notes_remediation._inspect(
        notes, ["discuss integers"], {"subject": "Christian Religious Education"})

    assert not any("no worked example" in f for f in findings)


# ── an experience named but not taught ───────────────────────────────────────


def test_a_lesson_that_names_an_experience_it_does_not_teach_is_a_target() -> None:
    """Lesson 4 wrote `experience 5` — "use IT tools and other resources such as
    print to carry out operations on integers" — under learning_experiences_used
    and then taught poster-making. The unused-experience check read the field
    and went quiet."""
    it_tools = ("use IT tools and other resources such as print to carry out "
                "operations on integers")
    notes = {"modules": [{
        "module_number": 4, "title": "Appreciating the Use of Integers",
        "exposition_segments": [
            {"topic": "Integers in Science",
             "body": "Discuss how integers are used in scientific measurements, "
                     "such as temperature, pressure and altitude. Scientists use "
                     "negative integers to represent below sea level."},
            {"topic": "Collaborative Activity",
             "body": "Organize a group activity where learners create a poster "
                     "illustrating the use of integers in various contexts. "
                     "Evaluate the group posters for understanding and creativity."},
        ],
        "resources_needed": ["poster materials", "markers"],
        "learning_experiences_used": [it_tools],
    }]}

    _score, findings, targets = notes_remediation._inspect(notes, [it_tools], {})

    assert 4 in targets
    assert any("nothing in the lesson does it" in f for f in findings)


def test_a_lesson_that_teaches_what_it_names_is_left_alone() -> None:
    it_tools = ("use IT tools and other resources such as print to carry out "
                "operations on integers")
    notes = {"modules": [{
        "module_number": 4, "title": "Integers with IT tools",
        "teacher_exposition": "Learners use IT tools — a calculator app and a "
                              "spreadsheet — and print resources such as the "
                              "textbook to carry out operations on integers, "
                              "checking each other's answers.",
        "learning_experiences_used": [it_tools],
    }]}

    _score, findings, _targets = notes_remediation._inspect(notes, [it_tools], {})

    assert not any("nothing in the lesson does it" in f for f in findings)
