"""What the station is doing, while it is doing it.

A generation ran for two minutes behind a spinner and then produced a guide
with three defects in it. The defects were found — the checks all worked — but
they were found at the end, reported as a score, and the operator's only move
was to press the button again and wait another two minutes to see whether it
had helped.

Two things were missing. The station never said what it was doing, and the
findings never fed back into the run that produced them.

This is the first: an append-only log of steps, written as they happen, carried
on a context variable so a service four calls deep can add to it without every
caller in between having to pass it down. When a job is running, each step is
flushed to that job's row, so the console shows the run live rather than
afterwards.
"""
from __future__ import annotations

import contextvars
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-run-log")

# Steps are cheap and a wedged run can write many. Keep the most recent.
MAX_STEPS = 200


@dataclass(slots=True)
class Step:
    at: float
    step: str
    detail: str = ""
    status: str = "running"   # running | ok | warn | fail

    def to_dict(self) -> dict[str, Any]:
        return {"at": round(self.at, 2), "step": self.step,
                "detail": self.detail, "status": self.status}


@dataclass(slots=True)
class RunLog:
    job_id: str = ""
    started_at: float = field(default_factory=time.monotonic)
    steps: list[Step] = field(default_factory=list)

    def add(self, step: str, detail: str = "", status: str = "ok") -> Step:
        entry = Step(at=time.monotonic() - self.started_at, step=step,
                     detail=detail, status=status)
        self.steps.append(entry)
        del self.steps[:-MAX_STEPS]
        return entry

    def to_dict(self) -> dict[str, Any]:
        return {"job_id": self.job_id,
                "elapsed_s": round(time.monotonic() - self.started_at, 1),
                "steps": [s.to_dict() for s in self.steps]}


_current: contextvars.ContextVar[RunLog | None] = contextvars.ContextVar(
    "cbc_run_log", default=None
)


def start(job_id: str = "") -> RunLog:
    log = RunLog(job_id=job_id)
    _current.set(log)
    return log


def stop() -> RunLog | None:
    log = _current.get()
    _current.set(None)
    return log


def current() -> RunLog | None:
    return _current.get()


def step(name: str, detail: str = "", status: str = "ok") -> None:
    """Record a step. Safe to call when nothing is listening.

    Written so a station can narrate itself unconditionally: outside a run
    there is no log, and this does nothing rather than requiring every call
    site to check first.
    """
    log = _current.get()
    if log is None:
        # Still worth the log line — this is what a person greps when the
        # console showed nothing.
        logger.info("%s%s", name, f": {detail}" if detail else "")
        return
    log.add(name, detail, status)
    logger.info("%s%s", name, f": {detail}" if detail else "")
    _flush(log)


def _flush(log: RunLog) -> None:
    """Push the steps onto the running job's row, so the console can poll them.

    Best-effort by design: a station that cannot write its progress must still
    finish its work. A failure here is logged once and never raised.
    """
    if not log.job_id:
        return
    try:
        from ..infra.db import execute, to_json

        execute(
            "UPDATE jobs SET result = result || CAST(:progress AS jsonb) "
            "WHERE job_id = :job_id AND status = 'running'",
            {"job_id": log.job_id, "progress": to_json({"progress": log.to_dict()})},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not flush run log for %s: %s", log.job_id, exc)
