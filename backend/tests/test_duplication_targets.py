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
        "exposition_segments": [{"topic": title, "body": "Learners discuss integers in pairs. " * 12}],
    }


def test_a_lesson_with_only_addition_and_subtraction_examples_is_a_target() -> None:
    """'50 - 20 + 15' and '5 - 3 + 4' pass arithmetic checks (answers correct)
    and pass every duplication check (text differs). Nothing stopped them
    reaching the Grade 9 page — a parent reads Grade 4 arithmetic.

    The loop now hears `example_check.check_notes`, which measures every
    lesson against its own rung of the GRADE's ladder — and that rung, at a
    level whose floor says the order of operations must matter, is not met by
    two kinds that are both additive.
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
        notes, ["discuss integers"], GRADE_9_MATHS)

    assert 1 in targets, "lesson 1 must be flagged for rewrite"
    assert any("never reach the demand" in f for f in findings), findings


GRADE_9_MATHS = {"grade": "grade-9", "subject": "Mathematics"}
GRADE_5_MATHS = {"grade": "grade-5", "subject": "Mathematics"}
GRADE_2_MATHS = {"grade": "grade-2", "subject": "Mathematics"}
PP1_CRE = {"grade": "pp1", "subject": "Christian Religious Education"}


def test_the_same_lesson_is_at_grade_for_grade_2_and_not_flagged() -> None:
    """The rule is the GRADE's, not Grade 9's. `50 - 20 + 15` is exactly what
    a Grade 2 design asks for, and Pre-Primary and Lower Primary have no
    floor at all."""
    notes = {"modules": [_ops_module(1, "Operations", [
        {"statement": r"Calculate $50 - 20 + 15$.",
         "steps": [{"working": r"$50 - 20 + 15 = 45$", "because": "left to right"}],
         "answer": "45"},
    ])]}

    _score, findings, targets = notes_remediation._inspect(
        notes, ["discuss integers"], GRADE_2_MATHS)

    assert not any("never reach the demand" in f for f in findings), findings
    assert 1 not in targets


def test_a_grade_5_lesson_is_held_to_the_upper_primary_floor() -> None:
    """Upper Primary asks for two kinds where order matters and no bracket;
    `96 ÷ 8 + 7 × 4` meets it, `50 − 20 + 15` does not."""
    at_grade = {"modules": [_ops_module(1, "Operations", [
        {"statement": r"Work out $96 \div 8 + 7 \times 4$.",
         "steps": [{"working": r"$96 \div 8 + 7 \times 4 = 12 + 28$",
                    "because": "divide and multiply before adding"},
                   {"working": r"$12 + 28 = 40$", "because": "add"}],
         "answer": "40"},
    ])]}
    below = {"modules": [_ops_module(1, "Operations", [
        {"statement": r"Work out $50 - 20 + 15$.",
         "steps": [{"working": r"$50 - 20 + 15 = 45$", "because": "left to right"}],
         "answer": "45"},
    ])]}

    _s, ok, _t = notes_remediation._inspect(at_grade, ["discuss integers"], GRADE_5_MATHS)
    _s, bad, targets = notes_remediation._inspect(below, ["discuss integers"], GRADE_5_MATHS)

    assert not any("never reach the demand" in f for f in ok), ok
    assert any("never reach the demand" in f for f in bad) and 1 in targets


def test_a_cre_guide_is_never_measured_for_arithmetic() -> None:
    notes = {"modules": [{
        "module_number": 1, "title": "Introducing God",
        "exposition_segments": [{"topic": "The name of God",
                                 "body": "Learners say the name of God in mother tongue. " * 8}],
        "learning_experiences_used": ["say the name of God in their mother tongue"],
    }]}

    _score, findings, targets = notes_remediation._inspect(
        notes, ["say the name of God in their mother tongue"], PP1_CRE)

    assert not any("demand" in f or "worked example" in f for f in findings), findings
    assert targets == []


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
        notes, ["discuss integers"], GRADE_9_MATHS)

    diff_findings = [f for f in findings if "never reach the demand" in f]
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
        notes, ["discuss integers"], GRADE_9_MATHS)

    assert 1 in targets
    assert any("no worked example" in f for f in findings)


def test_a_pp1_mathematical_activities_lesson_needs_none() -> None:
    """Sorting objects by colour has nothing to work through to an answer,
    and the floor table already says Pre-Primary has no floor."""
    notes = {"modules": [_ops_module(1, "Sorting", [])]}

    _score, findings, _t = notes_remediation._inspect(
        notes, ["discuss integers"], {"grade": "pp1", "subject": "Mathematical Activities"})

    assert not any("no worked example" in f for f in findings)


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


# ── the same shape with the numbers changed ──────────────────────────────────


def _clone(stmt: str, answer: str) -> dict:
    return {"statement": f"Evaluate the expression {stmt}.",
            "steps": [{"working": f"{stmt.strip('$')} = {answer}", "because": "work it"}],
            "answer": answer}


def test_the_same_shape_in_a_later_lesson_is_a_target() -> None:
    """Six lessons each worked `a + b × (−c) ± d` over `e − (−f)` — the floor's
    exemplar with new digits — and none was the same TEXT, so the expression
    check passed all six."""
    notes = {"modules": [
        _ops_module(1, "Basics", [_clone(r"$\dfrac{-12 + 4 \times (-3) + 6}{2 - 5}$", "6")]),
        _ops_module(2, "Combined", [_clone(r"$\dfrac{-12 + 3 \times (-4) - 6}{2 - (-3)}$", "-6")]),
        _ops_module(3, "Real life", [_clone(r"$\dfrac{-20 + 5 \times (-3) - 4}{2 - (-1)}$", "-13")]),
    ]}

    _score, findings, targets = notes_remediation._inspect(notes, ["discuss integers"], {})

    assert 2 in targets and 3 in targets and 1 not in [
        n for n in targets if any(f"Lesson {n} works an example of exactly the shape" in f
                                  for f in findings)]
    assert sum("exactly the shape" in f for f in findings) == 2


def test_a_different_shape_is_not_a_clone() -> None:
    notes = {"modules": [
        _ops_module(1, "A", [_clone(r"$\dfrac{-12 + 4 \times (-3) + 6}{2 - 5}$", "6")]),
        _ops_module(2, "B", [_clone(r"$(-5 + 10) - (3 \times 2)$", "-1")]),
        _ops_module(3, "C", [_clone(r"$-50 + 20 - 3 \times (-4)$", "-18")]),
    ]}

    _s, findings, _t = notes_remediation._inspect(notes, ["discuss integers"], {})

    assert not any("exactly the shape" in f for f in findings), findings


def test_the_skeleton_folds_signs_and_additive_operators() -> None:
    k = notes_remediation._skeleton
    assert k(r"$\dfrac{-12 + 4 \times (-3) + 6}{2 - 5}$") == \
        k(r"$\dfrac{-20 + 5 \times (-3) - 4}{2 - (-1)}$") == "(n±n×n±n)÷(n±n)"
    assert k(r"$3 + (-5) \times 2 - 4$") == "n±n×n±n"
    assert k(r"$50 - (30 + 20) + (-10)$") == "n±(n±n)±n"


# ── the exposition must teach what the examples use ──────────────────────────


def _lesson(n: int, title: str, prose: str, examples: list[dict]) -> dict:
    return {**_ops_module(n, title, examples),
            "exposition_segments": [{"topic": title, "body": prose}]}


SIGNED = {"statement": r"Evaluate $3 + (-5) \times 2 - 4$.",
          "steps": [{"working": r"$3 + (-5) \times 2 - 4 = 3 - 10 - 4$", "because": "multiply first"},
                    {"working": r"$3 - 10 - 4 = -11$", "because": "left to right"}],
          "answer": "-11"}


def test_multiplying_signed_numbers_before_the_sign_rule_is_taught_is_a_target() -> None:
    """Lesson 1 explained adding on a number line and worked `3 + (−5) × 2 − 4`;
    no lesson in the guide ever said what a negative times a positive gives."""
    notes = {"modules": [_lesson(
        1, "Basic Operations",
        "Demonstrate how to add and subtract integers using number cards. "
        "Show how to add 3 and -5 by moving left on the number line.",
        [SIGNED, SIGNED])]}

    _s, findings, targets = notes_remediation._inspect(
        notes, ["discuss integers"], GRADE_9_MATHS)

    assert 1 in targets
    assert any("sign rule" in f for f in findings), findings


def test_once_a_lesson_states_the_sign_rule_later_lessons_may_use_it() -> None:
    notes = {"modules": [
        _lesson(1, "Sign rules",
                "To multiply two integers, multiply the sizes; if the signs differ "
                "the product is negative, if they are the same it is positive.",
                [SIGNED, SIGNED]),
        _lesson(2, "Combined", "Apply BODMAS to the expressions below.",
                [{"statement": r"Work out $-6 \div 2 + 4 \times (-1)$.",
                  "steps": [{"working": r"$-6 \div 2 + 4 \times (-1) = -3 - 4$", "because": "÷ and × first"},
                            {"working": r"$-3 - 4 = -7$", "because": "add"}],
                  "answer": "-7"}] * 2),
    ]}

    _s, findings, _t = notes_remediation._inspect(notes, ["discuss integers"], GRADE_9_MATHS)

    assert not any("sign rule" in f for f in findings), findings


# ── a real-life lesson must work a real-life example ─────────────────────────


def test_a_real_life_lesson_with_only_bare_expressions_is_a_target() -> None:
    notes = {"modules": [{
        **_lesson(3, "Applying Integers to Real-Life Situations",
                  "Discuss how integers are used in temperature and finance. " * 3,
                  [_clone(r"$(-5 + 10) - (3 \times 2)$", "-1"),
                   _clone(r"$-50 + 20 - 3 \times (-4)$", "-18")]),
        "slos_covered": ["apply Integers to real-life situations"]}]}

    _s, findings, targets = notes_remediation._inspect(
        notes, ["discuss integers"], GRADE_9_MATHS)

    assert 3 in targets
    assert any("bare expression" in f for f in findings), findings


def test_a_real_life_lesson_with_a_situation_is_left_alone() -> None:
    situation = {
        "statement": "The temperature at dawn was $-5$°C. By noon it had risen by "
                     "$12$°C, and by midnight it had fallen by $3 \\times 4$°C. "
                     "What was the temperature at midnight?",
        "steps": [{"working": r"$-5 + 12 - 3 \times 4 = -5 + 12 - 12$", "because": "multiply first"},
                  {"working": r"$-5 + 12 - 12 = -5$", "because": "left to right"}],
        "answer": "$-5$°C"}
    notes = {"modules": [{
        **_lesson(3, "Applying Integers to Real-Life Situations",
                  "Discuss how integers are used in temperature and finance. " * 3,
                  [situation, _clone(r"$-50 + 20 - 3 \times (-4)$", "-18")]),
        "slos_covered": ["apply Integers to real-life situations"]}]}

    _s, findings, _t = notes_remediation._inspect(notes, ["discuss integers"], GRADE_9_MATHS)

    assert not any("bare expression" in f for f in findings), findings


def test_a_single_worked_example_is_short() -> None:
    notes = {"modules": [_ops_module(2, "Combined", [SIGNED])]}

    _s, findings, targets = notes_remediation._inspect(notes, ["discuss integers"], GRADE_9_MATHS)

    assert 2 in targets
    assert any("only one worked example" in f for f in findings)


# ── generic stems do not count as teaching an experience ─────────────────────


def test_it_tools_is_not_taught_by_a_lesson_that_merely_mentions_integers() -> None:
    """The lesson scored 3 of 8 on `integer`, `operation` and `out` — words
    every experience in the design shares — and passed."""
    design = [
        "discuss with peers and work out basic operations on integers using number cards and charts",
        "play games involving numbers and operations by picking integers and performing all basic operations",
        "work out combined operations of integers in the correct order",
        "carry out activities such as reading temperature changes in a thermometer",
        "use IT tools and other resources such as print to carry out operations on integers",
        "play creative games that involve integers",
    ]
    notes = {"modules": [{
        "module_number": 4, "title": "Evaluating Complex Expressions with Integers",
        "exposition_segments": [
            {"topic": "Understanding Complex Expressions",
             "body": "Introduce complex expressions involving integers, explaining how "
                     "they can represent real-life situations. Work through several "
                     "examples with the class, demonstrating how to apply the order "
                     "of operations. Show each step clearly."},
            {"topic": "Real-Life Applications",
             "body": "Present real-life scenarios where learners must evaluate "
                     "expressions involving integers, such as the total temperature "
                     "change over a week. Encourage learners to work in pairs."}],
        "resources_needed": ["calculators", "printed scenarios", "whiteboard"],
        "learning_experiences_used": [design[4]],
    }]}

    _s, findings, targets = notes_remediation._inspect(notes, design, {})

    assert 4 in targets
    assert any("nothing in the lesson does it" in f for f in findings), findings


# ── the rest of what the second guide showed ─────────────────────────────────


def test_a_non_integer_answer_in_the_integers_sub_strand_is_a_target() -> None:
    notes = {"modules": [_ops_module(2, "Combined", [
        _clone(r"$\dfrac{-10 + 5 \times (-3) - 2}{4 - (-2)}$", "$-4.5$"),
        _clone(r"$-6 \div 2 + 4 \times (-1)$", "$-7$")])]}

    _s, findings, targets = notes_remediation._inspect(
        notes, ["discuss integers"], GRADE_9_MATHS, sub_strand="Integers")

    assert 2 in targets
    assert any("not an integer" in f for f in findings), findings


def test_a_review_lesson_while_an_experience_goes_untaught_is_a_target() -> None:
    games = ("play games involving numbers and operations by picking integers "
             "and performing all basic operations")
    notes = {"modules": [
        _lesson(1, "Introduction to Integers", "Integers and number cards. " * 10,
                [SIGNED, SIGNED]),
        _lesson(6, "Review and Assessment of Integers",
                "Review the key concepts learned throughout the unit. " * 10,
                [SIGNED, SIGNED]),
    ]}

    _s, findings, targets = notes_remediation._inspect(
        notes, ["discuss integers", games], GRADE_9_MATHS)

    assert 6 in targets
    assert any("review or assessment lesson while" in f for f in findings), findings


def test_the_same_situation_on_new_numbers_is_the_same_example() -> None:
    def situation(a, b):
        return {"statement": f"A temperature changes from {a}°C to {b}°C. What is the total change in temperature?",
                "steps": [{"working": f"${b} - {a} = {b - a}$", "because": "final minus initial"}],
                "answer": f"{b - a}°C"}
    notes = {"modules": [
        _ops_module(4, "Review", [situation(20, -5), _clone(r"$-6 \div 2 + 4 \times (-1)$", "-7")]),
        _ops_module(5, "Applying", [situation(5, -3), _clone(r"$(-5 + 10) - (3 \times 2)$", "-1")]),
    ]}

    _s, findings, targets = notes_remediation._inspect(notes, ["discuss integers"], {})

    assert 5 in targets
    shape = [f for f in findings if "exactly the shape" in f]
    assert shape and "a temperature changes from n°c to n°c" in shape[0], shape


# ── the third guide on terra ─────────────────────────────────────────────────


def _temp(n: int, extra: dict | None = None) -> dict:
    """The example the model would not stop writing."""
    return {"statement": "A temperature drops from 5°C to -3°C. What is the change in temperature?",
            "steps": [{"working": "$-3 - 5 = -8$", "because": "final minus initial"}],
            "answer": "-8°C", **(extra or {})}


def test_an_example_an_earlier_lesson_worked_is_removed_from_the_later_one() -> None:
    """The same temperature problem was the worked example of lessons 1, 3, 5
    and 6. The hand-off said not to; the check found it every pass; the model
    wrote it again. A second copy of something already on the page is the one
    thing that can be removed without losing anything."""
    notes = {"modules": [
        _ops_module(1, "Basics", [_temp(1), SIGNED]),
        _ops_module(3, "IT tools", [_clone(r"$-50 + 20 \times (-3) - (-10)$", "-100"), _temp(3)]),
        _ops_module(5, "Real life", [_temp(5), _clone(r"$2 - (-4)$", "6")]),
    ]}

    note = notes_remediation.drop_repeated_examples(notes)

    assert "Removed 2 worked example(s)" in note
    assert len(notes["modules"][0]["worked_examples"]) == 2, "the first lesson keeps it"
    assert [e["answer"] for e in notes["modules"][1]["worked_examples"]] == ["-100"]
    assert [e["answer"] for e in notes["modules"][2]["worked_examples"]] == ["6"]
    assert notes_remediation.drop_repeated_examples(notes) == "", "idempotent"


def test_a_lessons_own_prose_and_example_sharing_an_expression_is_not_a_repeat() -> None:
    notes = {"modules": [{**_ops_module(4, "Combined", [_clone(r"$-5 + 3 \times (2 - 4)$", "-11")]),
                          "exposition_segments": [{"topic": "Worked", "body": r"Consider $-5 + 3 \times (2 - 4)$. " * 10}]}]}
    assert notes_remediation.drop_repeated_examples(notes) == ""
    assert len(notes["modules"][0]["worked_examples"]) == 1


def test_a_lesson_that_came_back_as_a_script_is_a_target() -> None:
    """Introduction / Development / Conclusion with "present the worked
    examples, explaining each step clearly" — a lesson plan with the content
    left out, and it printed as one."""
    notes = {"modules": [{
        "module_number": 5, "title": "Lesson 5: Applying Integers",
        "lesson_flow": [{"phase": "Introduction", "what_the_teacher_does": "Introduce integers."},
                        {"phase": "Development", "what_the_teacher_does": "Present the worked examples, explaining each step clearly."},
                        {"phase": "Conclusion", "what_the_teacher_does": "Summarise."}],
        "worked_examples": [_temp(5), _clone(r"$2 - (-4)$", "6")],
        "learning_experiences_used": ["discuss integers"],
    }]}

    _s, findings, targets = notes_remediation._inspect(notes, ["discuss integers"], GRADE_9_MATHS)

    assert 5 in targets
    assert any("no exposition topics" in f for f in findings), findings


def test_a_lesson_about_it_tools_is_not_told_it_does_not_teach_them() -> None:
    """The lesson introduced calculators, spreadsheets and educational software
    and used them for the calculations, and the check said nothing in it did
    the experience — "IT" had vanished into the pronoun stoplist and the
    experience's other words are filler."""
    design = [
        "discuss with peers and work out basic operations on integers using number cards and charts",
        "play games involving numbers and operations by picking integers and performing all basic operations",
        "work out combined operations of integers in the correct order",
        "carry out activities such as reading temperature changes in a thermometer",
        "use IT tools and other resources such as print to carry out operations on integers",
        "play creative games that involve integers",
    ]
    notes = {"modules": [{
        "module_number": 3, "title": "Lesson 3: Applying Integer Operations Using IT Tools",
        "exposition_segments": [
            {"topic": "Introduction to IT Tools for Integer Operations",
             "body": "Begin by introducing various IT tools such as calculators, spreadsheets, "
                     "and educational software that can assist in performing operations on "
                     "integers. Explain how these tools can simplify calculations and help "
                     "visualize problems. Highlight the importance of accuracy when using technology."},
            {"topic": "Real-Life Application",
             "body": "Present a debt of KSh 200, a payment of KSh 50 and a further loan of KSh 100. "
                     "Use IT tools to perform the calculations and visualize the results."}],
        "resources_needed": ["Calculators, spreadsheets, or educational software"],
        "learning_experiences_used": [design[4]],
    }]}

    _s, findings, _targets = notes_remediation._inspect(notes, design, {})

    assert not any("nothing in the lesson does it" in f for f in findings), findings


def test_a_lesson_whose_examples_have_no_negative_number_is_a_target() -> None:
    """`2000 + 1500 − 800` and `10 − (2 × 3) + 4` were the two examples of the
    combined-operations lesson of an Integers guide. The per-lesson demand
    check read the prose too, and the prose had a negative in it."""
    row = {**GRADE_9_MATHS, "sub_strand_name": "Integers",
           "slos": [{"id": "grade-9-Mat-1.1-2", "text": "work out combined operations of integers"}]}
    notes = {"modules": [_ops_module(4, "Combined", [
        _clone(r"$2000 + 1500 - 800$", "2700"),
        _clone(r"$10 - (2 \times 3) + 4$", "8")])]}

    _s, findings, targets = notes_remediation._inspect(notes, ["discuss integers"], row, sub_strand="Integers")

    assert 4 in targets
    assert any("no negative number" in f for f in findings), findings


def test_the_score_is_the_worst_dimension_not_the_mean() -> None:
    """Three of six lessons below the grade scored 94 because the other
    three dimensions were clean and the demand was one of four averaged."""
    import inspect as _inspect_mod
    source = _inspect_mod.getsource(notes_remediation._inspect)
    assert "round(min(scores), 1)" in source
