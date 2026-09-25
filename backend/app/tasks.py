"""The Celery tasks. One job per task, state in Postgres.

Redis is the BROKER — it carries the fact that there is work. Postgres holds
what the work is and what came of it, because that is what the console reads
and what has to survive a Redis restart. A queue whose state lives only in the
broker loses the run when the broker is flushed, which is a thing that happens.
"""
from __future__ import annotations

import logging

from .celery_app import celery_app

logger = logging.getLogger("cbc-tasks")


_state_loaded = False
_bindings_stamp: object = None


def _bindings_changed() -> bool:
    """Whether a stage binding was changed since this worker read them.

    Read once per process, a switch approved in the console reached the API
    and not the worker until someone restarted it — the worker went on writing
    with the model the admin had just switched away from.
    """
    global _bindings_stamp
    try:
        from .infra.db import fetch_one

        row = fetch_one("SELECT MAX(updated_at) AS at FROM stage_bindings") or {}
    except Exception:  # noqa: BLE001
        return False
    stamp = row.get("at")
    changed = _bindings_stamp is not None and stamp != _bindings_stamp
    _bindings_stamp = stamp
    return changed


def _load_state_once() -> None:
    """The stage bindings and provider credentials, from the database.

    The API loads them at startup; this process never did. It started with
    the credentials from the environment and no bindings at all, so every
    stage fell to the router's hard-coded fallback — gpt-4o-mini — whatever
    the console said. The runs the API's own thread picked up used the
    bound model; the runs this worker picked up used a 2024 model, and the
    two were compared as if they were the same pipeline.
    """
    global _state_loaded
    if _bindings_changed():
        _state_loaded = False
    if _state_loaded:
        return
    from .state import runtime_state

    try:
        runtime_state.load_from_db()
        _state_loaded = True
        logger.info("Worker loaded %d stage binding(s): %s",
                    len(runtime_state.stage_bindings),
                    ", ".join(sorted({b.model for b in runtime_state.stage_bindings.values()})) or "none")
    except Exception as exc:  # noqa: BLE001
        logger.error("Worker could not load stage bindings; falling back to defaults: %s", exc)


@celery_app.task(
    name="cbc.run_job",
    bind=True,
    # Celery-level retry is for infrastructure, not for the generation: a
    # provider error is counted by the jobs table and stops at two attempts.
    autoretry_for=(),
    acks_late=True,
)
def run_job(self, job_id: str) -> dict:
    """Run one queued job by id and record what happened.

    Routes are imported here rather than at module scope so the worker builds
    its handler registry the same way the API does — a worker that imports the
    queue but not the routes has an empty registry and fails every job with
    "no handler registered", which reads like a code bug and is a wiring one.
    """
    from . import routes  # noqa: F401
    from .routes import curriculum  # noqa: F401  (registers the job handlers)
    from .routes import model_scout  # noqa: F401  (registers the model_scout job)
    from .services import job_queue

    _load_state_once()
    info = getattr(self.request, "delivery_info", None) or {}
    outcome = job_queue.run_job_by_id(job_id, redelivered=bool(info.get("redelivered")))

    # Sent back to the queue for its second attempt: dispatch it again, because
    # nothing else will. Under the in-process worker the poll loop picked it
    # back up; a Celery task that returns is simply finished.
    if outcome.get("status") == job_queue.QUEUED:
        run_job.apply_async((job_id,), countdown=30)

    # Its sub-strand is being built by another worker. Not a failure and not an
    # attempt — it never ran — so it comes back shortly rather than being
    # retried or lost. Short, because the thing it waits for is one station,
    # not a whole grade.
    if outcome.get("status") == job_queue.WAITING:
        run_job.apply_async((job_id,), countdown=15)

    return outcome


@celery_app.task(name="app.tasks.sweep_jobs")
def sweep_jobs() -> dict:
    """Abandoned and stranded jobs back on the road, every few minutes."""
    from . import routes  # noqa: F401
    from .routes import curriculum  # noqa: F401
    from .services import job_queue

    return job_queue.sweep()


@celery_app.task(name="app.tasks.prune_service_logs")
def prune_service_logs() -> dict:
    """Drop log lines past their retention, on the hour."""
    from .services import log_store

    removed = log_store.prune()
    logger.info("Pruned %d service log line(s).", removed)
    return {"removed": removed}


@celery_app.task(name="app.tasks.weekly_model_scout")
def weekly_model_scout() -> dict:
    """Queue the week's model scout, unless an admin has switched it off.

    Queued as a job rather than run here, so it takes its turn behind the
    work already waiting and shows on the Queue board with its cost.
    """
    from .routes import model_scout
    from .services import platform_settings

    if not platform_settings.get("model_scout_enabled"):
        logger.info("Weekly model scout is switched off.")
        return {"skipped": "disabled"}
    return model_scout.queue_run("schedule", by="scheduler")
