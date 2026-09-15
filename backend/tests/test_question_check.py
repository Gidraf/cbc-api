"""The questions are checked the way the guide's worked examples are.

A printed paper is remembered for the key that was wrong, the distractor
that was also right, the sum set three times, and the Grade 9 paper whose
hardest item was 7 − 4. None of that is a shape fault, so none of it was
caught.
"""
from __future__ import annotations

from app.services import question_check, questions_remediation


def _mcq(label: str, stem: str, options: dict[str, str], key: str, **extra) -> dict:
    return {
        "question_id": f"q-{label.lower()}", "display_label": label,
        "question_type": "multiple_choice", "question_text": stem,
        "options": [{"id": k, "text": v, "is_correct": k == key} for k, v in options.items()],
        "correct_answer": key,
        "pedagogy": {"max_marks": 1, "bloom_level": extra.pop("bloom", "Application")},
        "curriculum": {"slo_id": "x", "serves": extra.pop("serves", [])},
        **extra,
    }


def _written(label: str, stem: str, answer: str, scheme: str = "", **extra) -> dict:
    return {
        "question_id": f"q-{label.lower()}", "display_label": label,
        "question_type": "quantitative_calculation", "question_text": stem,
        "model_answer": answer, "marking_scheme": scheme,
        "pedagogy": {"max_marks": 3, "bloom_level": extra.pop("bloom", "Application")},
        "curriculum": {"slo_id": "x", "serves": extra.pop("serves", [])},
        **extra,
    }


GRADE9 = dict(grade="grade-9", subject="Mathematics", strand="Numbers", sub_strand="Integers")


def _sound_batch() -> list[dict]:
    """Six correct Grade-9 items, at the grade, none repeated."""
    return [
        _mcq("Q1", "Work out $(-12) + 4 \\times (-3) - (-6)$.",
             {"A": "-18", "B": "-30", "C": "18", "D": "-6"}, "A"),
        _mcq("Q2", "Evaluate $[(-8) - 4] \\div (-3) + 5 \\times (-2)$.",
             {"A": "-6", "B": "6", "C": "-14", "D": "14"}, "A"),
        _written("Q3", "A trader starts the day with a balance of $-450$ shillings, earns $3 \\times 250$ "
                       "shillings from sales and then pays $2 \\times 160$ shillings in costs. Work out "
                       "the closing balance.",
                 "$-20$", "$-450 + 750 - 320 = -20$ (M1 for 750, M1 for 320, A1)"),
        _written("Q4", "Evaluate $\\frac{(-15) \\div 3 - (-2) \\times (-4) + 6}{-2 \\times 3 + (-4)}$.",
                 "$\\frac{7}{10}$", "Numerator $-5 - 8 + 6 = -7$; denominator $-6 - 4 = -10$; $-7 \\div -10 = 0.7$"),
        _mcq("Q5", "The temperature at a highland station was $-3^\\circ$C at dawn, rose by $9^\\circ$C "
                   "by noon and fell by $14^\\circ$C by midnight. What was the midnight temperature?",
             {"A": "$-8^\\circ$C", "B": "$8^\\circ$C", "C": "$-2^\\circ$C", "D": "$20^\\circ$C"}, "A"),
        _written("Q6", "Work out $(-3)^2 - 4 \\times (-5) + (-30) \\div 6$.", "$24$",
                 "$9 + 20 - 5 = 24$", bloom="Analysis"),
    ]


def test_a_sound_batch_is_clean() -> None:
    report = question_check.check(_sound_batch(), **GRADE9)

    assert report.clean, [f.says for f in report.findings]
    assert report.engine_checked >= 4
    assert report.engine_agreed == report.engine_checked
    assert report.score == 100


def test_a_wrong_key_is_moved_to_the_option_the_engine_agrees_with() -> None:
    batch = _sound_batch()
    batch[0]["options"][0]["is_correct"] = False
    batch[0]["options"][1]["is_correct"] = True          # says −30; the engine says −18
    batch[0]["correct_answer"] = "B"

    report = question_check.check(batch, **GRADE9)

    assert report.clean, [f.says for f in report.findings]
    assert report.repaired and "Moved" in report.repaired[0]
    assert batch[0]["correct_answer"] == "A"
    assert [o["id"] for o in batch[0]["options"] if o["is_correct"]] == ["A"]


def test_a_wrong_key_with_no_right_option_is_a_finding_on_that_item() -> None:
    batch = _sound_batch()
    batch[0]["options"] = [{"id": k, "text": v, "is_correct": k == "B"}
                           for k, v in {"A": "-20", "B": "-30", "C": "18", "D": "-6"}.items()]
    batch[0]["correct_answer"] = "B"

    report = question_check.check(batch, **GRADE9)

    kinds = {f.kind: f for f in report.findings}
    assert "wrong_key" in kinds
    assert kinds["wrong_key"].items == ["q-q1"]
    assert "-18" in kinds["wrong_key"].says


def test_a_distractor_equal_to_the_key_is_two_right_answers() -> None:
    batch = _sound_batch()
    batch[0]["options"][2]["text"] = "$-18$"            # C now equals the key

    report = question_check.check(batch, **GRADE9)

    assert any(f.kind == "two_right_answers" and f.items == ["q-q1"] for f in report.findings)


def test_a_wrong_model_answer_is_named_with_the_engine_value() -> None:
    batch = _sound_batch()
    batch[5]["model_answer"] = "$14$"

    report = question_check.check(batch, **GRADE9)

    found = [f for f in report.findings if f.kind == "wrong_answer"]
    assert found and found[0].items == ["q-q6"]
    assert "24" in found[0].says


def test_a_false_line_in_the_marking_scheme_is_caught() -> None:
    batch = _sound_batch()
    batch[2]["marking_scheme"] = "$3 \\times 250 = 650$ (M1); $-450 + 650 - 320 = -20$"

    report = question_check.check(batch, **GRADE9)

    assert any(f.kind == "scheme_states_a_false_equation" and f.items == ["q-q3"]
               for f in report.findings)


def test_an_item_that_sets_the_guides_worked_example_is_a_repeat() -> None:
    notes = {"modules": [{"module_number": 2, "title": "Lesson 2", "worked_examples": [
        {"statement": "Work out $(-12) + 4 \\times (-3) - (-6)$.", "answer": "$-18$"}]}]}

    report = question_check.check(_sound_batch(), notes=notes, **GRADE9)

    found = [f for f in report.findings if f.kind == "repeats_the_guide"]
    assert found and found[0].items == ["q-q1"] and "lesson 2" in found[0].says


def test_an_item_already_in_the_bank_is_named() -> None:
    existing = [{"question_id": "q-old-77", "question_text": "Work out $(-12) + 4 \\times (-3) - (-6)$."}]

    report = question_check.check(_sound_batch(), existing=existing, **GRADE9)

    found = [f for f in report.findings if f.kind == "already_in_the_bank"]
    assert found and found[0].items == ["q-q1"] and "q-old-77" in found[0].says


def test_the_same_question_twice_in_one_batch() -> None:
    batch = _sound_batch()
    batch.append(dict(batch[1], question_id="q-q7", display_label="Q7"))

    report = question_check.check(batch, **GRADE9)

    found = [f for f in report.findings if f.kind == "duplicate_in_batch"]
    assert found and found[0].items == ["q-q7"]


def test_a_paper_below_the_grade_is_a_finding_about_the_set() -> None:
    batch = [
        _mcq("Q1", "Work out $7 - 4$.", {"A": "3", "B": "11", "C": "-3", "D": "4"}, "A"),
        _mcq("Q2", "Work out $5 + 2$.", {"A": "7", "B": "3", "C": "10", "D": "-7"}, "A"),
        _mcq("Q3", "Work out $9 - 6$.", {"A": "3", "B": "15", "C": "-3", "D": "6"}, "A"),
        _mcq("Q4", "Work out $8 + 1$.", {"A": "9", "B": "7", "C": "-9", "D": "81"}, "A"),
        _written("Q5", "Work out $6 - 2$.", "$4$", "$6 - 2 = 4$"),
    ]

    report = question_check.check(batch, **GRADE9)

    assert any(f.kind == "below_the_grade" for f in report.findings), [f.kind for f in report.findings]


def test_every_item_at_recall_is_a_finding() -> None:
    batch = [dict(q, pedagogy={**q["pedagogy"], "bloom_level": "Recall"}) for q in _sound_batch()]

    report = question_check.check(batch, **GRADE9)

    assert any(f.kind == "nothing_above_recall" for f in report.findings)


SLOS = {"slos": [
    {"slo_id": "grade-9-Mat-1.1-1",
     "slo": "perform combined operations on integers in different situations"},
    {"slo_id": "grade-9-Mat-1.1-2",
     "slo": "represent integers on a number line and compare them using inequality symbols"},
]}


def _serving(batch: list[dict], ref: str) -> list[dict]:
    return [dict(q, curriculum={**q["curriculum"], "serves": [ref]}) for q in batch]


def test_an_outcome_nobody_assessed_is_named() -> None:
    design_row = SLOS

    report = question_check.check(_serving(_sound_batch(), "grade-9-Mat-1.1-1"),
                                  design_row=design_row, **GRADE9)

    found = [f for f in report.findings if f.kind == "outcome_not_assessed"]
    assert found and "number line" in found[0].says
    assert not found[0].items, "an uncovered outcome is about the set, not an item"


def test_a_batch_that_records_no_outcomes_is_not_judged_on_them() -> None:
    """Word overlap between a question and an outcome proves nothing either
    way; only what the item records counts."""
    report = question_check.check(_sound_batch(), design_row=SLOS, **GRADE9)

    assert not any(f.kind == "outcome_not_assessed" for f in report.findings)


def test_an_outcome_named_in_words_counts_as_served() -> None:
    batch = _sound_batch()
    batch[0]["curriculum"]["slo_text"] = "Perform combined operations on integers in different situations."
    batch[1]["curriculum"]["slo_text"] = "represent integers on a number line and compare them"

    report = question_check.check(batch, design_row=SLOS, **GRADE9)

    assert not any(f.kind == "outcome_not_assessed" for f in report.findings)


def test_drawn_figures_nobody_asks_about_is_a_finding() -> None:
    diagrams = [{"diagram_title": "Integer number line", "svg_markup": "<svg/>"}]

    report = question_check.check(_sound_batch(), diagrams=diagrams, **GRADE9)

    assert any(f.kind == "figures_unused" for f in report.findings)


def test_a_question_that_points_at_a_missing_figure() -> None:
    batch = _sound_batch()
    batch[5]["question_text"] = "Study the diagram below and state the integer marked P."

    report = question_check.check(batch, **GRADE9)

    assert any(f.kind == "figure_not_supplied" and f.items == ["q-q6"] for f in report.findings)


def test_an_answer_stated_in_the_stem() -> None:
    batch = _sound_batch()
    batch[5]["question_text"] = "Show that $(-3)^2 - 4 \\times (-5) + (-30) \\div 6 = 24$."

    report = question_check.check(batch, **GRADE9)

    assert any(f.kind == "answer_in_the_stem" and f.items == ["q-q6"] for f in report.findings)


def test_the_score_counts_faulty_items_and_set_findings() -> None:
    report = question_check.Report(checked=10)
    report.findings = [
        question_check.Finding("wrong_key", "a", items=["q1"]),
        question_check.Finding("wrong_key", "b", items=["q2"]),
        question_check.Finding("outcome_not_assessed", "c"),
    ]

    assert report.score == 80.0
    assert question_check.Report(checked=10).score == 100.0


# ── the loop ─────────────────────────────────────────────────────────────────

def test_a_clean_batch_makes_no_model_call() -> None:
    calls = []
    kept, report = questions_remediation.run(
        _sound_batch(), rewrite=lambda *a: calls.append(a), **GRADE9)

    assert not calls
    assert report.clean and report.stopped_because == "clean"
    assert len(kept) == 6


def test_copies_are_dropped_without_a_model_call() -> None:
    batch = _sound_batch()
    batch.append(dict(batch[1], question_id="q-q7", display_label="Q7"))
    calls = []

    kept, report = questions_remediation.run(batch, rewrite=lambda *a: calls.append(a), **GRADE9)

    assert not calls
    assert report.dropped == ["q-q7"]
    assert [q["display_label"] for q in kept] == ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]


def test_only_the_named_item_is_rewritten_and_the_rest_are_kept_byte_for_byte() -> None:
    batch = _sound_batch()
    batch[5]["model_answer"] = "$14$"
    seen = {}

    def rewrite(items, reasons, asks):
        seen["items"] = [q["display_label"] for q in items]
        seen["reasons"] = reasons
        fixed = dict(items[0], model_answer="$24$", question_id="q-q6-new", replaces="q-q6")
        return [fixed]

    kept, report = questions_remediation.run(batch, rewrite=rewrite, **GRADE9)

    assert seen["items"] == ["Q6"]
    assert "24" in seen["reasons"][0]
    assert report.clean and report.passes == 1
    assert report.rewritten == ["q-q6"]
    assert kept[:5] == _sound_batch()[:5]
    assert kept[5]["model_answer"] == "$24$" and kept[5]["display_label"] == "Q6"


def test_the_best_batch_is_kept_when_a_pass_makes_it_worse() -> None:
    batch = _sound_batch()
    batch[5]["model_answer"] = "$14$"

    def rewrite(items, reasons, asks):
        # Comes back still wrong, and breaks another item's key on the way.
        return [dict(items[0], model_answer="$13$", question_id="q-q6-b", replaces="q-q6")]

    kept, report = questions_remediation.run(batch, rewrite=rewrite, max_passes=3, **GRADE9)

    assert not report.clean
    assert report.stopped_because in ("no improvement", "passes exhausted")
    assert report.score_after >= report.score_before
    assert len(report.outstanding) == 1


def test_an_uncovered_outcome_asks_for_an_item_to_be_added() -> None:
    seen = {}

    def rewrite(items, reasons, asks):
        seen["asks"] = asks
        return [_mcq("Q7", "Which inequality correctly compares the integers $-7$ and $-2$ on a number line?",
                     {"A": "$-7 < -2$", "B": "$-7 > -2$", "C": "$-7 = -2$", "D": "$-2 < -7$"}, "A",
                     serves=["grade-9-Mat-1.1-2"], question_id="q-q7")]

    kept, report = questions_remediation.run(_serving(_sound_batch(), "grade-9-Mat-1.1-1"),
                                             design_row=SLOS, rewrite=rewrite, **GRADE9)

    assert seen["asks"] and "number line" in seen["asks"][0]
    assert report.added == 1 and len(kept) == 7
    assert report.clean, report.outstanding


# ── the station ──────────────────────────────────────────────────────────────

def test_the_batch_route_runs_the_loop_and_files_its_verdict() -> None:
    """A check that is not on the path the console runs is a check nobody
    runs. The gate has to see the self-check, and the bank has to keep it."""
    import inspect

    from app.routes import questions

    source = inspect.getsource(questions)
    body = source[source.index("def factory_generate_questions_batch("):]

    assert "questions_remediation" in body
    assert "_check_and_repair(" in body
    assert 'content={"questions": normalized_questions, "self_check": self_check.to_dict()}' in body
    assert 'filed_gate["self_check"] = self_check.to_dict()' in body
    assert '"self_check": self_check.to_dict()' in body


def test_the_gate_honours_the_batch_self_check() -> None:
    """A set whose own checks failed does not pass on the strength of a
    reviewer who never ran the arithmetic."""
    from app.services import quality_gate

    source = inspect_source(quality_gate.QualityGateService.run_layer_gate)
    assert 'content.get("self_check")' in source


def inspect_source(fn):
    import inspect

    return inspect.getsource(fn)


def test_trivial_items_beyond_the_allowance_fail_on_their_own() -> None:
    """A KJSEA Section A that opened with "identify what −3 represents"
    passed every check, because only a set where NOTHING reached the
    grade failed."""
    batch = _sound_batch() + [
        _mcq("Q7", "A thermometer records $-3^\\circ$C. Identify what the integer $-3$ represents.",
             {"A": "3 below zero", "B": "3 above zero", "C": "a fall of 3", "D": "no reading"}, "A"),
        _mcq("Q8", "State the directed integer that represents an outstanding debt of KSh 3,400.",
             {"A": "$-3400$", "B": "$+3400$", "C": "$0$", "D": "$\\pm 3400$"}, "A"),
        _mcq("Q9", "State the integer that represents a deposit of KSh 500.",
             {"A": "$+500$", "B": "$-500$", "C": "$0$", "D": "$50$"}, "A"),
        _mcq("Q10", "Work out $7 - 4$.", {"A": "3", "B": "11", "C": "-3", "D": "4"}, "A"),
    ]

    report = question_check.check(batch, **GRADE9)

    weak = [f for f in report.findings if f.kind == "below_the_grade_item"]
    names = sorted(i for f in weak for i in f.items)
    # 4 of 10 sit below the grade; a paper may carry 3 — one has to go, and
    # it is a trivial one, not the one-step calculation.
    assert len(names) == 1 and names[0] in ("q-q7", "q-q8", "q-q9")
    assert question_check.rung_of(batch[9], grade="grade-9", subject="Mathematics") == question_check.BELOW
    assert question_check.rung_of(batch[6], grade="grade-9", subject="Mathematics") == question_check.TRIVIAL
    assert question_check.rung_of(batch[0], grade="grade-9", subject="Mathematics") == question_check.AT


def test_a_subject_with_no_floor_is_not_placed_on_rungs() -> None:
    item = _mcq("Q1", "State the main cause of soil erosion in Kenya.", {"A": "a", "B": "b", "C": "c", "D": "d"}, "A")
    assert question_check.rung_of(item, grade="grade-6", subject="Agriculture and Nutrition") == question_check.UNMEASURED
