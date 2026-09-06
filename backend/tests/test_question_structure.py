"""Whether an item has the SHAPE its own type promises.

An item can be well written, correctly cited, curriculum-aligned and still
unusable: two options, a "structured" question with one part, four marks for a
calculation with no scheme to award them against. None of that is caught by
asking a model whether the question is good. All of it is caught by counting.

This is the gate that makes volume safe. A review queue of 250 items a day is
only worth having if a malformed item never reaches a person.
"""
from __future__ import annotations

from app.services import question_structure as qs

GOOD_MCQ = {
    "question_id": "q1", "question_type": "multiple_choice",
    "question_text": "What is the value of $-3 + 5$?",
    "pedagogy": {"max_marks": 1}, "correct_answer": "B",
    "options": [{"id": "A", "text": "-8"}, {"id": "B", "text": "2", "is_correct": True},
                {"id": "C", "text": "8"}, {"id": "D", "text": "-2"}],
}

GOOD_STRUCTURED = {
    "question_id": "q2", "question_type": "structured_inquiry",
    "question_text": "Work out the following, showing your working.",
    "pedagogy": {"max_marks": 4},
    "structured_parts": [
        {"part_id": "(a)", "sub_question": "Find $-12 \\div 3$.", "marks": 2},
        {"part_id": "(b)", "sub_question": "State the sign rule you used.", "marks": 2}],
    "model_answer": "-4", "marking_scheme": "-12/3 = -4 (2 marks). Sign rule (2 marks)",
}


def test_a_well_formed_item_passes_clean() -> None:
    for item in (GOOD_MCQ, GOOD_STRUCTURED):
        verdict = qs.check(item)
        assert verdict.ok, verdict.to_dict()
        assert verdict.score == 100.0


# ── selected response ───────────────────────────────────────────────────────


def test_two_options_is_a_coin_toss() -> None:
    verdict = qs.check({**GOOD_MCQ, "options": GOOD_MCQ["options"][:2]})

    assert verdict.blocked
    assert any(f.code == "too_few_options" for f in verdict.findings)


def test_all_of_the_above_is_refused() -> None:
    """It tests reading rather than the curriculum, and it cannot be shuffled
    or occluded."""
    verdict = qs.check({**GOOD_MCQ, "options": [
        *GOOD_MCQ["options"][:3], {"id": "D", "text": "All of the above"}]})

    assert verdict.blocked
    assert any(f.code == "meta_option" for f in verdict.findings)


def test_two_options_saying_the_same_thing_cannot_both_be_wrong() -> None:
    verdict = qs.check({**GOOD_MCQ, "options": [
        {"id": "A", "text": "2", "is_correct": True}, {"id": "B", "text": "8"},
        {"id": "C", "text": "8"}, {"id": "D", "text": "-2"}]})

    assert any(f.code == "duplicate_options" for f in verdict.findings)


def test_an_item_with_no_key_cannot_be_marked() -> None:
    stripped = [{k: v for k, v in o.items() if k != "is_correct"}
                for o in GOOD_MCQ["options"]]
    verdict = qs.check({**GOOD_MCQ, "options": stripped, "correct_answer": ""})

    assert verdict.blocked
    assert any(f.code == "no_key" for f in verdict.findings)


def test_two_keys_is_refused_as_well() -> None:
    verdict = qs.check({**GOOD_MCQ, "options": [
        {"id": "A", "text": "2", "is_correct": True},
        {"id": "B", "text": "-2", "is_correct": True},
        {"id": "C", "text": "8"}, {"id": "D", "text": "-8"}]})

    assert any(f.code == "several_keys" for f in verdict.findings)


def test_true_or_false_keeps_its_two_options() -> None:
    """Two options are the point of the structure, not a fault in it."""
    verdict = qs.check({
        "question_type": "true_false", "pedagogy": {"max_marks": 1},
        "question_text": "State whether $-3 + 5 = 2$ is true or false.",
        "correct_answer": "True",
        "options": [{"id": "A", "text": "True", "is_correct": True},
                    {"id": "B", "text": "False"}]})

    assert not any(f.code == "too_few_options" for f in verdict.findings)


def test_options_on_a_written_item_would_print_as_multiple_choice() -> None:
    verdict = qs.check({**GOOD_STRUCTURED, "options": [{"id": "A", "text": "x"}]})

    assert verdict.blocked
    assert any(f.code == "options_on_written_item" for f in verdict.findings)


# ── structured ──────────────────────────────────────────────────────────────


def test_a_structured_item_with_one_part_is_a_short_answer_mislabelled() -> None:
    verdict = qs.check({**GOOD_STRUCTURED,
                        "structured_parts": GOOD_STRUCTURED["structured_parts"][:1]})

    assert verdict.blocked
    assert any(f.code == "not_structured" for f in verdict.findings)


def test_parts_that_do_not_total_cannot_be_reconciled_by_a_marker() -> None:
    verdict = qs.check({**GOOD_STRUCTURED, "pedagogy": {"max_marks": 6}})

    assert verdict.blocked
    assert any(f.code == "parts_do_not_total" for f in verdict.findings)


def test_a_part_with_no_marks_can_have_nothing_awarded_for_it() -> None:
    verdict = qs.check({**GOOD_STRUCTURED, "pedagogy": {"max_marks": 2},
                        "structured_parts": [
                            {"part_id": "(a)", "sub_question": "Find it.", "marks": 2},
                            {"part_id": "(b)", "sub_question": "Say why.", "marks": 0}]})

    assert any(f.code == "part_without_marks" for f in verdict.findings)


# ── calculation and essay ───────────────────────────────────────────────────


def test_a_calculation_with_no_quantities_has_nothing_to_calculate() -> None:
    verdict = qs.check({
        "question_type": "quantitative_calculation", "pedagogy": {"max_marks": 3},
        "question_text": "Calculate the answer to the problem above.",
        "model_answer": "x", "marking_scheme": "Steps (3 marks)"})

    assert verdict.blocked
    assert any(f.code == "calculation_without_quantities" for f in verdict.findings)


def test_method_marks_need_a_scheme_to_be_awarded_against() -> None:
    verdict = qs.check({
        "question_type": "quantitative_calculation", "pedagogy": {"max_marks": 4},
        "question_text": "Calculate $-12 \\div 3$ and state the rule.",
        "model_answer": "-4"})

    assert verdict.blocked
    assert any(f.code == "no_working_expected" for f in verdict.findings)


def test_an_essay_needs_a_rubric_or_two_markers_will_disagree() -> None:
    verdict = qs.check({
        "question_type": "extended_essay", "pedagogy": {"max_marks": 10},
        "question_text": "Explain why the product of two negatives is positive.",
        "model_answer": "Because repeated subtraction reverses direction twice."})

    assert verdict.blocked
    assert any(f.code == "no_rubric" for f in verdict.findings)


def test_a_diagram_question_with_no_diagram_cannot_be_printed() -> None:
    verdict = qs.check({
        "question_type": "diagram_based", "pedagogy": {"max_marks": 1},
        "question_text": "Name the part labelled A on the figure.",
        "model_answer": "The numerator"})

    assert verdict.blocked
    assert any(f.code == "no_diagram" for f in verdict.findings)


# ── the things every item needs ─────────────────────────────────────────────


def test_a_fragment_is_not_a_question() -> None:
    verdict = qs.check({**GOOD_MCQ, "question_text": "Integers?"})

    assert verdict.blocked
    assert any(f.code == "stem_too_short" for f in verdict.findings)


def test_an_item_with_no_marks_cannot_go_on_a_paper() -> None:
    verdict = qs.check({**GOOD_MCQ, "pedagogy": {}})

    assert verdict.blocked
    assert any(f.code == "no_marks" for f in verdict.findings)


def test_a_written_item_with_no_answer_is_unmarkable() -> None:
    verdict = qs.check({
        "question_type": "short_answer", "pedagogy": {"max_marks": 2},
        "question_text": "State the additive inverse of $-7$."})

    assert verdict.blocked
    assert any(f.code == "unmarkable" for f in verdict.findings)


def test_a_type_this_system_does_not_set_is_refused_outright() -> None:
    verdict = qs.check({**GOOD_MCQ, "question_type": "riddle"})

    assert verdict.blocked
    assert verdict.findings[0].code == "unknown_type"
    assert "multiple_choice" in verdict.findings[0].fix


def test_every_finding_says_what_to_do_about_it() -> None:
    """A queue of rejections nobody can act on is a queue nobody works."""
    broken = {"question_type": "structured_inquiry", "question_text": "Do it.",
              "pedagogy": {}, "structured_parts": []}
    for finding in qs.check(broken).findings:
        assert finding.fix, finding.code
        assert finding.severity in (qs.BLOCKS, qs.WARNS)


# ── the batch ───────────────────────────────────────────────────────────────


def test_a_batch_reports_what_is_fit_to_review() -> None:
    report = qs.check_all([GOOD_MCQ, GOOD_STRUCTURED,
                           {**GOOD_MCQ, "options": GOOD_MCQ["options"][:2]}])

    assert report["total"] == 3
    assert report["clean"] == 2
    assert report["blocked"] == 1
    assert report["passed"] == 2
    assert report["by_finding"]["too_few_options"] == 1
    assert 0 < report["score"] < 100


def test_an_empty_batch_is_not_a_perfect_batch() -> None:
    """It does not divide by zero, and it does not score 100 either: a run
    that produced nothing must not read as a clean run. `total` is the signal
    a caller checks first."""
    for empty in ([], None):
        report = qs.check_all(empty)
        assert report["total"] == 0
        assert report["blocked"] == 0
        assert report["score"] == 0.0
