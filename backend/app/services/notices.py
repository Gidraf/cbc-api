"""Email the owner news about the videos: every 100 finished (how many are
booked, how many wait), and finished videos piling up unposted.

Checked every hour (celery beat). The first check only sets the starting
point, so turning it on never sends a backlog's worth at once. Sent with the
platform mailbox (services/mailer.py) to Settings → Auto-post → Email me
video news at.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("cbc-notices")


def _setting(key: str, default: Any) -> Any:
    from . import platform_settings

    try:
        return platform_settings.get(key, default)
    except Exception:  # noqa: BLE001
        return default


def _last(name: str) -> dict[str, Any] | None:
    from ..infra.db import fetch_one

    return fetch_one("SELECT sent_at, value FROM notices WHERE name = :n", {"n": name})


def _mark(name: str, when: datetime, value: dict[str, Any] | None = None) -> None:
    from ..infra.db import execute, to_json

    execute("""INSERT INTO notices (name, sent_at, value) VALUES (:n, :t, CAST(:v AS jsonb))
               ON CONFLICT (name) DO UPDATE SET sent_at = EXCLUDED.sent_at, value = EXCLUDED.value""",
            {"n": name, "t": when, "v": to_json(value or {})})


def facts(since: datetime, now: datetime) -> dict[str, int]:
    from ..infra.db import fetch_one

    row = fetch_one(
        """SELECT
             (SELECT COUNT(*) FROM question_videos v WHERE v.kind = 'social' AND v.made_at > :since) AS made,
             (SELECT COUNT(*) FROM question_videos v WHERE v.kind = 'social' AND v.made_at > :since
                AND EXISTS (SELECT 1 FROM social_posts s WHERE s.question_id = v.question_id)) AS made_booked,
             (SELECT COUNT(*) FROM question_videos v WHERE v.kind = 'social'
                AND NOT EXISTS (SELECT 1 FROM social_posts s WHERE s.question_id = v.question_id)) AS waiting,
             (SELECT COUNT(*) FROM social_posts WHERE posted_at IS NULL AND handed_at IS NULL
                AND status IN ('planned', 'failed')) AS booked_unposted,
             (SELECT COUNT(*) FROM social_posts WHERE scheduled_for >= :now AND scheduled_for < :week
                AND status <> 'gave_up') AS next_week,
             (SELECT COUNT(*) FROM jobs WHERE kind = 'social' AND status IN ('queued', 'running')) AS rendering,
             (SELECT COUNT(*) FROM social_posts WHERE posted_at >= :day AND posted_at <= :now) AS posted_today""",
        {"since": since, "now": now, "week": now + timedelta(days=7), "day": now - timedelta(days=1)}) or {}
    return {k: int(v or 0) for k, v in row.items()}


def _email(to: str, subject: str, lines: list[str], link: str) -> bool:
    from . import mailer

    body = "".join(f"<p style='margin:0 0 10px'>{html.escape(x)}</p>" for x in lines)
    if link:
        body += f"<p><a href='{html.escape(link, quote=True)}'>Open Auto-post</a></p>"
    page = (f"<html><body style='font-family:Arial,sans-serif;color:#1f2933'><h2 style='margin:0 0 14px'>"
            f"{html.escape(subject)}</h2>{body}</body></html>")
    return mailer.send(to, subject, "\n\n".join(lines + ([link] if link else [])), page)


def video_news(now: datetime | None = None) -> dict[str, Any]:
    """The hourly check: a milestone email, a surplus email, or nothing."""
    from . import email_links

    now = now or datetime.now(timezone.utc)
    to = str(_setting("notify_email", "") or "").strip()
    if not to:
        return {"sent": [], "reason": "No address set."}
    every = max(1, int(_setting("notify_every_videos", 100) or 100))
    surplus_at = max(1, int(_setting("notify_surplus_at", 20) or 20))
    link = (email_links.base_url() + "/play") if email_links.base_url() else ""
    sent: list[str] = []

    mark = _last("videos_made")
    if mark is None:
        _mark("videos_made", now)                       # the starting point: no backlog email
    else:
        f = facts(mark["sent_at"], now)
        if f["made"] >= every:
            lines = [f"{f['made']} new videos are finished since {mark['sent_at']:%d %b %H:%M} UTC.",
                     f"{f['made_booked']} of them are booked; {f['waiting']} finished videos are not booked or posted yet.",
                     f"{f['booked_unposted']} posts are booked and waiting; the next 7 days hold {f['next_week']}.",
                     f"{f['rendering']} more videos are being made. {f['posted_today']} went out in the last 24 hours."]
            if _email(to, f"{f['made']} new videos are ready", lines, link):
                _mark("videos_made", now, f)
                sent.append("videos_made")

    f = facts(now, now)
    last = _last("videos_waiting")
    if f["waiting"] >= surplus_at and (last is None or now - last["sent_at"] >= timedelta(hours=20)):
        lines = [f"{f['waiting']} finished videos are waiting — not booked, not posted.",
                 "Post them with Post now, raise videos a day in Auto-book, or press Schedule all.",
                 f"{f['booked_unposted']} posts are booked; the next 7 days hold {f['next_week']}."]
        if _email(to, f"{f['waiting']} videos are waiting to be posted", lines, link):
            _mark("videos_waiting", now, f)
            sent.append("videos_waiting")
    return {"sent": sent}
