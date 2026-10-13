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
            "daily_cap": num("poster_daily_cap", 30, HARD_DAILY_CAP),
            "platform_cap": num("poster_platform_cap", 8, HARD_DAILY_CAP),
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
    for p in (posted_today if live_today is None else live_today):
        per_platform[p["platform"]] = per_platform.get(p["platform"], 0) + 1
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
        rows = fetch_all(
            """SELECT * FROM social_posts WHERE posted_at IS NULL
               AND (:id = '' OR post_id = :id) AND (:p = '' OR platform = :p)
               ORDER BY scheduled_for NULLS LAST LIMIT 20""", {"id": post_id, "p": platform}) or []
        chosen, st = None, {}
        for row in rows:                  # the first whose video is made
            st = social.status(row["question_id"])
            if st.get("status") == "ready":
                chosen = row
                break
        why = ("" if chosen else "Nothing booked for that platform yet — book the next weeks first." if not rows
               else "The booked posts' videos are still being made — try again shortly.")
    else:
        day_start = now.astimezone(EAT).replace(hour=0, minute=0, second=0, microsecond=0)
        # The day's actions — a post going out live, or a video handed to a
        # platform's scheduler — are what the caps and the gap count.
        posted_today = fetch_all("SELECT platform FROM social_posts WHERE handed_at >= :d", {"d": day_start}) or []
        live_today = fetch_all("""SELECT platform FROM social_posts WHERE posted_at >= :d AND posted_at < :e""",
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
                st = social.status(chosen["question_id"])
                if st.get("status") == "ready":
                    break
                waiting += 1
            candidates = [c for c in candidates if c["post_id"] != chosen["post_id"]]
            chosen = None
        if not chosen and waiting:
            why = f"{waiting} due post(s) are waiting for their videos to be made."
    if not chosen:
        return {"post": None, "reason": why, "rules": rules}
    from .whiteboard import load

    q_text = social.display(load(chosen["question_id"]).get("question_text") or "")
    title = (f"{social.brand().get('hook') or 'Can you solve this?'} {q_text}")[:90].rstrip() + " #Shorts"
    when = chosen.get("scheduled_for")
    reserved = [str(g) for g in (chosen.get("groups") or [])]
    ahead = (not reserved and chosen["platform"] in rules["ahead_platforms"] and isinstance(when, datetime)
             and when - now > AHEAD_LEAD and when - now <= timedelta(days=rules["ahead_days"]))
    groups = [] if ahead else (reserved or groups_for(chosen["platform"], now, rules))
    return {"post": {"post_id": chosen["post_id"], "platform": chosen["platform"], "question_id": chosen["question_id"],
                     "video_url": st["url"], "thumbnail_url": st.get("thumbnail_url"), "caption": st.get("post") or "",
                     "title": title, "attempts": chosen.get("attempts") or 0,
                     "schedule_at": when.astimezone(EAT).isoformat() if ahead else "",
                     "groups": groups}, "reason": "", "rules": rules}


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
        elif (r["platform"] in rules["ahead_platforms"] and when - now > AHEAD_LEAD
              and when - now <= timedelta(days=rules["ahead_days"])):
            ahead.append({**r, "ahead": True})
    return due + ahead


def groups_for(platform: str, at: datetime, rules: dict[str, Any]) -> list[str]:
    """The group (if any) this post is also shared to: `group_shares_per_day`
    a day — with two, one before 13:00 and one after — each to the ticked
    group rested longest, and never the same group within `group_rest_days`."""
    from ..infra.db import fetch_all, fetch_one

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
    rest = timedelta(days=rules.get("group_rest_days", 7))
    row = fetch_one(
        """SELECT name FROM poster_groups WHERE platform = :p AND enabled
           AND (last_shared_for IS NULL OR last_shared_for <= :cut OR last_shared_for >= :after)
           ORDER BY last_shared_for NULLS FIRST, name LIMIT 1""",
        {"p": platform, "cut": at - rest, "after": at + rest})
    return [row["name"]] if row else []


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
        if groups:
            row = fetch_one("SELECT platform, posted_at FROM social_posts WHERE post_id = :id", {"id": post_id}) or {}
            for g in groups:
                execute("""INSERT INTO poster_groups (platform, name, enabled, last_shared_for) VALUES (:p, :n, TRUE, :t)
                           ON CONFLICT (platform, name) DO UPDATE SET last_shared_for = GREATEST(
                               COALESCE(poster_groups.last_shared_for, EXCLUDED.last_shared_for), EXCLUDED.last_shared_for)""",
                        {"p": row.get("platform") or "facebook", "n": g, "t": row.get("posted_at")})
    else:
        execute("""UPDATE social_posts SET status = CASE WHEN attempts + 1 >= :tries THEN 'gave_up' ELSE 'failed' END,
                   attempts = attempts + 1, last_error = :e, last_attempt_at = NOW(), updated_at = NOW() WHERE post_id = :id""",
                {"id": post_id, "e": error[:900], "tries": MAX_ATTEMPTS})
    return {"post_id": post_id, "ok": ok, "scheduled": scheduled, "groups": groups, "destinations": places}


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
            "handed_today": int(handed.get("n") or 0), "waiting": int(waiting.get("n") or 0),
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
