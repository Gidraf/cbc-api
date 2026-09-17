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


def test_a_task_started_again_replays_the_prompts_already_answered(monkeypatch) -> None:
    """A restart mid-run lost an hour of answered prompts once."""
    journal: dict[tuple[str, str], tuple[str, str]] = {}
    monkeypatch.setattr(byom, "_journal_get", lambda k, h: journal.get((k, h)))
    monkeypatch.setattr(byom, "_journal_put", lambda k, h, s, a, m: journal.__setitem__((k, h), (a, m)))

    def station(kind: str, params: dict) -> dict:
        one = llm_client.generate(_config(), [{"role": "user", "content": "lesson 1"}])
        two = llm_client.generate(_config(), [{"role": "user", "content": "lesson 2 after " + one.content["t"]}])
        return {"t": [one.content["t"], two.content["t"]]}

    first = byom.start("notes", {"grade": "grade-9", "sub_strand": "Integers"}, created_by="a", runner=station)
    byom.wait(first, 5, since_steps=0)
    byom.complete(first.task_id, {"t": "L1"}, model="antigravity")
    byom.wait(first, 5, since_steps=1)
    assert first.status == byom.AWAITING and first.pending.number == 2
    # …and here the platform restarts: the task is gone, the journal is not.
    byom.cancel(first.task_id)

    again = byom.start("notes", {"grade": "grade-9", "sub_strand": "Integers"}, created_by="a", runner=station)
    byom.wait(again, 5, since_steps=1)

    assert again.status == byom.AWAITING and again.pending.number == 2, "step 1 was replayed, step 2 is asked"
    assert again.replayed == 1 and again.steps[0].model_used == "antigravity (replayed)"
    assert "after L1" in again.pending.messages[0]["content"]
    byom.complete(again.task_id, {"t": "L2"}, model="antigravity")
    byom.wait(again, 5, since_steps=2)
    assert again.status == byom.DONE and again.result == {"t": ["L1", "L2"]}
    assert again.to_dict()["replayed"] == 1


def test_a_different_scope_never_replays_another_tasks_answers(monkeypatch) -> None:
    journal: dict[tuple[str, str], tuple[str, str]] = {}
    monkeypatch.setattr(byom, "_journal_get", lambda k, h: journal.get((k, h)))
    monkeypatch.setattr(byom, "_journal_put", lambda k, h, s, a, m: journal.__setitem__((k, h), (a, m)))

    def station(kind: str, params: dict) -> dict:
        return llm_client.generate(_config(), [{"role": "user", "content": "same prompt"}]).content

    one = byom.start("notes", {"sub_strand": "Integers"}, created_by="a", runner=station)
    byom.wait(one, 5, since_steps=0)
    byom.complete(one.task_id, {"x": 1})
    byom.wait(one, 5, since_steps=1)

    other = byom.start("notes", {"sub_strand": "Fractions"}, created_by="a", runner=station)
    byom.wait(other, 5, since_steps=0)
    assert other.status == byom.AWAITING, "another sub-strand's answer is not this one's"
    byom.cancel(other.task_id)


def test_starting_the_same_order_again_joins_the_live_task_instead_of_a_rival() -> None:
    """After an MCP reload an agent called cbc_produce again for the same
    paper; every call was a new task on its own thread, all writing the same
    sub-strands and each waiting on the agent for prompts it was answering
    for another. A night of that saved nothing."""
    def station(kind: str, params: dict) -> dict:
        byom.note("Scope", "Integers, Fractions")
        llm_client.generate(_config("notes_generation"), [{"role": "user", "content": "lesson 1"}])
        return {"paper": {"exam_id": "x"}}

    params = {"grade": "grade-9", "subject": "Mathematics", "kind": "term", "term": 1, "count": 30}
    first = byom.start("order", params, created_by="kit-antigravity", runner=station)
    byom.wait(first, 5, since_steps=0)
    assert first.status == byom.AWAITING

    assert byom.find_live("order", dict(params)) is first
    assert byom.find_live("order", {**params, "term": 2}) is None, "a different paper is a different task"
    assert byom.find_live("notes", params) is None

    # The progress the order wrote is on the task, live, not only in a result.
    view = first.to_dict()
    assert view["progress"][0]["what"] == "Scope" and view["progress"][0]["detail"] == "Integers, Fractions"
    assert view["elapsed_seconds"] >= 0

    byom.complete(first.task_id, {"ok": True})
    byom.wait(first, 5, since_steps=1)
    assert first.status == byom.DONE
    assert byom.find_live("order", params) is None, "a finished task is not joined"


def test_the_start_route_hands_back_the_live_twin() -> None:
    from types import SimpleNamespace

    from app.routes import agent as agent_routes

    def station(kind: str, params: dict) -> dict:
        llm_client.generate(_config("notes_generation"), [{"role": "user", "content": "lesson 1"}])
        return {}

    params = {"grade": "grade-7", "subject": "Mathematics", "strand": "", "sub_strand": "",
              "custom_instructions": "", "kind": "term", "term": 1, "count": 30}
    live = byom.start("order", params, created_by="kit-claude", runner=station)
    byom.wait(live, 5, since_steps=0)

    out = agent_routes.start_task(
        agent_routes.StartTaskRequest(station="order", grade="grade-7", subject="Mathematics",
                                      kind="term", term=1, count=30, wait_seconds=0),
        auth=SimpleNamespace(subject="kit-claude", role="operator", auth_type="api_key"),
    )
    assert out["task_id"] == live.task_id and out["joined_existing"] is True
    assert "already running" in out["note"] and live.joined == 1
    byom.cancel(live.task_id)
