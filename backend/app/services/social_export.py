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
    """Platforms and topics side by side, on what posted so far (a post the
    platform will publish later is still planned)."""
    now = datetime.now(timezone.utc)

    def out(r: dict[str, Any]) -> bool:
        t = r.get("posted_at")
        if not t:
            return False
        try:
            return (datetime.fromisoformat(t) if isinstance(t, str) else t) <= now
        except ValueError:
            return True

    def roll(rows: list[dict[str, Any]]) -> dict[str, Any]:
        live = [r for r in rows if out(r)]
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
    live = sorted((r for r in posts if out(r)), key=lambda r: -int(r.get("views") or 0))
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
AHEAD_CAPABLE = ("facebook",)          # platforms whose scheduler the poster can fill in
MAX_GROUPS_PER_POST = 5               # the owner's ceiling; Facebook itself allows 9
AHEAD_LEAD = timedelta(minutes=30)     # closer than this, a post just goes out live
GROUP_PLATFORMS = ("facebook",)
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
    def zero_ok(key: str, default: int, top: int) -> int:      # 0 is a real answer here
        raw = ps.get(key, default)
        try:
            return max(0, min(int(default if raw is None or raw == "" else raw), top))
        except (TypeError, ValueError):
            return default

    ahead_raw = ps.get("poster_ahead_platforms", None)
    ahead_raw = ["facebook"] if ahead_raw is None else ahead_raw
    ahead = [p.strip().lower() for p in (ahead_raw if isinstance(ahead_raw, list) else str(ahead_raw).split(",")) if p.strip()]
    return {"enabled": bool(ps.get("poster_enabled", False)),
            "ahead_platforms": [p for p in ahead if p in AHEAD_CAPABLE],
            "ahead_days": max(1, min(num("poster_ahead_days", 28, 29), 29)),
            "group_shares_per_day": zero_ok("poster_group_shares_per_day", 2, 6),
            "group_rest_days": max(1, num("poster_group_rest_days", 7, 60)),
            "groups_per_post": max(1, num("poster_groups_per_post", 5, MAX_GROUPS_PER_POST)),
            "daily_cap": num("poster_daily_cap", 30, HARD_DAILY_CAP),
            "platform_cap": num("poster_platform_cap", 16, HARD_DAILY_CAP),
            "videos_per_day": num("poster_videos_per_day", 8, HARD_DAILY_CAP),
            "photos_per_day": num("poster_photos_per_day", 8, HARD_DAILY_CAP),
            "live_per_day": zero_ok("poster_live_per_day", 0, HARD_DAILY_CAP),
            "min_gap_minutes": num("poster_min_gap_minutes", 20, 24 * 60),
            "hours": {"start": f"{start[0]:02d}:{start[1]:02d}", "end": f"{end[0]:02d}:{end[1]:02d}"},
            "platforms": [p for p in platforms if p in PLATFORMS]}


def decide(now: datetime, rules: dict[str, Any], *, posted_today: list[dict[str, Any]], last_posted_at: datetime | None,
           candidates: list[dict[str, Any]], logged_out: set[str],
           live_today: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any] | None, str]:
    """The next post the browser may publish now, or None and why.
    `posted_today`: the day's actions (the daily cap and the gap count them);
    `live_today`: what goes out on each platform today (the platform cap).
    Uploads ahead leave room in the day for its live group shares."""
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
    per_format: dict[tuple[str, str], int] = {}
    for p in (posted_today if live_today is None else live_today):
        per_platform[p["platform"]] = per_platform.get(p["platform"], 0) + 1
        key = (p["platform"], str(p.get("format") or "video"))
        per_format[key] = per_format.get(key, 0) + 1
    room_ahead = len(posted_today) < rules["daily_cap"] - int(rules.get("group_shares_per_day") or 0)
    skipped: set[str] = set()
    for c in candidates:
        platform = c["platform"]
        if platform not in rules["platforms"]:
            skipped.add(f"{platform} not enabled")
            continue
        if platform in logged_out:
            skipped.add(f"{platform} needs a login")
            continue
        if c.get("ahead") and not room_ahead:
            skipped.add("uploads ahead wait — the rest of today is kept for its live posts")
            continue
        if not c.get("ahead") and per_platform.get(platform, 0) >= rules["platform_cap"]:
            skipped.add(f"{platform} reached {rules['platform_cap']} today")
            continue
        fmt = str(c.get("format") or "video")
        cap = rules.get("photos_per_day" if fmt == "photo" else "videos_per_day")
        if not c.get("ahead") and cap is not None and per_format.get((platform, fmt), 0) >= int(cap):
            skipped.add(f"{platform} reached {cap} {fmt}s today")
            continue
        return c, ""
    return None, ("Nothing due" + (f" ({'; '.join(sorted(skipped))})" if skipped else "") + ".")


def _failed_long_ago(st: dict[str, Any]) -> bool:
    """A video that failed over an hour ago (a Mac that went away, a worker cut
    off): made again, rather than holding its booking up for ever."""
    from ..infra.db import fetch_one

    if st.get("status") != "failed" or not st.get("job_id"):
        return False
    row = fetch_one("SELECT COALESCE(finished_at, created_at) AS t FROM jobs WHERE job_id = :id", {"id": st["job_id"]}) or {}
    t = row.get("t")
    return isinstance(t, datetime) and datetime.now(timezone.utc) - t > timedelta(hours=1)


def schedule_next(now: datetime | None = None, *, book_if_empty: bool = True) -> dict[str, Any]:
    """"Schedule now": the next booked video to hand to Facebook's own
    scheduler at once — the soonest inside its window, its video made — with
    no wait between hand-overs, while today's limit has room."""
    from ..infra.db import fetch_all, fetch_one
    from . import social

    now = now or datetime.now(timezone.utc)
    rules = poster_rules()
    day_start = now.astimezone(EAT).replace(hour=0, minute=0, second=0, microsecond=0)
    done = int((fetch_one("SELECT COUNT(*) AS n FROM social_posts WHERE handed_at >= :d", {"d": day_start}) or {}).get("n") or 0)
    if done >= rules["daily_cap"]:
        return {"post": None, "reason": f"Today's limit of {rules['daily_cap']} is used — more tomorrow (or raise it in Settings → Auto-post)."}
    rows = fetch_all(
        """SELECT * FROM social_posts WHERE platform = 'facebook' AND COALESCE(format, 'video') = 'video'
           AND posted_at IS NULL AND handed_at IS NULL AND status IN ('planned', 'failed') AND attempts < :tries
           AND groups = '[]'::jsonb AND scheduled_for > :soon AND scheduled_for <= :until
           ORDER BY scheduled_for LIMIT 600""",
        {"tries": MAX_ATTEMPTS, "soon": now + AHEAD_LEAD, "until": now + timedelta(days=rules["ahead_days"])}) or []
    if not rows and book_if_empty:
        # A manual "Schedule now" with nothing booked inside the window: book
        # the window first (the Auto-book subjects), then hand them over.
        try:
            auto_book(now=now, force=True, days=rules["ahead_days"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Booking for Schedule now failed: %s", exc)
        return schedule_next(now, book_if_empty=False)
    # Every booking in the window is looked at, soonest first: the soonest are
    # often waiting for their videos to be made again, and a ready one may
    # sit behind them. Those not made are queued, the soonest 20 a press.
    waiting = queued = 0
    for row in rows:
        st = _media(row)
        if st.get("status") != "ready":
            if (st.get("status") == "none" or _failed_long_ago(st)) and queued < 20:
                try:
                    social.enqueue(row["question_id"], queued_by="schedule-now")
                    queued += 1
                except Exception:  # noqa: BLE001
                    pass
            waiting += 1
            continue
        from .whiteboard import load

        q_text = social.display(load(row["question_id"]).get("question_text") or "")
        title = (f"{social.brand().get('hook') or 'Can you solve this?'} {q_text}")[:90].rstrip() + " #Shorts"
        try:
            from ..infra.db import execute

            execute("UPDATE social_posts SET teacher = :t, marketing = :m WHERE post_id = :id",
                    {"t": str(st.get("teacher") or ""), "m": bool(st.get("marketing")), "id": row["post_id"]})
        except Exception:  # noqa: BLE001
            pass
        return {"post": {"post_id": row["post_id"], "platform": "facebook", "question_id": row["question_id"],
                         "format": "video", "step": row.get("step") or "walkthrough", "video_url": st["url"],
                         "image_url": "", "thumbnail_url": st.get("thumbnail_url"), "caption": _caption(st),
                         "title": title, "attempts": row.get("attempts") or 0,
                         "schedule_at": row["scheduled_for"].astimezone(EAT).isoformat(), "groups": []},
                "reason": "", "left_today": rules["daily_cap"] - done}
    why = (f"None of the {waiting} booked reel(s) in Facebook's window has its current video yet (videos made before "
           f"the marketing are made again) — {queued} more queued now; they go as each is ready." if waiting
           else "Nothing to schedule: no unposted questions left in the Auto-book subjects — add a subject or more questions.")
    return {"post": None, "reason": why}


def next_for_poster(now: datetime | None = None, *, platform: str = "", post_id: str = "",
                    dry: bool = False, share: str = "", groups: list[str] | None = None) -> dict[str, Any]:
    """What the poster's browser should publish now, with its files and text.
    A dry run (which publishes nothing) takes the next queued post for the
    platform, or the named post, without the day's rules — never one already
    handed to a platform's scheduler. "Post next now" uses it too.

    `share` (with `dry`) is a post-now button: "feed" — the feed only;
    "groups" — the feed and the next groups in turn, or the `groups` the
    owner picked. Either way it goes out live, now."""
    from ..infra.db import execute, fetch_all, fetch_one
    from . import social

    now = now or datetime.now(timezone.utc)
    rules = poster_rules()
    if dry and share and not post_id and platform in ("", "facebook"):
        # A post-now button: a new question — a finished video no post has
        # used — so the calendar keeps its bookings and nothing repeats.
        fresh, fresh_st = fresh_video(now, "facebook", created_by=POST_NOW)
        if fresh:
            post_id, platform = fresh["post_id"], "facebook"
    if dry:
        rows = fetch_all(
            """SELECT * FROM social_posts WHERE posted_at IS NULL AND handed_at IS NULL
               AND (:id = '' OR post_id = :id) AND (:p = '' OR platform = :p)
               ORDER BY scheduled_for NULLS LAST LIMIT 400""", {"id": post_id, "p": platform}) or []
        chosen, st = None, {}
        remade = 0
        for row in rows:                  # the first whose video (or card) is made, the soonest booked first
            st = _media(row)
            if st.get("status") == "ready":
                chosen = row
                break
            if st.get("status") == "none" and remade < 3 and str(row.get("format") or "video") == "video":
                # Out of date (made before the marketing, say): made again, so a later press finds it.
                try:
                    social.enqueue(row["question_id"], queued_by="post-now")
                    remade += 1
                except Exception:  # noqa: BLE001
                    pass
        rendering = 0
        if not chosen and not rows:
            try:
                rendering = int((fetch_one("""SELECT COUNT(*) AS n FROM jobs WHERE kind = 'social'
                                              AND status IN ('queued', 'running')""") or {}).get("n") or 0)
            except Exception:  # noqa: BLE001
                rendering = 0
        making = ""
        if not chosen and not rows and not rendering and share:
            # Nothing ready and nothing being made: one made now, on the standby worker.
            try:
                from . import video_factory

                # Queued, not dispatched: a Mac helper takes the most urgent video
                # within half a minute, and the sweep hands it to a worker if not.
                qid = video_factory.next_for_post_now()
                if qid and social.enqueue(qid, queued_by="post-now", on_demand=True,
                                          dispatch=False).get("status") in ("queued", "running"):
                    making = qid
            except Exception as exc:  # noqa: BLE001
                logger.info("Could not make a video for Post now: %s", exc)
        why = ("" if chosen else
               (f"Every finished video has been posted — {rendering} more are being made; Post now works again as each is ready."
                if rendering else
                "No finished video to post, so one is being made now — press Post now again in about 5 minutes."
                if making else "Every finished video has been posted and none are being made — book or make more videos.")
               if not rows else "The booked posts' videos are still being made — try again shortly.")
    else:
        if rules["ahead_platforms"] and not scheduler_trust(now)["trusted"]:
            # Facebook's scheduler has been losing reels: they go out live at their times instead.
            rules = {**rules, "ahead_platforms": []}
        day_start = now.astimezone(EAT).replace(hour=0, minute=0, second=0, microsecond=0)
        # The day's actions — a post going out live, or a video handed to a
        # platform's scheduler — are what the caps and the gap count.
        posted_today = fetch_all("SELECT platform, format FROM social_posts WHERE handed_at >= :d", {"d": day_start}) or []
        live_today = fetch_all("""SELECT platform, format FROM social_posts WHERE posted_at >= :d AND posted_at < :e""",
                               {"d": day_start, "e": day_start + timedelta(days=1)}) or []
        last = fetch_one("SELECT MAX(handed_at) AS t FROM social_posts WHERE handed_at IS NOT NULL") or {}
        rows = fetch_all(
            """SELECT * FROM social_posts WHERE posted_at IS NULL AND handed_at IS NULL AND status IN ('planned', 'failed')
               AND attempts < :tries AND scheduled_for IS NOT NULL AND scheduled_for <= :until
               ORDER BY scheduled_for, platform LIMIT 300""",
            {"tries": MAX_ATTEMPTS, "until": now + timedelta(days=rules["ahead_days"])}) or []
        candidates = work_order(now, rules, rows)
        logged_out = {r["platform"] for r in (fetch_all("SELECT platform FROM poster_state WHERE NOT logged_in") or [])}
        waiting = 0
        for _ in range(120):
            chosen, why = decide(now, rules, posted_today=posted_today, last_posted_at=last.get("t"),
                                 candidates=candidates, logged_out=logged_out, live_today=live_today)
            if not chosen:
                break
            drop = False
            if chosen.get("ahead"):
                # Facebook will not schedule a reel that is also shared to a
                # group: a post picked for a group share is kept back to go
                # out live at its time, and handed to no scheduler.
                if chosen.get("groups") or reserve_group(chosen, rules):
                    drop = True
            if not drop:
                st = _media(chosen)
                if st.get("status") == "ready":
                    break
                if st.get("status") == "none":
                    # Its video or card is out of date (the item or the board
                    # changed since it was made) or was never made: make it
                    # now, so the post goes out on a later look, not never.
                    try:
                        if str(chosen.get("format") or "video") == "photo":
                            from . import social_cards

                            social_cards.enqueue(chosen["question_id"], queued_by="poster")
                        else:
                            social.enqueue(chosen["question_id"], queued_by="poster")
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Could not queue the media for %s: %s", chosen["question_id"], exc)
                waiting += 1
            candidates = [c for c in candidates if c["post_id"] != chosen["post_id"]]
            chosen = None
        if not chosen and waiting:
            why = f"{waiting} due post(s) are waiting for their videos or cards to be made."
    if not chosen and not dry and not share:
        chosen, st = live_extra(now, rules)
    if not chosen:
        return {"post": None, "reason": why, "rules": rules}
    from .whiteboard import load

    q_text = social.display(load(chosen["question_id"]).get("question_text") or "")
    title = (f"{social.brand().get('hook') or 'Can you solve this?'} {q_text}")[:90].rstrip() + " #Shorts"
    when = chosen.get("scheduled_for")
    reserved = [str(g) for g in (chosen.get("groups") or [])]
    ahead = (not share and not reserved and chosen["platform"] in rules["ahead_platforms"] and isinstance(when, datetime)
             and when - now > AHEAD_LEAD and when - now <= timedelta(days=rules["ahead_days"]))
    if share == "feed":
        to_groups: list[str] = []
    elif share == "groups":
        to_groups = (picked_groups(chosen["platform"], groups) if groups
                     else group_rotation(chosen["platform"], now, rules))
        if not to_groups:
            return {"post": None, "rules": rules, "reason": (
                "None of the picked groups is one the poster found — press \"Read my groups from Facebook\"."
                if groups else "No group is free for a share: tick more groups, or wait for one to rest "
                f"({rules['group_rest_days']} days between shares to a group).")}
    else:
        to_groups = [] if ahead else (reserved or groups_for(chosen["platform"], now, rules))
    photo = str(chosen.get("format") or "video") == "photo"
    if photo:
        ahead, to_groups = False, []            # a card goes out live, to the feed
    if not photo:
        try:                                    # remember which teacher this video has
            execute("UPDATE social_posts SET teacher = :t, marketing = :m WHERE post_id = :id",
                    {"t": str(st.get("teacher") or ""), "m": bool(st.get("marketing")), "id": chosen["post_id"]})
        except Exception:  # noqa: BLE001
            pass
    return {"post": {"post_id": chosen["post_id"], "platform": chosen["platform"], "question_id": chosen["question_id"],
                     "format": "photo" if photo else "video", "step": chosen.get("step") or "walkthrough",
                     "video_url": "" if photo else st["url"], "image_url": st.get("url") if photo else "",
                     "thumbnail_url": None if photo else st.get("thumbnail_url"),
                     "caption": st.get("post") or "" if photo else _caption(st),
                     "title": title, "attempts": chosen.get("attempts") or 0,
                     "schedule_at": when.astimezone(EAT).isoformat() if ahead else "",
                     "groups": to_groups}, "reason": "", "rules": rules}


def comment_rules() -> dict[str, Any]:
    from . import platform_settings as ps

    try:
        delay = max(0, min(int(ps.get("poster_answer_delay_seconds", 60) or 60), 24 * 3600))
    except (TypeError, ValueError):
        delay = 60
    return {"enabled": bool(ps.get("poster_comment_thread", False)), "delay": delay}


def _caption(st: dict[str, Any]) -> str:
    """The post's text: the question alone when the rest goes in comments."""
    if comment_rules()["enabled"] and (st.get("thread") or {}).get("caption"):
        return st["thread"]["caption"]
    return st.get("post") or ""


def _media(row: dict[str, Any]) -> dict[str, Any]:
    """What a booked post shows, if it is made: the walkthrough video (with
    its post text), or the step's photo card (with its caption)."""
    from . import social

    if str(row.get("format") or "video") != "photo":
        return social.status(row["question_id"])
    from . import social_cards
    from .whiteboard import load

    q = load(row["question_id"])
    st = social_cards.status(row["question_id"], str(row.get("step") or "question"), q)
    if st.get("status") == "ready":
        st["post"] = social_cards.caption(q, str(row.get("step") or "question"))
    return st


def reserve_group(post: dict[str, Any], rules: dict[str, Any]) -> list[str]:
    """If this booked post should carry one of the day's group shares, write
    the group on it now (and rest the group from its time), so it goes out
    live with the share — and the day's other posts know the share is taken."""
    from ..infra.db import execute, to_json

    when = post.get("scheduled_for")
    if not isinstance(when, datetime):
        return []
    groups = groups_for(post["platform"], when, rules)
    if groups:
        execute("UPDATE social_posts SET groups = CAST(:g AS jsonb), updated_at = NOW() WHERE post_id = :id",
                {"id": post["post_id"], "g": to_json(groups)})
        for g in groups:
            execute("""UPDATE poster_groups SET last_shared_for = GREATEST(COALESCE(last_shared_for, :t), :t)
                       WHERE platform = :p AND name = :n""", {"p": post["platform"], "n": g, "t": when})
    return groups


def work_order(now: datetime, rules: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Posts due now first (they go out live), then posts to hand to a
    platform's scheduler ahead of time, soonest first. Pure."""
    due, ahead = [], []
    for r in rows:
        when = r.get("scheduled_for")
        if not isinstance(when, datetime):
            continue
        if when <= now:
            due.append(r)
        elif (str(r.get("format") or "video") == "video" and r["platform"] in rules["ahead_platforms"]
              and when - now > AHEAD_LEAD
              and when - now <= timedelta(days=rules["ahead_days"])):
            ahead.append({**r, "ahead": True})
    return due + ahead


def groups_for(platform: str, at: datetime, rules: dict[str, Any]) -> list[str]:
    """The groups (if any) this post is also shared to: `group_shares_per_day`
    posts a day carry a share — with two, one before 13:00 and one after —
    each to the next `groups_per_post` groups in turn (see `group_rotation`)."""
    from ..infra.db import fetch_all

    per_day = rules.get("group_shares_per_day", 0)
    if platform not in GROUP_PLATFORMS or per_day <= 0:
        return []
    local = at.astimezone(EAT)
    d0 = local.replace(hour=0, minute=0, second=0, microsecond=0)
    shared = fetch_all(           # shared already, or kept back for a share
        """SELECT COALESCE(posted_at, scheduled_for) AS t FROM social_posts WHERE platform = :p
           AND groups <> '[]'::jsonb AND status <> 'gave_up' AND COALESCE(posted_at, scheduled_for) >= :d0
           AND COALESCE(posted_at, scheduled_for) < :d1""",
        {"p": platform, "d0": d0, "d1": d0 + timedelta(days=1)}) or []
    if len(shared) >= per_day:
        return []
    if per_day == 2 and any((r["t"].astimezone(EAT).hour < 13) == (local.hour < 13) for r in shared if r.get("t")):
        return []                       # this half of the day has its share
    return group_rotation(platform, at, rules)


def group_rotation(platform: str, at: datetime, rules: dict[str, Any], *, limit: int = 0) -> list[str]:
    """The next groups in turn: the ticked groups rested longest (never
    shared first), `groups_per_post` of them, none shared within
    `group_rest_days`. Shares walk through every ticked group before any
    gets a second one, because each share marks its groups as just used."""
    from ..infra.db import fetch_all

    if platform not in GROUP_PLATFORMS:
        return []
    n = max(1, min(limit or rules.get("groups_per_post", MAX_GROUPS_PER_POST), MAX_GROUPS_PER_POST))
    rest = timedelta(days=rules.get("group_rest_days", 7))
    rows = fetch_all(
        """SELECT name FROM poster_groups WHERE platform = :p AND enabled
           AND (last_shared_for IS NULL OR last_shared_for <= :cut OR last_shared_for >= :after)
           ORDER BY last_shared_for NULLS FIRST, name LIMIT :n""",
        {"p": platform, "cut": at - rest, "after": at + rest, "n": n}) or []
    return [r["name"] for r in rows]


def picked_groups(platform: str, names: list[str]) -> list[str]:
    """Groups the owner picked by hand for one post: only groups the poster
    found on the platform, in the order picked, at most MAX_GROUPS_PER_POST.
    A hand pick may use a group that is not ticked for the rotation."""
    from ..infra.db import fetch_all

    wanted = [str(n).strip() for n in names if str(n).strip()]
    if platform not in GROUP_PLATFORMS or not wanted:
        return []
    known = {r["name"] for r in (fetch_all("SELECT name FROM poster_groups WHERE platform = :p AND name = ANY(:n)",
                                           {"p": platform, "n": wanted}) or [])}
    return [n for n in dict.fromkeys(wanted) if n in known][:MAX_GROUPS_PER_POST]


def record_attempt(post_id: str, *, ok: bool, url: str = "", error: str = "", dry_run: bool = False,
                   scheduled: bool = False, groups: list[str] | None = None,
                   destinations: list[str] | None = None) -> dict[str, Any]:
    """How a try went. `scheduled`: handed to the platform's scheduler — it
    goes out at its booked time, which becomes its posted time."""
    from ..infra.db import execute, fetch_one, to_json

    groups = [str(g)[:200] for g in (groups or [])][:9]
    places = [d for d in dict.fromkeys(str(x).lower() for x in (destinations or [])) if d in ("reel", "feed", "story", "post")]
    if dry_run:
        execute("UPDATE social_posts SET last_error = :e, last_attempt_at = NOW(), updated_at = NOW() WHERE post_id = :id",
                {"id": post_id, "e": ("dry run ok" if ok else f"dry run: {error}")[:900]})
    elif ok:
        execute(f"""UPDATE social_posts SET status = :st,
                   posted_at = {"COALESCE(scheduled_for, NOW())" if scheduled else "COALESCE(posted_at, NOW())"},
                   handed_at = NOW(), platform_scheduled = :sch, groups = CAST(:g AS jsonb),
                   destinations = CAST(:d AS jsonb),
                   url = COALESCE(NULLIF(:u, ''), url), attempts = attempts + 1, last_error = '',
                   last_attempt_at = NOW(), updated_at = NOW() WHERE post_id = :id""",
                {"id": post_id, "u": url, "st": "scheduled" if scheduled else "posted", "sch": scheduled,
                 "g": to_json(groups), "d": to_json(places)})
        if comment_rules()["enabled"]:
            # The comments follow once the post is out: now, or at its scheduled time.
            # A few minutes after it is out: a reel takes a while to show on the profile.
            execute("""UPDATE social_posts SET comments_state = 'pending', comments_next_at = posted_at + INTERVAL '3 minutes',
                       comments_attempts = 0, comments_error = ''
                       WHERE post_id = :id AND COALESCE(format, 'video') = 'video' AND comments_state = ''""",
                    {"id": post_id})
        if groups:
            row = fetch_one("SELECT platform, posted_at FROM social_posts WHERE post_id = :id", {"id": post_id}) or {}
            for g in groups:
                execute("""INSERT INTO poster_groups (platform, name, enabled, last_shared_for) VALUES (:p, :n, TRUE, :t)
                           ON CONFLICT (platform, name) DO UPDATE SET last_shared_for = GREATEST(
                               COALESCE(poster_groups.last_shared_for, EXCLUDED.last_shared_for), EXCLUDED.last_shared_for)""",
                        {"p": row.get("platform") or "facebook", "n": g, "t": row.get("posted_at")})
        _free_space_after_post()
    elif UNCONFIRMED_SCHEDULE.search(error or "") and fetch_one(
            "SELECT 1 AS x FROM social_posts WHERE post_id = :id AND scheduled_for > NOW()", {"id": post_id}):
        # Facebook may have scheduled it though it never said so: handing it
        # over again could put it out twice. It is taken as scheduled, and at
        # its time the profile is looked at (the first comment finds it): found,
        # it is confirmed; not there two hours on, it goes out live.
        execute("""UPDATE social_posts SET status = 'scheduled', posted_at = scheduled_for, handed_at = NOW(),
                   platform_scheduled = TRUE, attempts = attempts + 1, last_attempt_at = NOW(), updated_at = NOW(),
                   last_error = :e, comments_state = 'pending', comments_next_at = scheduled_for + INTERVAL '3 minutes',
                   comments_attempts = 0, comments_error = '' WHERE post_id = :id""",
                {"id": post_id, "e": "Facebook did not confirm the schedule — the profile is checked at its time; "
                                     "if the reel is not there, it goes out live."})
        return {"post_id": post_id, "ok": False, "scheduled": True, "unconfirmed": True}
    else:
        execute("""UPDATE social_posts SET status = CASE WHEN attempts + 1 >= :tries THEN 'gave_up' ELSE 'failed' END,
                   attempts = attempts + 1, last_error = :e, last_attempt_at = NOW(), updated_at = NOW() WHERE post_id = :id""",
                {"id": post_id, "e": error[:900], "tries": MAX_ATTEMPTS})
    return {"post_id": post_id, "ok": ok, "scheduled": scheduled, "groups": groups, "destinations": places}


def _free_space_after_post() -> None:
    """A post went out: the move job runs now, so a video posted on every
    platform it was planned for leaves the server for Drive straight away."""
    try:
        from . import drive_store

        drive_store.enqueue(queued_by="posted")
    except Exception:  # noqa: BLE001
        pass


# ── Facebook's scheduler, checked ────────────────────────────────────────────
#
# A reel handed to Facebook's scheduler is only taken to be out once the
# poster finds it on the profile (its first comment does). Not there two
# hours after its time, it was lost: it goes out live. When the scheduler
# loses reels and confirms none, posts stop being handed to it and go out
# live at their booked times, until it confirms one again.

UNCONFIRMED_SCHEDULE = re.compile(r"did not confirm the scheduled", re.I)
CONFIRM_WITHIN = timedelta(hours=2)
SCHEDULER_MISSED = "scheduler-missed"
SCHEDULER_CONFIRMED = "scheduler-confirmed"
SCHEDULER_UNVERIFIED = "scheduler-unverified"
LIVE_IF_LOST_WITHIN = timedelta(hours=12)     # older than this, a reel not found is not sent out again
FINDABLE_FOR = timedelta(days=2)              # a post without its link is searched for on the profile this long
SEARCH_COOLDOWN = timedelta(minutes=8)


def _searched_in_vain(now: datetime) -> bool:
    """A profile search failed a moment ago: the next turn goes to posts with links (the campaign)."""
    from ..infra.db import fetch_one

    row = fetch_one("""SELECT MAX(updated_at) AS t FROM social_posts WHERE url = ''
                       AND comments_error ILIKE 'Could not find the post%'""") or {}
    t = row.get("t")
    return isinstance(t, datetime) and now - t < SEARCH_COOLDOWN


def _give_up_unfindable(now: datetime) -> int:
    """Posts without their link, out longer than FINDABLE_FOR, whose thread
    never started: too far down the profile to find by scrolling."""
    from ..infra.db import fetch_one

    row = fetch_one("""WITH up AS (
                         UPDATE social_posts SET comments_state = 'failed',
                                comments_error = 'Too far down the profile to find without its link.'
                         WHERE comments_state = 'pending' AND url = '' AND posted_at < :old
                         RETURNING 1)
                       SELECT COUNT(*) AS n FROM up""", {"old": now - FINDABLE_FOR}) or {}
    return int(row.get("n") or 0)


def _not_on_profile(error: str) -> bool:
    return bool(re.search(r"could not find the post|not out yet|not on the profile", error or "", re.I))


def _awaiting_schedule(post_id: str) -> bool:
    from ..infra.db import fetch_one

    return bool(fetch_one("""SELECT 1 AS x FROM social_posts WHERE post_id = :id AND platform_scheduled
                             AND status = 'scheduled' AND url = ''""", {"id": post_id}))


def _scheduled_not_found(post_id: str, error: str, now: datetime) -> None:
    """A scheduled reel not on the profile: looked for again every half hour,
    and two hours after its time sent out live (booked for now)."""
    from ..infra.db import execute, fetch_one

    row = fetch_one("SELECT posted_at FROM social_posts WHERE post_id = :id", {"id": post_id}) or {}
    due = row.get("posted_at")
    if isinstance(due, datetime) and now - due > LIVE_IF_LOST_WITHIN:
        # Its time was long ago: too far down the profile to be sure it is not
        # there. Never sent out again (it could go out twice): marked unverified.
        execute("""UPDATE social_posts SET comments_state = 'failed', comments_error = :e, notes = :n, updated_at = NOW()
                   WHERE post_id = :id""",
                {"id": post_id, "n": SCHEDULER_UNVERIFIED,
                 "e": "Not found on the profile, and its time was too long ago to be sure; check Meta Business Suite."})
        return
    if isinstance(due, datetime) and now - due < CONFIRM_WITHIN:
        # Not counted as a failed try: it is looked for until the two hours are up.
        execute("""UPDATE social_posts SET comments_error = :e, comments_next_at = :next, updated_at = NOW()
                   WHERE post_id = :id""", {"id": post_id, "e": error[:900], "next": now + timedelta(minutes=30)})
        return
    execute("""UPDATE social_posts SET status = 'planned', posted_at = NULL, handed_at = NULL, platform_scheduled = FALSE,
               scheduled_for = :now, attempts = 0, notes = :n, comments_state = '', comments_attempts = 0,
               comments_next_at = NULL, comments_error = '', updated_at = NOW(), last_error = :e
               WHERE post_id = :id""",
            {"id": post_id, "now": now, "n": SCHEDULER_MISSED,
             "e": "Facebook's scheduler did not publish it (not on the profile two hours after its time) — it goes out live."})
    logger.warning("Scheduled reel %s was not on the profile two hours after its time; it goes out live.", post_id)


def recheck_scheduled(now: datetime | None = None) -> int:
    """Scheduled reels whose time has come and that nobody found yet — their
    comments given up on before this check existed — are looked for again."""
    from ..infra.db import fetch_one

    now = now or datetime.now(timezone.utc)
    row = fetch_one("""WITH up AS (
                         UPDATE social_posts SET comments_state = 'pending', comments_attempts = 0, comments_next_at = :now
                         WHERE platform_scheduled AND status = 'scheduled' AND url = '' AND posted_at <= :ripe
                           AND posted_at >= :recent
                           AND COALESCE(format, 'video') = 'video' AND platform = 'facebook'
                           AND comments_state IN ('', 'failed')
                         RETURNING 1)
                       SELECT COUNT(*) AS n FROM up""", {"now": now, "ripe": now - timedelta(minutes=5),
                                                 "recent": now - LIVE_IF_LOST_WITHIN}) or {}
    return int(row.get("n") or 0)


def _scheduler_overview(now: datetime) -> dict[str, Any]:
    """For the console: the trust, and the scheduled reels past their time not found yet."""
    from ..infra.db import fetch_one

    try:
        out = scheduler_trust(now)
        row = fetch_one("""SELECT COUNT(*) AS n FROM social_posts WHERE platform_scheduled AND status = 'scheduled'
                           AND url = '' AND posted_at <= :now""", {"now": now}) or {}
        return {**out, "unconfirmed": int(row.get("n") or 0)}
    except Exception:  # noqa: BLE001
        return {"trusted": True, "missed": 0, "confirmed": 0, "unconfirmed": 0, "note": ""}


def scheduler_trust(now: datetime | None = None) -> dict[str, Any]:
    """Is Facebook's scheduler publishing what it is handed? The last four
    days: lost reels against confirmed ones."""
    from ..infra.db import fetch_one

    now = now or datetime.now(timezone.utc)
    row = fetch_one("""SELECT COUNT(*) FILTER (WHERE notes = :m) AS missed,
                             COUNT(*) FILTER (WHERE notes = :c) AS confirmed
                      FROM social_posts WHERE updated_at >= :since""",
                    {"m": SCHEDULER_MISSED, "c": SCHEDULER_CONFIRMED, "since": now - timedelta(days=4)}) or {}
    missed, confirmed = int(row.get("missed") or 0), int(row.get("confirmed") or 0)
    trusted = not (missed >= 2 and confirmed == 0)
    return {"trusted": trusted, "missed": missed, "confirmed": confirmed,
            "note": "" if trusted else (f"Facebook's scheduler lost {missed} reel(s) in four days and published none the "
                                        "poster could find — posts go out live at their booked times instead.")}


def post_question(question_id: str, *, platform: str = "facebook", now: datetime | None = None) -> dict[str, Any]:
    """One question, picked in the console, booked for now so Post now can
    take it. Refused when it is already out or waiting in Facebook's
    scheduler (it would go out twice); its video is made first if need be."""
    from ..infra.db import execute, fetch_one
    from . import social
    from .whiteboard import load

    now = now or datetime.now(timezone.utc)
    q = load(question_id)
    pid = _post_id(question_id, platform)
    post = fetch_one("SELECT * FROM social_posts WHERE post_id = :id", {"id": pid})
    if post and post.get("handed_at") is not None:
        when = post.get("posted_at")
        at = when.astimezone(EAT).strftime("%d %b %H:%M") if isinstance(when, datetime) else ""
        if post.get("platform_scheduled") and isinstance(when, datetime) and when > now:
            return {"ok": False, "post_id": pid, "error": f"It is already scheduled on Facebook for {at}."}
        if post.get("platform_scheduled") and not post.get("url"):
            return {"ok": False, "post_id": pid, "error": f"It was handed to Facebook's scheduler for {at}; the poster is "
                                                          "checking the profile for it, and posts it live if it is not there."}
        link = f" — {post['url']}" if post.get("url") else ""
        return {"ok": False, "post_id": pid, "error": f"It was posted already ({at}){link}."}
    if post:
        execute("""UPDATE social_posts SET scheduled_for = :now, status = 'planned', attempts = 0, updated_at = NOW()
                   WHERE post_id = :id""", {"id": pid, "now": now})
    else:
        _plan_post(q, platform, now, POST_NOW)
    st = social.status(question_id)
    if st.get("status") != "ready":
        if st.get("status") not in ("queued", "running"):
            social.enqueue(question_id, queued_by=POST_NOW, on_demand=True, dispatch=False)
        return {"ok": False, "post_id": pid, "making": True,
                "error": "Its video is being made now — press Post again in about five minutes."}
    return {"ok": True, "post_id": pid}


# ── reconciling: every post found on the profile, matched to its booking ─────
#
# Posts without their link (a reel handed to Facebook's scheduler, one whose
# first comment never found it) cannot be commented on, measured or
# campaigned. Every few hours the poster scrolls the profile once, deep, and
# sends each post it sees — its link and its words; each is matched to a post
# here by its question's opening, middle or end. A match gets its link, a
# scheduled reel found is confirmed, and its comments start (or start again).

RECONCILE_EVERY = timedelta(hours=6)
RECONCILE_MIN = 3                     # unlinked posts it takes to be worth a deep scroll


def _norm_text(text: str) -> str:
    """As the poster's search reads a caption: letters and digits, lower case."""
    import unicodedata

    t = unicodedata.normalize("NFKD", str(text or "")).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def _needles(question: str, context: str = "") -> list[str]:
    """The opening, the middle and the end of a question (and its context's opening), 40 characters each."""
    out: list[str] = []
    for text in (question, context):
        n = _norm_text(text)
        if len(n) < 24:
            continue
        mid = len(n) // 2
        out += [n[:40], n[max(0, mid - 20):mid + 20], n[-40:]] if text is question else [n[:40]]
    return [x for x in dict.fromkeys(out) if len(x) >= 20]


def _unlinked(now: datetime) -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    return fetch_all("""SELECT post_id, question_id, status, platform_scheduled, notes, comments_state FROM social_posts
                        WHERE platform = 'facebook' AND COALESCE(format, 'video') = 'video' AND url = ''
                          AND handed_at IS NOT NULL AND posted_at <= :ripe AND posted_at >= :since
                        ORDER BY posted_at DESC LIMIT 400""",
                     {"ripe": now - timedelta(minutes=10), "since": now - timedelta(days=90)}) or []


def reconcile_due(now: datetime) -> bool:
    """Enough posts without their link, and no deep scroll in the last few hours."""
    from ..infra.db import fetch_one

    last = (fetch_one("SELECT MAX(at) AS t FROM campaign_log WHERE kind = 'reconcile'") or {}).get("t")
    if isinstance(last, datetime) and now - last < RECONCILE_EVERY:
        return False
    return len(_unlinked(now)) >= RECONCILE_MIN


def reconcile_job(now: datetime) -> dict[str, Any]:
    """The deep scroll, handed to the poster (and noted, so it is not handed twice)."""
    from ..infra.db import execute

    execute("INSERT INTO campaign_log (post_id, at, kind, ok) VALUES ('', :t, 'reconcile', TRUE)", {"t": now})
    return {"post_id": "reconcile", "stage": "reconcile", "platform": "facebook", "scrolls": 160, "comments": []}


def reconcile_result(items: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    """Match what the poster saw on the profile to the posts without their link."""
    from ..infra.db import execute
    from .whiteboard import load

    now = now or datetime.now(timezone.utc)
    seen = []
    for it in items or []:
        url = str(it.get("url") or "").strip()
        text = _norm_text(it.get("text") or "")
        if url.startswith("https://") and "facebook.com" in url and len(text) >= 20:
            seen.append((url, text))
    taken = {u for u, _ in seen}
    from ..infra.db import fetch_all

    have = {r["url"] for r in (fetch_all("SELECT url FROM social_posts WHERE url = ANY(:u)", {"u": list(taken)}) or [])}
    seen = [(u, t) for u, t in seen if u not in have]            # a link another post has is not this one
    matched, used = [], set()
    for post in _unlinked(now):
        try:
            q = load(post["question_id"])
        except Exception:  # noqa: BLE001
            continue
        from . import social

        needles = _needles(social.display(q.get("question_text") or ""), social.display(q.get("context") or ""))
        if not needles:
            continue
        hit = next(((u, t) for u, t in seen if u not in used and any(n in t for n in needles)), None)
        if not hit:
            continue
        used.add(hit[0])
        execute("""UPDATE social_posts SET url = :u, updated_at = NOW(),
                   status = CASE WHEN status = 'scheduled' THEN 'posted' ELSE status END,
                   notes = CASE WHEN platform_scheduled THEN :c ELSE notes END,
                   comments_state = CASE WHEN comments_state IN ('', 'failed', 'pending') THEN 'pending' ELSE comments_state END,
                   comments_attempts = CASE WHEN comments_state IN ('', 'failed', 'pending') THEN 0 ELSE comments_attempts END,
                   comments_next_at = CASE WHEN comments_state IN ('', 'failed', 'pending') THEN :now ELSE comments_next_at END,
                   comments_error = CASE WHEN comments_state IN ('', 'failed', 'pending') THEN '' ELSE comments_error END
                   WHERE post_id = :id AND url = ''""",
                {"u": hit[0], "id": post["post_id"], "c": SCHEDULER_CONFIRMED, "now": now})
        matched.append(post["post_id"])
    logger.info("Reconciled %d post(s) from %d seen on the profile.", len(matched), len(seen))
    return {"seen": len(seen), "matched": len(matched), "posts": matched, "left": len(_unlinked(now))}


# ── the comment thread ───────────────────────────────────────────────────────
#
# Once a post is out the poster comments under it: first the choices and
# "can you solve it?", then — `poster_answer_delay_seconds` later — the
# answer, and the answer with its working and the answer card. Only within
# posting hours. A post it cannot find or comment on is tried again in ten
# minutes, four times at most.

COMMENT_TRIES = 4


def boost_rules() -> dict[str, Any]:
    from . import platform_settings as ps

    def num(key: str, default: int, lo: int, hi: int) -> int:
        try:
            return max(lo, min(int(ps.get(key, default) or default), hi))
        except (TypeError, ValueError):
            return default

    return {"enabled": bool(ps.get("engage_boost", False)), "per_day": num("engage_boosts_per_day", 40, 1, 300),
            "hours": num("engage_boost_hours", 3, 1, 48)}


def score_of(m: dict[str, Any], own_comments: int = 0) -> float:
    """How a post is doing: reactions, others' comments (twice), shares (three
    times), and views (one point per fifty)."""
    others = max(0, int(m.get("comments") or 0) - own_comments)
    return round(int(m.get("reactions") or 0) + 2 * others + 3 * int(m.get("shares") or 0) + int(m.get("views") or 0) / 50, 2)


def _extras(question_id: str) -> list[str]:
    """The comments past the thread's four, for the engagement loop."""
    from . import social
    from .whiteboard import load

    q = load(question_id)
    data, _, _, _, b, _ = social._prepare(q)
    t = social.thread(q, data, b)
    return social.comment_library(q, data, b)[len(t["first"]) + len(t["later"]):]


def comments_next(now: datetime | None = None, *, check: bool = False,
                  roles: set[str] | None = None) -> dict[str, Any]:
    """The next comment step that is due, with its text, or why none: the
    thread's two steps, then — with Keep posts engaged on — a post's next
    extra comment, or a reading of a post's insights (the weakest first).
    `check`: the newest post that is out, whatever its state — for a dry
    run that finds it and its comment box and sends nothing."""
    from ..infra.db import execute, fetch_one
    from . import social, social_cards
    from .whiteboard import load

    now = now or datetime.now(timezone.utc)
    rules = poster_rules()
    local = now.astimezone(EAT)
    start = local.replace(hour=int(rules["hours"]["start"][:2]), minute=int(rules["hours"]["start"][3:]), second=0, microsecond=0)
    end = local.replace(hour=int(rules["hours"]["end"][:2]), minute=int(rules["hours"]["end"][3:]), second=0, microsecond=0)
    if check:
        row = fetch_one("""SELECT post_id, question_id, platform, url, 'pending' AS comments_state FROM social_posts
                           WHERE platform = 'facebook' AND COALESCE(format, 'video') = 'video' AND posted_at <= :now
                             AND handed_at IS NOT NULL ORDER BY posted_at DESC LIMIT 1""", {"now": now})
        if not row:
            return {"job": None, "reason": "No post is out yet to check against."}
    elif not (start <= local <= end):
        return {"job": None, "reason": "Outside posting hours."}
    else:
        row = None
    roles = roles if roles is not None else {"post", "comments"}
    if not check and "post" in roles:
        try:
            recheck_scheduled(now)
        except Exception as exc:  # noqa: BLE001
            logger.info("Could not recheck the scheduled reels: %s", exc)
    if not check and "post" not in roles:
        # A comments-only Mac: no post's own thread, straight to the readings and the campaign.
        row = {"skip": True}
    if not check and "post" in roles and reconcile_due(now):
        return {"job": reconcile_job(now), "reason": ""}
    if not check and not (row and row.get("skip")):
        try:
            _give_up_unfindable(now)
        except Exception as exc:  # noqa: BLE001
            logger.info("Could not tidy the comment queue: %s", exc)
    row = None if row and row.get("skip") else row or fetch_one(
        """SELECT post_id, question_id, platform, url, comments_state, boost_index FROM social_posts
           WHERE comments_state IN ('pending', 'part', 'boost') AND comments_attempts < :tries
             AND comments_next_at <= :now AND posted_at <= :now
             -- Found by searching the profile (no link yet): only a recent post,
             -- and not straight after a search that failed (the campaign's turn).
             AND (url <> '' OR (posted_at >= :fresh AND NOT :cool))
           -- An answer that is due goes before other posts' first comments (it
           -- follows its choices by a minute, not after a whole backlog), and
           -- the loop's extra comments come last.
           ORDER BY CASE comments_state WHEN 'part' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, comments_next_at
           LIMIT 1""", {"tries": COMMENT_TRIES, "now": now - timedelta(seconds=30),
                         "fresh": now - FINDABLE_FOR, "cool": _searched_in_vain(now)})
    if row and row["comments_state"] == "boost":
        extras = _extras(row["question_id"])
        k = int(row.get("boost_index") or 0)
        if k >= len(extras):
            execute("UPDATE social_posts SET comments_state = 'complete' WHERE post_id = :id", {"id": row["post_id"]})
            return {"job": None, "reason": "That post has every comment it can carry."}
        t = social.status(row["question_id"]).get("thread") or {}
        return {"job": {"post_id": row["post_id"], "platform": row["platform"], "url": row.get("url") or "",
                        "find": t.get("find") or "", "find_also": t.get("find_also") or [], "stage": "boost",
                        "comments": [extras[k]], "image_url": "", "measure": True}, "reason": ""}
    if not row:
        br = boost_rules()
        camp = campaign_rules()["enabled"] and not check and "comments" in roles
        if (br["enabled"] or camp) and not check and "comments" in roles:
            # Read a post's insights: the weakest (or never read) first.
            row = fetch_one("""SELECT post_id, question_id, platform, url FROM social_posts
                               WHERE platform = 'facebook' AND COALESCE(format, 'video') = 'video'
                                 AND handed_at IS NOT NULL AND posted_at <= :ripe AND posted_at >= :since
                                 AND comments_state IN ('done', '')
                                 AND (metrics_at IS NULL OR metrics_at < :stale)
                               ORDER BY metrics_at NULLS FIRST, score NULLS FIRST, posted_at DESC LIMIT 1""",
                            {"ripe": now - timedelta(hours=1), "since": now - timedelta(days=21),
                             "stale": now - timedelta(hours=br["hours"])})
            if row:
                t = social.status(row["question_id"]).get("thread") or {}
                return {"job": {"post_id": row["post_id"], "platform": row["platform"], "url": row.get("url") or "",
                                "find": t.get("find") or "", "find_also": t.get("find_also") or [], "stage": "measure",
                                "comments": [], "image_url": "", "measure": True}, "reason": ""}
        if camp:
            return campaign_next(now)
        return {"job": None, "reason": "No comments due."}
    st = social.status(row["question_id"])
    t = st.get("thread") or {}
    first = row["comments_state"] == "pending"
    image = ""
    try:
        q = load(row["question_id"])
        card = social_cards.status(row["question_id"], "answer", q)
        if first and card.get("status") != "ready":
            social_cards.enqueue(row["question_id"], queued_by="comments")   # made by the time the answer is due
        elif not first:
            if card.get("status") != "ready":
                card = social_cards.render(row["question_id"], "answer", q)  # not made yet: one card, made now
            image = card.get("url") if card.get("status") == "ready" else ""
    except Exception as exc:  # noqa: BLE001
        logger.info("No answer card for %s: %s", row["question_id"], exc)
        image = ""
    return {"job": {"post_id": row["post_id"], "platform": row["platform"], "url": row.get("url") or "",
                    "find": t.get("find") or "", "find_also": t.get("find_also") or [],
                    "stage": "first" if first else "later",
                    "comments": t.get("first" if first else "later") or [], "image_url": image,
                    "measure": not first}, "reason": ""}


def _save_metrics(post_id: str, m: dict[str, Any], now: datetime) -> float:
    """Store a reading of the post's numbers; its score, counting out our own comments."""
    from ..infra.db import execute, fetch_one

    row = fetch_one("SELECT comments_state, boost_index FROM social_posts WHERE post_id = :id", {"id": post_id}) or {}
    own = (4 if row.get("comments_state") in ("done", "boost", "complete") else 2 if row.get("comments_state") == "part" else 0) \
        + int(row.get("boost_index") or 0)
    score = score_of(m, own)
    vals = {k: max(0, int(m.get(k) or 0)) for k in ("views", "reactions", "comments", "shares")}
    execute("""INSERT INTO post_insights (post_id, at, views, reactions, comments, shares, score)
               VALUES (:id, :t, :views, :reactions, :comments, :shares, :score)""",
            {"id": post_id, "t": now, **vals, "score": score})
    execute("""UPDATE social_posts SET metrics_at = :t, score = :score, views = GREATEST(views, :views),
               likes = GREATEST(likes, :reactions), comments = GREATEST(comments, :comments),
               shares = GREATEST(shares, :shares), updated_at = NOW() WHERE post_id = :id""",
            {"id": post_id, "t": now, **vals, "score": score})
    return score


def _maybe_boost(post_id: str, score: float, now: datetime) -> bool:
    """A quiet post gets its next comment: the first right after its thread,
    then only if it has not improved since the last one (and the day allows)."""
    from ..infra.db import execute, fetch_one

    br = boost_rules()
    if not br["enabled"] or campaign_rules()["enabled"]:       # the campaign does this job when it is on
        return False
    row = fetch_one("SELECT comments_state, boost_last_at, boost_base FROM social_posts WHERE post_id = :id",
                    {"id": post_id}) or {}
    if row.get("comments_state") != "done":
        return False
    last = row.get("boost_last_at")
    if last is not None:
        if now - last < timedelta(hours=br["hours"]):
            return False
        base = float(row.get("boost_base") or 0)
        if score > base * 1.1 + 1:
            execute("UPDATE social_posts SET boost_base = :s WHERE post_id = :id", {"id": post_id, "s": score})
            return False                               # it is improving: leave it be
    day = now.astimezone(EAT).replace(hour=0, minute=0, second=0, microsecond=0)
    done_today = int((fetch_one("SELECT COUNT(*) AS n FROM social_posts WHERE boost_last_at >= :d", {"d": day}) or {}).get("n") or 0)
    if done_today >= br["per_day"]:
        return False
    execute("""UPDATE social_posts SET comments_state = 'boost', comments_next_at = :t, comments_attempts = 0
               WHERE post_id = :id""", {"id": post_id, "t": now})
    return True


def comments_result(post_id: str, *, stage: str, ok: bool, error: str = "", url: str = "",
                    metrics: dict[str, Any] | None = None, now: datetime | None = None,
                    groups: list[str] | None = None) -> dict[str, Any]:
    from ..infra.db import execute

    now = now or datetime.now(timezone.utc)
    score = _save_metrics(post_id, metrics, now) if metrics else None
    if stage in ("campaign", "share"):
        campaign_result(post_id, stage=stage, ok=ok, error=error, now=now, groups=groups)
        return {"post_id": post_id, "ok": ok, "score": score}
    if stage == "measure":
        if not ok:
            execute("UPDATE social_posts SET metrics_at = :t, comments_error = :e WHERE post_id = :id",
                    {"id": post_id, "t": now, "e": error[:900]})
            return {"post_id": post_id, "ok": False}
        return {"post_id": post_id, "ok": True, "score": score,
                "boost": _maybe_boost(post_id, score if score is not None else 0.0, now)}
    if ok and stage == "boost":
        execute("""UPDATE social_posts SET comments_state = 'done', boost_index = boost_index + 1, boost_last_at = :t,
                   boost_base = COALESCE(:s, score, 0), comments_error = '', comments_attempts = 0,
                   url = COALESCE(NULLIF(:u, ''), url), updated_at = NOW() WHERE post_id = :id""",
                {"id": post_id, "t": now, "s": score, "u": url})
    elif ok:
        delay = comment_rules()["delay"]
        execute("""UPDATE social_posts SET comments_state = :st, comments_next_at = :next, comments_error = '',
                   comments_attempts = 0, url = COALESCE(NULLIF(:u, ''), url), updated_at = NOW() WHERE post_id = :id""",
                {"id": post_id, "st": "part" if stage == "first" else "done",
                 "next": now + timedelta(seconds=delay) if stage == "first" else None, "u": url})
        if stage == "later" and score is not None:
            _maybe_boost(post_id, score, now)        # the first extra comment follows the thread
        # Found on the profile: a reel handed to Facebook's scheduler is out.
        execute("""UPDATE social_posts SET status = 'posted', notes = :c
                   WHERE post_id = :id AND status = 'scheduled' AND platform_scheduled""",
                {"id": post_id, "c": SCHEDULER_CONFIRMED})
    elif stage == "first" and _not_on_profile(error) and _awaiting_schedule(post_id):
        _scheduled_not_found(post_id, error, now)
    else:
        execute("""UPDATE social_posts SET comments_attempts = comments_attempts + 1, comments_error = :e,
                   comments_state = CASE WHEN comments_attempts + 1 >= :tries
                                         THEN (CASE WHEN comments_state = 'boost' THEN 'done' ELSE 'failed' END)
                                         ELSE comments_state END,
                   comments_next_at = :next, updated_at = NOW() WHERE post_id = :id""",
                {"id": post_id, "e": error[:900], "tries": COMMENT_TRIES, "next": now + timedelta(minutes=10)})
    return {"post_id": post_id, "ok": ok, "score": score}


def comments_backfill(days: int = 7, *, now: datetime | None = None) -> int:
    """Posts already out (the last `days` days) get the same comments."""
    from ..infra.db import fetch_one

    now = now or datetime.now(timezone.utc)
    row = fetch_one("""WITH up AS (
                         UPDATE social_posts SET comments_state = 'pending', comments_next_at = posted_at,
                                comments_attempts = 0, comments_error = ''
                         WHERE COALESCE(format, 'video') = 'video' AND platform = 'facebook' AND comments_state = ''
                           AND posted_at IS NOT NULL AND posted_at >= :since AND handed_at IS NOT NULL
                         RETURNING 1)
                       SELECT COUNT(*) AS n FROM up""", {"since": now - timedelta(days=max(1, days))}) or {}
    return int(row.get("n") or 0)


# ── the owner's groups ───────────────────────────────────────────────────────

def save_found_groups(platform: str, names: list[str]) -> list[dict[str, Any]]:
    """The groups the poster found in the platform's picker; new ones start
    unticked — the owner chooses which welcome teaching posts."""
    from ..infra.db import execute

    for n in dict.fromkeys(str(x).strip()[:200] for x in names if str(x).strip()):
        execute("""INSERT INTO poster_groups (platform, name) VALUES (:p, :n)
                   ON CONFLICT (platform, name) DO UPDATE SET seen_at = NOW()""", {"p": platform, "n": n})
    return list_groups(platform)


def list_groups(platform: str = "facebook") -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    rows = fetch_all("""SELECT name, enabled, last_shared_for, seen_at FROM poster_groups WHERE platform = :p
                        ORDER BY enabled DESC, name""", {"p": platform}) or []
    for r in rows:
        for k in ("last_shared_for", "seen_at"):
            if r.get(k) is not None and hasattr(r[k], "isoformat"):
                r[k] = r[k].isoformat()
    return rows


def set_groups(platform: str, enabled: list[str]) -> list[dict[str, Any]]:
    from ..infra.db import execute

    execute("UPDATE poster_groups SET enabled = (name = ANY(:names)) WHERE platform = :p",
            {"p": platform, "names": [str(n) for n in enabled]})
    return list_groups(platform)


def set_login_state(platform: str, logged_in: bool, note: str = "") -> None:
    from ..infra.db import execute

    execute("""INSERT INTO poster_state (platform, logged_in, note, checked_at) VALUES (:p, :l, :n, NOW())
               ON CONFLICT (platform) DO UPDATE SET logged_in = EXCLUDED.logged_in, note = EXCLUDED.note, checked_at = NOW()""",
            {"p": platform, "l": logged_in, "n": note[:300]})


def poster_overview() -> dict[str, Any]:
    from ..infra.db import fetch_all, fetch_one

    now = datetime.now(timezone.utc)
    day_start = now.astimezone(EAT).replace(hour=0, minute=0, second=0, microsecond=0)
    states = fetch_all("SELECT platform, logged_in, note, checked_at FROM poster_state ORDER BY platform") or []
    today = fetch_all("""SELECT platform, COUNT(*) AS n FROM social_posts WHERE posted_at >= :d AND posted_at <= :now
                         GROUP BY platform""", {"d": day_start, "now": now}) or []
    queue = fetch_all(
        """SELECT post_id, platform, question_id, scheduled_for, status, attempts, last_error FROM social_posts
           WHERE posted_at IS NULL AND handed_at IS NULL AND status IN ('planned', 'failed')
           ORDER BY scheduled_for NULLS LAST LIMIT 30""") or []
    ahead = fetch_one("""SELECT COUNT(*) AS n, MAX(posted_at) AS until FROM social_posts
                         WHERE platform_scheduled AND posted_at > :now""", {"now": now}) or {}
    handed = fetch_one("SELECT COUNT(*) AS n FROM social_posts WHERE handed_at >= :d", {"d": day_start}) or {}
    waiting = fetch_one("""SELECT COUNT(*) AS n FROM social_posts WHERE posted_at IS NULL AND handed_at IS NULL
                           AND status IN ('planned', 'failed')""") or {}
    recent = fetch_all(
        """SELECT post_id, platform, question_id, status, posted_at, url, last_error, last_attempt_at FROM social_posts
           WHERE last_attempt_at IS NOT NULL ORDER BY last_attempt_at DESC LIMIT 20""") or []
    for rows in (states, queue, recent):
        for r in rows:
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
    until = ahead.get("until")
    return {"rules": poster_rules(), "posted_today": {r["platform"]: int(r["n"]) for r in today},
            "states": states, "queue": queue, "recent": recent,
            "scheduled_ahead": {"count": int(ahead.get("n") or 0), "until": until.isoformat() if hasattr(until, "isoformat") else until},
            "scheduler": _scheduler_overview(now),
            "handed_today": int(handed.get("n") or 0), "waiting": int(waiting.get("n") or 0),
            "comments": {**comment_rules(), **{r["comments_state"]: int(r["n"]) for r in (fetch_all(
                """SELECT comments_state, COUNT(*) AS n FROM social_posts WHERE comments_state <> ''
                   GROUP BY comments_state""") or [])}},
            # What "Schedule now" and "Post now" may still do today.
            "left_today": max(0, poster_rules()["daily_cap"] - int(handed.get("n") or 0)),
            "schedulable": int((fetch_one(
                """SELECT COUNT(*) AS n FROM social_posts WHERE platform = 'facebook' AND COALESCE(format, 'video') = 'video'
                   AND posted_at IS NULL AND handed_at IS NULL AND status IN ('planned', 'failed')
                   AND groups = '[]'::jsonb AND scheduled_for > :soon AND scheduled_for <= :until""",
                {"soon": now + AHEAD_LEAD, "until": now + timedelta(days=poster_rules()["ahead_days"])}) or {}).get("n") or 0),
            "groups": list_groups("facebook")}


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
    record_activity(poster_id, "poster", status.get("today") or {})


def record_activity(device: str, kind: str, today: dict[str, Any]) -> None:
    """A Mac's counts for its day (the day it says), kept a row a day for its history."""
    from datetime import date

    from ..infra.db import execute, to_json

    day = str(today.get("day") or "")
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return
    counts = {k: int(v) for k, v in today.items() if k != "day" and str(v).lstrip("-").isdigit()}
    execute("""INSERT INTO device_activity (device, kind, day, counts) VALUES (:dev, :k, :d, CAST(:c AS jsonb))
               ON CONFLICT (device, kind, day) DO UPDATE SET counts = EXCLUDED.counts""",
            {"dev": device[:80], "k": kind, "d": d, "c": to_json(counts)})


def device_names() -> dict[str, str]:
    import json

    from . import platform_settings

    try:
        raw = platform_settings.get("device_names", "") or ""
        got = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
    except (ValueError, TypeError):
        got = {}
    return {str(k)[:80]: str(v)[:60] for k, v in got.items() if isinstance(got, dict)}


def device_history(device: str, kind: str, days: int = 14) -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    rows = fetch_all("""SELECT day, counts FROM device_activity WHERE device = :dev AND kind = :k
                        AND day >= CURRENT_DATE - (:n * INTERVAL '1 day') ORDER BY day""",
                     {"dev": device[:80], "k": kind, "n": days}) or []
    return [{"day": r["day"].isoformat(), **(r.get("counts") or {})} for r in rows]


def forget_device(device: str, kind: str) -> None:
    """Off the list: its check-ins, its jobs and its name (it reappears if it checks in again)."""
    import json

    from ..infra.db import execute
    from . import platform_settings

    if kind == "render":
        execute("DELETE FROM render_helpers WHERE worker = :d", {"d": device[:80]})
    else:
        execute("DELETE FROM poster_heartbeat WHERE poster_id = :d", {"d": device[:80]})
        roles = poster_roles()
        if roles.pop(device[:80], None) is not None:
            platform_settings.set_many({"poster_roles": json.dumps(roles)}, updated_by="devices")
    execute("DELETE FROM device_activity WHERE device = :d AND kind = :k", {"d": device[:80], "k": kind})
    names = device_names()
    if names.pop(device[:80], None) is not None:
        platform_settings.set_many({"device_names": json.dumps(names)}, updated_by="devices")


def pull_poster() -> dict[str, Any] | None:
    """The active poster: of those that checked in within the last two
    minutes, the one started most recently. With two Macs installed, the
    newest one posts and the other stands by (see `standing_by`), so a post
    never goes out twice; restarting a poster makes it the active one."""
    from ..infra.db import fetch_one

    row = fetch_one(
        """SELECT poster_id, status, seen_at FROM poster_heartbeat
           WHERE seen_at > NOW() - make_interval(secs => :age)
           ORDER BY CASE WHEN status->>'started' ~ '^[0-9.]+$' THEN (status->>'started')::float ELSE 0 END DESC,
                    seen_at DESC LIMIT 1""",
        {"age": PULL_FRESH_SECONDS})
    if not row:
        return None
    status = dict(row.get("status") or {})
    return {**status, "online": True, "poster_id": row["poster_id"], "mode": status.get("mode") or "local",
            "seen_at": row["seen_at"].isoformat() if hasattr(row["seen_at"], "isoformat") else row["seen_at"]}


ROLES = ("post", "comments", "likes")


def poster_roles() -> dict[str, list[str]]:
    """Which jobs each Mac does ({poster_id: ["post", "comments", "likes"]}); a Mac not listed does them all."""
    import json

    from . import platform_settings

    try:
        raw = platform_settings.get("poster_roles", "") or ""
        got = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw if isinstance(raw, dict) else {})
    except (ValueError, TypeError):
        got = {}
    return {str(k)[:80]: [r for r in v if r in ROLES] for k, v in got.items() if isinstance(v, list)}


def fresh_posters() -> list[dict[str, Any]]:
    """The posters that checked in lately, the one started most recently first."""
    from ..infra.db import fetch_all

    rows = fetch_all("""SELECT poster_id, status, seen_at FROM poster_heartbeat
                        WHERE seen_at > NOW() - make_interval(secs => :age)
                        ORDER BY CASE WHEN status->>'started' ~ '^[0-9.]+$' THEN (status->>'started')::float ELSE 0 END DESC,
                                 seen_at DESC""", {"age": PULL_FRESH_SECONDS}) or []
    return [dict(r) for r in rows]


def standing_by(poster_id: str, role: str = "post") -> str:
    """Why this poster must not take this kind of work now, or "". Each job
    (posting, the comment campaign, liking back) goes to the newest Mac that
    has it; a Mac with no jobs set does them all."""
    if not poster_id:
        return ""                     # a poster too old to say who it is
    roles = poster_roles()
    has = lambda pid: role in roles.get(pid, list(ROLES))  # noqa: E731
    if not has(poster_id[:80]):
        return f"Not this Mac's job ({role})."
    for p in fresh_posters():
        if has(str(p["poster_id"])):
            other = str(p["poster_id"])
            if other != poster_id[:80]:
                return f"Standing by: {other} does the {role} job. Restart this one to make it take over."
            return ""
    return ""


def queue_command(action: str, platform: str = "", post_id: str = "", by: str = "",
                  options: dict[str, Any] | None = None, target: str = "") -> int:
    from ..infra.db import fetch_one, to_json

    row = fetch_one("""INSERT INTO poster_commands (action, platform, post_id, created_by, options, target)
                       VALUES (:a, :p, :id, :by, CAST(:o AS jsonb), :t) RETURNING command_id""",
                    {"a": action, "p": platform, "id": post_id, "by": by, "o": to_json(options or {}), "t": target[:80]})
    return int((row or {}).get("command_id") or 0)


def take_command(poster_id: str = "", *, active: bool = True) -> dict[str, Any] | None:
    """The oldest command nobody has taken; commands older than ten minutes
    are dropped — a "log in" pressed an hour ago is not what anyone wants now."""
    from ..infra.db import execute, fetch_one

    execute("""UPDATE poster_commands SET taken_at = NOW(), done_at = NOW(), result = '{"expired": true}'::jsonb
               WHERE taken_at IS NULL AND created_at < NOW() - INTERVAL '10 minutes'""")
    row = fetch_one(
        """UPDATE poster_commands SET taken_at = NOW() WHERE command_id = (
               SELECT command_id FROM poster_commands WHERE taken_at IS NULL
                 -- Its own commands first (sent to this Mac by name), then the posting
                 -- Mac's (sent to nobody in particular) if this is the one.
                 AND (target = :me OR (target = '' AND :active))
               ORDER BY (target = :me) DESC, created_at
               LIMIT 1 FOR UPDATE SKIP LOCKED)
           RETURNING command_id, action, platform, post_id, options""", {"me": poster_id[:80], "active": active})
    # A boost nobody took: say so on the post, so it can be pressed again.
    execute("""UPDATE social_posts SET boost_state = 'failed', boost_error = 'The poster was not running — press Boost again.'
               WHERE boost_state = 'queued' AND post_id IN (SELECT post_id FROM poster_commands
                     WHERE action = 'boost' AND result->>'expired' = 'true')""")
    return dict(row) if row else None


def finish_command(command_id: int, result: dict[str, Any]) -> None:
    from ..infra.db import execute, fetch_one, to_json

    row = fetch_one("""UPDATE poster_commands SET done_at = NOW(), result = CAST(:r AS jsonb) WHERE command_id = :id
                       RETURNING action, post_id""", {"id": command_id, "r": to_json(result)}) or {}
    if row.get("action") == "boost" and row.get("post_id"):
        ok = bool(result.get("ok"))
        state = "boosted" if ok else "check" if result.get("unsure") else "failed"
        execute("""UPDATE social_posts SET boost_state = :st, boost_error = :e,
                          boosted_at = CASE WHEN :ok THEN NOW() ELSE boosted_at END WHERE post_id = :id""",
                {"st": state, "e": "" if ok else str(result.get("error") or "")[:500], "ok": ok, "id": row["post_id"]})


# ── boosting: paid reach for a post, only when the owner presses Boost ───────

BOOST_DAILY_KSH = 200
BOOST_DAYS = 5


def boost(post_id: str, *, daily_ksh: int = BOOST_DAILY_KSH, days: int = BOOST_DAYS, by: str = "",
          again: bool = False) -> dict[str, Any]:
    """Ask the poster to boost one post that is out — at `daily_ksh` a day for
    `days` days. Nothing is ever boosted without this call; the poster checks
    Facebook's total against these numbers before it confirms."""
    from ..infra.db import execute, fetch_one
    from . import social

    daily_ksh, days = int(daily_ksh), int(days)
    if not (50 <= daily_ksh <= 5000) or not (1 <= days <= 30):
        raise ValueError("A boost is KSh 50–5,000 a day, for 1–30 days.")
    row = fetch_one("""SELECT post_id, question_id, platform, url, handed_at, boost_state FROM social_posts
                       WHERE post_id = :id""", {"id": post_id})
    if not row or not row.get("handed_at"):
        raise ValueError("Only a post that is out can be boosted.")
    if row["platform"] != "facebook":
        raise ValueError("Boosting is set up for Facebook only.")
    if row.get("boost_state") == "queued":
        raise ValueError("This post's boost is already on its way.")
    if row.get("boost_state") in ("boosted", "check") and not again:
        raise ValueError("This post was boosted (or may have been — check Ads Manager). Press Boost again to add another.")
    t = social.status(row["question_id"]).get("thread") or {}
    command_id = queue_command("boost", "facebook", post_id, by=by,
                               options={"daily_ksh": daily_ksh, "days": days, "find": t.get("find") or "",
                                        "find_also": t.get("find_also") or [], "url": row.get("url") or ""})
    execute("""UPDATE social_posts SET boost_state = 'queued', boost_daily_ksh = :d, boost_days = :n, boost_error = ''
               WHERE post_id = :id""", {"d": daily_ksh, "n": days, "id": post_id})
    return {"post_id": post_id, "command_id": command_id, "daily_ksh": daily_ksh, "days": days,
            "total_ksh": daily_ksh * days}


def boost_candidates(limit: int = 50) -> list[dict[str, Any]]:
    """Posts that are out with the platform pitch, newest first, with their
    numbers — the ones worth paying to show more people."""
    from ..infra.db import fetch_all

    rows = fetch_all("""SELECT p.post_id, p.question_id, p.posted_at, p.url, p.score, p.marketing, p.boost_state,
                               p.boost_daily_ksh, p.boost_days, p.boost_error, p.boosted_at, p.teacher,
                               LEFT(COALESCE(q.content->>'question_text', ''), 140) AS question_text
                        FROM social_posts p LEFT JOIN question_dna q ON q.question_id = p.question_id
                        WHERE p.platform = 'facebook' AND p.handed_at IS NOT NULL AND COALESCE(p.format, 'video') = 'video'
                        ORDER BY p.marketing DESC, p.posted_at DESC LIMIT :n""", {"n": limit}) or []
    return [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()} for r in rows]


def command_result(command_id: int) -> dict[str, Any] | None:
    from ..infra.db import fetch_one

    row = fetch_one("SELECT done_at, result FROM poster_commands WHERE command_id = :id", {"id": command_id})
    return dict(row["result"] or {}) if row and row.get("done_at") else None


# ── booking ahead: the next weeks, a random few videos a day ─────────────────
#
# One run keeps the next `days` days booked: it starts the day after the last
# booked post (or tomorrow) and fills up to `days` days from today, so running
# it every two weeks or every month tops the calendar up rather than piling
# more onto it. Each day gets a random number of videos at random times inside
# the posting hours, spaced by the gap; a video goes to every chosen platform
# at a different time. A question is never booked twice. Videos not made yet
# are queued for rendering, earliest post first, and the poster passes over a
# post whose video is not ready.

POSTER_PLATFORMS = ("tiktok", "instagram", "facebook", "youtube", "linkedin")


def day_times(rng: Any, day: date, count: int, rules: dict[str, Any]) -> list[datetime]:
    """`count` random times on `day` inside the posting hours, at least the
    gap apart (fewer if the hours cannot hold them)."""
    start = int(rules["hours"]["start"][:2]) * 60 + int(rules["hours"]["start"][3:])
    end = int(rules["hours"]["end"][:2]) * 60 + int(rules["hours"]["end"][3:]) - 15   # room to finish the last one
    gap = max(1, int(rules["min_gap_minutes"]) + 2)    # a little over the gap: the poster ticks once a minute
    window = max(0, end - start)
    count = min(count, window // gap + 1)
    if count <= 0:
        return []
    slack = window - (count - 1) * gap
    picks = sorted(rng.uniform(0, slack) for _ in range(count))
    return [datetime.combine(day, time(0, 0), tzinfo=EAT) + timedelta(minutes=round(start + p + i * gap))
            for i, p in enumerate(picks)]


def videos_a_day_limit(rules: dict[str, Any], platforms: list[str]) -> int:
    """How many videos one day can hold on these platforms under the caps."""
    n = max(1, len(platforms))
    start = int(rules["hours"]["start"][:2]) * 60 + int(rules["hours"]["start"][3:])
    end = int(rules["hours"]["end"][:2]) * 60 + int(rules["hours"]["end"][3:]) - 15
    fits = (max(0, end - start) // (int(rules["min_gap_minutes"]) + 2) + 1) // n
    return max(0, min(rules["platform_cap"], rules["daily_cap"] // n, fits))


def default_platforms() -> list[str]:
    """The platforms the poster is logged into, else Facebook."""
    from ..infra.db import fetch_all

    try:
        rows = fetch_all("SELECT platform FROM poster_state WHERE logged_in") or []
    except Exception:  # noqa: BLE001
        rows = []
    found = [r["platform"] for r in rows if r["platform"] in POSTER_PLATFORMS]
    return sorted(found) or ["facebook"]


def day_counts(rng: Any, n_days: int, low: int, high: int, total: int = 0) -> list[int]:
    """Videos per day: each random in [low, high]; with `total`, they add up
    to it (as near as [low, high] allows), spread at random."""
    if not total:
        return [rng.randint(low, high) for _ in range(n_days)]
    total = min(total, n_days * high)
    counts = [min(low, total // n_days)] * n_days
    left = total - sum(counts)
    while left > 0:
        open_days = [i for i, c in enumerate(counts) if c < high]
        if not open_days:
            break
        counts[rng.choice(open_days)] += 1
        left -= 1
    return counts


def lay_out(rng: Any, days: list[date], videos: list[str], platforms: list[str], rules: dict[str, Any], *,
            low: int, high: int, total: int = 0) -> list[dict[str, Any]]:
    """The calendar: per day a random number of videos in [low, high] (adding
    up to `total` when given), each on every platform at its own random time.
    Pure — no database."""
    out: list[dict[str, Any]] = []
    pool = list(videos)
    wanted = day_counts(rng, len(days), low, high, total)
    for day, want in zip(days, wanted):
        if not pool:
            break
        n = min(want, len(pool))
        if n <= 0:
            continue
        chosen, pool = pool[:n], pool[n:]
        slots = day_times(rng, day, n * len(platforms), rules)
        pairs = [(qid, p) for qid in chosen for p in platforms]
        rng.shuffle(pairs)
        pairs = pairs[:len(slots)]
        out.append({"date": day.isoformat(), "videos": len({q for q, _ in pairs}),
                    "posts": [{"question_id": q, "platform": p, "at": at} for (q, p), at in zip(pairs, slots)]})
        unposted = [q for q in chosen if q not in {q2 for q2, _ in pairs}]
        pool = unposted + pool          # anything the day could not hold goes first tomorrow
    return out


def book_ahead(grade: str, subject: str, sub_strand: str = "", *, days: int = 25, low: int = 5, high: int = 15,
               platforms: list[str] | None = None, today: date | None = None, seed: int | None = None,
               dry: bool = False, created_by: str = "", total: int = 0, ready_only: bool = False) -> dict[str, Any]:
    """Keep the next `days` days booked — `total` videos over them when given.
    `ready_only`: only videos already made (book what is generated). `dry`
    shows the plan, writes nothing."""
    import random

    from ..infra.db import fetch_all, fetch_one
    from . import question_rows, social
    from .question_dna import question_dna_service

    rng = random.Random(seed)
    rules = poster_rules()
    platforms = [p for p in (platforms or default_platforms()) if p in POSTER_PLATFORMS]
    if not platforms:
        raise ValueError("Pick at least one of: " + ", ".join(POSTER_PLATFORMS))
    notes: list[str] = []
    room = videos_a_day_limit(rules, platforms)
    if room <= 0:
        raise ValueError("The posting rules leave no room for a post (Settings → Auto-post).")
    low, high = max(1, min(low, high)), max(1, max(low, high))
    if high > room:
        notes.append(f"At most {room} videos a day fit {len(platforms)} platform(s) under the caps "
                     f"({rules['daily_cap']} a day, {rules['platform_cap']} per platform, {rules['min_gap_minutes']} min "
                     "apart) — raise them in Settings → Auto-post for more.")
        high, low = room, min(low, room)

    today = today or datetime.now(EAT).date()
    last = fetch_one("""SELECT MAX(scheduled_for) AS t FROM social_posts
                        WHERE scheduled_for IS NOT NULL AND status <> 'gave_up'""") or {}
    last_day = last["t"].astimezone(EAT).date() if last.get("t") else None
    first = max(today + timedelta(days=1), (last_day + timedelta(days=1)) if last_day else today)
    end = today + timedelta(days=max(1, days))
    span = [first + timedelta(days=i) for i in range((end - first).days + 1)]
    if not span:
        return {"booked": False, "first_day": None, "last_day": last_day.isoformat() if last_day else None,
                "days": [], "videos": 0, "posts": 0, "to_render": 0, "platforms": platforms,
                "notes": [f"Already booked through {last_day:%a %d %b} — nothing to add yet."]}

    booked = {r["question_id"] for r in (fetch_all("SELECT DISTINCT question_id FROM social_posts") or [])}
    rows = question_dna_service.list_questions(grade=grade or None, subject=subject or None,
                                               sub_strand=sub_strand or None, limit=2000)
    candidates = [q for q in question_rows.flatten_all(rows)
                  if str(q.get("status") or "") not in ("needs_review", "rejected", "superseded")
                  and str(q.get("question_id")) not in booked]
    rng.shuffle(candidates)                       # mix the topics
    if total and total > high * len(span):
        notes.append(f"{total} videos do not fit {len(span)} day(s) at most {high} a day — booking {high * len(span)}.")
    need = min(total, high * len(span)) if total else high * len(span)
    usable: list[str] = []
    state: dict[str, str] = {}
    for q in candidates:
        if len(usable) >= need:
            break
        try:
            st = social.status(str(q["question_id"]), q)
        except Exception as exc:  # noqa: BLE001
            logger.info("Skipping %s: %s", q.get("question_id"), exc)
            continue
        if st.get("status") == "failed" or not st.get("scenes"):
            continue
        if ready_only and st.get("status") != "ready":
            continue
        usable.append(str(q["question_id"]))
        state[str(q["question_id"])] = str(st.get("status"))
    usable.sort(key=lambda qid: state[qid] != "ready")     # finished videos take the nearest days

    calendar = lay_out(rng, span, usable, platforms, rules, low=low, high=high, total=total)
    used = [p["question_id"] for d in calendar for p in d["posts"]]
    posts = sum(len(d["posts"]) for d in calendar)
    if ready_only and len(calendar) < len(span):
        notes.append(f"All {len(set(used))} finished videos not yet booked fill {len(calendar)} of {len(span)} days — "
                     "make more (Video batches) and book again.")
    elif len(calendar) < len(span):
        notes.append(f"Only enough unbooked questions for {len(calendar)} of {len(span)} days in this scope — "
                     "widen it (a whole subject) or add questions.")
    to_render = [q for q in dict.fromkeys(used) if state.get(q) != "ready"]
    if not dry:
        by_id = {str(q["question_id"]): q for q in candidates}
        for d in calendar:
            for p in d["posts"]:
                _plan_post(by_id[p["question_id"]], p["platform"], p["at"], created_by)
        for qid in sorted(to_render, key=lambda q: min(p["at"] for d in calendar for p in d["posts"] if p["question_id"] == q)):
            if state.get(qid) in ("queued", "running"):
                continue
            try:
                social.enqueue(qid, queued_by=created_by or "social-plan")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not queue the video for %s: %s", qid, exc)
    return {"booked": not dry, "first_day": calendar[0]["date"] if calendar else None,
            "last_day": calendar[-1]["date"] if calendar else None, "platforms": platforms,
            "days": [{"date": d["date"], "videos": d["videos"],
                      "times": [f"{p['at'].astimezone(EAT):%H:%M} {p['platform']}" for p in d["posts"]]}
                     for d in calendar],
            "videos": len(set(used)), "posts": posts, "to_render": len(to_render), "notes": notes}


# ── a month at a time ────────────────────────────────────────────────────────
#
# The calendar the owner books by: any month, each day showing what is
# booked, what the platform already holds, what went out, and the room left
# for the videos a day they want. Booking fills only that room, each post
# 30–60 minutes from the next; Facebook is handed each one once it is inside
# its 29-day window, so a month booked today reaches Facebook day by day.

LIVE_EXTRA = "live-extra"
POST_NOW = "post-now"


def month_days(year: int, month: int) -> list[date]:
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return [first + timedelta(days=i) for i in range((nxt - first).days)]


def _state(row: dict[str, Any], now: datetime) -> str:
    """booked · on_platform (handed to its scheduler, not out yet) · posted · failed."""
    if str(row.get("status") or "") == "gave_up":
        return "failed"
    posted = row.get("posted_at")
    if row.get("handed_at") is not None:
        return "on_platform" if (row.get("platform_scheduled") and isinstance(posted, datetime) and posted > now) else "posted"
    if posted is not None:
        return "posted"
    return "booked"


def month_view(year: int, month: int, *, platforms: list[str] | None = None, per_day: int = 10,
               now: datetime | None = None) -> dict[str, Any]:
    """Each day of the month: its posts by state, and the room left for
    `per_day` videos (on each platform)."""
    from ..infra.db import fetch_all

    now = now or datetime.now(timezone.utc)
    rules = poster_rules()
    platforms = [p for p in (platforms or ["facebook"]) if p in POSTER_PLATFORMS] or ["facebook"]
    days = month_days(year, month)
    lo = datetime.combine(days[0], time(0, 0), tzinfo=EAT)
    hi = datetime.combine(days[-1] + timedelta(days=1), time(0, 0), tzinfo=EAT)
    rows = fetch_all(
        """SELECT post_id, question_id, platform, scheduled_for, posted_at, handed_at, platform_scheduled, status,
                  created_by, COALESCE(format, 'video') AS format, teacher
           FROM social_posts WHERE platform = ANY(:p) AND COALESCE(format, 'video') = 'video'
             AND COALESCE(scheduled_for, posted_at) >= :lo AND COALESCE(scheduled_for, posted_at) < :hi""",
        {"p": platforms, "lo": lo, "hi": hi}) or []
    today = now.astimezone(EAT).date()
    window_end = today + timedelta(days=rules["ahead_days"])
    by_day: dict[date, list[dict[str, Any]]] = {d: [] for d in days}
    for r in rows:
        when = r.get("scheduled_for") or r.get("posted_at")
        d = when.astimezone(EAT).date()
        if d in by_day:
            by_day[d].append({**r, "_when": when, "_state": _state(r, now)})
    out, open_days, free_total = [], 0, 0
    for d in days:
        items = sorted(by_day[d], key=lambda r: r["_when"])
        count = {k: sum(1 for r in items if r["_state"] == k) for k in ("booked", "on_platform", "posted", "failed")}
        per_platform = {p: sum(1 for r in items if r["platform"] == p and r["_state"] != "failed") for p in platforms}
        bookable = d > today
        free = max(0, per_day - max(per_platform.values() or [0])) if bookable else 0
        if free:
            open_days += 1
            free_total += free
        out.append({"date": d.isoformat(), "bookable": bookable, "free": free, **count,
                    "live_extra": sum(1 for r in items if r.get("created_by") == LIVE_EXTRA),
                    "to_platform_on": (d - timedelta(days=rules["ahead_days"])).isoformat()
                    if d > window_end and "facebook" in platforms else "",
                    "posts": [{"time": f"{r['_when'].astimezone(EAT):%H:%M}", "platform": r["platform"],
                               "state": r["_state"], "question_id": r["question_id"],
                               "teacher": str(r.get("teacher") or "")} for r in items]})
    return {"year": year, "month": month, "per_day": per_day, "platforms": platforms, "days": out,
            "open_days": open_days, "free": free_total, "facebook_until": window_end.isoformat(),
            "today": today.isoformat(), "rules": {"hours": rules["hours"], "min_gap_minutes": rules["min_gap_minutes"],
                                                  "live_per_day": rules["live_per_day"], "daily_cap": rules["daily_cap"],
                                                  "teacher": _teacher_now(), "lessons_per_day": _lessons_target()}}


def _teacher_now() -> str:
    from . import teacher

    return teacher.mode()


def _lessons_target() -> int:
    from . import platform_settings

    try:
        return int(platform_settings.get("video_daily_target", 200) or 0)
    except (TypeError, ValueError):
        return 0


def spaced_times(rng: Any, day: date, count: int, rules: dict[str, Any], *, gap_min: int, gap_max: int,
                 taken: list[datetime] | None = None) -> list[datetime]:
    """Up to `count` times on `day` inside the posting hours, each `gap_min`
    to `gap_max` minutes after the one before, and at least `gap_min` from
    any post the day already has. Pure."""
    gap_min = max(int(rules["min_gap_minutes"]), int(gap_min), 1)
    gap_max = max(gap_min, int(gap_max))
    start = int(rules["hours"]["start"][:2]) * 60 + int(rules["hours"]["start"][3:])
    end = int(rules["hours"]["end"][:2]) * 60 + int(rules["hours"]["end"][3:]) - 15
    base = datetime.combine(day, time(0, 0), tzinfo=EAT)
    busy = [int((t.astimezone(EAT) - base).total_seconds() // 60) for t in (taken or [])]
    out: list[int] = []
    t = start + rng.uniform(0, min(gap_max - gap_min, 30))
    while len(out) < count and t <= end:
        clash = [b for b in busy + out if abs(b - t) < gap_min]
        if clash:
            t = max(clash) + gap_min
            continue
        out.append(round(t))
        t += rng.uniform(gap_min, gap_max)
    return [base + timedelta(minutes=m) for m in out]


def _unbooked(grade: str, subject: str, sub_strand: str, need: int, *, ready_only: bool = False
              ) -> tuple[list[str], dict[str, str], dict[str, dict[str, Any]]]:
    """Up to `need` questions in scope with no post yet whose video is made
    or can be — the made ones first. (ids, their video state, the questions)"""
    import random

    from ..infra.db import fetch_all
    from . import question_rows, social
    from .question_dna import question_dna_service

    booked = {r["question_id"] for r in (fetch_all("SELECT DISTINCT question_id FROM social_posts") or [])}
    rows = question_dna_service.list_questions(grade=grade or None, subject=subject or None,
                                               sub_strand=sub_strand or None, limit=2000)
    candidates = [q for q in question_rows.flatten_all(rows)
                  if str(q.get("status") or "") not in ("needs_review", "rejected", "superseded")
                  and str(q.get("question_id")) not in booked]
    random.shuffle(candidates)                       # mix the topics
    usable: list[str] = []
    state: dict[str, str] = {}
    for q in candidates:
        if len(usable) >= need:
            break
        try:
            st = social.status(str(q["question_id"]), q)
        except Exception as exc:  # noqa: BLE001
            logger.info("Skipping %s: %s", q.get("question_id"), exc)
            continue
        if st.get("status") == "failed" or not st.get("scenes") or (ready_only and st.get("status") != "ready"):
            continue
        usable.append(str(q["question_id"]))
        state[str(q["question_id"])] = str(st.get("status"))
    usable.sort(key=lambda qid: state[qid] != "ready")
    return usable, state, {str(q["question_id"]): q for q in candidates}


def _days_view(first: date, last: date, *, platforms: list[str], per_day: int,
               now: datetime | None = None) -> list[dict[str, Any]]:
    """The calendar's days from `first` to `last`, across months."""
    out: list[dict[str, Any]] = []
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        out += [d for d in month_view(y, m, platforms=platforms, per_day=per_day, now=now)["days"]
                if first <= date.fromisoformat(d["date"]) <= last]
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


Scope = tuple[str, str, str]          # grade, subject, sub-strand ("" for the whole subject)


def _pool(scopes: list[Scope], need: int, *, ready_only: bool = False
          ) -> tuple[list[str], dict[str, str], dict[str, dict[str, Any]]]:
    """Unbooked questions from every scope, taken in turn (subjects mixed),
    made videos first — never one with a post already."""
    per = -(-need // max(1, len(scopes))) + 2
    lists, state, by_id = [], {}, {}
    for g, subj, ss in scopes:
        try:
            ids, st, qs = _unbooked(g, subj, ss, per, ready_only=ready_only)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read the bank for %s %s: %s", g, subj, exc)
            continue
        lists.append(ids)
        state.update(st)
        by_id.update(qs)
    pool: list[str] = []
    while any(lists) and len(pool) < need:
        for ids in lists:
            if ids and len(pool) < need:
                q = ids.pop(0)
                if q not in pool:
                    pool.append(q)
    pool.sort(key=lambda q: state.get(q) != "ready")
    return pool, state, by_id


def _fill(days: list[dict[str, Any]], scopes: list[Scope], *, per_day: int, gap_min: int, gap_max: int,
          platforms: list[str], ready_only: bool, dry: bool, created_by: str, rng: Any,
          full_note: str) -> dict[str, Any]:
    """Book the open room of these calendar days."""
    from . import social

    rules = poster_rules()
    notes: list[str] = []
    room = {d["date"]: d["free"] for d in days if d["free"] > 0}
    if not room:
        return {"booked": False, "days": [], "videos": 0, "posts": 0, "to_render": 0, "ready": 0, "platforms": platforms,
                "notes": [full_note], "first_day": None, "last_day": None}
    taken = {d["date"]: [datetime.combine(date.fromisoformat(d["date"]), time(*map(int, p["time"].split(":"))), tzinfo=EAT)
                         for p in d["posts"]] for d in days}
    usable, state, by_id = _pool(scopes, sum(room.values()), ready_only=ready_only)
    pool = list(usable)
    plan_days: list[dict[str, Any]] = []
    short_days = 0
    for day_s, free in sorted(room.items()):
        if not pool:
            break
        day = date.fromisoformat(day_s)
        n = min(free, len(pool))
        slots = spaced_times(rng, day, n * len(platforms), rules, gap_min=gap_min, gap_max=gap_max,
                             taken=taken.get(day_s))
        n = min(n, len(slots) // len(platforms))
        if n < free:
            short_days += 1
        if n <= 0:
            continue
        chosen, pool = pool[:n], pool[n:]
        pairs = [(q, p) for q in chosen for p in platforms]
        rng.shuffle(pairs)
        posts = [{"question_id": q, "platform": p, "at": at} for (q, p), at in zip(pairs, sorted(slots)[:len(pairs)])]
        plan_days.append({"date": day_s, "add": n, "posts": posts})
    used = list(dict.fromkeys(p["question_id"] for d in plan_days for p in d["posts"]))
    if short_days:
        notes.append(f"{short_days} day(s) could not hold all {per_day} at {gap_min}–{gap_max} min apart within "
                     f"{rules['hours']['start']}–{rules['hours']['end']} — closer spacing or longer hours fit more.")
    slots = sum(room.values())
    if len(used) < slots:
        notes.append(f"{len(used)} finished videos for {slots} open slots — make more videos and book again."
                     if ready_only else
                     f"{len(used)} unbooked questions for {slots} open slots — widen the scope (more subjects) "
                     "or add questions.")
    to_render = [q for q in used if state.get(q) != "ready"]
    if not dry:
        for d in plan_days:
            for p in d["posts"]:
                _plan_post(by_id[p["question_id"]], p["platform"], p["at"], created_by)
        for qid in to_render:
            if state.get(qid) in ("queued", "running"):
                continue
            try:
                social.enqueue(qid, queued_by=created_by or "month-plan")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not queue the video for %s: %s", qid, exc)
    return {"booked": not dry, "platforms": platforms, "videos": len(used),
            "posts": sum(len(d["posts"]) for d in plan_days), "to_render": len(to_render),
            "ready": len(used) - len(to_render), "notes": notes,
            "first_day": plan_days[0]["date"] if plan_days else None,
            "last_day": plan_days[-1]["date"] if plan_days else None,
            "days": [{"date": d["date"], "add": d["add"],
                      "times": [f"{p['at'].astimezone(EAT):%H:%M} {p['platform']}" for p in d["posts"]]}
                     for d in plan_days]}


def _platforms(platforms: list[str] | None) -> list[str]:
    out = [p for p in (platforms or ["facebook"]) if p in POSTER_PLATFORMS]
    if not out:
        raise ValueError("Pick at least one of: " + ", ".join(POSTER_PLATFORMS))
    return out


def book_month(grade: str, subject: str, sub_strand: str = "", *, year: int, month: int, per_day: int = 10,
               gap_min: int = 30, gap_max: int = 60, platforms: list[str] | None = None, ready_only: bool = False,
               dry: bool = False, created_by: str = "", seed: int | None = None,
               now: datetime | None = None) -> dict[str, Any]:
    """Fill the month's open room: each day from tomorrow up to `per_day`
    videos (on each platform), 30–60 minutes apart, around what it already
    holds. Videos not made yet are queued, the soonest first. `dry` shows
    the plan and writes nothing."""
    import random

    platforms = _platforms(platforms)
    per_day = max(1, min(int(per_day), HARD_DAILY_CAP))
    days = month_view(year, month, platforms=platforms, per_day=per_day, now=now)["days"]
    return _fill(days, [(grade, subject, sub_strand)], per_day=per_day, gap_min=gap_min, gap_max=gap_max,
                 platforms=platforms, ready_only=ready_only, dry=dry, created_by=created_by, rng=random.Random(seed),
                 full_note="Every day left in this month is already full at this many a day.")


# ── booking itself ───────────────────────────────────────────────────────────
#
# With Auto-book on, the calendar keeps itself full: every two hours the next
# `poster_auto_book_days` days are topped up to `poster_auto_book_per_day`
# videos, from the scopes in `poster_auto_book_scopes` (or, if none are set,
# the grades and subjects booked before). New questions are booked as they
# come into the bank, their videos queued at once; no question is booked twice.

AUTO_BOOK = "auto-book"


def auto_book_rules() -> dict[str, Any]:
    from . import platform_settings as ps

    def num(key: str, default: int, lo: int, hi: int) -> int:
        try:
            return max(lo, min(int(ps.get(key, default) or default), hi))
        except (TypeError, ValueError):
            return default

    raw = ps.get("poster_auto_book_scopes", None) or []
    items = raw if isinstance(raw, list) else str(raw).split(",")
    scopes: list[Scope] = []
    for item in items:
        parts = [x.strip() for x in str(item).split("|")]
        if len(parts) >= 2 and parts[0] and parts[1]:
            scopes.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    return {"enabled": bool(ps.get("poster_auto_book", False)), "per_day": num("poster_auto_book_per_day", 10, 1, HARD_DAILY_CAP),
            "days": num("poster_auto_book_days", 30, 1, 62), "scopes": scopes, "platforms": ["facebook"]}


def _scopes_booked_before() -> list[Scope]:
    from ..infra.db import fetch_all

    rows = fetch_all("""SELECT grade, subject, COUNT(*) AS n FROM social_posts
                        WHERE grade <> '' AND subject <> '' GROUP BY grade, subject ORDER BY n DESC LIMIT 6""") or []
    return [(str(r["grade"]), str(r["subject"]), "") for r in rows]


def auto_book(*, now: datetime | None = None, force: bool = False, dry: bool = False,
              seed: int | None = None, days: int | None = None) -> dict[str, Any]:
    """Top the calendar up: tomorrow to `days` ahead, `per_day` a day."""
    import random

    rules = auto_book_rules()
    if not (rules["enabled"] or force):
        return {"booked": False, "posts": 0, "notes": ["Auto-book is off."]}
    scopes = rules["scopes"] or _scopes_booked_before()
    if not scopes:
        return {"booked": False, "posts": 0, "notes": ["Nothing to book from: set the subjects to book (Auto-book)."]}
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(EAT).date()
    span = rules["days"] if days is None else max(1, int(days))
    days = _days_view(today + timedelta(days=1), today + timedelta(days=span), platforms=rules["platforms"],
                      per_day=rules["per_day"], now=now)
    out = _fill(days, scopes, per_day=rules["per_day"], gap_min=30, gap_max=60, platforms=rules["platforms"],
                ready_only=False, dry=dry, created_by=AUTO_BOOK, rng=random.Random(seed),
                full_note=f"The next {rules['days']} days are full at {rules['per_day']} a day.")
    return {**out, "scopes": [list(sc) for sc in scopes], "days_ahead": rules["days"], "per_day": rules["per_day"]}


def fresh_video(now: datetime, platform: str = "facebook", *, created_by: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """A finished video no post has ever used, booked for now — a new
    question each time, so nothing goes out twice."""
    from ..infra.db import fetch_all, fetch_one
    from . import social
    from .whiteboard import load

    # Every unused video is looked at, newest first: the newest are often the
    # ones being made again (not ready yet), and a ready one may sit behind them.
    made = fetch_all("""SELECT question_id FROM question_videos v WHERE kind = 'social'
                        AND NOT EXISTS (SELECT 1 FROM social_posts s WHERE s.question_id = v.question_id)
                        ORDER BY made_at DESC LIMIT 2000""") or []
    for row in made:
        qid = str(row["question_id"])
        try:
            st = social.status(qid)
            if st.get("status") != "ready":
                continue
            q = load(qid)
        except Exception:  # noqa: BLE001
            continue
        _plan_post(q, platform, now, created_by)
        post = fetch_one("SELECT * FROM social_posts WHERE post_id = :id", {"id": _post_id(qid, platform)})
        if post:
            return post, st
    return None, {}


_no_extra_until: dict[str, float] = {"t": 0.0}


def live_extra(now: datetime, rules: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Nothing booked is due: post a finished video no booking uses, live on
    Facebook, while today's `live_per_day` allows — the chance taken when the
    computer is on. Booked as it goes out, so the calendar shows it."""
    import time as _time

    from ..infra.db import fetch_one

    n = int(rules.get("live_per_day") or 0)
    if n <= 0 or not rules["enabled"] or "facebook" not in rules["platforms"] or _time.time() < _no_extra_until["t"]:
        return None, {}
    local = now.astimezone(EAT)
    start = local.replace(hour=int(rules["hours"]["start"][:2]), minute=int(rules["hours"]["start"][3:]), second=0, microsecond=0)
    end = local.replace(hour=int(rules["hours"]["end"][:2]), minute=int(rules["hours"]["end"][3:]), second=0, microsecond=0)
    if not (start <= local <= end):
        return None, {}
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    counts = fetch_one("""SELECT COUNT(*) FILTER (WHERE created_by = :x) AS extras, COUNT(*) AS actions,
                                 MAX(handed_at) AS last FROM social_posts WHERE handed_at >= :d""",
                       {"x": LIVE_EXTRA, "d": day_start}) or {}
    if int(counts.get("extras") or 0) >= n or int(counts.get("actions") or 0) >= rules["daily_cap"]:
        return None, {}
    last = fetch_one("SELECT MAX(handed_at) AS t FROM social_posts WHERE handed_at IS NOT NULL") or {}
    if last.get("t") and now - last["t"] < timedelta(minutes=rules["min_gap_minutes"]):
        return None, {}
    if fetch_one("SELECT 1 AS x FROM poster_state WHERE platform = 'facebook' AND NOT logged_in"):
        return None, {}
    post, st = fresh_video(now, "facebook", created_by=LIVE_EXTRA)
    if post:
        return post, st
    _no_extra_until["t"] = _time.time() + 15 * 60      # none ready: look again in a quarter of an hour
    return None, {}


# ── photo + video series ─────────────────────────────────────────────────────

SERIES_FULL = ("teaser", "question", "answer", "walkthrough")
SERIES_SHORT = ("question", "answer", "walkthrough")


def series_shape(photos: int, videos: int) -> list[tuple[str, ...]]:
    """A day's runs: full series (3 cards and the video) while the budget
    holds, a short one (question, answer, video) with what is left, and the
    remaining videos on their own. Pure."""
    runs: list[tuple[str, ...]] = []
    while photos >= 3 and videos >= 1:
        runs.append(SERIES_FULL)
        photos, videos = photos - 3, videos - 1
    while photos >= 2 and videos >= 1:
        runs.append(SERIES_SHORT)
        photos, videos = photos - 2, videos - 1
    runs += [("walkthrough",)] * max(0, videos)
    return runs


def interleave(rng: Any, runs: list[list[Any]]) -> list[Any]:
    """Merge the runs into one day: each run keeps its order, and which run
    goes next is random (longer runs a little more often, so a series is
    spread over the day rather than bunched at its end). Pure."""
    runs = [list(r) for r in runs if r]
    out: list[Any] = []
    while runs:
        weights = [len(r) for r in runs]
        pick = rng.choices(range(len(runs)), weights=weights)[0]
        out.append(runs[pick].pop(0))
        runs = [r for r in runs if r]
    return out


def _plan_step(q: dict[str, Any], platform: str, step: str, at: datetime, created_by: str) -> str:
    from ..infra.db import execute

    link = q.get("curriculum") or {}
    fmt = "video" if step == "walkthrough" else "photo"
    post_id = _post_id(q["question_id"], platform) if fmt == "video" else \
        "sp_" + hashlib.sha256(f"{q['question_id']}:{platform}:{step}".encode()).hexdigest()[:16]
    execute(
        """INSERT INTO social_posts (post_id, question_id, platform, grade, subject, sub_strand, scheduled_for,
                                     created_by, format, step)
           VALUES (:id, :qid, :platform, :grade, :subject, :ss, :at, :by, :fmt, :step)
           ON CONFLICT (post_id) DO UPDATE SET scheduled_for = EXCLUDED.scheduled_for, format = EXCLUDED.format,
               step = EXCLUDED.step, updated_at = NOW()
           WHERE social_posts.posted_at IS NULL""",
        {"id": post_id, "qid": q["question_id"], "platform": platform, "grade": str(link.get("grade") or ""),
         "subject": str(link.get("subject") or ""), "ss": str(link.get("sub_strand") or ""), "at": at,
         "by": created_by, "fmt": fmt, "step": step})
    return post_id


def book_series(grade: str, subject: str, sub_strand: str = "", *, days: int = 7, photos: int | None = None,
                videos: int | None = None, platform: str = "facebook", today: date | None = None,
                seed: int | None = None, dry: bool = False, created_by: str = "") -> dict[str, Any]:
    """Book the next `days` days as series: per day up to `photos` cards and
    `videos` videos (the Auto-post settings, 8 and 8), each question's steps
    in order — "Can you solve this?", the question, the answer, then its
    walkthrough — spread through the day among single videos. Questions with
    a figure go first. Cards and videos not made yet are queued."""
    import random

    from ..infra.db import fetch_all, fetch_one
    from . import question_rows, social, social_cards
    from .question_dna import question_dna_service

    rng = random.Random(seed)
    rules = poster_rules()
    photos = rules["photos_per_day"] if photos is None else max(0, int(photos))
    videos = rules["videos_per_day"] if videos is None else max(0, int(videos))
    if platform not in POSTER_PLATFORMS:
        raise ValueError("Pick one of: " + ", ".join(POSTER_PLATFORMS))
    if platform != "facebook":
        photos = 0                                 # the poster posts cards on Facebook only, for now
    shape = series_shape(photos, videos)
    per_day = sum(len(r) for r in shape)
    if not per_day:
        raise ValueError("Photos and videos a day are both 0.")
    notes: list[str] = []
    fits = len(day_times(rng, date.today(), per_day, rules))
    if fits < per_day:
        notes.append(f"{per_day} posts do not fit a day {rules['min_gap_minutes']} min apart between "
                     f"{rules['hours']['start']} and {rules['hours']['end']} — {fits} a day. Lower the gap "
                     "(Settings → Auto-post) for all of them.")
    today = today or datetime.now(EAT).date()
    last = fetch_one("""SELECT MAX(scheduled_for) AS t FROM social_posts WHERE platform = :p AND scheduled_for IS NOT NULL
                        AND status <> 'gave_up'""", {"p": platform}) or {}
    last_day = last["t"].astimezone(EAT).date() if last.get("t") else None
    first = max(today + timedelta(days=1), (last_day + timedelta(days=1)) if last_day else today)
    span = [first + timedelta(days=i) for i in range(max(1, days))]

    booked = {r["question_id"] for r in (fetch_all("SELECT DISTINCT question_id FROM social_posts WHERE platform = :p",
                                                   {"p": platform}) or [])}
    rows = question_dna_service.list_questions(grade=grade or None, subject=subject or None,
                                               sub_strand=sub_strand or None, limit=2000)
    pool = [q for q in question_rows.flatten_all(rows)
            if str(q.get("status") or "") not in ("needs_review", "rejected", "superseded")
            and str(q.get("question_id")) not in booked]
    rng.shuffle(pool)
    pool.sort(key=lambda q: not (isinstance(q.get("diagram"), dict) and q["diagram"].get("diagram_id")))

    def usable() -> dict[str, Any] | None:
        while pool:
            q = pool.pop(0)
            try:
                st = social.status(str(q["question_id"]), q)
            except Exception:  # noqa: BLE001
                continue
            if st.get("status") != "failed" and st.get("scenes"):
                q["_video"] = st.get("status")
                return q
        return None

    calendar: list[dict[str, Any]] = []
    chosen: dict[str, dict[str, Any]] = {}
    for day in span:
        runs: list[list[tuple[str, str]]] = []
        for run in shape:
            q = usable()
            if not q:
                break
            chosen[q["question_id"]] = q
            runs.append([(q["question_id"], step) for step in run])
        if not runs:
            notes.append("Not enough unbooked questions in this scope for more days — widen it or add questions.")
            break
        order = interleave(rng, runs)
        slots = day_times(rng, day, len(order), rules)
        posts = [{"question_id": qid, "step": step, "at": at} for (qid, step), at in zip(order, slots)]
        calendar.append({"date": day.isoformat(), "posts": posts})

    if not dry:
        for d in calendar:
            for p in d["posts"]:
                _plan_step(chosen[p["question_id"]], platform, p["step"], p["at"], created_by)
        for qid, q in chosen.items():
            try:
                if any(p["question_id"] == qid and p["step"] != "walkthrough" for d in calendar for p in d["posts"]):
                    social_cards.enqueue(qid, queued_by=created_by or "series")
                if q.get("_video") not in ("ready", "queued", "running"):
                    social.enqueue(qid, queued_by=created_by or "series")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not queue the media for %s: %s", qid, exc)
    count = lambda fmt: sum(1 for d in calendar for p in d["posts"] if (p["step"] == "walkthrough") == (fmt == "video"))  # noqa: E731
    return {"booked": not dry, "platform": platform, "first_day": calendar[0]["date"] if calendar else None,
            "last_day": calendar[-1]["date"] if calendar else None, "photos": count("photo"), "videos": count("video"),
            "questions": len(chosen),
            "days": [{"date": d["date"], "times": [f"{p['at'].astimezone(EAT):%H:%M} {p['step']}" for p in d["posts"]]}
                     for d in calendar], "notes": notes}


# ── starting again: every video with the pitch, every question out afresh ───

def relaunch(*, render_limit: int = 200, by: str = "") -> dict[str, Any]:
    """Every video made again with the platform pitch, and the questions that
    went out posted afresh: their posts are kept in social_posts_history and
    taken off, so booking treats each as never posted. Posts booked but not
    out stay booked; their videos are queued again, the soonest first."""
    from ..infra.db import execute, fetch_one
    from . import platform_settings, teacher

    platform_settings.set_many({"social_marketing": True}, updated_by=by or "relaunch")
    # The columns both tables have: social_posts grows (a migration adds one)
    # after the history table was cut from it.
    from ..infra.db import fetch_all

    cols = [r["column_name"] for r in fetch_all("""
        SELECT h.column_name FROM information_schema.columns h
        JOIN information_schema.columns p ON p.table_name = 'social_posts' AND p.column_name = h.column_name
             AND p.table_schema = h.table_schema
        WHERE h.table_name = 'social_posts_history' AND h.table_schema = current_schema()
        ORDER BY h.ordinal_position""") or []]
    names = ", ".join(f'"{c}"' for c in cols)
    moved = fetch_one(f"""WITH out AS (
                             INSERT INTO social_posts_history ({names}, archived_at, archived_why)
                             SELECT {", ".join(f'p."{c}"' for c in cols)}, NOW(), 'relaunch with the platform pitch'
                             FROM social_posts p
                             WHERE p.handed_at IS NOT NULL AND COALESCE(p.format, 'video') = 'video'
                               AND COALESCE(p.posted_at, NOW()) <= NOW()     -- out, not waiting in Facebook's scheduler
                             RETURNING post_id)
                         SELECT COUNT(*) AS n FROM out""") or {}
    execute("""DELETE FROM social_posts WHERE post_id IN (SELECT post_id FROM social_posts_history
                                                         WHERE archived_why = 'relaunch with the platform pitch')
               AND handed_at IS NOT NULL AND COALESCE(posted_at, NOW()) <= NOW()""")
    queued = teacher.render_now(teacher.mode() if teacher.mode() != "off" else "classroom", limit=render_limit,
                                pause_lessons=True, by=by or "relaunch")
    return {"archived_posts": int(moved.get("n") or 0), **queued}


# ── performance: which posts do best, and how each grows day by day ──────────

def performance(*, days: int = 14, sort: str = "views_per_day", now: datetime | None = None) -> dict[str, Any]:
    """Posts that are out, ranked by what they earn a day since they went out,
    each with its daily growth (views, reactions, comments, shares) from the
    poster's readings of its insights — the last reading each day, less the
    day before's."""
    from ..infra.db import fetch_all

    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=max(1, min(days, 90)))
    posts = fetch_all("""SELECT p.post_id, p.question_id, p.posted_at, p.url, p.marketing, p.boost_state, p.teacher,
                                p.views, p.likes AS reactions, p.comments, p.shares, p.score,
                                LEFT(COALESCE(q.content->>'question_text', ''), 140) AS question_text,
                                q.curriculum_link->>'subject' AS subject, q.curriculum_link->>'sub_strand' AS sub_strand,
                                -- How often the owner's own Macs opened the post: its thread, each reading
                                -- of its insights, each campaign comment or share, each like-back scan.
                                (CASE WHEN p.comments_state IN ('done', 'boost', 'complete') THEN 2
                                      WHEN p.comments_state = 'part' THEN 1 ELSE 0 END
                                 + COALESCE(p.boost_index, 0)
                                 + (SELECT COUNT(*) FROM post_insights i WHERE i.post_id = p.post_id)
                                 + (SELECT COUNT(*) FROM campaign_log c WHERE c.post_id = p.post_id)
                                 + (SELECT COUNT(*) FROM engage_log e WHERE e.target = p.post_id AND e.kind LIKE 'scan%')
                                ) AS own_visits
                         FROM social_posts p LEFT JOIN question_dna q ON q.question_id = p.question_id
                         WHERE p.platform = 'facebook' AND p.handed_at IS NOT NULL AND p.posted_at <= :now
                           AND COALESCE(p.format, 'video') = 'video'""", {"now": now}) or []
    readings = fetch_all("""SELECT DISTINCT ON (post_id, (at AT TIME ZONE 'Africa/Nairobi')::date)
                                   post_id, (at AT TIME ZONE 'Africa/Nairobi')::date AS day, views, reactions, comments, shares
                            FROM post_insights WHERE at >= :since - INTERVAL '1 day'
                            ORDER BY post_id, (at AT TIME ZONE 'Africa/Nairobi')::date, at DESC""", {"since": since}) or []
    by_post: dict[str, list[dict[str, Any]]] = {}
    for r in readings:
        by_post.setdefault(r["post_id"], []).append(r)
    keys = ("views", "reactions", "comments", "shares")
    out = []
    for p in posts:
        age = max(1.0, (now - p["posted_at"]).total_seconds() / 86400) if p.get("posted_at") else 1.0
        totals = {k: int(p.get(k) or 0) for k in keys}
        daily, prev = [], None
        for r in sorted(by_post.get(p["post_id"], []), key=lambda x: x["day"]):
            vals = {k: int(r.get(k) or 0) for k in keys}
            if prev is not None:
                daily.append({"day": r["day"].isoformat(), **{k: max(0, vals[k] - prev[k]) for k in keys}})
            prev = vals
        daily = [d for d in daily if d["day"] >= since.astimezone(EAT).date().isoformat()]
        engagement = totals["reactions"] + totals["comments"] + totals["shares"]
        last = daily[-1] if daily else {k: 0 for k in keys}
        before = daily[-2] if len(daily) > 1 else None
        row = {**{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in p.items()},
               "age_days": round(age, 1), "views_per_day": round(totals["views"] / age, 1),
               "engagement_per_day": round(engagement / age, 1),
               "today": {k: last.get(k, 0) for k in keys},
               "growing": (before is not None and (last.get("views", 0) + 0.0) > before.get("views", 0)),
               "daily": daily[-days:]}
        out.append(row)
    order = {"views_per_day": lambda r: r["views_per_day"], "engagement_per_day": lambda r: r["engagement_per_day"],
             "views_today": lambda r: r["today"]["views"], "comments": lambda r: int(r.get("comments") or 0),
             "newest": lambda r: r.get("posted_at") or ""}.get(sort, lambda r: r["views_per_day"])
    out.sort(key=order, reverse=True)
    # The account's own day by day: every post's growth added up.
    totals_by_day: dict[str, dict[str, int]] = {}
    for r in out:
        for d in r["daily"]:
            t = totals_by_day.setdefault(d["day"], {k: 0 for k in keys})
            for k in keys:
                t[k] += d[k]
    return {"posts": out, "days": [{"day": d, **v} for d, v in sorted(totals_by_day.items())], "sort": sort}


# ── the comment campaign ─────────────────────────────────────────────────────
#
# After a post's thread (choices, then the answer) every post that is out gets
# comments up to the floor (20) — the oldest first — and then the best
# performing posts (views a day, a few at a time) get more, up to the target
# (150), and a share to the groups once a day, until each reaches the views
# goal (1,000); then the next best takes its place. All of it within posting
# hours, a comment every one to four minutes, never more than the day's limit.

def campaign_rules() -> dict[str, Any]:
    from . import platform_settings as ps

    def num(key: str, default: int, lo: int, hi: int) -> int:
        try:
            return max(lo, min(int(ps.get(key, default) or default), hi))
        except (TypeError, ValueError):
            return default

    return {"enabled": bool(ps.get("campaign_enabled", False)), "floor": num("campaign_floor", 20, 0, 150),
            "target": num("campaign_target", 150, 1, 150), "views_goal": num("campaign_views_goal", 1000, 1, 10_000_000),
            "focus": num("campaign_focus_posts", 3, 1, 30), "per_post_day": num("campaign_per_post_day", 25, 1, 150),
            "daily": num("campaign_daily_limit", 300, 1, 5000), "share": bool(ps.get("campaign_share", True))}


def _campaign_gap(last: datetime) -> timedelta:
    n = int(hashlib.sha256(last.isoformat().encode()).hexdigest(), 16)
    return timedelta(seconds=60 + n % 180)


def _campaign_items(question_id: str) -> list[dict[str, str]]:
    from . import social
    from .whiteboard import load

    q = load(question_id)
    data, _, _, _, b, _ = social._prepare(q)
    return social.campaign_comments(q, data, b)


def campaign_next(now: datetime | None = None) -> dict[str, Any]:
    """The campaign's next comment (or share), or why none."""
    from ..infra.db import execute, fetch_all, fetch_one
    from . import social

    now = now or datetime.now(timezone.utc)
    r = campaign_rules()
    if not r["enabled"]:
        return {"job": None, "reason": "The comment campaign is off."}
    day = now.astimezone(EAT).replace(hour=0, minute=0, second=0, microsecond=0)
    today = fetch_one("""SELECT COUNT(*) FILTER (WHERE kind = 'comment' AND ok) AS n, MAX(at) AS last
                         FROM campaign_log WHERE at >= :d""", {"d": day}) or {}
    if int(today.get("n") or 0) >= r["daily"]:
        return {"job": None, "reason": f"Today's {r['daily']} campaign comments are up."}
    last = today.get("last")
    if last and now - last < _campaign_gap(last):
        return {"job": None, "reason": "Pacing: the next comment in a minute or two."}
    base = """SELECT p.post_id, p.question_id, p.platform, p.url, p.campaign_index, p.views,
                     COALESCE(p.views, 0) / GREATEST(EXTRACT(EPOCH FROM (:now - p.posted_at)) / 86400.0, 1) AS per_day,
                     (SELECT COUNT(*) FROM campaign_log c WHERE c.post_id = p.post_id AND c.at >= :d
                        AND c.kind = 'comment' AND c.ok) AS today,
                     (SELECT MAX(at) FROM campaign_log c WHERE c.post_id = p.post_id AND c.kind = 'share' AND c.ok) AS shared_at
              FROM social_posts p
              WHERE p.platform = 'facebook' AND COALESCE(p.format, 'video') = 'video' AND p.handed_at IS NOT NULL
                AND p.posted_at <= :ripe AND NOT p.campaign_done
                AND (p.comments_state IN ('done', 'complete', 'boost') OR (p.comments_state = 'failed' AND p.url <> ''))"""
    params = {"now": now, "d": day, "ripe": now - timedelta(minutes=30)}
    # Every post to the floor first, the oldest first (4 comments are its thread).
    row = fetch_one(base + """ AND p.campaign_index + 4 < :floor
                     AND (SELECT COUNT(*) FROM campaign_log c WHERE c.post_id = p.post_id AND c.at >= :d
                          AND c.kind = 'comment' AND c.ok) < :per
                     ORDER BY p.posted_at ASC LIMIT 1""", {**params, "floor": r["floor"], "per": r["per_post_day"]})
    phase = "floor"
    if not row:
        # Then the best performing posts, a few at a time, until the views goal.
        focus = fetch_all(base + """ AND p.campaign_index + 4 < :target AND COALESCE(p.views, 0) < :goal
                           ORDER BY per_day DESC NULLS LAST, p.posted_at DESC LIMIT :n""",
                          {**params, "target": r["target"], "goal": r["views_goal"], "n": r["focus"]}) or []
        if r["share"]:
            due = next((f for f in focus if not f.get("shared_at") or now - f["shared_at"] > timedelta(hours=24)), None)
            if due:
                groups = groups_for("facebook", now, poster_rules())
                if groups:
                    t = social.status(due["question_id"]).get("thread") or {}
                    return {"job": {"post_id": due["post_id"], "platform": "facebook", "stage": "share",
                                    "find": t.get("find") or "", "find_also": t.get("find_also") or [],
                                    "groups": groups, "comments": [], "image_url": ""}, "reason": ""}
        row = next((f for f in focus if int(f.get("today") or 0) < r["per_post_day"]), None)
        phase = "focus"
    if not row:
        return {"job": None, "reason": "Every post has its comments for today."}
    try:
        items = _campaign_items(row["question_id"])
    except Exception as exc:  # noqa: BLE001
        return {"job": None, "reason": f"Could not prepare the comments: {exc}"}
    k = int(row.get("campaign_index") or 0) + 4          # the thread's four come first in the list
    if k >= len(items):
        execute("UPDATE social_posts SET campaign_done = TRUE WHERE post_id = :id", {"id": row["post_id"]})
        return {"job": None, "reason": "That post has every comment it can carry."}
    item = items[k]
    t = social.status(row["question_id"]).get("thread") or {}
    return {"job": {"post_id": row["post_id"], "platform": row["platform"], "url": row.get("url") or "",
                    "find": t.get("find") or "", "find_also": t.get("find_also") or [], "stage": "campaign",
                    "phase": phase, "comments": [item["text"]], "image_url": item.get("image_url") or "",
                    "measure": False}, "reason": ""}


def campaign_result(post_id: str, *, stage: str, ok: bool, error: str = "", now: datetime | None = None,
                    groups: list[str] | None = None) -> None:
    from ..infra.db import execute

    now = now or datetime.now(timezone.utc)
    for g in (groups or [])[:20] if ok and stage == "share" else []:
        execute("""INSERT INTO poster_groups (platform, name, enabled, last_shared_for) VALUES ('facebook', :n, TRUE, :t)
                   ON CONFLICT (platform, name) DO UPDATE SET last_shared_for = :t""", {"n": str(g)[:200], "t": now})
    execute("INSERT INTO campaign_log (post_id, at, kind, ok) VALUES (:id, :t, :k, :ok)",
            {"id": post_id, "t": now, "k": "share" if stage == "share" else "comment", "ok": ok})
    if ok and stage == "campaign":
        execute("UPDATE social_posts SET campaign_index = campaign_index + 1, comments_error = '' WHERE post_id = :id",
                {"id": post_id})
    elif not ok:
        execute("UPDATE social_posts SET comments_error = :e WHERE post_id = :id", {"id": post_id, "e": error[:900]})


def campaign_status(now: datetime | None = None) -> dict[str, Any]:
    from ..infra.db import fetch_one

    now = now or datetime.now(timezone.utc)
    r = campaign_rules()
    day = now.astimezone(EAT).replace(hour=0, minute=0, second=0, microsecond=0)
    t = fetch_one("""SELECT COUNT(*) FILTER (WHERE kind = 'comment' AND ok) AS comments,
                            COUNT(*) FILTER (WHERE kind = 'share' AND ok) AS shares,
                            COUNT(*) FILTER (WHERE NOT ok) AS failed FROM campaign_log WHERE at >= :d""", {"d": day}) or {}
    p = fetch_one("""SELECT COUNT(*) FILTER (WHERE campaign_index + 4 < :floor) AS below_floor,
                            COUNT(*) FILTER (WHERE campaign_index + 4 >= :floor) AS at_floor,
                            COUNT(*) FILTER (WHERE COALESCE(views, 0) >= :goal) AS reached_goal
                     FROM social_posts WHERE platform = 'facebook' AND handed_at IS NOT NULL
                       AND COALESCE(format, 'video') = 'video'""", {"floor": r["floor"], "goal": r["views_goal"]}) or {}
    return {**r, "today": {k: int(t.get(k) or 0) for k in ("comments", "shares", "failed")},
            "posts": {k: int(p.get(k) or 0) for k in ("below_floor", "at_floor", "reached_goal")}}

