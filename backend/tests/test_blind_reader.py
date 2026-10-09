"""The blind reader: one item at a time, without its key. On qwen3:14b's
first items it caught all six wrong or arguable keys the key-visible batch
read had passed."""
from __future__ import annotations

from types import SimpleNamespace

from app.services import question_audit, questions_remediation


def _mcq(qid, stem, options, key, **extra):
    return {"question_id": qid, "display_label": qid.upper(), "question_type": "multiple_choice",
            "question_text": stem, "options": [{"id": k, "text": v, "is_correct": k == key} for k, v in options.items()],
            "correct_answer": key, **extra}


EUPHEMISM = _mcq("q1", "Which of the following is an example of a euphemism?",
                 {"A": "He is dead.", "B": "He is no longer with us.", "C": "He passed away.", "D": "He is gone."}, "B")
GREETING = _mcq("q2", "Which greeting is used in the evening?",
                {"A": "早上好", "B": "晚上好", "C": "下午好", "D": "老师好"}, "B")


def _reader(replies):
    seen = []

    def generate(config, messages, temperature=0.0):
        seen.append(messages[0]["content"])
        return SimpleNamespace(content=replies[len(seen) - 1])
    return generate, seen


def test_the_reader_never_sees_the_key_and_reads_one_item_at_a_time():
    generate, seen = _reader([{"answer": "B", "defensible": ["B"]}, {"answer": "B", "defensible": ["B"]}])
    question_audit.blind_check([EUPHEMISM, GREETING], generate=generate, model_config=object())
    assert len(seen) == 2, "one call per item"
    for prompt in seen:
        assert "KEY" not in prompt and "is_correct" not in prompt and "correct_answer" not in prompt
    assert "He passed away" in seen[0] and "晚上好" not in seen[0]


def test_an_item_with_more_than_one_defensible_option_fails():
    generate, _ = _reader([{"answer": "B", "defensible": ["B", "C", "D"], "reason": "all three are euphemisms"}])
    found = question_audit.blind_check([EUPHEMISM], generate=generate, model_config=object())
    assert [f.kind for f in found] == ["blind_ambiguous"]
    assert "C, D" in found[0].says and found[0].items == ["q1"]


def test_a_key_the_reader_does_not_reach_fails():
    generate, _ = _reader([{"answer": "A", "defensible": ["A"], "reason": "早上好 is morning"}])
    found = question_audit.blind_check([GREETING], generate=generate, model_config=object())
    assert [f.kind for f in found] == ["blind_key"] and "not the key B" in found[0].says


def test_a_clean_item_passes():
    generate, _ = _reader([{"answer": "B", "defensible": ["B"]}])
    assert question_audit.blind_check([GREETING], generate=generate, model_config=object()) == []


def test_a_key_the_engine_proved_is_not_put_to_the_reader(monkeypatch):
    """The reader slipped on a sum ("14 + 16 = 28"); the engine does not."""
    sums = _mcq("q3", "Work out $14 + 16$.", {"A": "28", "B": "30", "C": "16", "D": "14"}, "B")
    generate, seen = _reader([{"answer": "A", "defensible": ["A"]}])
    assert question_audit.blind_check([sums], generate=generate, model_config=object()) == []
    assert seen == []


def test_the_figure_data_is_read_since_the_drawing_cannot_be():
    atom = _mcq("q4", "Study the atom in the figure. Which element is it?",
                {"A": "Oxygen", "B": "Sulphur", "C": "Neon", "D": "Argon"}, "B",
                figure={"kind": "atom", "protons": 16, "neutrons": 16})
    generate, seen = _reader([{"answer": "B", "defensible": ["B"]}])
    question_audit.blind_check([atom], generate=generate, model_config=object())
    assert '"protons": 16' in seen[0]


def test_only_wrong_items_are_held_not_weak_ones():
    assert questions_remediation.holds("blind_ambiguous") and questions_remediation.holds("wrong_key")
    assert questions_remediation.holds("reader_key") and questions_remediation.holds("figure_contradicts_stem")
    for weak in ("no_walkthrough", "few_figures", "table_over_used", "below_the_grade_item", "reader_distractor"):
        assert not questions_remediation.holds(weak), weak


def test_items_the_loop_could_not_fix_are_filed_needs_review(monkeypatch):
    from app.routes import questions
    from app.services.questions_remediation import Report

    calls = []
    monkeypatch.setattr(questions.question_dna_service, "set_status",
                        lambda qid, status, review_audit=None: calls.append((qid, status, review_audit)))
    items = [{"question_id": "Q1", "display_label": "Q1"}, {"question_id": "Q2", "display_label": "Q2"}]
    saved = [{"question_id": "q-saved-1", "review_audit": {}}, {"question_id": "q-saved-2", "review_audit": {}}]
    report = Report(held=["Q2"], outstanding=["Q2: besides the key B, option(s) C can be defended as correct."])
    questions._hold_what_still_fails(items, saved, report)
    assert [(c[0], c[1]) for c in calls] == [("q-saved-2", "needs_review")]
    assert "option(s) C" in calls[0][2]["held"]["why"][0]
