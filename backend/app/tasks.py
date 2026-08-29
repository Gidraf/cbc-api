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
    from .services import job_queue

    outcome = job_queue.run_job_by_id(job_id)

    # Sent back to the queue for its second attempt: dispatch it again, because
    # nothing else will. Under the in-process worker the poll loop picked it
    # back up; a Celery task that returns is simply finished.
    if outcome.get("status") == job_queue.QUEUED:
        run_job.apply_async((job_id,), countdown=30)

    return outcome
