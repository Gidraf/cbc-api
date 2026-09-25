"""Run a station on a model it is not bound to, and keep nothing it writes.

The weekly scout asks "would this model do the job?" by having it do the job
on a handful of sub-strands. The answer has to come from the real station —
the same prompts, the same repairs, the same gate — or it answers a different
question. But the station saves what it writes: items into the bank, events
onto the day's board, figures into the library. A trial that did that would
put an untried model's work in front of a teacher and count it towards the
day's target.

So a trial is a context. Inside it, stages of the trial's tier resolve to the
candidate model, and each station's writes check `active()` and skip.
"""
from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator
from dataclasses import dataclass

# The panel's judge stays fixed: a candidate that marked its own work would
# pass itself. The questions gate scores with rules, not a model; this names
# the model stages that judge, so no trial ever swaps them.
JUDGES = frozenset({"reviewer_panel"})


@dataclass(frozen=True)
class Trial:
    tier: str
    model: str


_current: contextvars.ContextVar[Trial | None] = contextvars.ContextVar("cbc_model_trial", default=None)


def active() -> Trial | None:
    return _current.get()


@contextlib.contextmanager
def trial(tier: str, model: str) -> Iterator[Trial]:
    token = _current.set(Trial(tier=tier, model=model))
    try:
        yield _current.get()  # type: ignore[misc]
    finally:
        _current.reset(token)


@contextlib.contextmanager
def dry_run() -> Iterator[None]:
    """A trial on the models in use: the baseline, measured the same way."""
    token = _current.set(Trial(tier="", model=""))
    try:
        yield
    finally:
        _current.reset(token)


def model_for(stage: str, provider: str) -> str | None:
    """The trial's model for this stage, or None to resolve as usual."""
    current = _current.get()
    if current is None or not current.model or provider != "openai" or stage in JUDGES:
        return None
    from .model_policy import tier_of

    return current.model if tier_of(stage) == current.tier else None
