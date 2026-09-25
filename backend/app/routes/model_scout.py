"""The weekly model scout: its runs, its findings, and the admin's decisions.

Admin only, all of it. Approving a recommendation changes which model writes
every guide and question on the platform; that is not an operator's call.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..services import job_queue, model_scout
from ..services.auth import AuthContext, require_roles

router = APIRouter(prefix="/api/v1/model-scout", tags=["Model scout"])

_admin = require_roles("admin")


def _run_job(job: dict[str, Any]) -> dict[str, Any]:
    payload = dict(job.get("payload") or {})
    return model_scout.run(str(payload.get("trigger") or "schedule"))


# A job like any other: on the Queue board, metered, retried once, and run by
# the same worker — so a trial costs what the board says it cost.
job_queue.register("model_scout", _run_job)


def queue_run(trigger: str, *, by: str = "") -> dict[str, Any]:
    job = job_queue.enqueue("model_scout", "", "", {"trigger": trigger}, queued_by=by)
    route = job_queue.dispatch(job.job_id)
    return {"job_id": job.job_id, "dispatched": route}


@router.get("")
def scout_overview(_: AuthContext = Depends(_admin)) -> dict[str, Any]:
    """Models in use, open recommendations, recent runs, prices."""
    return model_scout.overview()


@router.post("/run")
def scout_run_now(auth: AuthContext = Depends(_admin)) -> dict[str, Any]:
    """Queue a run now rather than waiting for the week."""
    return queue_run("manual", by=getattr(auth, "subject", ""))


@router.post("/refresh-prices")
def scout_refresh_prices(_: AuthContext = Depends(_admin)) -> dict[str, Any]:
    """Read the pricing page now. No trials, no spend."""
    from ..services import price_book

    return price_book.refresh("openai")


@router.post("/recommendations/{rec_id}/approve")
def scout_approve(rec_id: str, auth: AuthContext = Depends(_admin)) -> dict[str, Any]:
    return model_scout.approve(rec_id, by=getattr(auth, "subject", "") or "admin")


@router.post("/recommendations/{rec_id}/reject")
def scout_reject(rec_id: str, auth: AuthContext = Depends(_admin)) -> dict[str, Any]:
    return model_scout.reject(rec_id, by=getattr(auth, "subject", "") or "admin")


@router.post("/recommendations/{rec_id}/rollback")
def scout_rollback(rec_id: str, auth: AuthContext = Depends(_admin)) -> dict[str, Any]:
    return model_scout.rollback(rec_id, by=getattr(auth, "subject", "") or "admin")
