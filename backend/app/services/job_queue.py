"""Queue the long work and report on it, instead of holding a request open.

Generating one sub-strand's notes takes about a minute. A grade's worth takes an
afternoon. Held open on an HTTP request each one blocks a browser tab, times out
at the proxy, and loses everything on a refresh — so the work was done one item
at a time with somebody watching it.

Queued instead: the request records what to do and returns immediately, a single
worker runs the jobs, and the console reads progress from the table.

Deliberately SEQUENTIAL. These calls cost money and hit provider rate limits,
and ten at once is how a run fails halfway with no way to tell which half — the
failures interleave, the retries double-charge, and the partial output looks
like a complete one. One at a time is slower and knowable.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger("cbc-jobs")

QUEUED, RUNNING, DONE, FAILED, CANCELLED = "queued", "running", "done", "failed", "cancelled"
TERMINAL = frozenset({DONE, FAILED, CANCELLED})

# A job that has crashed twice will crash a third time; retrying past this
# spends money to learn nothing.
MAX_ATTEMPTS = 2

# How long the worker sleeps when the queue is empty.
IDLE_SECONDS = 3.0

# Every kind the queue can run, and the callable that runs it. Registered by
# the routes at import time so this module stays free of route imports.
_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}

_worker: threading.Thread | None = None
_stop = threading.Event()


def register(kind: str, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    _HANDLERS[kind] = handler


def known_kinds() -> list[str]:
    return sorted(_HANDLERS)


@dataclass(slots=True)
class Job:
    job_id: str = ""
    batch_id: str = ""
    kind: str = ""
    grade: str = ""
    subject: str = ""
    strand: str = ""
    sub_strand: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = QUEUED

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id, "batch_id": self.batch_id, "kind": self.kind,
            "grade": self.grade, "subject": self.subject, "strand": self.strand,
            "sub_strand": self.sub_strand, "status": self.status,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def enqueue(
    kind: str, grade: str, subject: str, payload: dict[str, Any], *,
    strand: str = "", sub_strand: str = "", batch_id: str = "", queued_by: str = "",
) -> Job:
    """Record one unit of work. Identical queued work is not queued twice."""
    from ..errors import raise_api_error
    from ..infra.db import execute, fetch_one, to_json

    if kind not in _HANDLERS:
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{kind}' is not a job this queue can run. Known: {', '.join(known_kinds())}.",
        )

    seed = f"{kind}:{grade}:{subject}:{strand}:{sub_strand}"
    job_id = f"job_{hashlib.sha256(f'{seed}:{_now()}'.encode()).hexdigest()[:16]}"

    # Queuing the same sub-strand's notes twice runs the model twice and files
    # two versions that differ only by sampling noise.
    duplicate = fetch_one(
        """
        SELECT job_id FROM jobs
        WHERE kind = :kind AND grade = :grade AND LOWER(subject) = LOWER(:subject)
          AND strand = :strand AND sub_strand = :sub_strand
          AND status IN ('queued', 'running')
        LIMIT 1
        """,
        {"kind": kind, "grade": grade, "subject": subject,
         "strand": strand, "sub_strand": sub_strand},
    )
    if duplicate:
        logger.info("Already queued: %s for %s.", kind, sub_strand or subject)
        return Job(job_id=str(duplicate["job_id"]), kind=kind, grade=grade,
                   subject=subject, strand=strand, sub_strand=sub_strand,
                   batch_id=batch_id, status=QUEUED)

    execute(
        """
        INSERT INTO jobs (job_id, batch_id, kind, grade, subject, strand,
                          sub_strand, payload, status, queued_by)
        VALUES (:job_id, :batch_id, :kind, :grade, :subject, :strand,
                :sub_strand, CAST(:payload AS jsonb), 'queued', :queued_by)
        """,
        {"job_id": job_id, "batch_id": batch_id, "kind": kind, "grade": grade,
         "subject": subject, "strand": strand, "sub_strand": sub_strand,
         "payload": to_json(payload), "queued_by": queued_by},
    )
    return Job(job_id=job_id, batch_id=batch_id, kind=kind, grade=grade,
               subject=subject, strand=strand, sub_strand=sub_strand)


def cancel(job_id: str = "", batch_id: str = "") -> int:
    """Stop work that has not started. A running job is left to finish.

    Killing it mid-flight would leave the artifact half-written with no record
    of which half, and the tokens are already spent either way.
    """
    from ..infra.db import execute, fetch_one

    if not (job_id or batch_id):
        return 0
    row = fetch_one(
        "SELECT COUNT(*) AS n FROM jobs WHERE status = 'queued' "
        "AND (job_id = :job_id OR (batch_id <> '' AND batch_id = :batch_id))",
        {"job_id": job_id, "batch_id": batch_id},
    )
    execute(
        "UPDATE jobs SET status = 'cancelled', finished_at = NOW() "
        "WHERE status = 'queued' AND (job_id = :job_id "
        "OR (batch_id <> '' AND batch_id = :batch_id))",
        {"job_id": job_id, "batch_id": batch_id},
    )
    return int((row or {}).get("n") or 0)


def _claim() -> dict[str, Any] | None:
    """Take the oldest queued job, atomically, so two workers cannot share one."""
    from ..infra.db import fetch_one

    return fetch_one(
        """
        UPDATE jobs SET status = 'running', attempts = attempts + 1, started_at = NOW()
        WHERE job_id = (
            SELECT job_id FROM jobs WHERE status = 'queued'
            ORDER BY created_at ASC FOR UPDATE SKIP LOCKED LIMIT 1
        )
        RETURNING *
        """
    )


def run_one() -> dict[str, Any] | None:
    """Run the next queued job. Returns what it did, or None if idle."""
    from ..infra.db import execute, to_json

    job = _claim()
    if not job:
        return None

    job_id = str(job["job_id"])
    kind = str(job["kind"])
    handler = _HANDLERS.get(kind)

    if handler is None:
        execute(
            "UPDATE jobs SET status = 'failed', error = :error, finished_at = NOW() "
            "WHERE job_id = :job_id",
            {"job_id": job_id, "error": f"No handler registered for '{kind}'."},
        )
        return {"job_id": job_id, "status": FAILED}

    try:
        result = handler(dict(job))
    except Exception as exc:  # noqa: BLE001
        attempts = int(job.get("attempts") or 1)
        # Back to the queue once. A job that has crashed twice will crash a
        # third time, and retrying spends money to learn nothing.
        status = QUEUED if attempts < MAX_ATTEMPTS else FAILED
        logger.error("Job %s (%s) failed on attempt %d: %s", job_id, kind, attempts, exc)
        execute(
            "UPDATE jobs SET status = :status, error = :error, "
            "finished_at = CASE WHEN :status = 'failed' THEN NOW() ELSE NULL END "
            "WHERE job_id = :job_id",
            {"job_id": job_id, "status": status, "error": str(exc)[:1000]},
        )
        return {"job_id": job_id, "status": status, "error": str(exc)[:300]}

    execute(
        "UPDATE jobs SET status = 'done', result = CAST(:result AS jsonb), "
        "finished_at = NOW() WHERE job_id = :job_id",
        {"job_id": job_id, "result": to_json(result if isinstance(result, dict) else {})},
    )
    return {"job_id": job_id, "status": DONE}


def _loop() -> None:
    while not _stop.is_set():
        try:
            if run_one() is None:
                _stop.wait(IDLE_SECONDS)
        except Exception as exc:  # noqa: BLE001
            # The worker must outlive any single failure; a queue whose worker
            # dies looks exactly like a queue with nothing in it.
            logger.error("Job worker error: %s", exc)
            _stop.wait(IDLE_SECONDS)


def start_worker() -> bool:
    """Start the single background worker, if it is not already running."""
    global _worker

    if _worker is not None and _worker.is_alive():
        return False
    _stop.clear()
    _worker = threading.Thread(target=_loop, name="cbc-job-worker", daemon=True)
    _worker.start()
    logger.info("Job worker started (sequential, %d kinds).", len(_HANDLERS))
    return True


def stop_worker() -> None:
    _stop.set()


def worker_running() -> bool:
    return _worker is not None and _worker.is_alive()


# ── Reading progress ────────────────────────────────────────────────────────

def status(
    batch_id: str = "", grade: str = "", subject: str = "", limit: int = 200,
) -> dict[str, Any]:
    """What the queue is doing, for the console to poll."""
    from ..infra.db import fetch_all, fetch_one

    where = ["1=1"]
    params: dict[str, Any] = {"limit": max(1, min(limit, 500))}
    if batch_id:
        where.append("batch_id = :batch_id")
        params["batch_id"] = batch_id
    if grade:
        where.append("(grade = :grade OR grade = :alt_grade)")
        params["grade"] = grade
        params["alt_grade"] = grade.replace("grade-", "")
    if subject:
        where.append("LOWER(subject) = LOWER(:subject)")
        params["subject"] = subject

    clause = " AND ".join(where)
    jobs = fetch_all(
        f"""
        SELECT job_id, batch_id, kind, grade, subject, strand, sub_strand,
               status, attempts, error, created_at, started_at, finished_at
        FROM jobs WHERE {clause}
        ORDER BY created_at DESC LIMIT :limit
        """,
        params,
    ) or []

    counts = {row["status"]: int(row["n"]) for row in (fetch_all(
        f"SELECT status, COUNT(*) AS n FROM jobs WHERE {clause} GROUP BY status",
        {k: v for k, v in params.items() if k != "limit"},
    ) or [])}

    total = sum(counts.values())
    finished = sum(counts.get(s, 0) for s in TERMINAL)
    running = fetch_one(
        "SELECT kind, subject, sub_strand FROM jobs WHERE status = 'running' "
        "ORDER BY started_at ASC LIMIT 1"
    )

    return {
        "worker_running": worker_running(),
        "counts": counts,
        "total": total,
        "finished": finished,
        "percentage": round(finished / total * 100) if total else 0,
        "now_running": running,
        "jobs": jobs,
    }
