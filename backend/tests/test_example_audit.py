"""A second reader for the worked examples.

Every mechanical check reads the arithmetic; none reads the story. A guide
scored 94 with "expenses include KSh 1,500 for transportation" worked as
`+ 1500`, and Nairobi at −5°C at night.
"""
from __future__ import annotations

import json

from app.services import example_audit, notes_remediation

GUIDE = {"modules": [
    {"module_number": 3, "title": "Lesson 3", "worked_examples": [
        {"statement": "A budget starts at KSh 5000; expenses include KSh 1200 for supplies, "
                      "KSh 800 for food and KSh 1500 for transportation. What remains?",
         "steps": [{"working": "$5000 - (1200 + 800) + 1500 = 4500$", "because": "…"}],
         "answer": "KSh 4500"},
        {"statement": "A thermometer shows 10°C in the morning and -4°C by evening. Change?",
         "steps": [{"working": "$-4 - 10 = -14$", "because": "final minus initial"}],
         "answer": "-14°C"}]},
    {"module_number": 6, "title": "Lesson 6", "worked_examples": [
        {"statement": "The temperature in Nairobi is 25°C by day and drops to -5°C at night. Change?",
         "steps": [{"working": "$-5 - 25 = -30$", "because": "…"}], "answer": "-30°C"}]},
]}


class _Resp:
    def __init__(self, content):
        self.content = content


def _reader(verdicts):
    asked: list[str] = []

    def generate(config, messages, temperature=0.0):
        asked.append(messages[-1]["content"])
        return _Resp({"verdicts": verdicts})
    return generate, asked


def test_every_example_is_put_to_the_reader_with_its_working() -> None:
    generate, asked = _reader([])
    example_audit.audit(GUIDE, generate=generate, model_config=object(),
                        grade="grade-9", subject="Mathematics", sub_strand="Integers")

    assert len(asked) == 1, "one call for the whole guide"
    assert "LESSON 3, EXAMPLE 1" in asked[0] and "LESSON 6, EXAMPLE 1" in asked[0]
    assert "5000 - (1200 + 800) + 1500" in asked[0]
    assert "Nairobi" in asked[0]
    assert "solve it yourself" in asked[0]


def test_a_wrong_verdict_becomes_a_finding_that_names_its_lesson() -> None:
    generate, _ = _reader([
        {"lesson": 3, "example": 1, "verdict": "wrong",
         "reason": "Transportation is an expense and is added; the remaining budget is 5000 - 3500 = 1500."},
        {"lesson": 3, "example": 2, "verdict": "right", "reason": ""},
        {"lesson": 6, "example": 1, "verdict": "wrong",
         "reason": "Nairobi does not reach -5°C; the context cannot be true."},
        {"lesson": 9, "example": 1, "verdict": "wrong", "reason": "no such example"},
    ])

    findings, targets = example_audit.audit(GUIDE, generate=generate, model_config=object())

    assert targets == [3, 6]
    assert findings[0].startswith("Lesson 3 worked example 1 is wrong: Transportation is an expense")
    assert any("Nairobi" in f for f in findings)
    assert len(findings) == 2, "a verdict on an example that does not exist is ignored"


def test_a_reader_that_fails_is_silent_not_fatal() -> None:
    def broken(*a, **k):
        raise RuntimeError("provider down")
    assert example_audit.audit(GUIDE, generate=broken, model_config=object()) == ([], [])
    assert example_audit.audit({"modules": []}, generate=broken, model_config=object()) == ([], [])


def test_the_reader_accepts_json_as_text() -> None:
    def generate(config, messages, temperature=0.0):
        return _Resp(json.dumps({"verdicts": [
            {"lesson": 6, "example": 1, "verdict": "WRONG", "reason": "Nairobi is never -5°C."}]}))
    findings, targets = example_audit.audit(GUIDE, generate=generate, model_config=object())
    assert targets == [6] and "Nairobi" in findings[0]


def test_the_loop_takes_the_readers_findings_as_its_own() -> None:
    """An audit finding names its lesson and is a rewrite target, and it
    costs the score: a 94 with an added expense on the page is not a 94."""
    seen: dict = {}

    def audit(notes):
        seen["called"] = seen.get("called", 0) + 1
        return (["Lesson 3 worked example 1 is wrong: an expense is added."], [3])

    from tests.test_notes_remediation import DESIGN, SLOS, _guide
    guide = _guide()
    _notes, report = notes_remediation.run(
        guide, design_experiences=DESIGN, slos=SLOS, audit=audit)

    assert seen["called"] >= 1
    assert any("is wrong: an expense is added" in f for f in report.outstanding)
