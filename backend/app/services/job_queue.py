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

WHERE IT RUNS. Redis carries the fact that there is work; Postgres holds what
the work is and what came of it. Celery runs it, in its own container, so a
refresh, a navigation, a proxy timeout or an API restart cannot touch a
generation in flight. The in-process thread below is a FALLBACK for a machine
with no broker — it dies with the API process and multiplies if the API is
scaled, so it is what you get when Celery cannot be reached, not what you get
by default.
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
_celery_checked_at: float = 0.0
_celery_ok: bool = False


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
    # Reviews and approvals are keyed on an ARTIFACT, not on a sub-strand: two
    # reviews of two versions of the same sub-strand are different work, and
    # collapsing them means the second version is never looked at.
    artifact_id = str((payload or {}).get("artifact_id") or "")
    duplicate = fetch_one(
        """
        SELECT job_id FROM jobs
        WHERE kind = :kind AND grade = :grade AND LOWER(subject) = LOWER(:subject)
          AND strand = :strand AND sub_strand = :sub_strand
          AND COALESCE(payload->>'artifact_id', '') = :artifact_id
          AND COALESCE(payload->>'layer', '') = :layer
          -- And the pipeline STEP. A pipeline advances by queueing the next
          -- step for the same sub-strand while the current one is still
          -- 'running' — it is the running job that queues it — so without the
          -- index every stage after the first was silently swallowed as a
          -- duplicate of the job that had just asked for it, and the run
          -- stopped dead one stage in looking like it had finished.
          AND COALESCE(payload->>'index', '') = :step_index
          AND status IN ('queued', 'running')
        LIMIT 1
        -- Only work still in flight. A finished draft waiting to be accepted is
        -- not a duplicate: asking for it again is asking for a regeneration.
        """,
        {"kind": kind, "grade": grade, "subject": subject,
         "strand": strand, "sub_strand": sub_strand,
         "artifact_id": artifact_id,
         "layer": str((payload or {}).get("layer") or ""),
         "step_index": str((payload or {}).get("index"))
         if (payload or {}).get("index") is not None else ""},
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
    dispatch(job_id)
    return Job(job_id=job_id, batch_id=batch_id, kind=kind, grade=grade,
               subject=subject, strand=strand, sub_strand=sub_strand)


def dispatch(job_id: str) -> str:
    """Hand one job to Celery, or fall back to the in-process worker.

    Returns which route it took, so the caller can say so rather than guess.
    Dispatch failure is never fatal: the row is already in the table, and the
    fallback worker claims the oldest queued job regardless of who queued it.
    """
    try:
        from ..celery_app import broker_available

        if broker_available():
            from ..tasks import run_job

            run_job.apply_async((job_id,))
            return "celery"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not dispatch %s to Celery: %s", job_id, exc)

    # No broker, or Celery is not installed. The work still has to run.
    start_worker()
    return "in_process"


def consume(job_id: str = "", *, kind: str = "", grade: str = "", subject: str = "",
            strand: str = "") -> int:
    """Mark finished work as accepted or discarded, so it stops being a draft.

    A queued generation whose result is a draft stays on the console until
    somebody decides about it. Without this it would reappear after every save,
    offering to overwrite the thing it had just been used to write.
    """
    from ..infra.db import execute, fetch_one

    if not (job_id or (kind and grade and subject and strand)):
        return 0
    params = {"job_id": job_id, "kind": kind, "grade": grade,
              "alt_grade": grade.replace("grade-", ""), "subject": subject,
              "strand": strand}
    clause = (
        "consumed_at IS NULL AND (job_id = :job_id OR (:job_id = '' "
        "AND kind = :kind AND (grade = :grade OR grade = :alt_grade) "
        "AND LOWER(subject) = LOWER(:subject) AND LOWER(strand) = LOWER(:strand)))"
    )
    row = fetch_one(f"SELECT COUNT(*) AS n FROM jobs WHERE {clause}", params)
    execute(f"UPDATE jobs SET consumed_at = NOW() WHERE {clause}", params)
    return int((row or {}).get("n") or 0)


def drafts(kind: str, grade: str = "", subject: str = "", limit: int = 100) -> list[dict[str, Any]]:
    """Finished queued work nobody has accepted or discarded yet, with results.

    `status()` deliberately omits results — across a grade they are megabytes.
    A draft is the one case where the result IS the point.
    """
    from ..infra.db import fetch_all

    where = ["kind = :kind", "status = 'done'", "consumed_at IS NULL"]
    params: dict[str, Any] = {"kind": kind, "limit": max(1, min(limit, 200))}
    if grade:
        where.append("(grade = :grade OR grade = :alt_grade)")
        params["grade"] = grade
        params["alt_grade"] = grade.replace("grade-", "")
    if subject:
        where.append("LOWER(subject) = LOWER(:subject)")
        params["subject"] = subject

    return fetch_all(
        f"""
        SELECT job_id, batch_id, kind, grade, subject, strand, status,
               result, created_at, finished_at
        FROM jobs WHERE {' AND '.join(where)}
        ORDER BY created_at ASC LIMIT :limit
        """,
        params,
    ) or []


def retry(job_id: str = "", grade: str = "", subject: str = "") -> list[str]:
    """Put failed work back in the queue, by hand.

    A job that crashes twice is parked rather than retried, because retrying a
    genuine defect spends money to learn nothing. But "parked" was a dead end:
    the console said the job was left for the operator and gave them no way to
    do anything with it, so a job that failed on a bug we have since FIXED
    stayed failed for ever.

    Deliberately manual, and deliberately attempt-resetting. A person clicking
    retry after a deploy is a different act from the queue retrying on its own,
    and it should get a full budget of attempts rather than the one it had left.
    """
    from ..infra.db import execute, fetch_all

    where = ["status = 'failed'"]
    params: dict[str, Any] = {}
    if job_id:
        where.append("job_id = :job_id")
        params["job_id"] = job_id
    if grade:
        where.append("(grade = :grade OR grade = :alt_grade)")
        params["grade"] = grade
        params["alt_grade"] = grade.replace("grade-", "")
    if subject:
        where.append("LOWER(subject) = LOWER(:subject)")
        params["subject"] = subject
    if not job_id and not (grade or subject):
        # Retrying every failure everywhere is never what somebody meant.
        return []

    clause = " AND ".join(where)
    rows = fetch_all(f"SELECT job_id FROM jobs WHERE {clause}", params) or []
    if not rows:
        return []

    execute(
        f"UPDATE jobs SET status = 'queued', attempts = 0, error = '', "
        f"started_at = NULL, finished_at = NULL WHERE {clause}",
        params,
    )

    retried = [str(r["job_id"]) for r in rows]
    for one in retried:
        dispatch(one)
    logger.info("Retried %d failed job(s) by hand.", len(retried))
    return retried


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


def _claim_by_id(job_id: str) -> dict[str, Any] | None:
    """Take one specific job, atomically.

    A broker can redeliver a message — a worker lost mid-job, a visibility
    timeout, an operator requeuing by hand. Without this the same generation
    runs twice and files two versions that differ only by sampling noise.
    """
    from ..infra.db import fetch_one

    return fetch_one(
        """
        UPDATE jobs SET status = 'running', attempts = attempts + 1, started_at = NOW()
        WHERE job_id = :job_id AND status = 'queued'
        RETURNING *
        """,
        {"job_id": job_id},
    )


def run_job_by_id(job_id: str) -> dict[str, Any]:
    """Run the job Celery was handed. Returns what happened."""
    job = _claim_by_id(job_id)
    if not job:
        # Already running, already finished, or cancelled while it waited.
        # None of those is an error, and none of them should run it again.
        logger.info("Job %s was not claimable; leaving it alone.", job_id)
        return {"job_id": job_id, "status": "skipped"}
    return _execute(job)


def run_one() -> dict[str, Any] | None:
    """Run the next queued job. Returns what it did, or None if idle."""
    job = _claim()
    if not job:
        return None
    return _execute(job)


def _execute(job: dict[str, Any]) -> dict[str, Any]:
    """Run one already-claimed job and record the outcome.

    Shared by the Celery task and the fallback worker on purpose: two copies of
    this would drift, and the one that drifted would be the one nobody watches.
    """
    from ..infra.db import execute, to_json

    from . import run_meter

    job_id = str(job["job_id"])
    kind = str(job["kind"])
    handler = _HANDLERS.get(kind)
    meter = run_meter.start(job_id)

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
        run_meter.stop()
        # Which build produced this failure. Without it a failure from before a
        # fix and one from after are the same red line in the console, and the
        # only way to tell them apart is to remember when you restarted — which
        # nobody does. Three rounds went on exactly that ambiguity.
        from .generation_version import VERSION as _BUILD

        # A job that failed halfway still spent whatever it spent. Recording
        # only successes makes the bill look smaller than the statement.
        execute(
            "UPDATE jobs SET status = :status, error = :error, "
            "result = CAST(:failure AS jsonb), "
            "llm_calls = llm_calls + :calls, total_tokens = total_tokens + :tokens, "
            "cost_usd = cost_usd + :cost, "
            "finished_at = CASE WHEN :status = 'failed' THEN NOW() ELSE NULL END "
            "WHERE job_id = :job_id",
            {"job_id": job_id, "status": status, "error": str(exc)[:1000],
             "failure": to_json({"failed_under_build": _BUILD,
                                 "failed_at": _now(),
                                 "error_type": type(exc).__name__}),
             "calls": meter.calls, "tokens": meter.total_tokens,
             "cost": round(meter.cost_usd, 6)},
        )
        return {"job_id": job_id, "status": status, "error": str(exc)[:300]}

    run_meter.stop()
    execute(
        "UPDATE jobs SET status = 'done', result = CAST(:result AS jsonb), "
        "finished_at = NOW(), llm_calls = :calls, total_tokens = :tokens, "
        "cost_usd = :cost WHERE job_id = :job_id",
        {"job_id": job_id, "result": to_json(result if isinstance(result, dict) else {}),
         "calls": meter.calls, "tokens": meter.total_tokens,
         "cost": round(meter.cost_usd, 6)},
    )
    return {"job_id": job_id, "status": DONE, "cost_usd": round(meter.cost_usd, 6)}


# A job whose worker was killed mid-generation leaves a row saying "running"
# that nothing will ever finish. Long enough that a slow generation is never
# mistaken for a dead one — the task time limit is an hour.
STALLED_MINUTES = int(__import__("os").getenv("JOB_STALLED_MINUTES", "75"))


def recover_stalled() -> int:
    """Return abandoned work to the queue and dispatch it again.

    Deploys, crashes and OOM kills all leave the same trace: status 'running',
    started_at in the past, nothing running it. Under the in-process worker
    that row was invisible for ever; the console showed a job in progress that
    had died with the process that owned it.

    Only jobs with attempts left are recovered. One that has already burned its
    attempts is marked failed with a reason, because retrying it a third time
    spends money to learn what two crashes already established.
    """
    from ..infra.db import execute, fetch_all

    stalled = fetch_all(
        """
        SELECT job_id, kind, attempts FROM jobs
        WHERE status = 'running'
          AND started_at < NOW() - (:minutes * INTERVAL '1 minute')
        """,
        {"minutes": STALLED_MINUTES},
    ) or []
    if not stalled:
        return 0

    requeued = 0
    for job in stalled:
        job_id = str(job["job_id"])
        if int(job.get("attempts") or 0) >= MAX_ATTEMPTS:
            execute(
                "UPDATE jobs SET status = 'failed', finished_at = NOW(), "
                "error = :error WHERE job_id = :job_id AND status = 'running'",
                {"job_id": job_id,
                 "error": "Abandoned mid-run and out of attempts — the worker "
                          "that owned it did not come back."},
            )
            continue
        execute(
            "UPDATE jobs SET status = 'queued', started_at = NULL "
            "WHERE job_id = :job_id AND status = 'running'",
            {"job_id": job_id},
        )
        dispatch(job_id)
        requeued += 1

    logger.info("Recovered %d stalled job(s) of %d abandoned.", requeued, len(stalled))
    return requeued


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


def _celery_reachable() -> bool:
    """Whether the broker is up, cached briefly.

    Called on every status poll, and a TCP probe per poll per open console is
    not free.
    """
    global _celery_checked_at, _celery_ok

    now = time.time()
    if now - _celery_checked_at < 15.0:
        return _celery_ok
    try:
        from ..celery_app import broker_available

        _celery_ok = broker_available()
    except Exception:  # noqa: BLE001
        _celery_ok = False
    _celery_checked_at = now
    return _celery_ok


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
               status, attempts, error, created_at, started_at, finished_at,
               -- Which step of the chain a pipeline job is on. Without it every
               -- stage of a full run reads as "pipeline" and the operator
               -- cannot tell reading the design from writing the questions.
               (payload->'steps'->>COALESCE((payload->>'index')::int, 0)) AS step,
               -- Which build produced a failure, so a stale one is visibly stale.
               (result->>'failed_under_build') AS failed_under_build
        FROM jobs WHERE {clause}
        ORDER BY created_at DESC LIMIT :limit
        """,
        params,
    ) or []

    # Where each waiting job sits. "Queued" with no number is indistinguishable
    # from "stuck", and an operator who queued a grade wants to know whether
    # theirs is next or fortieth.
    positions = {
        str(row["job_id"]): int(row["position"])
        for row in (fetch_all(
            """
            SELECT job_id, ROW_NUMBER() OVER (ORDER BY created_at ASC) AS position
            FROM jobs WHERE status = 'queued'
            """
        ) or [])
    }
    by_kind = {
        f"{row['kind']}:{row['status']}": int(row["n"])
        for row in (fetch_all(
            f"SELECT kind, status, COUNT(*) AS n FROM jobs WHERE {clause} "
            f"GROUP BY kind, status",
            {k: v for k, v in params.items() if k != "limit"},
        ) or [])
    }
    for job in jobs:
        job["position"] = positions.get(str(job.get("job_id")), 0)

    counts = {row["status"]: int(row["n"]) for row in (fetch_all(
        f"SELECT status, COUNT(*) AS n FROM jobs WHERE {clause} GROUP BY status",
        {k: v for k, v in params.items() if k != "limit"},
    ) or [])}

    total = sum(counts.values())
    finished = sum(counts.get(s, 0) for s in TERMINAL)
    running = fetch_one(
        # `strand` too: a sub-strand generation job has no sub_strand — the
        # strand IS the unit of work — so without it the banner said only
        # "running" with nothing named.
        "SELECT kind, subject, strand, sub_strand FROM jobs WHERE status = 'running' "
        "ORDER BY started_at ASC LIMIT 1"
    )

    return {
        "worker_running": worker_running() or _celery_reachable(),
        "runs_on": "celery" if _celery_reachable() else (
            "in_process" if worker_running() else "nothing"
        ),
        "counts": counts,
        "counts_by_kind": by_kind,
        "queue_depth": len(positions),
        "total": total,
        "finished": finished,
        "percentage": round(finished / total * 100) if total else 0,
        "now_running": running,
        "jobs": jobs,
    }
