"""A topic's social posts, ready to schedule — and how each one did.

`export_zip` gathers every finished post in a scope into one download: the
videos, thumbnails and captions numbered in posting order, and a
`schedule.csv` that spreads them over days and times on the platforms
chosen — the shape a scheduling tool's bulk upload, or a person working
down a list, wants. The same plan is written to `social_posts`, so the
tracker already knows what is due where.

The tracker is one row per post per platform: when it went out, its link,
and its numbers as they come in. `summary` compares platforms and topics
on what matters for growth — views, the share of viewers who engaged,
and followers gained.
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
import tempfile
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

logger = logging.getLogger("cbc-social-export")

PLATFORMS = ("tiktok", "instagram", "youtube", "facebook", "linkedin", "whatsapp", "x")
STATS = ("views", "likes", "comments", "shares", "saves", "follows")


def _slug(text: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:n] or "post"


def plan(count: int, *, start: date, per_day: int, times: list[str]) -> list[datetime]:
    """When each of `count` posts goes out: `per_day` a day from `start`, at
    the given times (24-hour, East Africa Time)."""
    eat = timezone(timedelta(hours=3))
    slots = [time(*map(int, t.split(":"))) for t in times[:per_day]] or [time(19, 0)]
    per_day = len(slots)
    return [datetime.combine(start + timedelta(days=i // per_day), slots[i % per_day], tzinfo=eat) for i in range(count)]


def ready_posts(grade: str, subject: str, sub_strand: str, limit: int = 300) -> list[dict[str, Any]]:
    """Every finished social post in the scope, in curriculum order."""
    from . import question_rows, social
    from .question_dna import question_dna_service

    rows = question_dna_service.list_questions(grade=grade or None, subject=subject or None,
                                               sub_strand=sub_strand or None, limit=limit)
    out = []
    for q in question_rows.flatten_all(rows):
        if str(q.get("status") or "") in ("needs_review", "rejected", "superseded"):
            continue
        try:
            st = social.status(str(q["question_id"]), q)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping %s: %s", q.get("question_id"), exc)
            continue
        if st.get("status") == "ready" and st.get("url"):
            out.append({**st, "question": q})
    return out


def export_zip(grade: str, subject: str, sub_strand: str, *, start: date, per_day: int = 1,
               times: list[str] | None = None, platforms: list[str] | None = None,
               record: bool = True, created_by: str = "") -> tuple[str, int]:
    """Write the zip to a temporary file. Returns (path, number of posts)."""
    from ..infra.storage import object_storage

    posts = ready_posts(grade, subject, sub_strand)
    if not posts:
        return "", 0
    platforms = [p for p in (platforms or ["tiktok", "instagram", "youtube"]) if p in PLATFORMS] or ["tiktok"]
    when = plan(len(posts), start=start, per_day=max(1, per_day), times=times or ["19:00"])
    handle = tempfile.NamedTemporaryFile(prefix="social-", suffix=".zip", delete=False)
    rows = []
    with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_STORED) as zf:
        for n, (post, at) in enumerate(zip(posts, when), start=1):
            q = post["question"]
            link = q.get("curriculum") or {}
            stem = f"{n:03d}_{at:%Y-%m-%d_%H%M}_{_slug(link.get('sub_strand'), 24)}"
            video = object_storage.read_bytes(object_storage.object_name_of(post["url"]))
            if not video:
                continue
            zf.writestr(f"videos/{stem}.mp4", video)
            thumb = object_storage.read_bytes(object_storage.object_name_of(post.get("thumbnail_url") or ""))
            if thumb:
                zf.writestr(f"thumbnails/{stem}.jpg", thumb)
            caption = post.get("post") or ""
            zf.writestr(f"captions/{stem}.txt", caption)
            rows.append({"number": n, "date": f"{at:%Y-%m-%d}", "time": f"{at:%H:%M}", "timezone": "EAT (UTC+3)",
                         "platforms": " ".join(platforms), "video": f"videos/{stem}.mp4",
                         "thumbnail": f"thumbnails/{stem}.jpg" if thumb else "", "caption": caption,
                         "topic": link.get("sub_strand") or "", "question_id": q["question_id"]})
            if record:
                for platform in platforms:
                    _plan_post(q, platform, at, created_by)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()) if rows else ["number"])
        writer.writeheader()
        writer.writerows(rows)
        zf.writestr("schedule.csv", buffer.getvalue())
        zf.writestr("README.txt", _README.format(count=len(rows), first=rows[0]["date"] if rows else "",
                                                 last=rows[-1]["date"] if rows else "", per_day=per_day,
                                                 platforms=", ".join(platforms)))
    handle.close()
    return handle.name, len(rows)


def _post_id(question_id: str, platform: str) -> str:
    return "sp_" + hashlib.sha256(f"{question_id}:{platform}".encode()).hexdigest()[:16]


def _plan_post(q: dict[str, Any], platform: str, at: datetime, created_by: str) -> None:
    from ..infra.db import execute

    link = q.get("curriculum") or {}
    execute(
        """
        INSERT INTO social_posts (post_id, question_id, platform, grade, subject, sub_strand, scheduled_for, created_by)
        VALUES (:id, :qid, :platform, :grade, :subject, :ss, :at, :by)
        ON CONFLICT (post_id) DO UPDATE SET scheduled_for = EXCLUDED.scheduled_for, updated_at = NOW()
        WHERE social_posts.posted_at IS NULL
        """,
        {"id": _post_id(q["question_id"], platform), "qid": q["question_id"], "platform": platform,
         "grade": str(link.get("grade") or ""), "subject": str(link.get("subject") or ""),
         "ss": str(link.get("sub_strand") or ""), "at": at, "by": created_by})


# ── the tracker ──────────────────────────────────────────────────────────────

def list_posts(grade: str = "", subject: str = "", sub_strand: str = "", platform: str = "") -> list[dict[str, Any]]:
    from ..infra.db import fetch_all
    from . import grade_sql

    grade_filter = f"(:grade = '' OR {grade_sql.clause('p.grade')})"
    rows = fetch_all(
        f"""
        SELECT p.*, LEFT(COALESCE(q.content->>'question_text', ''), 160) AS question_text
        FROM social_posts p LEFT JOIN question_dna q ON q.question_id = p.question_id
        WHERE {grade_filter} AND (:subject = '' OR LOWER(p.subject) = LOWER(:subject))
          AND (:ss = '' OR LOWER(p.sub_strand) = LOWER(:ss)) AND (:platform = '' OR p.platform = :platform)
        ORDER BY COALESCE(p.posted_at, p.scheduled_for, p.created_at), p.platform
        """, {"grade": grade, "subject": subject, "ss": sub_strand, "platform": platform}) or []
    for r in rows:
        for k in ("scheduled_for", "posted_at", "created_at", "updated_at"):
            if r.get(k) is not None and hasattr(r[k], "isoformat"):
                r[k] = r[k].isoformat()
    return rows


def save_post(values: dict[str, Any], *, created_by: str = "") -> dict[str, Any]:
    """Record a post, or update its link and numbers."""
    from ..infra.db import execute, fetch_one

    qid = str(values.get("question_id") or "")
    platform = str(values.get("platform") or "").lower()
    post_id = str(values.get("post_id") or "") or _post_id(qid, platform)
    existing = fetch_one("SELECT * FROM social_posts WHERE post_id = :id", {"id": post_id})
    if not existing:
        if not qid or platform not in PLATFORMS:
            raise ValueError("A new post needs its question and one of: " + ", ".join(PLATFORMS))
        from .whiteboard import load

        link = load(qid).get("curriculum") or {}
        execute("""INSERT INTO social_posts (post_id, question_id, platform, grade, subject, sub_strand, created_by)
                   VALUES (:id, :qid, :p, :g, :s, :ss, :by)""",
                {"id": post_id, "qid": qid, "p": platform, "g": str(link.get("grade") or ""),
                 "s": str(link.get("subject") or ""), "ss": str(link.get("sub_strand") or ""), "by": created_by})
    sets, params = [], {"id": post_id}
    for key in STATS:
        if values.get(key) is not None:
            sets.append(f"{key} = :{key}")
            params[key] = max(0, int(values[key]))
    for key in ("url", "notes"):
        if values.get(key) is not None:
            sets.append(f"{key} = :{key}")
            params[key] = str(values[key])[:1000]
    if values.get("watch_pct") is not None:
        sets.append("watch_pct = :watch_pct")
        params["watch_pct"] = max(0.0, min(100.0, float(values["watch_pct"])))
    for key in ("posted_at", "scheduled_for"):
        if values.get(key) is not None:
            sets.append(f"{key} = :{key}")
            params[key] = values[key] or None
    if values.get("posted") is True and not values.get("posted_at"):
        sets.append("posted_at = COALESCE(posted_at, NOW())")
    if sets:
        execute(f"UPDATE social_posts SET {', '.join(sets)}, updated_at = NOW() WHERE post_id = :id", params)
    return next(r for r in list_posts() if r["post_id"] == post_id)


def delete_post(post_id: str) -> None:
    from ..infra.db import execute

    execute("DELETE FROM social_posts WHERE post_id = :id", {"id": post_id})


def summary(posts: list[dict[str, Any]]) -> dict[str, Any]:
    """Platforms and topics side by side, on what posted so far."""
    def roll(rows: list[dict[str, Any]]) -> dict[str, Any]:
        live = [r for r in rows if r.get("posted_at")]
        totals = {k: sum(int(r.get(k) or 0) for r in live) for k in STATS}
        views = totals["views"]
        engaged = totals["likes"] + totals["comments"] + totals["shares"] + totals["saves"]
        watch = [float(r["watch_pct"]) for r in live if r.get("watch_pct") is not None]
        return {"posts": len(live), "planned": len(rows) - len(live), **totals,
                "views_per_post": round(views / len(live), 1) if live else 0,
                "engagement_rate": round(100 * engaged / views, 2) if views else 0,
                "follows_per_1000_views": round(1000 * totals["follows"] / views, 2) if views else 0,
                "avg_watch_pct": round(sum(watch) / len(watch), 1) if watch else None}

    by_platform: dict[str, list] = {}
    by_topic: dict[str, list] = {}
    for r in posts:
        by_platform.setdefault(r["platform"], []).append(r)
        by_topic.setdefault(r.get("sub_strand") or "—", []).append(r)
    live = sorted((r for r in posts if r.get("posted_at")), key=lambda r: -int(r.get("views") or 0))
    return {"overall": roll(posts),
            "by_platform": {k: roll(v) for k, v in sorted(by_platform.items())},
            "by_topic": {k: roll(v) for k, v in sorted(by_topic.items())},
            "top": [{k: r.get(k) for k in ("post_id", "platform", "question_text", "views", "likes", "follows", "url")}
                    for r in live[:5]]}


_README = """Social posts — {count} videos, {first} to {last}, {per_day} a day on {platforms}.

videos/      the MP4s, numbered in posting order: 001_<date>_<time>_<topic>.mp4
thumbnails/  a cover image for each, same name
captions/    the post text for each (question, answer, working, hashtags), same name
schedule.csv one row per post: date, time (East Africa Time), platforms, files, caption

Scheduling:
  * A scheduling tool (Buffer, Metricool, Later, Hootsuite …): use its bulk upload with
    schedule.csv, or drag the videos in order and paste each caption.
  * Facebook and Instagram: Meta Business Suite → Planner schedules Reels for both.
  * TikTok: tiktok.com → Upload on a computer lets you set a posting time.
  * YouTube Shorts: YouTube Studio → Upload → Visibility → Schedule.

When a post goes out, mark it posted and paste its link in Play → Performance;
add its views, likes, comments, shares and follows as they come in to compare
platforms and topics.
"""


# ── the browser poster ───────────────────────────────────────────────────────
#
# The rules live here, not in the poster: whatever the browser does, it is
# handed at most one post at a time, and only when the day's cap, the
# platform's cap, the gap since the last post and the posting hours allow.

HARD_DAILY_CAP = 30
MAX_ATTEMPTS = 3
EAT = timezone(timedelta(hours=3))


def poster_rules() -> dict[str, Any]:
    from . import platform_settings as ps

    def num(key: str, default: int, top: int) -> int:
        try:
            return max(0, min(int(ps.get(key, default) or default), top))
        except (TypeError, ValueError):
            return default

    hours = str(ps.get("poster_hours", "06:00-22:00") or "06:00-22:00")
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", hours)
    start, end = ((int(m[1]), int(m[2])), (int(m[3]), int(m[4]))) if m else ((6, 0), (22, 0))
    raw = ps.get("poster_platforms", None) or ["tiktok", "instagram", "facebook", "youtube", "linkedin"]
    platforms = [p.strip().lower() for p in (raw if isinstance(raw, list) else str(raw).split(",")) if p.strip()]
    return {"enabled": bool(ps.get("poster_enabled", False)),
            "daily_cap": num("poster_daily_cap", 30, HARD_DAILY_CAP),
            "platform_cap": num("poster_platform_cap", 8, HARD_DAILY_CAP),
            "min_gap_minutes": num("poster_min_gap_minutes", 20, 24 * 60),
            "hours": {"start": f"{start[0]:02d}:{start[1]:02d}", "end": f"{end[0]:02d}:{end[1]:02d}"},
            "platforms": [p for p in platforms if p in PLATFORMS]}


def decide(now: datetime, rules: dict[str, Any], *, posted_today: list[dict[str, Any]], last_posted_at: datetime | None,
           candidates: list[dict[str, Any]], logged_out: set[str]) -> tuple[dict[str, Any] | None, str]:
    """The next post the browser may publish now, or None and why."""
    if not rules["enabled"]:
        return None, "Auto-post is off (Settings → Auto-post)."
    local = now.astimezone(EAT)
    start = local.replace(hour=int(rules["hours"]["start"][:2]), minute=int(rules["hours"]["start"][3:]), second=0, microsecond=0)
    end = local.replace(hour=int(rules["hours"]["end"][:2]), minute=int(rules["hours"]["end"][3:]), second=0, microsecond=0)
    if not (start <= local <= end):
        return None, f"Outside posting hours ({rules['hours']['start']}–{rules['hours']['end']} EAT)."
    if len(posted_today) >= rules["daily_cap"]:
        return None, f"Today's cap of {rules['daily_cap']} posts is reached."
    if last_posted_at is not None:
        wait = timedelta(minutes=rules["min_gap_minutes"]) - (now - last_posted_at)
        if wait > timedelta(0):
            return None, f"Next post allowed in {int(wait.total_seconds() // 60) + 1} min (gap {rules['min_gap_minutes']} min)."
    per_platform: dict[str, int] = {}
    for p in posted_today:
        per_platform[p["platform"]] = per_platform.get(p["platform"], 0) + 1
    skipped: set[str] = set()
    for c in candidates:
        platform = c["platform"]
        if platform not in rules["platforms"]:
            skipped.add(f"{platform} not enabled")
            continue
        if platform in logged_out:
            skipped.add(f"{platform} needs a login")
            continue
        if per_platform.get(platform, 0) >= rules["platform_cap"]:
            skipped.add(f"{platform} reached {rules['platform_cap']} today")
            continue
        return c, ""
    return None, ("Nothing due" + (f" ({'; '.join(sorted(skipped))})" if skipped else "") + ".")


def next_for_poster(now: datetime | None = None, *, platform: str = "", post_id: str = "",
                    dry: bool = False) -> dict[str, Any]:
    """What the poster's browser should publish now, with its files and text.
    A dry run (which publishes nothing) takes the next queued post for the
    platform, or the named post, without the day's rules."""
    from ..infra.db import fetch_all, fetch_one
    from . import social

    now = now or datetime.now(timezone.utc)
    rules = poster_rules()
    if dry:
        chosen = fetch_one(
            """SELECT * FROM social_posts WHERE posted_at IS NULL
               AND (:id = '' OR post_id = :id) AND (:p = '' OR platform = :p)
               ORDER BY scheduled_for NULLS LAST LIMIT 1""", {"id": post_id, "p": platform})
        why = "" if chosen else "Nothing queued for that platform — download posts for scheduling first."
    else:
        day_start = now.astimezone(EAT).replace(hour=0, minute=0, second=0, microsecond=0)
        posted_today = fetch_all("SELECT platform FROM social_posts WHERE posted_at >= :d", {"d": day_start}) or []
        last = fetch_one("SELECT MAX(posted_at) AS t FROM social_posts WHERE posted_at IS NOT NULL") or {}
        candidates = fetch_all(
            """SELECT * FROM social_posts WHERE posted_at IS NULL AND status IN ('planned', 'failed')
               AND attempts < :tries AND scheduled_for IS NOT NULL AND scheduled_for <= :now
               ORDER BY scheduled_for, platform LIMIT 50""", {"tries": MAX_ATTEMPTS, "now": now}) or []
        logged_out = {r["platform"] for r in (fetch_all("SELECT platform FROM poster_state WHERE NOT logged_in") or [])}
        chosen, why = decide(now, rules, posted_today=posted_today, last_posted_at=last.get("t"),
                             candidates=candidates, logged_out=logged_out)
    if not chosen:
        return {"post": None, "reason": why, "rules": rules}
    st = social.status(chosen["question_id"])
    if st.get("status") != "ready":
        return {"post": None, "reason": f"The video for {chosen['question_id']} is not made yet.", "rules": rules}
    from .whiteboard import load

    q_text = social.display(load(chosen["question_id"]).get("question_text") or "")
    title = (f"{social.brand().get('hook') or 'Can you solve this?'} {q_text}")[:90].rstrip() + " #Shorts"
    return {"post": {"post_id": chosen["post_id"], "platform": chosen["platform"], "question_id": chosen["question_id"],
                     "video_url": st["url"], "thumbnail_url": st.get("thumbnail_url"), "caption": st.get("post") or "",
                     "title": title, "attempts": chosen.get("attempts") or 0}, "reason": "", "rules": rules}


def record_attempt(post_id: str, *, ok: bool, url: str = "", error: str = "", dry_run: bool = False) -> dict[str, Any]:
    from ..infra.db import execute

    if dry_run:
        execute("UPDATE social_posts SET last_error = :e, last_attempt_at = NOW(), updated_at = NOW() WHERE post_id = :id",
                {"id": post_id, "e": ("dry run ok" if ok else f"dry run: {error}")[:900]})
    elif ok:
        execute("""UPDATE social_posts SET status = 'posted', posted_at = COALESCE(posted_at, NOW()), url = COALESCE(NULLIF(:u, ''), url),
                   attempts = attempts + 1, last_error = '', last_attempt_at = NOW(), updated_at = NOW() WHERE post_id = :id""",
                {"id": post_id, "u": url})
    else:
        execute("""UPDATE social_posts SET status = CASE WHEN attempts + 1 >= :tries THEN 'gave_up' ELSE 'failed' END,
                   attempts = attempts + 1, last_error = :e, last_attempt_at = NOW(), updated_at = NOW() WHERE post_id = :id""",
                {"id": post_id, "e": error[:900], "tries": MAX_ATTEMPTS})
    return {"post_id": post_id, "ok": ok}


def set_login_state(platform: str, logged_in: bool, note: str = "") -> None:
    from ..infra.db import execute

    execute("""INSERT INTO poster_state (platform, logged_in, note, checked_at) VALUES (:p, :l, :n, NOW())
               ON CONFLICT (platform) DO UPDATE SET logged_in = EXCLUDED.logged_in, note = EXCLUDED.note, checked_at = NOW()""",
            {"p": platform, "l": logged_in, "n": note[:300]})


def poster_overview() -> dict[str, Any]:
    from ..infra.db import fetch_all

    now = datetime.now(timezone.utc)
    day_start = now.astimezone(EAT).replace(hour=0, minute=0, second=0, microsecond=0)
    states = fetch_all("SELECT platform, logged_in, note, checked_at FROM poster_state ORDER BY platform") or []
    today = fetch_all("SELECT platform, COUNT(*) AS n FROM social_posts WHERE posted_at >= :d GROUP BY platform", {"d": day_start}) or []
    queue = fetch_all(
        """SELECT post_id, platform, question_id, scheduled_for, status, attempts, last_error FROM social_posts
           WHERE posted_at IS NULL AND status IN ('planned', 'failed') ORDER BY scheduled_for NULLS LAST LIMIT 30""") or []
    recent = fetch_all(
        """SELECT post_id, platform, question_id, status, posted_at, url, last_error, last_attempt_at FROM social_posts
           WHERE last_attempt_at IS NOT NULL ORDER BY last_attempt_at DESC LIMIT 20""") or []
    for rows in (states, queue, recent):
        for r in rows:
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
    return {"rules": poster_rules(), "posted_today": {r["platform"]: int(r["n"]) for r in today},
            "states": states, "queue": queue, "recent": recent}


# ── a poster the server cannot reach (on the owner's Mac) ─────────────────────
#
# It asks instead of being told: it takes the console's commands from a queue,
# reports a heartbeat with its status, and uploads its screenshots here.

PULL_FRESH_SECONDS = 120


def heartbeat(poster_id: str, status: dict[str, Any]) -> None:
    from ..infra.db import execute, to_json

    execute("""INSERT INTO poster_heartbeat (poster_id, status, seen_at) VALUES (:id, CAST(:s AS jsonb), NOW())
               ON CONFLICT (poster_id) DO UPDATE SET status = EXCLUDED.status, seen_at = NOW()""",
            {"id": poster_id[:80], "s": to_json(status)})


def pull_poster() -> dict[str, Any] | None:
    """The most recent poster that checked in within the last two minutes."""
    from ..infra.db import fetch_one

    row = fetch_one(
        """SELECT poster_id, status, seen_at FROM poster_heartbeat
           WHERE seen_at > NOW() - make_interval(secs => :age) ORDER BY seen_at DESC LIMIT 1""",
        {"age": PULL_FRESH_SECONDS})
    if not row:
        return None
    status = dict(row.get("status") or {})
    return {**status, "online": True, "poster_id": row["poster_id"], "mode": status.get("mode") or "local",
            "seen_at": row["seen_at"].isoformat() if hasattr(row["seen_at"], "isoformat") else row["seen_at"]}


def queue_command(action: str, platform: str = "", post_id: str = "", by: str = "") -> int:
    from ..infra.db import fetch_one

    row = fetch_one("""INSERT INTO poster_commands (action, platform, post_id, created_by)
                       VALUES (:a, :p, :id, :by) RETURNING command_id""",
                    {"a": action, "p": platform, "id": post_id, "by": by})
    return int((row or {}).get("command_id") or 0)


def take_command() -> dict[str, Any] | None:
    """The oldest command nobody has taken; commands older than ten minutes
    are dropped — a "log in" pressed an hour ago is not what anyone wants now."""
    from ..infra.db import execute, fetch_one

    execute("""UPDATE poster_commands SET taken_at = NOW(), done_at = NOW(), result = '{"expired": true}'::jsonb
               WHERE taken_at IS NULL AND created_at < NOW() - INTERVAL '10 minutes'""")
    row = fetch_one(
        """UPDATE poster_commands SET taken_at = NOW() WHERE command_id = (
               SELECT command_id FROM poster_commands WHERE taken_at IS NULL ORDER BY created_at
               LIMIT 1 FOR UPDATE SKIP LOCKED)
           RETURNING command_id, action, platform, post_id""")
    return dict(row) if row else None


def finish_command(command_id: int, result: dict[str, Any]) -> None:
    from ..infra.db import execute, to_json

    execute("UPDATE poster_commands SET done_at = NOW(), result = CAST(:r AS jsonb) WHERE command_id = :id",
            {"id": command_id, "r": to_json(result)})


def command_result(command_id: int) -> dict[str, Any] | None:
    from ..infra.db import fetch_one

    row = fetch_one("SELECT done_at, result FROM poster_commands WHERE command_id = :id", {"id": command_id})
    return dict(row["result"] or {}) if row and row.get("done_at") else None
