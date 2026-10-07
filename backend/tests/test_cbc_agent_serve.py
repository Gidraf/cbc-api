"""`serve`: every task the platform is waiting on, answered on a local model,
without stopping — against a fake queue and a fake model, in-process."""
from __future__ import annotations

import argparse

import pytest

from app.agent_clients import cbc_agent


class _Queue:
    def __init__(self, tasks):
        # task_id -> list of (expect, prompt); each answered in order
        self.tasks = {tid: {"prompts": p, "answers": [], "status": "awaiting"} for tid, p in tasks.items()}
        self.calls: list[tuple[str, str, dict | None]] = []

    def view(self, tid):
        t = self.tasks[tid]
        out = {"task_id": tid, "station": "questions", "status": t["status"], "created_at": 1.0,
               "params": {"grade": "grade-9", "subject": "Integrated Science", "sub_strand": tid},
               "steps_completed": len(t["answers"]), "result": {}}
        if t["status"] == "awaiting":
            expect, text = t["prompts"][len(t["answers"])]
            out["step"] = {"number": len(t["answers"]) + 1, "stage": "q", "expect": expect,
                           "messages": [{"role": "user", "content": text}]}
        return out

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/api/v1/agent/tasks":
            return {"live": [{k: v for k, v in self.view(t).items() if k != "step"}
                             for t, s in self.tasks.items() if s["status"] != "done"], "ledger": []}
        tid = path.split("/")[5]
        if method == "POST":
            t = self.tasks[tid]
            assert body["step"] == len(t["answers"]) + 1, "every answer names its step"
            t["answers"].append(body["content"])
            if len(t["answers"]) == len(t["prompts"]):
                t["status"] = "done"
        return self.view(tid)


def _args(**kw):
    base = dict(model="qwen3:14b", llm_url="http://localhost:11434/v1", poll=0, until_empty=True,
                max_attempts=2, think=False, download="", window="")
    return argparse.Namespace(**{**base, **kw})


def test_serve_answers_every_waiting_task_and_stops_when_the_queue_is_clear(monkeypatch) -> None:
    queue = _Queue({"t-atoms": [("text", "Name element 10."), ("json", "protons in sulphur?")],
                    "t-waves": [("text", "What is a wave?")]})
    monkeypatch.setattr(cbc_agent, "_platform", queue)
    monkeypatch.setattr(cbc_agent, "_model", lambda url, model, messages, **kw: f"answer to {messages[0]['content']}")

    cbc_agent.serve(_args())

    assert queue.tasks["t-atoms"]["answers"] == ["answer to Name element 10.", "answer to protons in sulphur?"]
    assert queue.tasks["t-waves"]["answers"] == ["answer to What is a wave?"]


def test_a_task_whose_model_keeps_failing_is_set_aside_not_allowed_to_block(monkeypatch) -> None:
    queue = _Queue({"t-broken": [("text", "BREAK")], "t-fine": [("text", "fine")]})
    monkeypatch.setattr(cbc_agent, "_platform", queue)
    monkeypatch.setattr(cbc_agent.time, "sleep", lambda s: None)

    def model(url, model, messages, **kw):
        if messages[0]["content"] == "BREAK":
            raise TimeoutError("ollama timed out")
        return "ok"

    monkeypatch.setattr(cbc_agent, "_model", model)
    cbc_agent.serve(_args())

    assert queue.tasks["t-fine"]["answers"] == ["ok"], "the healthy task was still served"
    assert queue.tasks["t-broken"]["status"] == "awaiting", "the broken one waits for a later pass"


def test_a_platform_restart_is_waited_out(monkeypatch) -> None:
    queue = _Queue({"t-one": [("text", "hello")]})
    down = {"left": 2}

    def flaky(method, path, body=None):
        if down["left"]:
            down["left"] -= 1
            raise cbc_agent.PlatformError("502 bad gateway", 502)
        return queue(method, path, body)

    monkeypatch.setattr(cbc_agent, "_platform", flaky)
    monkeypatch.setattr(cbc_agent.time, "sleep", lambda s: None)
    monkeypatch.setattr(cbc_agent, "_model", lambda *a, **k: "hi")
    cbc_agent.serve(_args())
    assert queue.tasks["t-one"]["answers"] == ["hi"]


def test_a_refusal_is_not_retried_forever(monkeypatch) -> None:
    def refuse(method, path, body=None):
        raise cbc_agent.PlatformError("401 unauthorised", 401)

    monkeypatch.setattr(cbc_agent, "_platform", refuse)
    with pytest.raises(cbc_agent.PlatformError):
        cbc_agent.serve(_args())


def test_ollama_is_asked_to_keep_the_model_loaded(monkeypatch) -> None:
    sent = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"message": {"content": "<think>hmm</think>ok"}}'

    def urlopen(req, timeout=0):
        import json
        sent.update(json.loads(req.data))
        return _Resp()

    monkeypatch.setattr(cbc_agent, "_is_ollama", lambda url: True)
    monkeypatch.setattr(cbc_agent.urllib.request, "urlopen", urlopen)
    out = cbc_agent._model("http://localhost:11434/v1", "qwen3:14b", [{"role": "user", "content": "x"}],
                           expect="json", temperature=0.2)
    assert out == "ok", "the reasoning is stripped"
    assert sent["keep_alive"] and sent["think"] is False
    assert sent["options"]["num_ctx"] >= 16384 and sent["options"]["num_predict"] >= 4096
    assert sent["format"] == "json"


@pytest.mark.parametrize("window, hhmm, inside", [
    ("00:00-07:00", "00:00", True), ("00:00-07:00", "06:59", True), ("00:00-07:00", "07:00", False),
    ("00:00-07:00", "13:30", False), ("22:00-06:00", "23:15", True), ("22:00-06:00", "05:00", True),
    ("22:00-06:00", "12:00", False), ("", "12:00", True),
])
def test_the_serving_window(window, hhmm, inside) -> None:
    import time as _t

    h, m = map(int, hhmm.split(":"))
    now = _t.struct_time((2026, 10, 7, h, m, 0, 0, 280, -1))
    assert cbc_agent._in_window(window, now) is inside


def test_outside_the_window_nothing_is_asked_and_the_model_is_not_loaded(monkeypatch) -> None:
    queue = _Queue({"t-one": [("text", "hello")]})
    monkeypatch.setattr(cbc_agent, "_platform", queue)
    monkeypatch.setattr(cbc_agent, "_in_window", lambda w, now=None: False)
    monkeypatch.setattr(cbc_agent, "_model", lambda *a, **k: pytest.fail("no model call outside the window"))
    cbc_agent.serve(_args(window="00:00-07:00"))
    assert queue.tasks["t-one"]["answers"] == []


def test_when_the_window_closes_it_stops_before_the_next_prompt_and_frees_the_model(monkeypatch) -> None:
    queue = _Queue({"t-long": [("text", "one"), ("text", "two"), ("text", "three")]})
    monkeypatch.setattr(cbc_agent, "_platform", queue)
    calls = {"n": 0}

    def model(*a, **k):
        calls["n"] += 1
        return "ok"

    # Open for the first prompt, closed from then on.
    monkeypatch.setattr(cbc_agent, "_in_window", lambda w, now=None: calls["n"] == 0)
    unloaded = []
    monkeypatch.setattr(cbc_agent, "_unload", lambda url, m: unloaded.append(m))
    monkeypatch.setattr(cbc_agent, "_model", model)
    cbc_agent.serve(_args(window="00:00-07:00", until_empty=False))

    assert queue.tasks["t-long"]["answers"] == ["ok"], "the rest waits on the platform for tonight"
    assert unloaded == ["qwen3:14b"], "the memory is given back"


def test_the_window_grows_for_a_long_prompt_and_stops_at_the_cap(monkeypatch) -> None:
    monkeypatch.setattr(cbc_agent, "NUM_CTX", 24576)
    monkeypatch.setattr(cbc_agent, "MAX_CTX", 32768)
    short = [{"role": "user", "content": "x" * 20_000}]
    two_questions = [{"role": "user", "content": "x" * 71_151}]      # what a 2-question batch sent
    huge = [{"role": "user", "content": "x" * 200_000}]
    assert cbc_agent._context_for(short) == 24576, "no reload for an ordinary prompt"
    assert cbc_agent._context_for(two_questions) == 28672, "room to answer, not 4k"
    assert cbc_agent._context_for(huge) == 32768


def test_a_model_server_that_restarts_mid_request_is_retried(monkeypatch) -> None:
    """Ollama's launch agent was swapped while a step was being written; the
    request came back RemoteDisconnected and a one-off `run` died with it."""
    import http.client

    calls = {"n": 0}

    def once(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise http.client.RemoteDisconnected("Remote end closed connection without response")
        return "answer"

    monkeypatch.setattr(cbc_agent, "_model_once", once)
    monkeypatch.setattr(cbc_agent.time, "sleep", lambda s: None)
    assert cbc_agent._model("http://localhost:11434/v1", "qwen3:14b", [], expect="json", temperature=0.2) == "answer"
    assert calls["n"] == 2


def test_a_model_that_is_not_there_is_not_retried(monkeypatch) -> None:
    import urllib.error

    def once(*a, **k):
        raise urllib.error.HTTPError("u", 404, "model 'qwen2.5:32b' not found", {}, None)

    monkeypatch.setattr(cbc_agent, "_model_once", once)
    with pytest.raises(urllib.error.HTTPError):
        cbc_agent._model("http://localhost:11434/v1", "qwen2.5:32b", [], expect="json", temperature=0.2)
