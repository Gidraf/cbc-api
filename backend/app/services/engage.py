"""Liking back the people who engage with the owner's posts.

The poster reads the comments under the owner's recent posts (`scan`): it
likes each comment and notes who wrote it. Then, one person at a time
(`like_person`), it visits each new commenter and likes a few of their own
recent posts. It never comments on anyone else's post — a comment can land
on a sad one; that waits for an AI that reads the context.

Facebook limits automated liking, so all of it counts against one daily
number (Settings → Auto-post → Likes a day, 40 to start, 300 at most), only
within posting hours, with a random wait of one to four minutes between
actions — paced like a person, not a burst.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

EAT = timezone(timedelta(hours=3))
SCAN_EVERY = timedelta(hours=6)
SCAN_DAYS = 14
TRIES = 3


def rules() -> dict[str, Any]:
    from . import platform_settings as ps

    def num(key: str, default: int, lo: int, hi: int) -> int:
        try:
            return max(lo, min(int(ps.get(key, default) or default), hi))
        except (TypeError, ValueError):
            return default

    return {"enabled": bool(ps.get("engage_enabled", False)), "per_day": num("engage_likes_per_day", 40, 1, 300),
            "per_person": num("engage_likes_per_person", 2, 1, 5)}


def _gap(now: datetime) -> timedelta:
    """One to four minutes, different each time but the same for a given minute."""
    n = int(hashlib.sha256(now.strftime("%Y%m%d%H%M").encode()).hexdigest(), 16)
    return timedelta(seconds=60 + n % 180)


def today(now: datetime) -> dict[str, int]:
    from ..infra.db import fetch_one

    day = now.astimezone(EAT).replace(hour=0, minute=0, second=0, microsecond=0)
    row = fetch_one("""SELECT COALESCE(SUM(likes), 0) AS likes, MAX(at) AS last FROM engage_log WHERE at >= :d""",
                    {"d": day}) or {}
    people = fetch_one("SELECT COUNT(*) AS n FROM engage_people") or {}
    waiting = fetch_one(f"SELECT COUNT(*) AS n FROM engage_people WHERE last_liked_at IS NULL AND tries < {TRIES}") or {}
    return {"likes": int(row.get("likes") or 0), "people": int(people.get("n") or 0),
            "waiting": int(waiting.get("n") or 0), "_last": row.get("last")}


def next_action(now: datetime | None = None) -> dict[str, Any]:
    """The next thing to do: read a post's comments, like a person's posts, or nothing (and why)."""
    from ..infra.db import fetch_one
    from . import social, social_export

    now = now or datetime.now(timezone.utc)
    r = rules()
    if not r["enabled"]:
        return {"action": None, "reason": "Liking back is off."}
    pr = social_export.poster_rules()
    local = now.astimezone(EAT)
    start = local.replace(hour=int(pr["hours"]["start"][:2]), minute=int(pr["hours"]["start"][3:]), second=0, microsecond=0)
    end = local.replace(hour=int(pr["hours"]["end"][:2]), minute=int(pr["hours"]["end"][3:]), second=0, microsecond=0)
    if not (start <= local <= end):
        return {"action": None, "reason": "Outside posting hours."}
    t = today(now)
    left = r["per_day"] - t["likes"]
    if left <= 0:
        return {"action": None, "reason": f"Today's {r['per_day']} likes are given."}
    if t["_last"] and now - t["_last"] < _gap(t["_last"]):
        return {"action": None, "reason": "Pacing: the next like comes in a minute or two."}
    person = fetch_one(f"""SELECT profile_url, name FROM engage_people WHERE last_liked_at IS NULL AND tries < {TRIES}
                           ORDER BY first_seen LIMIT 1""")
    if person:
        return {"action": {"kind": "like_person", "url": person["profile_url"], "name": person["name"],
                           "count": min(r["per_person"], left)}, "reason": ""}
    post = fetch_one("""SELECT post_id, question_id, url FROM social_posts
                        WHERE platform = 'facebook' AND COALESCE(format, 'video') = 'video' AND handed_at IS NOT NULL
                          AND posted_at <= :ripe AND posted_at >= :since
                          AND (scanned_at IS NULL OR scanned_at < :stale)
                        ORDER BY scanned_at NULLS FIRST, posted_at DESC LIMIT 1""",
                     {"ripe": now - timedelta(minutes=15), "since": now - timedelta(days=SCAN_DAYS), "stale": now - SCAN_EVERY})
    if not post:
        return {"action": None, "reason": "Every recent post was read in the last six hours."}
    try:
        find = (social.status(post["question_id"]).get("thread") or {}).get("find") or ""
    except Exception:  # noqa: BLE001
        find = ""
    return {"action": {"kind": "scan", "post_id": post["post_id"], "url": post.get("url") or "", "find": find,
                       "count": min(15, left)}, "reason": ""}


def record(kind: str, *, target: str = "", likes: int = 0, people: list[dict[str, str]] | None = None,
           error: str = "", now: datetime | None = None) -> dict[str, Any]:
    """How an action went: the likes it gave, the people it found."""
    from ..infra.db import execute

    now = now or datetime.now(timezone.utc)
    execute("INSERT INTO engage_log (at, kind, target, likes) VALUES (:t, :k, :g, :n)",
            {"t": now, "k": kind if not error else f"{kind}-failed", "g": target[:500], "n": max(0, int(likes))})
    added = 0
    if kind == "scan":
        execute("UPDATE social_posts SET scanned_at = :t WHERE post_id = :id", {"t": now, "id": target})
        for p in (people or [])[:60]:
            url = profile_url(str(p.get("url") or ""))
            if not url.startswith("https://") or "facebook.com" not in url:
                continue
            execute("""INSERT INTO engage_people (profile_url, name, seen_on, first_seen) VALUES (:u, :n, :p, :t)
                       ON CONFLICT (profile_url) DO NOTHING""",
                    {"u": url, "n": str(p.get("name") or "")[:120], "p": target, "t": now})
            added += 1
    elif kind == "like_person":
        if error:
            execute("UPDATE engage_people SET tries = tries + 1, note = :e WHERE profile_url = :u",
                    {"u": target, "e": error[:300]})
        else:
            execute("UPDATE engage_people SET last_liked_at = :t, likes = likes + :n, note = '' WHERE profile_url = :u",
                    {"u": target, "t": now, "n": max(0, int(likes))})
    return {"ok": not error, "people_added": added}


def profile_url(href: str) -> str:
    """A person's profile, tidied: tracking dropped, profile.php keeps its id."""
    from urllib.parse import parse_qs, urlparse

    u = urlparse(href.strip())
    if not u.scheme.startswith("http") or "facebook.com" not in u.netloc:
        return ""
    host = "https://www.facebook.com"
    if u.path.rstrip("/").endswith("profile.php"):
        pid = (parse_qs(u.query).get("id") or [""])[0]
        return f"{host}/profile.php?id={pid}" if pid.isdigit() else ""
    path = u.path.rstrip("/")
    if not path or path.count("/") > 1 or path.split("/")[1] in ("groups", "reel", "watch", "photo", "story.php", "hashtag", "pages"):
        return ""
    return host + path


# ── the owner's own posts: which get the comment thread ──────────────────────

def recent_posts(days: int = 14, now: datetime | None = None) -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    now = now or datetime.now(timezone.utc)

    rows = fetch_all("""SELECT p.post_id, p.question_id, p.posted_at, p.comments_state, p.comments_error, p.scanned_at,
                               LEFT(COALESCE(q.content->>'question_text', ''), 140) AS question_text
                        FROM social_posts p LEFT JOIN question_dna q ON q.question_id = p.question_id
                        WHERE p.platform = 'facebook' AND COALESCE(p.format, 'video') = 'video' AND p.handed_at IS NOT NULL
                          AND p.posted_at <= :now AND p.posted_at >= :since
                        ORDER BY p.posted_at DESC LIMIT 200""", {"now": now, "since": now - timedelta(days=max(1, days))}) or []
    for r in rows:
        for k, v in list(r.items()):
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat()
    return rows


def queue_comments(post_ids: list[str], now: datetime | None = None) -> int:
    """The chosen posts get the comment thread (again, if it failed before)."""
    from ..infra.db import fetch_one

    now = now or datetime.now(timezone.utc)
    ids = [str(p) for p in post_ids][:200]
    if not ids:
        return 0
    row = fetch_one("""WITH up AS (UPDATE social_posts SET comments_state = 'pending', comments_next_at = :t,
                                          comments_attempts = 0, comments_error = ''
                                   WHERE post_id = ANY(:ids) AND comments_state IN ('', 'failed') RETURNING 1)
                       SELECT COUNT(*) AS n FROM up""", {"t": now, "ids": ids}) or {}
    return int(row.get("n") or 0)
