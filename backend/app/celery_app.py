"""Celery, so generation outlives the browser tab that asked for it.

The work was done on the HTTP request that asked for it. A guide takes a
minute, a strand's sub-strands take longer, and a grade takes an afternoon —
so a refresh, a navigation, a proxy timeout or a deploy lost whatever was in
flight, with no record of what had been running.

The in-process thread that replaced it was better but still wrong in two ways:
it dies with the API process, and it multiplies if the API is ever scaled to
more than one container — three replicas is three workers racing the same
table.

So the work runs in its own process, on its own container, with Redis as the
broker. Redis is already in the stack and already healthy-checked, so this adds
a worker rather than an architecture.

CONCURRENCY IS ONE BY DESIGN. These calls cost money and hit provider rate
limits, and ten at once is how a run fails halfway with no way to tell which
half — the failures interleave, the retries double-charge, and partial output
looks exactly like complete output. Raise CELERY_CONCURRENCY only with a rate
limiter in front of the providers.
"""
from __future__ import annotations

import logging
import os

from celery import Celery

from .settings import settings

logger = logging.getLogger("cbc-celery")

BROKER_URL = os.getenv("CELERY_BROKER_URL", settings.redis_url)
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", settings.redis_url)
TASK_QUEUE = os.getenv("CELERY_TASK_QUEUE", "cbc_generation")

# `include` rather than `autodiscover_tasks`: autodiscovery runs while this
# module is still executing, so importing app.tasks — which imports THIS module
# — is a cycle, and Celery swallows it. The worker then starts cleanly, prints
# an empty [tasks] list, and fails every job it is handed with "unregistered
# task". `include` is resolved when the worker boots, after this module exists.
celery_app = Celery(
    "cbc", broker=BROKER_URL, backend=RESULT_BACKEND, include=["app.tasks"]
)

celery_app.conf.update(
    task_default_queue=TASK_QUEUE,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,

    # Acknowledge AFTER the job finishes. Acknowledging on receipt means a
    # worker killed mid-generation loses the job silently — the row says
    # "running" for ever and nothing ever picks it up again.
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # One job in the worker at a time. Prefetching reserves jobs a busy worker
    # will not start for minutes, which makes the queue look stuck to anyone
    # reading it and starves a second worker if one is ever added.
    worker_prefetch_multiplier=1,

    # A generation that has not finished in an hour is not going to. Without a
    # ceiling one wedged provider call holds a worker for ever.
    task_time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT", "3600")),
    task_soft_time_limit=int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "3300")),

    # Retries are decided by the jobs table, not by Celery: the row counts
    # attempts and stops at two, so a crash loop cannot spend money learning
    # the same thing repeatedly.
    task_default_retry_delay=30,

    broker_connection_retry_on_startup=True,
)

def broker_available() -> bool:
    """Whether a Celery broker can actually be reached right now.

    Asked before dispatching, so a missing broker degrades to the in-process
    worker instead of accepting work that will never run. Silently queueing
    into a broker nobody is listening to is the worst of the three outcomes:
    the console says "queued" and means "lost".
    """
    try:
        connection = celery_app.connection()
        connection.ensure_connection(max_retries=0, timeout=2)
        connection.release()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Celery broker unreachable (%s); falling back in-process.", exc)
        return False
