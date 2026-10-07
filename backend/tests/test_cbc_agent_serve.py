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
                max_attempts=2, think=False, download="")
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
