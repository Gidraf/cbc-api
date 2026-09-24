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

import contextlib
import contextvars
import logging
import time
from collections.abc import Iterator
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
    # A meter opened inside a job's meter (see `measure`) adds to both, so the
    # job's bill stays whole while one step inside it is priced on its own.
    parent: "Meter | None" = None
    # Whoever opened this meter files the cost itself (the legacy pipeline
    # writes `generation_costs` per stage), so `add` must not file it again.
    accounted: bool = False

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


@contextlib.contextmanager
def measure(accounted: bool = False) -> Iterator[Meter]:
    """Price one piece of work, inside a job or outside one.

    The questions station needs the cost of ITS calls to put a price on each
    item it saves — the generation, the repairs and the checks, not only the
    first call. Inside a queued job the calls still count towards the job; from
    a plain HTTP request, where no job meter exists, this is the only meter.
    """
    meter = begin()
    meter.accounted = accounted
    try:
        yield meter
    finally:
        end(meter)


def begin() -> Meter:
    """`measure()` for a function too long to indent under a `with`.

    Pair with `end()`. One left open by an exception is harmless: it hands
    every call on to the meter it was opened inside, so nothing goes uncounted,
    and the job's `stop()` clears it with the rest.
    """
    meter = Meter(parent=_current.get())
    _current.set(meter)
    return meter


def end(meter: Meter) -> Meter:
    """Close a `begin()` meter and give the calls back to the one around it."""
    if _current.get() is meter:
        _current.set(meter.parent)
    return meter


def _filed_elsewhere(meter: Meter | None) -> bool:
    """Whether a queued job or the legacy pipeline will file this call's cost."""
    while meter is not None:
        if meter.job_id or meter.accounted:
            return True
        meter = meter.parent
    return False


def _file_direct(usage: Any, model: str, provider: str) -> None:
    """File a call no job and no pipeline run will file.

    A call from a plain HTTP request — the studio writing questions there and
    then, a station run from the board without the queue — was metered by
    nothing and written nowhere, so "spend to date" left it out entirely.
    """
    try:
        from datetime import date

        from .cost_tracker import calculate_cost, persist_stage_cost

        persist_stage_cost(f"direct-{date.today().isoformat()}", "direct",
                           calculate_cost(model, provider, usage))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not file a direct call to %s/%s: %s", provider, model, exc)


def add(usage: Any, model: str, provider: str) -> None:
    """Record one model call against whatever job is running.

    A call outside any job is filed on its own (`_file_direct`), so the spend
    total is the whole bill and not only the queued part of it.
    """
    meter = _current.get()
    if not _filed_elsewhere(meter):
        _file_direct(usage, model, provider)
    if meter is None:
        return

    try:
        from .cost_tracker import calculate_cost

        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        cost = calculate_cost(model, provider, usage)
        spent = float(getattr(cost, "total_cost_usd", 0.0) or 0.0)

        each: Meter | None = meter
        while each is not None:
            each.calls += 1
            each.prompt_tokens += prompt
            each.completion_tokens += completion
            each.models[model] = each.models.get(model, 0) + 1
            each.cost_usd += spent
            each = each.parent
        logger.info(
            "metered %s/%s: in=%d (cached %d) out=%d cost=$%.4f",
            provider, model, prompt, int(getattr(usage, "cached_tokens", 0) or 0),
            completion, spent)
    except Exception as exc:  # noqa: BLE001
        # A meter that raises would fail a generation that otherwise worked.
        # Losing a cost figure is the lesser harm by a wide margin.
        logger.warning("Could not meter a call to %s/%s: %s", provider, model, exc)
