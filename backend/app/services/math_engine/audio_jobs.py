"""Narration audio, synthesised off the request thread.

`build_simulation_track` used to call the TTS provider inline, once per step,
at a 25-second timeout each. A five-step walkthrough therefore held an HTTP
request open for up to two minutes while the console showed a spinner with no
way to tell a slow synthesis from a dead one — and every other long job in this
system already goes to the queue.

So the track is written immediately with `audio_status='pending'` and the audio
is filled in afterwards. The player already degrades correctly: with no
`audio_url` it advances on each step's `duration_ms`, so a walkthrough is
usable the moment it is built and gains narration when the worker gets to it.
"""
from __future__ import annotations

import logging
from typing import Any

from ...infra.db import execute, fetch_one, to_json
from .tts_service import tts_service

logger = logging.getLogger("cbc-math-audio")

JOB_KIND = "walkthrough_audio"


def enqueue_audio(simulation_id: str, curriculum_link: dict[str, Any], *,
                  queued_by: str = "") -> str:
    """Ask the worker to narrate this walkthrough. Returns the job id, or ""."""
    from .. import job_queue

    try:
        job = job_queue.enqueue(
            JOB_KIND,
            grade=str(curriculum_link.get("grade") or ""),
            subject=str(curriculum_link.get("subject") or ""),
            payload={"simulation_id": simulation_id},
            strand=str(curriculum_link.get("strand") or ""),
            sub_strand=str(curriculum_link.get("sub_strand") or ""),
            queued_by=queued_by,
        )
        return job.job_id
    except Exception as exc:  # noqa: BLE001
        # A walkthrough without narration is still a walkthrough. Never fail
        # the build because the queue would not take the audio.
        logger.warning("Could not queue narration for %s: %s", simulation_id, exc)
        return ""


def run_audio_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Synthesise every step of one stored walkthrough."""
    simulation_id = str((payload or {}).get("simulation_id") or "")
    if not simulation_id:
        return {"status": "skipped", "reason": "no simulation_id"}

    row = fetch_one(
        "SELECT track FROM math_simulations WHERE simulation_id = :sid",
        {"sid": simulation_id},
    )
    if not row:
        return {"status": "skipped", "reason": f"no walkthrough {simulation_id}"}

    track = row.get("track") or {}
    steps = track.get("steps") or []
    if not steps:
        return {"status": "skipped", "reason": "no steps"}

    synthesised = 0
    failed = 0
    for step in steps:
        if step.get("audio_url"):
            continue
        try:
            url = tts_service.synthesize_step_audio(
                step.get("narration") or "", simulation_id, int(step.get("index", 0))
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Narration failed for %s step %s: %s",
                           simulation_id, step.get("index"), exc)
            url = None
        if url:
            step["audio_url"] = url
            synthesised += 1
        else:
            failed += 1

    # `ready` only when every step speaks. A half-narrated walkthrough that
    # claims to be ready is the kind of thing nobody notices until a class is
    # watching it.
    if failed == 0 and synthesised:
        status = "ready"
    elif synthesised:
        status = "partial"
    else:
        status = "unavailable"

    track["steps"] = steps
    execute(
        """
        UPDATE math_simulations
           SET track = CAST(:track AS jsonb), audio_status = :status, updated_at = NOW()
         WHERE simulation_id = :sid
        """,
        {"track": to_json(track), "status": status, "sid": simulation_id},
    )
    logger.info("Narrated %s: %d step(s), %d failed, status=%s",
                simulation_id, synthesised, failed, status)
    return {"status": status, "synthesised": synthesised, "failed": failed,
            "simulation_id": simulation_id}
