"""Devcast: the developer series for LinkedIn — its catalogue and calendar,
and narrated VS Code–style videos rendered from a script."""
from __future__ import annotations

import csv
import io
import re
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from ..errors import raise_api_error
from ..services.auth import AuthContext, require_roles

router = APIRouter(prefix="/api/v1/devcast", tags=["Devcast (developer videos)"])

MAKERS = require_roles("admin", "operator", "developer")


def _script(episode_id: str) -> dict[str, Any]:
    from ..services.devcast_series import SCRIPTS

    if episode_id not in SCRIPTS:
        raise_api_error("NOT_FOUND", f"No script written for {episode_id} yet.")
    return SCRIPTS[episode_id]


def _checked(script: dict[str, Any]) -> dict[str, Any]:
    from ..services import devcast

    try:
        return devcast.validate(script)
    except ValueError as exc:
        raise_api_error("VALIDATION_FAILED", str(exc))
        return {}


@router.get("/series")
def series(_: AuthContext = Depends(MAKERS)) -> dict[str, Any]:
    from ..services.devcast_series import SCRIPTS, SERIES

    return {"series": [{"id": s["id"], "name": s["name"], "app": s["app"], "built_on": s["built_on"],
                        "episodes": len(s["episodes"]),
                        "scripts": sum(1 for k in SCRIPTS if k.startswith(s["id"] + "-"))} for s in SERIES],
            "total": sum(len(s["episodes"]) for s in SERIES)}


@router.get("/episodes")
def episodes(series_id: str = Query("", alias="series"), _: AuthContext = Depends(MAKERS)) -> dict[str, Any]:
    from ..services.devcast_series import episodes as all_episodes

    items = all_episodes(series_id)
    if series_id and not items:
        raise_api_error("NOT_FOUND", f"No series {series_id}.")
    return {"episodes": items, "count": len(items)}


@router.get("/calendar.csv")
def calendar_csv(start: str = Query("", description="First posting day, YYYY-MM-DD (default tomorrow)"),
                 per_day: int = Query(2, ge=1, le=5),
                 times: str = Query("07:30,12:30,17:30,20:00,21:30", description="24-hour EAT times"),
                 _: AuthContext = Depends(MAKERS)) -> Response:
    """All 300 posts with a date and time — for a scheduler's bulk upload."""
    from ..services.devcast_series import calendar

    try:
        first = date.fromisoformat(start) if start else date.today() + timedelta(days=1)
    except ValueError:
        raise_api_error("VALIDATION_FAILED", "start is a date such as 2026-10-20.")
        return Response()
    slots = [t.strip() for t in times.split(",") if t.strip()]
    if len(slots) < per_day or not all(re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", t) for t in slots):
        raise_api_error("VALIDATION_FAILED", f"Give at least {per_day} 24-hour times, such as 07:30,12:30.")
    rows = calendar(first, per_day=per_day, times=slots)
    fields = ["number", "date", "time", "timezone", "platform", "series_name", "episode", "of", "kind", "title",
              "hook", "has_script", "id", "post", "facebook_post"]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    name = f"linkedin-devcast-{first:%Y%m%d}-{len(rows)}posts.csv"
    return Response(buffer.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/scripts/{episode_id}")
def get_script(episode_id: str, _: AuthContext = Depends(MAKERS)) -> dict[str, Any]:
    return _script(episode_id)


@router.get("/scripts/{episode_id}/preview.html")
def script_preview(episode_id: str, voice: str = Query(""), voiced: bool = Query(True),
                   autoplay: bool = Query(False), _: AuthContext = Depends(MAKERS)) -> HTMLResponse:
    from ..services import devcast

    return HTMLResponse(devcast.live_page(_script(episode_id), voice, voiced=voiced, autoplay=autoplay))


@router.post("/preview", response_class=HTMLResponse)
def preview(script: dict[str, Any] = Body(...), voice: str = Query(""), voiced: bool = Query(False),
            _: AuthContext = Depends(MAKERS)) -> HTMLResponse:
    """Any script, live — to try a new episode before it is rendered."""
    from ..services import devcast

    return HTMLResponse(devcast.live_page(_checked(script), voice, voiced=voiced))


@router.get("/scripts/{episode_id}/video")
def script_video(episode_id: str, voice: str = Query(""), _: AuthContext = Depends(MAKERS)) -> dict[str, Any]:
    from ..services import devcast

    return devcast.status(_script(episode_id), voice)


@router.post("/scripts/{episode_id}/video")
def make_script_video(episode_id: str, voice: str = Query(""), auth: AuthContext = Depends(MAKERS)) -> dict[str, Any]:
    from ..services import devcast
    from .play import _may_make_videos

    _may_make_videos(auth)
    return devcast.enqueue(_script(episode_id), voice=voice, queued_by=str(auth.subject or ""))


@router.post("/render")
def render(script: dict[str, Any] = Body(...), voice: str = Query(""),
           auth: AuthContext = Depends(MAKERS)) -> dict[str, Any]:
    """Queue any script's MP4; returns its state, with the URL once made."""
    from ..services import devcast
    from .play import _may_make_videos

    _may_make_videos(auth)
    return devcast.enqueue(_checked(script), voice=voice, queued_by=str(auth.subject or ""))


class BookDevcast(BaseModel):
    start: str = ""                  # first day, YYYY-MM-DD (default tomorrow, or after the last booked)
    per_day: int = 2
    times: list[str] = []
    platforms: list[str] = ["linkedin", "facebook"]
    dry: bool = False


@router.post("/book")
def book(payload: BookDevcast, auth: AuthContext = Depends(MAKERS)) -> dict[str, Any]:
    """Put the written episodes on the auto-poster's calendar for LinkedIn and
    Facebook, with developer captions; their videos are queued."""
    from ..services.devcast_series import book as book_episodes
    from .play import _may_make_videos

    _may_make_videos(auth)
    if not 1 <= payload.per_day <= 5:
        raise_api_error("VALIDATION_FAILED", "per_day is 1–5.")
    times = [t.strip() for t in payload.times if t.strip()]
    if times and (len(times) < payload.per_day or not all(re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", t) for t in times)):
        raise_api_error("VALIDATION_FAILED", f"Give at least {payload.per_day} 24-hour times, such as 07:30.")
    try:
        first = date.fromisoformat(payload.start) if payload.start else None
        return book_episodes(start=first, per_day=payload.per_day, times=times or None, platforms=payload.platforms,
                             dry=payload.dry, created_by=str(auth.subject or ""))
    except ValueError as exc:
        raise_api_error("VALIDATION_FAILED", str(exc))
        return {}


@router.get("/posts")
def posts(platform: str = Query(""), _: AuthContext = Depends(MAKERS)) -> dict[str, Any]:
    """The developer posts: when each goes out, where it went, how it did."""
    from ..services import social_export

    rows = social_export.list_posts(subject="Developers", platform=platform)
    return {"posts": rows, "summary": social_export.summary(rows)}
