"""Repairing an item that failed a check, instead of throwing it away.

The structure gate holds a malformed question before a person can waste
attention on it. Holding it is right; discarding it is not — the item was
generated, paid for, and is usually wrong in exactly one nameable way. At 500
items a day the difference between repairing and regenerating is the difference
between recovering the work and buying it twice.

The prompt for this had been seeded since the beginning and nothing ever
called it.
"""
from __future__ import annotations

import inspect
import json

import pytest

from app.services import content_repair, question_structure

BROKEN = {
    "question_id": "q1", "question_type": "multiple_choice",
    "question_text": "What is the value of $-3 + 5$?",
    "pedagogy": {"max_marks": 1}, "correct_answer": "B",
    "options": [{"id": "A", "text": "-8"}, {"id": "B", "text": "2", "is_correct": True}],
}
MENDED = {**BROKEN, "options": BROKEN["options"] + [
    {"id": "C", "text": "8"}, {"id": "D", "text": "-2"}]}


class _Response:
    def __init__(self, payload):
        self.content = json.dumps(payload)


@pytest.fixture
def model(monkeypatch):
    calls: list[str] = []

    def _generate(resolved, messages, **kwargs):
        calls.append(messages[0]["content"])
        return _Response({"repaired": MENDED,
                          "changes": [{"field": "options", "why": "two more"}],
                          "unrepairable": []})

    from app.services import llm_client as module

    monkeypatch.setattr(module.llm_client, "generate", _generate)
    from app.services.langfuse_context import langfuse_context_service as ctx
    monkeypatch.setattr(ctx, "get_agent_prompt", lambda _a: "{{ validation_failures }} {{ content_to_repair }}")
    return calls


def test_an_item_the_gate_blocked_is_repaired_and_re_checked(model) -> None:
    verdicts = question_structure.check_all([BROKEN])["verdicts"]

    out = content_repair.repair_questions([BROKEN], verdicts, grade="grade-9",
                                          subject="Mathematics", resolved=object())

    assert out.attempted == 1
    assert len(out.repaired) == 1
    assert out.still_broken == []
    assert not question_structure.check(out.repaired[0]).blocked


def test_the_repair_is_told_exactly_what_failed(model) -> None:
    verdicts = question_structure.check_all([BROKEN])["verdicts"]

    content_repair.repair_questions([BROKEN], verdicts, grade="grade-9",
                                    subject="Mathematics", resolved=object())

    prompt = model[0]
    assert "coin toss" in prompt, "the finding"
    assert "Write 3–5 options" in prompt, "and the fix"


def test_a_repair_that_does_not_clear_the_gate_is_still_held(monkeypatch) -> None:
    """A repair nobody verified is a claim, and this gate exists because claims
    about an item's shape are not taken on trust."""
    from app.services import llm_client as module
    from app.services.langfuse_context import langfuse_context_service as ctx

    monkeypatch.setattr(ctx, "get_agent_prompt", lambda _a: "x")
    monkeypatch.setattr(module.llm_client, "generate",
                        lambda *a, **k: _Response({"repaired": BROKEN}))

    verdicts = question_structure.check_all([BROKEN])["verdicts"]
    out = content_repair.repair_questions([BROKEN], verdicts, grade="grade-9",
                                          subject="Mathematics", resolved=object())

    assert out.repaired == []
    assert len(out.still_broken) == 1


def test_a_model_that_fails_loses_the_repair_not_the_run(monkeypatch) -> None:
    from app.services import llm_client as module
    from app.services.langfuse_context import langfuse_context_service as ctx

    monkeypatch.setattr(ctx, "get_agent_prompt", lambda _a: "x")

    def _boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(module.llm_client, "generate", _boom)

    verdicts = question_structure.check_all([BROKEN])["verdicts"]
    out = content_repair.repair_questions([BROKEN], verdicts, grade="grade-9",
                                          subject="Mathematics", resolved=object())

    assert out.repaired == [] and len(out.still_broken) == 1


def test_items_that_passed_are_never_sent_for_repair(model) -> None:
    verdicts = question_structure.check_all([MENDED])["verdicts"]

    out = content_repair.repair_questions([MENDED], verdicts, grade="grade-9",
                                          subject="Mathematics", resolved=object())

    assert out.attempted == 0
    assert model == [], "no model call for an item that was already fine"


def test_only_one_attempt_is_made() -> None:
    """A second pass on an item the first could not fix is paying twice for the
    same answer, and the gate holds it either way."""
    assert content_repair.ATTEMPTS == 1


def test_the_question_route_repairs_before_it_discards() -> None:
    from app.routes import questions

    source = inspect.getsource(questions)

    assert "content_repair.repair_questions(" in source
    # And re-measures, because the gate reports what is FILED and a repaired
    # item is a different item.
    repair_block = source.split("content_repair.repair_questions(")[1][:900]
    assert "question_structure.check_all(normalized_questions)" in repair_block
    assert "except Exception" in repair_block, "a failed repair is not a failed run"
