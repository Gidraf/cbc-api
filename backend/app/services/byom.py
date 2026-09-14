"""Bring your own model: the platform assembles the prompts, your agent answers them.

Every station here assembles a prompt — the design extract, the demand
profile, the lessons already written, the format of the national paper —
and then calls a provider with it. The prompt is the expensive part to
get right and the call is the expensive part to pay for. This splits them.

A task runs a station exactly as the queue would, in a thread, with one
difference: when the station would call a model, it stops and hands the
messages out through the API instead. Whatever you run — Claude Code,
Codex, Antigravity, a local Ollama, a script — reads the messages, answers
them on the model you are already paying for, and posts the answer back.
The station picks up as if the provider had answered, and everything
downstream is the platform's: the normaliser, the engine, the checks, the
figure renderer, the paper, the PDF.

The agent never sees a credential, and the platform never needs to reach
your machine: your side pulls prompts and pushes answers, so a laptop
behind a home router can drive a server on the internet.

A task's live state — the thread, the pending step — lives in the API
process. A restart loses it; the record in `agent_tasks` says so, and the
agent starts the task again. Runs are short compared with a deploy.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-byom")

# How long a station waits for the agent to answer one prompt before the
# task fails. Long, because a person may be watching the agent think.
STEP_TIMEOUT_SECONDS = int(os.getenv("BYOM_STEP_TIMEOUT_SECONDS", "2700"))
# Finished tasks are kept in memory this long for the agent to read.
KEEP_DONE_SECONDS = 6 * 3600

RUNNING, AWAITING, DONE, FAILED, CANCELLED = "running", "awaiting", "done", "failed", "cancelled"


@dataclass
class Step:
    number: int
    stage: str
    provider_hint: str
    model_hint: str
    messages: list[dict[str, str]]
    temperature: float
    expect: str            # "json" | "text"
    effort: str
    asked_at: float
    answered_at: float = 0.0
    model_used: str = ""
    chars: int = 0

    def to_dict(self, *, with_messages: bool = True) -> dict[str, Any]:
        out = {"number": self.number, "stage": self.stage, "expect": self.expect,
               "temperature": self.temperature, "effort": self.effort,
               "model_hint": self.model_hint, "provider_hint": self.provider_hint,
               "asked_at": self.asked_at, "answered_at": self.answered_at,
               "model_used": self.model_used, "chars": self.chars}
        if with_messages:
            out["messages"] = self.messages
        return out


@dataclass
class Task:
    task_id: str
    station: str
    params: dict[str, Any]
    created_by: str
    status: str = RUNNING
    steps: list[Step] = field(default_factory=list)
    pending: Step | None = None
    answer: Any = None
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    wake: threading.Event = field(default_factory=threading.Event)
    changed: threading.Condition = field(default_factory=threading.Condition)
    cancel: bool = False

    def to_dict(self, *, with_result: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "task_id": self.task_id, "station": self.station, "params": self.params,
            "status": self.status, "created_by": self.created_by,
            "created_at": self.created_at, "finished_at": self.finished_at,
            "steps_completed": len(self.steps), "error": self.error,
            "step": self.pending.to_dict() if self.pending else None,
            "history": [s.to_dict(with_messages=False) for s in self.steps],
        }
        if with_result and self.status == DONE:
            out["result"] = self.result
        return out


_TASKS: dict[str, Task] = {}
_LOCK = threading.Lock()
_current: contextvars.ContextVar[Task | None] = contextvars.ContextVar("byom_task", default=None)


class StepCancelled(RuntimeError):
    """The agent cancelled the task while a prompt was pending."""


def current() -> Task | None:
    return _current.get()


def get(task_id: str) -> Task | None:
    with _LOCK:
        return _TASKS.get(task_id)


def all_tasks() -> list[Task]:
    with _LOCK:
        _sweep()
        return sorted(_TASKS.values(), key=lambda t: t.created_at, reverse=True)


def _sweep() -> None:
    cutoff = time.time() - KEEP_DONE_SECONDS
    for task_id in [t for t, task in _TASKS.items()
                    if task.status in (DONE, FAILED, CANCELLED) and task.finished_at < cutoff]:
        _TASKS.pop(task_id, None)


def _notify(task: Task) -> None:
    with task.changed:
        task.changed.notify_all()


def defer(config: Any, messages: list[dict[str, str]], *, temperature: float,
          expect: str, effort: str) -> tuple[str, str]:
    """Hand the prompt out and wait for the answer. Returns (raw_text, model).

    Called from the LLM client, on the station's thread, in place of a
    provider call. The station is blocked here until the agent posts.
    """
    task = current()
    assert task is not None
    step = Step(number=len(task.steps) + 1, stage=str(getattr(config, "pipeline_stage", "") or ""),
                provider_hint=str(getattr(config, "provider", "") or ""),
                model_hint=str(getattr(config, "model", "") or ""),
                messages=[{"role": str(m.get("role") or "user"), "content": str(m.get("content") or "")}
                          for m in messages], temperature=temperature, expect=expect,
                effort=effort, asked_at=time.time())
    task.pending = step
    task.answer = None
    task.wake.clear()
    task.status = AWAITING
    _notify(task)
    logger.info("BYOM task %s step %d (%s) awaiting the agent: %d chars of prompt",
                task.task_id, step.number, step.stage, sum(len(m["content"]) for m in step.messages))

    from . import platform_settings

    timeout = int(platform_settings.get("byom_step_timeout_seconds") or STEP_TIMEOUT_SECONDS)
    if not task.wake.wait(timeout):
        raise TimeoutError(f"the agent did not answer step {step.number} within {timeout // 60} minutes")
    if task.cancel:
        raise StepCancelled("cancelled")
    raw, model = task.answer if isinstance(task.answer, tuple) else (task.answer, "")
    step.answered_at = time.time()
    step.model_used = model or "agent"
    step.chars = len(raw or "")
    task.steps.append(step)
    task.pending = None
    task.status = RUNNING
    _notify(task)
    return raw or "", model or "agent"


def complete(task_id: str, content: Any, model: str = "") -> Task:
    """The agent's answer to the pending step."""
    task = get(task_id)
    if task is None:
        raise KeyError(task_id)
    if task.status != AWAITING or task.pending is None:
        raise ValueError(f"task {task_id} is {task.status}; nothing is awaiting an answer")
    raw = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    task.answer = (raw, model)
    task.wake.set()
    return task


def cancel(task_id: str) -> Task | None:
    task = get(task_id)
    if task is None:
        return None
    task.cancel = True
    task.wake.set()
    if task.status in (RUNNING, AWAITING):
        task.status = CANCELLED
        task.finished_at = time.time()
        _notify(task)
    return task


def wait(task: Task, seconds: float, *, since_steps: int) -> Task:
    """Block until the task has a new pending step, or has finished."""
    deadline = time.time() + max(0.0, seconds)
    with task.changed:
        while time.time() < deadline:
            if task.status in (DONE, FAILED, CANCELLED):
                break
            if task.status == AWAITING and task.pending is not None and len(task.steps) >= since_steps:
                break
            task.changed.wait(timeout=min(1.0, max(0.05, deadline - time.time())))
    return task


def start(station: str, params: dict[str, Any], *, created_by: str, runner: Any) -> Task:
    """Run `runner(station, params)` on its own thread as a task."""
    task = Task(task_id="task-" + secrets.token_urlsafe(9), station=station, params=params,
                created_by=created_by)
    with _LOCK:
        _sweep()
        _TASKS[task.task_id] = task

    def _run() -> None:
        token = _current.set(task)
        try:
            task.result = runner(station, params)
            task.status = DONE
        except StepCancelled:
            task.status = CANCELLED
        except Exception as exc:  # noqa: BLE001
            logger.warning("BYOM task %s failed: %s", task.task_id, exc)
            task.status = FAILED
            task.error = str(exc)[:600]
        finally:
            task.pending = None
            task.finished_at = time.time()
            _current.reset(token)
            _record(task)
            _notify(task)
            try:
                from . import webhooks

                webhooks.emit("agent_task.done" if task.status == DONE else "agent_task.failed",
                              {"task_id": task.task_id, "station": task.station, "params": task.params,
                               "status": task.status, "steps": len(task.steps), "error": task.error,
                               "result": _summary(task.result)})
            except Exception as exc:  # noqa: BLE001
                logger.debug("Webhook not sent: %s", exc)

    threading.Thread(target=_run, name=f"byom-{task.task_id}", daemon=True).start()
    return task


def _record(task: Task) -> None:
    """The finished task, on disk, for the ledger the console shows."""
    try:
        from ..infra.db import execute, to_json

        execute(
            """
            INSERT INTO agent_tasks (task_id, station, params, status, created_by, steps, model_used,
                                     error, result, created_at, finished_at)
            VALUES (:task_id, :station, CAST(:params AS jsonb), :status, :created_by, :steps, :model_used,
                    :error, CAST(:result AS jsonb), to_timestamp(:created_at), to_timestamp(:finished_at))
            ON CONFLICT (task_id) DO UPDATE SET status = EXCLUDED.status, steps = EXCLUDED.steps,
                error = EXCLUDED.error, result = EXCLUDED.result, finished_at = EXCLUDED.finished_at
            """,
            {"task_id": task.task_id, "station": task.station, "params": to_json(task.params),
             "status": task.status, "created_by": task.created_by, "steps": len(task.steps),
             "model_used": ", ".join(sorted({s.model_used for s in task.steps if s.model_used})),
             "error": task.error,
             "result": to_json(_summary(task.result)), "created_at": task.created_at,
             "finished_at": task.finished_at or time.time()},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record BYOM task %s: %s", task.task_id, exc)


def _summary(result: Any) -> dict[str, Any]:
    """What the ledger keeps of a result: ids, counts, gate — not the content."""
    if not isinstance(result, dict):
        return {}
    keep = {}
    for key in ("artifact", "artifact_id", "saved", "batch_count", "requested_count", "quality_gate",
                "self_check", "quality", "sub_strand", "model", "review_cycles", "drawings"):
        if key in result:
            keep[key] = result[key]
    return keep
