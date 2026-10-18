"""The daily video job: lesson videos made every day, without anyone asking.

Every half hour (celery beat) it tops the day up towards `video_daily_target`
(200 by default): it counts the lesson videos made today and the ones already
queued, and queues more for questions that have none — the focus subjects
first (sciences, technical subjects, mathematics, ICT), questions with a
figure before those without, lower grades first within that. The render lane
makes one video at a time, so the queue never floods the worker.

`backfill` fills the registry (question_videos) from what storage already
holds — videos made before the registry existed, and those moved to Drive.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("cbc-video-factory")

EAT = timezone(timedelta(hours=3))
BATCH = 25                      # queued per run at most: a half-hour's work and some
FOCUS = ("science", "physics", "chemistry", "biology", "agriculture", "mathematic", "technical", "technology",
         "computer", "ict", "engineering", "aviation", "electricity", "building", "metalwork", "woodwork")
_HIDDEN = ("needs_review", "rejected", "superseded")


def target() -> int:
    from . import platform_settings as ps

    try:
        return max(0, int(ps.get("video_daily_target", 200)))
    except (TypeError, ValueError):
        return 200


def made_today(now: datetime | None = None) -> int:
    from ..infra.db import fetch_one

    start = (now or datetime.now(timezone.utc)).astimezone(EAT).replace(hour=0, minute=0, second=0, microsecond=0)
    row = fetch_one("SELECT COUNT(*) AS n FROM question_videos WHERE kind = 'lesson' AND made_at >= :d", {"d": start})
    return int((row or {}).get("n") or 0)


def pending() -> int:
    from ..infra.db import fetch_one
    from .whiteboard import JOB_KIND

    row = fetch_one("SELECT COUNT(*) AS n FROM jobs WHERE kind = :k AND status IN ('queued', 'running')", {"k": JOB_KIND})
    return int((row or {}).get("n") or 0)


def candidates(limit: int) -> list[str]:
    """Questions with no lesson video and none being made: focus subjects,
    figures, lower grades first."""
    from ..infra.db import fetch_all
    from .whiteboard import JOB_KIND

    focus = " OR ".join(f"LOWER(d.curriculum_link->>'subject') LIKE '%{w}%'" for w in FOCUS)
    rows = fetch_all(f"""
        SELECT d.question_id FROM question_dna d
        WHERE d.status <> ALL(:hidden) AND d.superseded_by IS NULL
          AND NOT EXISTS (SELECT 1 FROM question_videos v WHERE v.question_id = d.question_id AND v.kind = 'lesson')
          AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.kind = :k AND j.status IN ('queued', 'running', 'failed')
                          AND j.payload->>'artifact_id' = d.question_id
                          AND (j.status <> 'failed' OR j.created_at > NOW() - INTERVAL '3 days'))
        ORDER BY CASE WHEN ({focus}) THEN 0 ELSE 1 END,
                 CASE WHEN COALESCE(d.content->'diagram'->>'diagram_id', '') <> '' THEN 0 ELSE 1 END,
                 d.grade_ordinal NULLS LAST, d.question_id
        LIMIT :n""", {"hidden": list(_HIDDEN), "k": JOB_KIND, "n": limit}) or []
    return [r["question_id"] for r in rows]


def top_up(now: datetime | None = None) -> dict[str, Any]:
    """Queue what today still needs. Returns the counts (for the log and the console)."""
    from . import whiteboard

    goal = target()
    done, waiting = made_today(now), pending()
    want = max(0, min(BATCH, goal - done - waiting))
    queued = []
    for qid in candidates(want) if want else []:
        try:
            got = whiteboard.enqueue(qid, queued_by="daily-videos")
            if got.get("status") in ("queued", "running"):
                queued.append(qid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not queue the video of %s: %s", qid, exc)
    out = {"target": goal, "made_today": done, "waiting": waiting, "queued_now": len(queued)}
    if queued:
        logger.info("Daily videos: %s", out)
    return out


def backfill(limit: int = 20000) -> int:
    """Record videos storage already holds (made before the registry, or
    moved to Drive) so Play and the job know about them."""
    from ..infra.db import execute, fetch_all
    from ..infra.storage import object_storage
    from ..settings import settings

    found: dict[tuple[str, str], tuple[str, str]] = {}

    def note(object_name: str) -> None:
        parts = object_name.split("/")
        if len(parts) == 3 and parts[2].endswith(".mp4") and parts[0] in ("videos", "social"):
            kind = "lesson" if parts[0] == "videos" else "social"
            found[(parts[1], kind)] = (parts[2][:-4], object_name)

    try:
        client = object_storage._get_client()
        for prefix in ("videos/", "social/"):
            for n, obj in enumerate(client.list_objects(settings.minio_bucket, prefix=prefix, recursive=True)):
                if n > limit:
                    break
                note(obj.object_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Backfill could not list storage: %s", exc)
    for row in fetch_all("SELECT object_name FROM drive_objects") or []:
        note(str(row["object_name"]))
    for (qid, kind), (key, name) in found.items():
        execute("""INSERT INTO question_videos (question_id, kind, video_key, object_name, made_at)
                   VALUES (:q, :k, :key, :o, NOW() - INTERVAL '30 days') ON CONFLICT (question_id, kind) DO NOTHING""",
                {"q": qid, "k": kind, "key": key, "o": name})
    return len(found)


def summary() -> dict[str, Any]:
    from ..infra.db import fetch_one

    total = fetch_one("SELECT COUNT(*) AS n FROM question_videos WHERE kind = 'lesson'") or {}
    return {"target": target(), "made_today": made_today(), "waiting": pending(),
            "with_video": int(total.get("n") or 0)}


# ── social videos: every question gets its vertical video, without asking ────
#
# Every half hour the job queues social videos for questions that have none
# (the focus subjects, figures and lower grades first), up to
# `social_daily_target` a day and never more than SOCIAL_QUEUE waiting at once —
# so it fills the render helpers' idle time and never floods them. Auto-book
# then books the ready ones for posting.

SOCIAL_QUEUE = 30


def social_target() -> int:
    from . import platform_settings as ps

    try:
        return max(0, int(ps.get("social_daily_target", 150)))
    except (TypeError, ValueError):
        return 150


def social_made_today(now: datetime | None = None) -> int:
    from ..infra.db import fetch_one

    start = (now or datetime.now(timezone.utc)).astimezone(EAT).replace(hour=0, minute=0, second=0, microsecond=0)
    row = fetch_one("SELECT COUNT(*) AS n FROM question_videos WHERE kind = 'social' AND made_at >= :d", {"d": start})
    return int((row or {}).get("n") or 0)


def social_pending() -> int:
    from ..infra.db import fetch_one

    row = fetch_one("SELECT COUNT(*) AS n FROM jobs WHERE kind = 'social' AND status IN ('queued', 'running')")
    return int((row or {}).get("n") or 0)


def social_candidates(limit: int) -> list[str]:
    """Questions with no social video and none being made."""
    from ..infra.db import fetch_all

    focus = " OR ".join(f"LOWER(d.curriculum_link->>'subject') LIKE '%{w}%'" for w in FOCUS)
    rows = fetch_all(f"""
        SELECT d.question_id FROM question_dna d
        WHERE d.status <> ALL(:hidden) AND d.superseded_by IS NULL
          AND NOT EXISTS (SELECT 1 FROM question_videos v WHERE v.question_id = d.question_id AND v.kind = 'social')
          AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.kind = 'social' AND j.status IN ('queued', 'running', 'failed')
                          AND j.payload->>'question_id' = d.question_id
                          AND (j.status <> 'failed' OR j.created_at > NOW() - INTERVAL '3 days'))
        ORDER BY CASE WHEN ({focus}) THEN 0 ELSE 1 END,
                 CASE WHEN COALESCE(d.content->'diagram'->>'diagram_id', '') <> '' THEN 0 ELSE 1 END,
                 d.grade_ordinal NULLS LAST, d.question_id
        LIMIT :n""", {"hidden": list(_HIDDEN), "n": limit}) or []
    return [r["question_id"] for r in rows]


def stale_social(limit: int, scan: int = 80) -> list[str]:
    """Questions whose social video was made before the current cut (the pitch
    added, the teacher changed): the oldest first, a few dozen looked at a run."""
    from ..infra.db import fetch_all
    from . import social

    rows = fetch_all("""SELECT v.question_id FROM question_videos v
                        WHERE v.kind = 'social'
                          AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.kind = 'social' AND j.status IN ('queued', 'running')
                                          AND j.payload->>'question_id' = v.question_id)
                        ORDER BY v.made_at ASC LIMIT :n""", {"n": scan}) or []
    out = []
    for r in rows:
        try:
            if social.status(r["question_id"], legacy=False).get("status") == "none":
                out.append(r["question_id"])
        except Exception:  # noqa: BLE001
            continue
        if len(out) >= limit:
            break
    return out


def next_for_post_now() -> str:
    """One question to make a video for on the spot, when Post now has nothing ready."""
    picks = social_candidates(1) or stale_social(1)
    return picks[0] if picks else ""


def top_up_social(now: datetime | None = None) -> dict[str, Any]:
    """Queue social videos for questions that have none, towards the day's target."""
    from . import social

    goal, done, waiting = social_target(), social_made_today(now), social_pending()
    want = max(0, min(BATCH, goal - done, SOCIAL_QUEUE - waiting))
    queued = []
    picks = social_candidates(want) if want else []
    if want and len(picks) < want:
        picks += stale_social(want - len(picks))       # then the videos made before the current cut
    for qid in picks:
        try:
            got = social.enqueue(qid, queued_by="daily-social")
            if got.get("status") in ("queued", "running"):
                queued.append(qid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not queue the social video of %s: %s", qid, exc)
    out = {"target": goal, "made_today": done, "waiting": waiting, "queued_now": len(queued)}
    if queued:
        logger.info("Daily social videos: %s", out)
    return out


def coverage() -> dict[str, Any]:
    """How many questions have their videos — for the console."""
    from ..infra.db import fetch_one

    row = fetch_one("""SELECT COUNT(*) AS questions,
                              COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM question_videos v WHERE v.question_id = d.question_id
                                                             AND v.kind = 'social')) AS social,
                              COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM question_videos v WHERE v.question_id = d.question_id
                                                             AND v.kind = 'lesson')) AS lesson
                       FROM question_dna d WHERE d.status <> ALL(:hidden) AND d.superseded_by IS NULL""",
                    {"hidden": list(_HIDDEN)}) or {}
    return {k: int(row.get(k) or 0) for k in ("questions", "social", "lesson")} | {
        "social_target": social_target(), "social_made_today": social_made_today(), "social_waiting": social_pending()}

