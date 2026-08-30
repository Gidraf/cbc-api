"""Generate a grade unattended, and stop when quality falls through the floor.

The ask is simple: once the pipeline is reliably good, set it going, come back,
download everything, review it at leisure. The danger is equally simple —
unattended generation that keeps going while quality collapses produces a grade
of content nobody can use, at full price, and the operator finds out at the end.

So an auto-run is a pipeline run with a floor. Every finished item is scored by
`quality_score` against what its own validators actually checked, and when the
recent average drops below the floor the run halts and cancels what has not
started. A few bad sub-strands stops it; a bad grade does not happen.

Two deliberate choices.

It halts on the RECENT average, not the lifetime one. A run that starts well
and degrades — a provider silently swapping models, a design that stops
parsing — has a lifetime average that stays healthy long after the output stops
being usable.

It refuses to judge on too little evidence. An item scored on one signal out of
five is not a pass, and a run that halted on three such items would be halting
on noise. Below a minimum confidence the item is recorded and excluded from the
decision, and the run says so.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .quality_score import ItemScore

logger = logging.getLogger("cbc-auto-run")

RUNNING, HALTED, DONE, STOPPED = "running", "halted", "done", "stopped"

# How many recent items the decision is made on. Fewer than this and one bad
# sub-strand halts a grade; many more and a run degrades for an hour first.
DEFAULT_WINDOW = 5

# The floor an operator would set having watched the pipeline reach it.
DEFAULT_FLOOR = 95.0

# An item scored against less than this share of the scoring scheme is recorded
# but not voted on.
MIN_CONFIDENCE = 0.5


@dataclass(slots=True)
class AutoRun:
    run_id: str = ""
    batch_id: str = ""
    grade: str = ""
    subjects: list[str] = field(default_factory=list)
    floor: float = DEFAULT_FLOOR
    window: int = DEFAULT_WINDOW
    status: str = RUNNING
    items: list[dict[str, Any]] = field(default_factory=list)
    halted_reason: str = ""

    @property
    def judged(self) -> list[dict[str, Any]]:
        return [i for i in self.items if i.get("counted")]

    @property
    def average(self) -> float:
        rated = self.judged
        return round(sum(i["score"] for i in rated) / len(rated), 1) if rated else 0.0

    @property
    def recent_average(self) -> float:
        """The mean of the window. Reported, because operators read means."""
        tail = self.judged[-self.window:]
        return round(sum(i["score"] for i in tail) / len(tail), 1) if tail else 0.0

    @property
    def recent_median(self) -> float:
        """The median of the window. This is what the halt decides on.

        A mean halts on one bad item: four sub-strands at 97 and one at 55
        averages 89, and a whole grade stops because of a single sub-strand
        that could simply be regenerated. The median ignores the outlier and
        still falls the moment MOST of the window is bad, which is the
        difference between "one went wrong" and "it is going wrong".
        """
        tail = sorted(i["score"] for i in self.judged[-self.window:])
        if not tail:
            return 0.0
        middle = len(tail) // 2
        if len(tail) % 2:
            return round(tail[middle], 1)
        return round((tail[middle - 1] + tail[middle]) / 2, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "batch_id": self.batch_id,
            "grade": self.grade, "subjects": self.subjects,
            "floor": self.floor, "window": self.window, "status": self.status,
            "items_scored": len(self.items),
            "items_counted": len(self.judged),
            "average": self.average,
            "recent_average": self.recent_average,
            "recent_median": self.recent_median,
            "halted_reason": self.halted_reason,
            "items": self.items,
            "weakest_items": sorted(
                (i for i in self.judged), key=lambda i: i["score"]
            )[:5],
        }


def _row_to_run(row: dict[str, Any]) -> AutoRun:
    return AutoRun(
        run_id=str(row.get("run_id") or ""),
        batch_id=str(row.get("batch_id") or ""),
        grade=str(row.get("grade") or ""),
        subjects=list(row.get("subjects") or []),
        floor=float(row.get("floor") or DEFAULT_FLOOR),
        window=int(row.get("window_size") or DEFAULT_WINDOW),
        status=str(row.get("status") or RUNNING),
        items=list(row.get("items") or []),
        halted_reason=str(row.get("halted_reason") or ""),
    )


def start(
    grade: str, subjects: list[str], batch_id: str, *,
    floor: float = DEFAULT_FLOOR, window: int = DEFAULT_WINDOW,
    started_by: str = "",
) -> AutoRun:
    from ..infra.db import execute, to_json

    run_id = "auto_" + hashlib.sha256(
        f"{grade}{subjects}{datetime.now(timezone.utc).isoformat()}".encode()
    ).hexdigest()[:16]

    execute(
        """
        INSERT INTO auto_runs (run_id, batch_id, grade, subjects, floor,
                               window_size, status, started_by)
        VALUES (:run_id, :batch_id, :grade, CAST(:subjects AS jsonb), :floor,
                :window, 'running', :started_by)
        """,
        {"run_id": run_id, "batch_id": batch_id, "grade": grade,
         "subjects": to_json(subjects), "floor": floor, "window": window,
         "started_by": started_by},
    )
    logger.info("Auto-run %s started for %s (floor %.0f).", run_id, grade, floor)
    return AutoRun(run_id=run_id, batch_id=batch_id, grade=grade,
                   subjects=subjects, floor=floor, window=window)


def for_batch(batch_id: str) -> AutoRun | None:
    from ..infra.db import fetch_one

    if not batch_id:
        return None
    row = fetch_one(
        "SELECT * FROM auto_runs WHERE batch_id = :batch_id "
        "ORDER BY started_at DESC LIMIT 1",
        {"batch_id": batch_id},
    )
    return _row_to_run(row) if row else None


def get(run_id: str = "", grade: str = "") -> AutoRun | None:
    from ..infra.db import fetch_one

    if run_id:
        row = fetch_one("SELECT * FROM auto_runs WHERE run_id = :run_id",
                        {"run_id": run_id})
    else:
        row = fetch_one(
            "SELECT * FROM auto_runs WHERE (:grade = '' OR grade = :grade) "
            "ORDER BY started_at DESC LIMIT 1",
            {"grade": grade},
        )
    return _row_to_run(row) if row else None


def record(batch_id: str, item: ItemScore, *, label: str = "") -> AutoRun | None:
    """Score one finished item into its run, and decide whether to keep going.

    Returns the run when it has just halted, so the caller can cancel what is
    still queued. Returns None when there is no auto-run for this batch — an
    ordinary queued run is not gated.
    """
    from ..infra.db import execute, to_json

    run = for_batch(batch_id)
    if run is None or run.status != RUNNING:
        return None

    counted = item.confidence >= MIN_CONFIDENCE
    run.items.append({
        "label": label or item.sub_strand or item.kind,
        "kind": item.kind,
        "score": item.score,
        "confidence": item.confidence,
        "weakest": item.weakest,
        "counted": counted,
        "at": datetime.now(timezone.utc).isoformat(),
    })

    # Only decide once the window is full. Halting on the first two items is
    # halting on the variance of two items.
    judged = run.judged
    if len(judged) >= run.window and run.recent_median < run.floor:
        run.status = HALTED
        weakest = min(judged[-run.window:], key=lambda i: i["score"])
        run.halted_reason = (
            f"Most of the last {run.window} items came in below the floor: median "
            f"{run.recent_median} against {run.floor:.0f} (mean "
            f"{run.recent_average}). Weakest: '{weakest['label']}' at "
            f"{weakest['score']}, let down by "
            f"{weakest['weakest'].replace('_', ' ') or 'no single measure'}. "
            f"Nothing further has been started."
        )
        logger.warning("Auto-run %s halted: %s", run.run_id, run.halted_reason)

    execute(
        """
        UPDATE auto_runs SET items = CAST(:items AS jsonb), items_scored = :scored,
               average = :average, recent_average = :recent, status = :status,
               halted_reason = :reason,
               finished_at = CASE WHEN :status <> 'running' THEN NOW() ELSE NULL END
        WHERE run_id = :run_id
        """,
        {"items": to_json(run.items), "scored": len(run.items),
         "average": run.average, "recent": run.recent_average,
         "status": run.status, "reason": run.halted_reason,
         "run_id": run.run_id},
    )
    return run if run.status == HALTED else None


def stop(run_id: str, reason: str = "stopped by the operator") -> int:
    """End a run and cancel whatever it had queued."""
    from ..infra.db import execute

    from . import job_queue

    run = get(run_id=run_id)
    if run is None:
        return 0
    execute(
        "UPDATE auto_runs SET status = :status, halted_reason = :reason, "
        "finished_at = NOW() WHERE run_id = :run_id AND status = 'running'",
        {"status": STOPPED, "reason": reason, "run_id": run_id},
    )
    return job_queue.cancel(batch_id=run.batch_id)
