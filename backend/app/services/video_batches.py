"""Batches of social videos, queued together and followed to the end.

`queue` picks up to `count` questions in a scope — a whole subject, or some
of its topics — whose videos are not made, queued or being made, mixes the
topics unless asked not to, and queues them under one batch. `list_batches`
reads each batch's progress from its jobs, with a finishing estimate from how
long recent renders took. A batch can be cancelled (what has not started) or
its failures retried.
"""
from __future__ import annotations

import logging
import random
import secrets
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("cbc-video-batches")

SKIP_STATUSES = ("needs_review", "rejected", "superseded")


def queue(grade: str, subject: str, sub_strands: list[str] | None = None, *, count: int = 50, mix: bool = True,
          label: str = "", by: str = "", seed: int | None = None) -> dict[str, Any]:
    from ..infra.db import execute, to_json
    from . import question_rows, social
    from .question_dna import question_dna_service

    sub_strands = [s for s in (sub_strands or []) if s.strip()]
    rows: list[dict[str, Any]] = []
    for ss in (sub_strands or [""]):
        rows += question_dna_service.list_questions(grade=grade or None, subject=subject or None,
                                                    sub_strand=ss or None, limit=2000) or []
    questions = [q for q in question_rows.flatten_all(rows) if str(q.get("status") or "") not in SKIP_STATUSES]
    if mix:
        random.Random(seed).shuffle(questions)
    batch_id = f"vb_{datetime.now(timezone.utc):%Y%m%d%H%M}_{secrets.token_hex(3)}"
    already = {"ready": 0, "queued": 0, "running": 0, "nothing to draw": 0}
    chosen: list[str] = []
    for q in questions:
        if len(chosen) >= count:
            break
        qid = str(q.get("question_id") or "")
        try:
            st = social.status(qid, q, older=False)          # what needs making: an older video does not count
        except Exception as exc:  # noqa: BLE001
            logger.info("Skipping %s: %s", qid, exc)
            continue
        state = str(st.get("status"))
        if not st.get("scenes"):
            already["nothing to draw"] += 1
            continue
        if state in already:
            already[state] += 1
        elif state in ("none", "failed"):
            chosen.append(qid)
    queued, failed = 0, []
    for qid in chosen:
        try:
            got = social.enqueue(qid, queued_by=by or "batch", batch_id=batch_id)
            queued += got.get("status") == "queued"
        except Exception as exc:  # noqa: BLE001
            failed.append({"question_id": qid, "error": str(exc)[:200]})
    if queued:
        execute("""INSERT INTO video_batches (batch_id, label, grade, subject, sub_strands, requested, queued, created_by)
                   VALUES (:id, :label, :g, :s, CAST(:ss AS jsonb), :req, :q, :by)""",
                {"id": batch_id, "label": label[:120] or (", ".join(sub_strands) if sub_strands else subject)[:120],
                 "g": grade, "s": subject, "ss": to_json(sub_strands), "req": count, "q": queued, "by": by})
    return {"batch_id": batch_id if queued else "", "requested": count, "queued": queued,
            "already": {k: v for k, v in already.items() if v}, "failed": failed,
            "short": max(0, count - queued),
            "note": "" if queued >= count else
                    f"Only {queued} of {count} — every other question in this scope already has a video or one on its way."}


def recent_render_seconds() -> float | None:
    """The median of recent finished renders, for an estimate."""
    from ..infra.db import fetch_one

    row = fetch_one("""SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (finished_at - started_at))) AS s
                       FROM (SELECT finished_at, started_at FROM jobs WHERE kind = 'social' AND status = 'done'
                             AND started_at IS NOT NULL AND finished_at IS NOT NULL
                             ORDER BY finished_at DESC LIMIT 50) recent""") or {}
    return float(row["s"]) if row.get("s") is not None else None


def summarise(batch: dict[str, Any], counts: dict[str, int], per_video: float | None, renders: int,
              ahead: int, rendering: list[dict[str, Any]] | None = None,
              resumed: int = 0) -> dict[str, Any]:
    """One batch's progress and a finishing estimate. Pure. `ahead`: render
    jobs queued before this batch's next one. `rendering`: the videos being
    made now, each with the stage and percentage it reported — counted into
    the batch's progress, so the bar moves while a video is made rather than
    only when one is finished."""
    rendering = list(rendering or [])
    total = sum(counts.values())
    waiting = counts.get("queued", 0) + counts.get("waiting_for_scope", 0)
    left = waiting + counts.get("running", 0)
    under_way = sum(float(r.get("pct") or 0) for r in rendering) / 100.0
    settled = counts.get("done", 0) + counts.get("failed", 0) + counts.get("cancelled", 0)
    progress = round(100 * (settled + under_way) / total, 1) if total else 0.0
    eta = None
    if per_video and left:
        # The videos in hand have part of their render behind them.
        eta = round(max(0.0, (ahead + left - under_way)) * per_video / max(1, renders))
    created = batch.get("created_at")
    return {**batch, "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
            "total": total, "done": counts.get("done", 0), "running": counts.get("running", 0), "waiting": waiting,
            "failed": counts.get("failed", 0), "cancelled": counts.get("cancelled", 0),
            "finished": left == 0, "eta_seconds": eta,
            "progress_pct": min(100.0, progress), "rendering": rendering, "resumed": resumed}


_STAGE_WORDS = {"script": "Writing the script", "voice": "Narrating", "draw": "Drawing",
                "mux": "Mixing sound", "save": "Saving", "done": "Finishing"}


def _rendering(row: dict[str, Any]) -> dict[str, Any]:
    """One video being made, as the batch screen shows it."""
    live = row.get("live") if isinstance(row.get("live"), dict) else {}
    stage = str(live.get("stage") or "")
    return {"job_id": row.get("job_id"), "question_id": row.get("question_id") or "",
            "title": (row.get("title") or row.get("sub_strand") or "")[:90],
            "stage": _STAGE_WORDS.get(stage, stage.capitalize() or "Starting"),
            "pct": round(float(live.get("pct") or 0), 1),
            "frame": f"{live.get('n')} of {live.get('total')}" if stage == "draw" and live.get("total") else "",
            "seconds": int(row.get("seconds") or 0), "resumed": int(row.get("interruptions") or 0) > 0}


def list_batches(limit: int = 20) -> dict[str, Any]:
    from ..infra.db import fetch_all, fetch_one
    from .job_queue import _render_limit

    batches = fetch_all("SELECT * FROM video_batches ORDER BY created_at DESC LIMIT :n", {"n": limit}) or []
    per_video = recent_render_seconds()
    out = []
    for b in batches:
        rows = fetch_all("SELECT status, COUNT(*) AS n FROM jobs WHERE batch_id = :id GROUP BY status",
                         {"id": b["batch_id"]}) or []
        first_waiting = fetch_one("""SELECT MIN(created_at) AS t FROM jobs WHERE batch_id = :id AND status = 'queued'""",
                                  {"id": b["batch_id"]}) or {}
        ahead = 0
        if first_waiting.get("t"):
            ahead = int((fetch_one("""SELECT COUNT(*) AS n FROM jobs WHERE status = 'queued' AND kind IN ('social', 'video')
                                      AND created_at < :t""", {"t": first_waiting["t"]}) or {}).get("n") or 0)
        live_rows = fetch_all(
            """SELECT job_id, sub_strand, payload->>'question_id' AS question_id, payload->>'title' AS title,
                      live, interruptions, EXTRACT(EPOCH FROM (NOW() - started_at))::int AS seconds
               FROM jobs WHERE batch_id = :id AND status = 'running' ORDER BY started_at""",
            {"id": b["batch_id"]}) or []
        resumed = int((fetch_one("SELECT COUNT(*) AS n FROM jobs WHERE batch_id = :id AND interruptions > 0",
                                 {"id": b["batch_id"]}) or {}).get("n") or 0)
        out.append(summarise(dict(b), {r["status"]: int(r["n"]) for r in rows}, per_video, _render_limit(), ahead,
                             rendering=[_rendering(r) for r in live_rows], resumed=resumed))
    return {"batches": out, "seconds_per_video": round(per_video) if per_video else None, "renders_at_once": _render_limit()}


def cancel(batch_id: str) -> int:
    from . import job_queue

    return job_queue.cancel(batch_id=batch_id) if batch_id else 0


def retry(batch_id: str) -> int:
    """Put the batch's failed renders back in the queue with a fresh budget."""
    from ..infra.db import execute, fetch_all
    from . import job_queue

    rows = fetch_all("SELECT job_id FROM jobs WHERE batch_id = :id AND status = 'failed'", {"id": batch_id}) or []
    if not rows:
        return 0
    execute("""UPDATE jobs SET status = 'queued', attempts = 0, error = '', started_at = NULL, finished_at = NULL
               WHERE batch_id = :id AND status = 'failed'""", {"id": batch_id})
    for r in rows:
        job_queue.dispatch(str(r["job_id"]))
    return len(rows)
