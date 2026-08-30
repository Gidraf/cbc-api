"""What a run is actually spending, while it is spending it.

Auto mode showed a progress bar. A progress bar answers "how far" and nothing
else — not what is running, not what it produced, and not what it has cost. The
last one matters most here: the pipeline spends real money against a business
that is still clearing loans, and the only way to see the bill was to wait for
it.

Every model call already returns its token usage and the pricing table already
exists. Nothing was joining them to the job that made the call.

This is a context variable rather than a parameter because the alternative is
threading a meter through fourteen route handlers and every service they call,
and the one that gets missed is the one that spends the most.
"""
from __future__ import annotations

import contextvars
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-run-meter")


@dataclass(slots=True)
class Meter:
    job_id: str = ""
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    models: dict[str, int] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def seconds(self) -> float:
        return round(time.monotonic() - self.started_at, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "llm_calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "models": self.models,
            "seconds": self.seconds,
        }


_current: contextvars.ContextVar[Meter | None] = contextvars.ContextVar(
    "cbc_run_meter", default=None
)


def start(job_id: str = "") -> Meter:
    meter = Meter(job_id=job_id)
    _current.set(meter)
    return meter


def stop() -> Meter | None:
    meter = _current.get()
    _current.set(None)
    return meter


def current() -> Meter | None:
    return _current.get()


def add(usage: Any, model: str, provider: str) -> None:
    """Record one model call against whatever job is running.

    Silent when nothing is metered — a call from a plain HTTP request is not an
    error, it is just not part of a run.
    """
    meter = _current.get()
    if meter is None:
        return

    try:
        from .cost_tracker import calculate_cost

        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        meter.calls += 1
        meter.prompt_tokens += prompt
        meter.completion_tokens += completion
        meter.models[model] = meter.models.get(model, 0) + 1

        cost = calculate_cost(model, provider, usage)
        meter.cost_usd += float(getattr(cost, "total_cost_usd", 0.0) or 0.0)
    except Exception as exc:  # noqa: BLE001
        # A meter that raises would fail a generation that otherwise worked.
        # Losing a cost figure is the lesser harm by a wide margin.
        logger.warning("Could not meter a call to %s/%s: %s", provider, model, exc)
