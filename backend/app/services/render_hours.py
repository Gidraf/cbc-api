"""When the render helpers on Macs may take videos.

One schedule for every Mac, per weekday:

    always   any time
    hours    between `from` and `to` (24-hour, the Mac's own clock; "22:00"–"06:00" runs past midnight)
    idle     only while nobody has touched the Mac for `idle_minutes`
    off      never

Stored as JSON in the `render_schedule` setting; the helper reads it every
minute, so a change reaches every Mac within a minute. A video already being
made is always finished.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MODES = ("always", "hours", "idle", "off")
DEFAULT = {"days": {d: {"mode": "always", "from": "18:00", "to": "23:59"} for d in DAYS}, "idle_minutes": 10}


def clean(raw: Any) -> dict[str, Any]:
    """A schedule as stored, made whole and valid; anything unreadable: always."""
    try:
        got = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw if isinstance(raw, dict) else {})
    except ValueError:
        got = {}
    out = {"days": {}, "idle_minutes": DEFAULT["idle_minutes"]}
    try:
        out["idle_minutes"] = max(1, min(int(got.get("idle_minutes", DEFAULT["idle_minutes"])), 240))
    except (TypeError, ValueError):
        pass
    days = got.get("days") if isinstance(got.get("days"), dict) else {}
    for d in DAYS:
        day = days.get(d) if isinstance(days.get(d), dict) else {}
        mode = day.get("mode") if day.get("mode") in MODES else "always"
        hhmm = lambda v, dflt: v if isinstance(v, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v) else dflt  # noqa: E731
        out["days"][d] = {"mode": mode, "from": hhmm(day.get("from"), "18:00"), "to": hhmm(day.get("to"), "23:59")}
    return out


def current() -> dict[str, Any]:
    from . import platform_settings

    try:
        return clean(platform_settings.get("render_schedule", ""))
    except Exception:  # noqa: BLE001
        return clean("")


def allowed(schedule: dict[str, Any], now: datetime, idle_seconds: float | None) -> tuple[bool, str]:
    """May a Mac take a video now? And why not, in a few words."""
    day = schedule["days"][DAYS[now.weekday()]]
    mode = day["mode"]
    if mode == "always":
        return True, ""
    if mode == "off":
        return False, "not today"
    if mode == "idle":
        need = schedule["idle_minutes"] * 60
        if idle_seconds is None:
            return False, "cannot tell whether the Mac is idle"
        return (idle_seconds >= need, "" if idle_seconds >= need else f"the Mac is in use (waits {schedule['idle_minutes']} idle minutes)")
    t = now.strftime("%H:%M")
    start, end = day["from"], day["to"]
    inside = start <= t <= end if start <= end else (t >= start or t <= end)
    return inside, "" if inside else f"outside {start}–{end}"
