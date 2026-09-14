"""Bring your own model: the station asks, the agent answers, the platform
does the rest."""
from __future__ import annotations

import time

from app.services import byom
from app.services.llm_client import llm_client
from app.services.provider_router import ResolvedModelConfig


def _config(stage: str = "question_generation") -> ResolvedModelConfig:
    return ResolvedModelConfig(pipeline_stage=stage, provider="openai", model="gpt-5.6-terra",
                               resolved_base_url="", credential_ref_id="", api_key=None)


def test_a_station_run_as_a_task_hands_its_prompts_out_and_takes_the_answers_back() -> None:
    def station(kind: str, params: dict) -> dict:
        first = llm_client.generate(_config("notes_generation"), [{"role": "user", "content": "write lesson 1"}])
        second = llm_client.generate(_config("notes_generation"),
                                     [{"role": "user", "content": "write lesson 2 after " + first.content["title"]}],
                                     expect="json")
        return {"lessons": [first.content, second.content], "model": second.model}

    task = byom.start("notes", {"grade": "grade-9"}, created_by="tester", runner=station)
    byom.wait(task, 5, since_steps=0)

    assert task.status == byom.AWAITING
    assert task.pending is not None and task.pending.number == 1
    assert task.pending.messages == [{"role": "user", "content": "write lesson 1"}]
    assert task.pending.stage == "notes_generation" and task.pending.model_hint == "gpt-5.6-terra"

    byom.complete(task.task_id, {"title": "Lesson 1"}, model="ollama/llama3.1")
    byom.wait(task, 5, since_steps=1)

    assert task.status == byom.AWAITING and task.pending.number == 2
    assert "after Lesson 1" in task.pending.messages[0]["content"], "the station saw the first answer"

    byom.complete(task.task_id, '{"title": "Lesson 2"}', model="claude-code")
    byom.wait(task, 5, since_steps=2)

    assert task.status == byom.DONE
    assert task.result == {"lessons": [{"title": "Lesson 1"}, {"title": "Lesson 2"}], "model": "claude-code"}
    assert [s.model_used for s in task.steps] == ["ollama/llama3.1", "claude-code"]
    assert task.to_dict()["steps_completed"] == 2


def test_no_provider_is_called_and_no_tokens_are_billed() -> None:
    seen = {}

    def station(kind: str, params: dict) -> dict:
        resp = llm_client.generate(_config(), [{"role": "user", "content": "q"}])
        seen["usage"] = resp.usage
        seen["provider"] = resp.provider
        return {}

    task = byom.start("questions", {}, created_by="t", runner=station)
    byom.wait(task, 5, since_steps=0)
    byom.complete(task.task_id, {"questions": []})
    byom.wait(task, 5, since_steps=1)

    assert task.status == byom.DONE
    assert seen["provider"] == "agent" and seen["usage"].total_tokens == 0


def test_a_text_answer_is_taken_as_text_when_the_station_asked_for_text() -> None:
    def station(kind: str, params: dict) -> dict:
        resp = llm_client.generate(_config("diagram_generation"), [{"role": "user", "content": "draw"}], expect="text")
        return {"svg": resp.content}

    task = byom.start("diagram", {}, created_by="t", runner=station)
    byom.wait(task, 5, since_steps=0)
    assert task.pending.expect == "text"
    byom.complete(task.task_id, "```svg\n<svg/>\n```")
    byom.wait(task, 5, since_steps=1)
    assert task.result == {"svg": "<svg/>"}


def test_a_station_that_fails_reports_it_and_a_cancelled_task_stops() -> None:
    def broken(kind: str, params: dict) -> dict:
        raise RuntimeError("no notes for this sub-strand")

    task = byom.start("questions", {}, created_by="t", runner=broken)
    for _ in range(50):
        if task.status != byom.RUNNING:
            break
        time.sleep(0.05)
    assert task.status == byom.FAILED and "no notes" in task.error

    def slow(kind: str, params: dict) -> dict:
        llm_client.generate(_config(), [{"role": "user", "content": "q"}])
        return {}

    task = byom.start("notes", {}, created_by="t", runner=slow)
    byom.wait(task, 5, since_steps=0)
    byom.cancel(task.task_id)
    for _ in range(50):
        if task.status == byom.CANCELLED and task.finished_at:
            break
        time.sleep(0.05)
    assert task.status == byom.CANCELLED


def test_the_agent_routes_exist_and_run_the_queues_own_handlers() -> None:
    import inspect

    from app.routes import agent

    source = inspect.getsource(agent)
    for path in ('"/tasks"', '"/tasks/{task_id}/complete"', '"/tasks/{task_id}/wait"', '"/manifest"',
                 '"/engines/solve"', '"/engines/figure"', '"/engines/map"', '"/engines/check-questions"'):
        assert path in source
    assert "curriculum._PIPELINE_HANDLERS.get(station) or curriculum._BUNDLE_HANDLERS.get(station)" in source
    assert "require_roles(" in source
