"""A second reader answers every item cold and says which keys it cannot reach.

The engine reads the arithmetic and nothing else. A Social Studies paper
with a wrong key had no check at all.
"""
from __future__ import annotations

import json

from app.services import question_audit, questions_remediation
from tests.test_question_check import GRADE9, _mcq, _sound_batch


class _Resp:
    def __init__(self, content):
        self.content = content


def _reader(verdicts):
    calls = []

    def generate(config, messages, temperature=0.0, effort=""):
        calls.append(messages[0]["content"])
        return _Resp({"verdicts": verdicts})

    generate.calls = calls
    return generate


def test_a_key_the_reader_cannot_reach_is_a_finding_on_that_item() -> None:
    batch = [
        _mcq("Q1", "Which lake is the source of the River Nile?",
             {"A": "Lake Turkana", "B": "Lake Victoria", "C": "Lake Naivasha", "D": "Lake Nakuru"}, "A"),
        _mcq("Q2", "Which town is the capital of Kenya?",
             {"A": "Mombasa", "B": "Nairobi", "C": "Kisumu", "D": "Nakuru"}, "B"),
    ]
    generate = _reader([
        {"item": "Q1", "verdict": "fail", "kind": "key", "my_answer": "B", "reason": "The Nile leaves Lake Victoria at Jinja."},
        {"item": "Q2", "verdict": "pass", "kind": "", "my_answer": "B", "reason": ""},
    ])

    findings = question_audit.audit(batch, generate=generate, model_config=object(),
                                    notes_text="Lesson 1: the source of the Nile is Lake Victoria.",
                                    subject="Social Studies")

    assert len(findings) == 1
    assert findings[0].kind == "reader_key" and findings[0].items == ["q-q1"]
    assert "Jinja" in findings[0].says and "reader's answer: B" in findings[0].says
    assert "source of the Nile is Lake Victoria" in generate.calls[0], "the reader sees the lessons"
    assert "← KEY" in generate.calls[0]


def test_a_reader_cannot_overturn_a_value_the_engine_verified() -> None:
    batch = _sound_batch()
    generate = _reader([
        {"item": "Q1", "verdict": "fail", "kind": "key", "my_answer": "-30", "reason": "I make it -30."},
    ])

    findings = question_audit.audit(batch, generate=generate, model_config=object(), **{})

    assert findings == []


def test_a_reader_agreeing_with_the_key_in_other_words_is_not_a_failure() -> None:
    batch = [_mcq("Q1", "Which town is the capital of Kenya?",
                  {"A": "Mombasa", "B": "Nairobi", "C": "Kisumu", "D": "Nakuru"}, "B")]
    for my_answer in ("B", "b)", "Nairobi", "nairobi"):
        generate = _reader([{"item": "Q1", "verdict": "fail", "kind": "key", "my_answer": my_answer,
                             "reason": "the answer is Nairobi"}])
        assert question_audit.audit(batch, generate=generate, model_config=object()) == [], my_answer


def test_a_story_verdict_stands_on_its_reason() -> None:
    batch = [_mcq("Q1", "Which of these is a county in Kenya?",
                  {"A": "Nairobi", "B": "Mombasa", "C": "Kisumu", "D": "Nakuru"}, "A")]
    generate = _reader([{"item": "Q1", "verdict": "fail", "kind": "ambiguous", "my_answer": "",
                         "reason": "All four are counties."}])

    findings = question_audit.audit(batch, generate=generate, model_config=object())

    assert len(findings) == 1 and findings[0].kind == "reader_ambiguous"


def test_a_broken_reader_finds_nothing_rather_than_failing_the_run() -> None:
    def broken(*a, **k):
        raise RuntimeError("no model")

    assert question_audit.audit(_sound_batch(), generate=broken, model_config=object()) == []
    assert question_audit.audit(_sound_batch(), generate=lambda *a, **k: _Resp("not json"),
                                model_config=object()) == []


def test_the_loop_asks_the_reader_only_about_items_the_engine_has_not_condemned() -> None:
    batch = _sound_batch()
    batch[5]["model_answer"] = "$14$"          # the engine condemns Q6
    asked = []

    def audit(items):
        asked.append([q["display_label"] for q in items])
        return []

    def rewrite(items, reasons, asks):
        return [dict(items[0], model_answer="$24$", question_id="q-q6-new", replaces="q-q6")]

    kept, report = questions_remediation.run(batch, rewrite=rewrite, audit=audit, **GRADE9)

    assert "Q6" not in asked[0]
    assert report.clean


def test_the_reader_is_wired_into_the_station() -> None:
    import inspect

    from app.routes import questions

    source = inspect.getsource(questions._check_and_repair)
    assert "question_audit.audit(" in source
    assert "audit=audit" in source
