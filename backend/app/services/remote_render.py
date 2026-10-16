"""Videos rendered on another machine — the owner's Mac — beside the server.

A server with no GPU draws the 3D teacher in software, a video every ten to
fifteen minutes; a Mac draws one in under two. The render helper on the Mac
(app/render_helper.py) asks for work over the API:

    claim     a queued render (soonest-needed first) is marked running and
              handed over with everything needed to draw it with no database:
              the script, the voice and its pace, the frame (brand, cover,
              teacher), the hand, the music;
    heartbeat while it draws, so the sweep does not take the job back;
    done      the MP4 and thumbnail uploaded, stored under the names the
              server would have used, the job finished;
    failed    back to the queue (or failed, after three tries).

The server's own render worker keeps going: both take jobs atomically
(FOR UPDATE SKIP LOCKED / the claim's status check), so one video is never
made twice, and a job the Mac holds does not count against the server's
render slots.
"""
from __future__ import annotations

import base64
import logging
from typing import Any

logger = logging.getLogger("cbc-remote-render")

KINDS = ("social", "video")
TRIES = 3


def _spec(job: dict[str, Any]) -> dict[str, Any] | None:
    """What the helper needs to draw this job — or None if it is already made."""
    from ..infra.storage import object_storage
    from . import social, whiteboard
    from .math_engine.tts_service import _rate

    payload = dict(job.get("payload") or {})
    qid = str(payload.get("question_id") or payload.get("artifact_id") or "").replace("social:", "")
    q = whiteboard.load(qid)
    try:
        rate = _rate()
    except Exception:  # noqa: BLE001
        rate = "+0%"
    hand = None
    try:
        hand = whiteboard.hand()
    except Exception:  # noqa: BLE001
        hand = None
    if job["kind"] == "social":
        data, sdata, voice, title, b, key = social._prepare(q, str(payload.get("voice") or ""))
        name = f"{social.PREFIX}/{qid}/{key}.mp4"
        if object_storage.object_exists(name):
            return None
        framing = social.frame_payload(q, b)
        music = ""
        if framing.get("music_url"):
            raw = whiteboard._hand_bytes(framing["music_url"])
            music = base64.b64encode(raw).decode() if raw else ""
        return {"kind": "social", "question_id": qid, "data": sdata, "title": title, "voice": voice, "rate": rate,
                "social": framing, "prefix": social.PREFIX, "key": key, "hand": hand, "music": music,
                "post": social.post_text(q, data, b)}
    data, voice, title = whiteboard._script_for(q, str(payload.get("voice") or ""))
    key = whiteboard.cache_key(data, voice)
    if object_storage.object_exists(whiteboard.object_name(qid, key)):
        return None
    return {"kind": "video", "question_id": qid, "data": data, "title": title, "voice": voice, "rate": rate,
            "social": None, "prefix": "videos", "key": key, "hand": hand, "music": "", "post": ""}


def claim(worker: str) -> dict[str, Any]:
    """The next queued render, marked running for `worker`, with its spec."""
    from ..infra.db import execute, fetch_one, to_json
    from .job_queue import _priority

    for _ in range(8):                      # skip past any that turn out to be made already
        job = fetch_one(
            f"""UPDATE jobs SET status = 'running', started_at = NOW(), heartbeat_at = NOW(),
                       attempts = attempts + 1, live = CAST(:live AS jsonb)
                WHERE job_id = (SELECT job_id FROM jobs WHERE status = 'queued' AND kind IN {KINDS}
                                ORDER BY {_priority('jobs')} DESC, created_at ASC
                                FOR UPDATE SKIP LOCKED LIMIT 1)
                RETURNING *""",
            {"live": to_json({"where": "mac", "worker": worker[:80], "stage": "claimed"})})
        if not job:
            return {"job": None}
        try:
            spec = _spec(job)
        except Exception as exc:  # noqa: BLE001
            fail(str(job["job_id"]), f"could not prepare: {exc}", worker=worker)
            continue
        if spec is None:
            execute("UPDATE jobs SET status = 'done', finished_at = NOW(), result = CAST(:r AS jsonb) WHERE job_id = :id",
                    {"id": job["job_id"], "r": to_json({"status": "done", "cached": True})})
            continue
        execute("UPDATE jobs SET live = CAST(:live AS jsonb) WHERE job_id = :id",
                {"id": job["job_id"], "live": to_json({"where": "mac", "worker": worker[:80], "stage": "claimed",
                                                       "prefix": spec["prefix"], "key": spec["key"],
                                                       "question_id": spec["question_id"]})})
        return {"job": {"job_id": job["job_id"], "kind": job["kind"]}, "spec": spec}
    return {"job": None}


def _held(job_id: str) -> dict[str, Any] | None:
    from ..infra.db import fetch_one

    return fetch_one("""SELECT job_id, kind, payload, live, attempts FROM jobs
                        WHERE job_id = :id AND status = 'running' AND live->>'where' = 'mac'""", {"id": job_id})


def heartbeat(job_id: str, stage: str = "", pct: float = 0.0) -> bool:
    from ..infra.db import fetch_one

    row = fetch_one("""UPDATE jobs SET heartbeat_at = NOW(),
                              live = live || jsonb_build_object('stage', CAST(:s AS text), 'pct', CAST(:p AS float))
                       WHERE job_id = :id AND status = 'running' AND live->>'where' = 'mac' RETURNING job_id""",
                    {"id": job_id, "s": stage[:40], "p": float(pct)})
    return bool(row)


def done(job_id: str, video: bytes, thumb: bytes | None, seconds: float = 0.0) -> dict[str, Any]:
    """Store what the Mac made under the server's own names and finish the job."""
    from ..infra.db import execute, to_json
    from ..infra.storage import object_storage
    from . import whiteboard

    job = _held(job_id)
    if not job:
        raise ValueError("That job is not running on a render helper.")
    live = job.get("live") or {}
    prefix, key, qid = str(live.get("prefix") or ""), str(live.get("key") or ""), str(live.get("question_id") or "")
    if not (prefix and key and qid) or len(video) < 10_000 or video[4:8] != b"ftyp":
        raise ValueError("That is not the video this job was for.")
    name = f"{prefix}/{qid}/{key}.mp4"
    url = object_storage.save_bytes(name, video, "video/mp4")
    out: dict[str, Any] = {"status": "done", "question_id": qid, "url": url, "key": key, "seconds": seconds,
                           "rendered_on": live.get("worker") or "mac"}
    thumb_name = f"{prefix}/{qid}/{key}.jpg"
    if thumb:
        out["thumbnail_url"] = object_storage.save_bytes(thumb_name, thumb, "image/jpeg")
    if prefix == "social":
        try:
            from . import social

            st = social.status(qid)
            if st.get("post"):
                object_storage.save_text(f"{prefix}/{qid}/{key}.txt", st["post"])
        except Exception as exc:  # noqa: BLE001
            logger.info("No post text for %s: %s", qid, exc)
    whiteboard.record_video(qid, prefix, key, name)
    try:
        from . import drive_store

        drive_store.copy_now(name, thumb_name if thumb else "")
    except Exception as exc:  # noqa: BLE001
        logger.info("Drive copy after a Mac render skipped: %s", exc)
    execute("""UPDATE jobs SET status = 'done', finished_at = NOW(), result = CAST(:r AS jsonb),
                       live = live || '{"stage": "done", "pct": 100}'::jsonb WHERE job_id = :id""",
            {"id": job_id, "r": to_json(out)})
    return out


def fail(job_id: str, error: str, *, worker: str = "") -> dict[str, Any]:
    """Back to the queue for another try — on the server or the Mac — or failed after three."""
    from ..infra.db import fetch_one
    from . import job_queue

    row = fetch_one("""UPDATE jobs SET status = CASE WHEN attempts >= :tries THEN 'failed' ELSE 'queued' END,
                              error = :e, started_at = NULL, heartbeat_at = NULL,
                              finished_at = CASE WHEN attempts >= :tries THEN NOW() ELSE NULL END,
                              live = '{}'::jsonb
                       WHERE job_id = :id AND status = 'running' RETURNING status""",
                    {"id": job_id, "e": f"{worker or 'render helper'}: {error}"[:1000], "tries": TRIES})
    status = (row or {}).get("status")
    if status == "queued":
        try:
            job_queue.dispatch(job_id)
        except Exception:  # noqa: BLE001
            pass
    return {"job_id": job_id, "status": status}
