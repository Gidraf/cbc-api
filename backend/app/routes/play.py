"""Play: every question as a game, a simulator and a narrated walkthrough.

Open to every signed-in role — the studio's `user` included — because this
is what a school buys alongside the papers. The specs come from the play
engine; every number in them comes from the maths engine.
"""
from __future__ import annotations

import html
import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from ..errors import raise_api_error
from ..services.auth import AuthContext, require_roles

logger = logging.getLogger("cbc-play")
router = APIRouter(prefix="/api/v1/play", tags=["Play"])

ANY = require_roles("admin", "operator", "reviewer", "developer", "user", "poster")
# The question content (games, walkthroughs, videos): people, not the poster's key.
CONTENT = require_roles("admin", "operator", "reviewer", "developer", "user")
_HIDDEN = ("needs_review", "rejected", "superseded")


def _gate(auth: AuthContext, question_id: str) -> None:
    """A parent's or teacher's account opens a question it owns (bought or
    wrote) or every question on the video plan; staff open all."""
    from ..services import entitlements

    if not entitlements.may_open(auth.subject, auth.role, question_id):
        raise_api_error("PAYMENT_REQUIRED", entitlements.locked_reason(auth.role),
                        detail={"question_id": question_id, "plan": entitlements.plan_status(auth.subject, auth.role)})


def _open_ids(auth: AuthContext, ids: list[str]) -> set[str] | None:
    """Of these, the ones this account has open already (owned, or opened
    with a free play) — None meaning all of them (staff, the pass)."""
    from ..services import entitlements

    if entitlements.staff(auth.role) or entitlements.has_video_plan(auth.subject, auth.role):
        return None
    return entitlements.owned_ids(auth.subject, ids) | entitlements.opened_ids(auth.subject, ids)


def _with_videos(ids: list[str], kind: str = "lesson") -> set[str]:
    from ..infra.db import fetch_all

    if not ids:
        return set()
    rows = fetch_all("SELECT question_id FROM question_videos WHERE kind = :k AND question_id = ANY(:ids)",
                     {"k": kind, "ids": ids}) or []
    return {r["question_id"] for r in rows}


def _has_figure(q: dict[str, Any]) -> bool:
    binding = q.get("diagram")
    return isinstance(binding, dict) and bool(binding.get("diagram_id") or binding.get("svg_markup"))


def _bank(grade: str, subject: str, sub_strand: str, limit: int) -> list[dict[str, Any]]:
    from ..services import question_rows
    from ..services.question_dna import question_dna_service

    rows = question_dna_service.list_questions(grade=grade or None, subject=subject or None,
                                               sub_strand=sub_strand or None, limit=limit)
    return [q for q in question_rows.flatten_all(rows) if str(q.get("status") or "") not in _HIDDEN]


def _one(question_id: str, owner: str = "") -> dict[str, Any]:
    from ..services import user_questions

    try:
        return user_questions.load(question_id, owner)
    except Exception:  # noqa: BLE001
        raise_api_error("NOT_FOUND", f"No question {question_id}.")
    return {}


@router.get("/catalog")
def video_catalog(auth: AuthContext = Depends(CONTENT)) -> dict[str, Any]:
    """The grades and subjects that have videos, with how many — what Play
    lists first, so nobody picks a topic with nothing to watch."""
    from ..infra.db import fetch_all

    rows = fetch_all("""SELECT d.curriculum_link->>'grade' AS grade, d.curriculum_link->>'subject' AS subject,
                               MIN(d.grade_ordinal) AS ordinal, COUNT(*) AS videos
                        FROM question_videos v JOIN question_dna d ON d.question_id = v.question_id
                        WHERE v.kind = 'lesson' AND d.status <> ALL(:hidden)
                        GROUP BY 1, 2 ORDER BY MIN(d.grade_ordinal) NULLS LAST, 2""", {"hidden": list(_HIDDEN)}) or []
    return {"items": [{"grade": r["grade"], "subject": r["subject"], "videos": int(r["videos"])} for r in rows]}


@router.get("/items")
def playable_items(grade: str = Query(""), subject: str = Query(""), sub_strand: str = Query(""),
                   kind: str = Query("", description="number_line | balance | bodmas | fraction_bar | choice"),
                   figures: Literal["any", "only", "none"] = Query("any", description="only: with a figure; none: without"),
                   videos: bool = Query(False, description="only questions that have a video"),
                   limit: int = Query(200, ge=1, le=1000),
                   auth: AuthContext = Depends(CONTENT)) -> dict[str, Any]:
    """Items in a scope — what Play lists. Each says how it plays, whether it
    has a figure and a video, and whether this account has it open
    (`locked`: no free plays left and not owned)."""
    from ..services import entitlements, play_engine, user_questions

    out = []
    counts: dict[str, int] = {}
    pool = _bank(grade, subject, sub_strand, limit)
    if auth.role == "user":
        pool += user_questions.list_for(auth.subject, grade=grade, subject=subject)
    if figures != "any":
        pool = [q for q in pool if _has_figure(q) == (figures == "only")]
    ids = [str(q.get("question_id")) for q in pool]
    with_video = _with_videos(ids)
    if videos:
        pool = [q for q in pool if str(q.get("question_id")) in with_video]
    opened = _open_ids(auth, ids)
    left = None if opened is None else entitlements.free_left(auth.subject)
    for q in pool:
        play = play_engine.spec_for(q)
        primary = play.get("primary") or {}
        k = primary.get("kind")
        has_video = str(q.get("question_id")) in with_video
        if kind and k != kind:
            continue
        if not k and not has_video and not _has_figure(q):
            continue                         # nothing to play and nothing to watch
        if k:
            counts[k] = counts.get(k, 0) + 1
        is_open = opened is None or str(q.get("question_id")) in opened
        out.append({"question_id": q.get("question_id"), "question_text": q.get("question_text"),
                    "sub_strand": (q.get("curriculum") or {}).get("sub_strand"), "kind": k or "watch",
                    "also_choice": bool(play.get("choice")) and k != "choice",
                    "key_agrees": play.get("key_agrees"), "status": q.get("status"),
                    "has_video": has_video, "has_figure": _has_figure(q), "open": is_open,
                    "locked": not is_open and not left})
    return {"items": out, "counts": counts, "free_left": left}


@router.get("/items/{question_id}")
def play_item(question_id: str, auth: AuthContext = Depends(CONTENT)) -> dict[str, Any]:
    """One item: its game/simulator spec and its walkthrough scenes."""
    from ..services import play_engine

    _gate(auth, question_id)
    q = _one(question_id, auth.subject)
    return {"question": {k: q.get(k) for k in ("question_id", "question_text", "stimulus_context", "question_type",
                                               "diagram", "curriculum")},
            "play": play_engine.spec_for(q),
            "walkthrough": play_engine.walkthrough(q, grade=str((q.get("curriculum") or {}).get("grade") or ""))}


@router.get("/session")
def game_session(grade: str = Query(...), subject: str = Query(...), sub_strand: str = Query(""),
                 mode: str = Query("mixed", description="mixed | choice | number_line | balance | bodmas | fraction_bar"),
                 count: int = Query(10, ge=1, le=50), seed: str = Query(""),
                 auth: AuthContext = Depends(CONTENT)) -> dict[str, Any]:
    """A round: `count` items played as `mode`, shuffled by `seed` — from the
    questions this account may open."""
    import random

    from ..services import play_engine, user_questions

    pool = _bank(grade, subject, sub_strand, 600)
    if auth.role == "user":
        pool += user_questions.list_for(auth.subject, grade=grade, subject=subject)
    opened = _open_ids(auth, [str(q.get("question_id")) for q in pool])
    if opened is not None:
        from ..services import entitlements

        # What is open already, then as many new ones as free plays are left
        # (each one dealt spends a play, and stays open after).
        left = entitlements.free_left(auth.subject)
        random.Random(seed or None).shuffle(pool)
        fresh = [q for q in pool if str(q.get("question_id")) not in opened][:max(0, min(left, count))]
        fresh = [q for q in fresh if entitlements.may_open(auth.subject, auth.role, str(q.get("question_id")))]
        pool = [q for q in pool if str(q.get("question_id")) in opened] + fresh
    random.Random(seed or None).shuffle(pool)
    items = play_engine.session(pool, mode=mode, count=count)
    if not items:
        if opened is not None:
            raise_api_error("NOT_FOUND", "None of your questions here plays as a game yet. Buy a paper on this topic, "
                                         "write your own questions, or take the video plan to play them all.")
        raise_api_error("NOT_FOUND", f"Nothing in the bank plays as '{mode}' for this scope yet.")
    return {"mode": mode, "count": len(items), "items": items}


class CheckRequest(BaseModel):
    expected: Any
    given: Any


@router.post("/check")
def check(payload: CheckRequest, _: AuthContext = Depends(CONTENT)) -> dict[str, Any]:
    """Whether a learner's typed value is the value: 3/4, 0.75 and 6/8 agree."""
    from ..services import play_engine

    return {"correct": play_engine.check_answer(payload.expected, payload.given)}


@router.get("/items/{question_id}/walkthrough.html")
def walkthrough_page(question_id: str, voice: str = Query("en-KE"), autoplay: bool = Query(True),
                     auth: AuthContext = Depends(CONTENT)) -> HTMLResponse:
    """A self-playing walkthrough, for a projector or a share link: GSAP
    animates each scene while the device's voice reads it, and the next
    scene starts when the sentence ends."""
    from ..services import play_engine

    _gate(auth, question_id)
    q = _one(question_id, auth.subject)
    data = play_engine.walkthrough(q)
    return HTMLResponse(walkthrough_html(data, title=str(q.get("question_text") or "")[:80], voice=voice,
                                         autoplay=autoplay))


@router.get("/items/{question_id}/whiteboard.html")
def whiteboard_page(question_id: str, autoplay: bool = Query(False), voice: str = Query(""),
                    auth: AuthContext = Depends(CONTENT)) -> HTMLResponse:
    """The item worked on a whiteboard: a marker writes each line, circles
    the side sum, draws the number line or the scale, boxes the answer and
    strikes out the trap — voiced by the server in the console's chosen
    voice, the same as the MP4. Self-contained, so it works offline on a
    projector."""
    from ..services import whiteboard

    _gate(auth, question_id)
    q = _one(question_id, auth.subject)
    data, voice, title = whiteboard._script_for(q, _voice(voice))
    return HTMLResponse(whiteboard.live_page(data, title=title, voice=voice, autoplay=autoplay))


@router.get("/items/{question_id}/video")
def video_status(question_id: str, voice: str = Query(""), auth: AuthContext = Depends(CONTENT)) -> dict[str, Any]:
    """The MP4 for this item: ready, queued, running, failed or none. Only
    staff see its file's address (and fetch it signed in); everyone else
    watches it through /watch."""
    from ..services import entitlements, whiteboard

    out = whiteboard.status(question_id, _one(question_id, auth.subject), _voice(voice))
    if not entitlements.staff(auth.role):
        # Staff fetch the file with their sign-in (the asset route checks it);
        # everyone else never sees its address, and streams it.
        for key in ("url", "thumbnail_url", "job_id"):
            out.pop(key, None)
    out["watch"] = entitlements.may_open(auth.subject, auth.role, question_id, spend=False)
    return out


@router.get("/items/{question_id}/watch")
def watch_link(question_id: str, voice: str = Query(""), auth: AuthContext = Depends(CONTENT)) -> dict[str, Any]:
    """A short-lived link that streams this item's video in the page — on the
    pass, for a question owned, or with a free play (staff always)."""
    from ..services import entitlements, rate_limit, streaming, whiteboard

    rate_limit.hit("watch_owner", auth.subject)
    st = whiteboard.status(question_id, _one(question_id, auth.subject), _voice(voice))
    if st.get("status") != "ready":
        raise_api_error("NOT_FOUND", "This question's video is not made yet.")
    _gate(auth, question_id)            # the pass, owning it, or one free play
    return streaming.watch_link(auth.subject, whiteboard.object_name(question_id, st["key"]))


def _may_make_videos(auth: AuthContext) -> None:
    """Rendering is minutes of server time per video, so for now only an
    admin, or someone named in Settings → Video makers, may start one."""
    from ..services import platform_settings

    raw = platform_settings.get("video_makers", ["gidraf"]) or []
    names = raw if isinstance(raw, list) else str(raw).replace(";", ",").split(",")
    makers = {str(m).strip().lower() for m in names if str(m).strip()}
    # Trusted by name: so a video maker's name can never be signed up for
    # by someone else (routes/auth.py refuses it), and a developer's "api"
    # account is never one.
    if auth.role == "admin" or (auth.role != "api" and str(auth.subject or "").lower() in makers):
        return
    raise_api_error("FORBIDDEN", "Only an admin or a named video maker can make videos for now.")


@router.post("/items/{question_id}/video")
def make_video(question_id: str, voice: str = Query(""), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Queue the whiteboard video. Made once per version of the item and kept."""
    from ..services import whiteboard

    _may_make_videos(auth)
    _one(question_id)
    return whiteboard.enqueue(question_id, queued_by=str(getattr(auth, "subject", "") or "whiteboard"),
                              voice=_voice(voice))


class VideoBatch(BaseModel):
    grade: str
    subject: str
    sub_strand: str = ""
    kind: str = ""          # only items that play as this kind; "" for all
    limit: int = 40


STAFF = require_roles("admin", "operator", "reviewer", "developer")


@router.post("/videos")
def make_videos(payload: VideoBatch, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """A video for every item in a scope — a topic's worth of content."""
    import hashlib

    _may_make_videos(auth)
    from ..services import play_engine, whiteboard

    items = _bank(payload.grade, payload.subject, payload.sub_strand, 1000)
    if payload.kind:
        items = [q for q in items if (play_engine.spec_for(q).get("primary") or {}).get("kind") == payload.kind]
    items = items[:max(1, min(payload.limit, 200))]
    if not items:
        raise_api_error("NOT_FOUND", "No items in this scope to draw.")
    batch = "vid_" + hashlib.sha256(
        f"{payload.grade}{payload.subject}{payload.sub_strand}{payload.kind}".encode()).hexdigest()[:10]
    counts: dict[str, int] = {}
    out = []
    for q in items:
        qid = str(q.get("question_id") or "")
        try:
            got = whiteboard.enqueue(qid, queued_by=str(getattr(auth, "subject", "") or "whiteboard"), batch_id=batch)
        except Exception as exc:  # noqa: BLE001
            got = {"question_id": qid, "status": "failed", "error": str(exc)[:200]}
        counts[got["status"]] = counts.get(got["status"], 0) + 1
        out.append({k: got.get(k) for k in ("question_id", "status", "url", "job_id", "error")})
    return {"batch_id": batch, "counts": counts, "items": out}


@router.get("/videos")
def list_videos(grade: str = Query(...), subject: str = Query(...), sub_strand: str = Query(""),
                limit: int = Query(60, ge=1, le=300), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Every item in a scope with its video's state — the content library."""
    _may_make_videos(auth)            # production tools: file links and posts
    from ..services import whiteboard

    out = []
    for q in _bank(grade, subject, sub_strand, limit):
        qid = str(q.get("question_id") or "")
        try:
            st = whiteboard.status(qid, q)
        except Exception as exc:  # noqa: BLE001
            st = {"question_id": qid, "status": "failed", "error": str(exc)[:200]}
        out.append({**st, "question_text": str(q.get("question_text") or "")[:160]})
    return {"items": out, "ready": sum(1 for v in out if v["status"] == "ready")}


# ── social posts ──────────────────────────────────────────────────────────────

@router.get("/items/{question_id}/social.html")
def social_page(question_id: str, voice: str = Query(""),
                teacher: Literal["", "off", "female", "male", "alternate", "classroom"] = Query(""),
                auth: AuthContext = Depends(ANY)) -> HTMLResponse:
    """The vertical cut, live and voiced — what the post's video will be.
    `teacher` previews it with a woman or a man teacher, or none, whatever
    Settings says; empty follows Settings."""
    _may_make_videos(auth)            # production tools: file links and posts
    from ..services import social

    return HTMLResponse(social.live_page(_one(question_id), _voice(voice), teacher_mode=teacher or None))


@router.get("/items/{question_id}/social")
def social_status(question_id: str, voice: str = Query(""), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """The social post for this item: its video, thumbnail and post text, or where they are."""
    _may_make_videos(auth)            # production tools: file links and posts
    from ..services import social

    return social.status(question_id, _one(question_id), _voice(voice))


@router.post("/items/{question_id}/social")
def make_social(question_id: str, voice: str = Query(""), fresh: bool = Query(False),
                auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Queue the social video. `fresh`: make it again as Settings say now —
    with the teacher — even if one made before the teacher still serves."""
    from ..services import social

    _may_make_videos(auth)
    _one(question_id)
    return social.enqueue(question_id, queued_by=str(getattr(auth, "subject", "") or "social"), voice=_voice(voice),
                          fresh=fresh, priority=5 if fresh else 0)


@router.post("/social")
def make_socials(payload: VideoBatch, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """A social post for every item in a scope — a fortnight of daily posts."""
    import hashlib

    _may_make_videos(auth)
    from ..services import play_engine, social

    items = _bank(payload.grade, payload.subject, payload.sub_strand, 1000)
    if payload.kind:
        items = [q for q in items if (play_engine.spec_for(q).get("primary") or {}).get("kind") == payload.kind]
    items = items[:max(1, min(payload.limit, 200))]
    if not items:
        raise_api_error("NOT_FOUND", "No items in this scope to post.")
    batch = "soc_" + hashlib.sha256(
        f"{payload.grade}{payload.subject}{payload.sub_strand}{payload.kind}".encode()).hexdigest()[:10]
    counts: dict[str, int] = {}
    out = []
    for q in items:
        qid = str(q.get("question_id") or "")
        try:
            got = social.enqueue(qid, queued_by=str(getattr(auth, "subject", "") or "social"), batch_id=batch)
        except Exception as exc:  # noqa: BLE001
            got = {"question_id": qid, "status": "failed", "error": str(exc)[:200]}
        counts[got["status"]] = counts.get(got["status"], 0) + 1
        out.append({k: got.get(k) for k in ("question_id", "status", "url", "job_id", "error")})
    return {"batch_id": batch, "counts": counts, "items": out}


class QueueBatch(BaseModel):
    grade: str
    subject: str
    sub_strands: list[str] = []      # none: the whole subject
    count: int = 50
    mix: bool = True                  # mix the topics
    label: str = ""


@router.post("/social/batches")
def queue_video_batch(payload: QueueBatch, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Queue up to `count` new social videos — only questions with no video
    made or on its way — as one batch to follow."""
    from ..services import video_batches

    _may_make_videos(auth)
    if not 1 <= payload.count <= 500:
        raise_api_error("VALIDATION_FAILED", "A batch is 1–500 videos.")
    return video_batches.queue(payload.grade, payload.subject, payload.sub_strands, count=payload.count, mix=payload.mix,
                               label=payload.label, by=str(getattr(auth, "subject", "") or ""))


@router.get("/social/batches")
def video_batches_status(limit: int = Query(20, ge=1, le=100), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import video_batches

    _may_make_videos(auth)
    return video_batches.list_batches(limit)


@router.get("/social/drive")
def videos_on_drive(auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Whether Google Drive is set up, what has moved there, what is moving."""
    from ..services import drive_store

    _may_make_videos(auth)
    return drive_store.summary()


@router.post("/social/drive/move")
def move_videos_to_drive(auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Move finished videos to Google Drive now, rather than at the next half hour."""
    from ..services import drive_store

    _may_make_videos(auth)
    if not drive_store.configured():
        raise_api_error("VALIDATION_FAILED", "Google Drive is not set up: add GOOGLE_DRIVE_CLIENT_ID, "
                                             "GOOGLE_DRIVE_CLIENT_SECRET and GOOGLE_DRIVE_REFRESH_TOKEN to .env "
                                             "(backend/scripts/drive_auth.py makes the token).")
    return drive_store.enqueue(queued_by=str(getattr(auth, "subject", "") or "console")) or {}


@router.post("/social/batches/{batch_id}/cancel")
def cancel_video_batch(batch_id: str, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import video_batches

    _may_make_videos(auth)
    return {"cancelled": video_batches.cancel(batch_id)}


@router.post("/social/batches/{batch_id}/retry")
def retry_video_batch(batch_id: str, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import video_batches

    _may_make_videos(auth)
    return {"retried": video_batches.retry(batch_id)}


@router.get("/social")
def list_socials(grade: str = Query(...), subject: str = Query(...), sub_strand: str = Query(""),
                 limit: int = Query(60, ge=1, le=300), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Every item in a scope with its social post — ready to download and paste."""
    _may_make_videos(auth)            # production tools: file links and posts
    from ..services import social

    out = []
    for q in _bank(grade, subject, sub_strand, limit):
        qid = str(q.get("question_id") or "")
        try:
            st = social.status(qid, q)
        except Exception as exc:  # noqa: BLE001
            st = {"question_id": qid, "status": "failed", "error": str(exc)[:200]}
        out.append({**st, "question_text": str(q.get("question_text") or "")[:160]})
    return {"items": out, "ready": sum(1 for v in out if v["status"] == "ready")}


OPERATORS = require_roles("admin", "operator")


@router.post("/social/asset")
async def social_asset(kind: str = Form(..., description="logo | music"), file: UploadFile = File(...),
                       auth: AuthContext = Depends(OPERATORS)) -> dict[str, Any]:
    """The logo (PNG or SVG) or the background music (MP3) for social videos."""
    import hashlib

    from ..infra.storage import object_storage
    from ..services import platform_settings, whiteboard

    payload = await file.read()
    if kind == "logo":
        is_svg = payload.lstrip()[:1] == b"<" and b"<svg" in payload[:2000]
        if not (whiteboard.png_size(payload) or is_svg):
            raise_api_error("VALIDATION_FAILED", "Send the logo as a PNG or an SVG.")
        ext, ctype, limit, key = ("svg" if is_svg else "png"), ("image/svg+xml" if is_svg else "image/png"), 2, "social_logo_url"
    elif kind == "music":
        if not (payload[:3] == b"ID3" or payload[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
            raise_api_error("VALIDATION_FAILED", "Send the music as an MP3.")
        ext, ctype, limit, key = "mp3", "audio/mpeg", 15, "social_music_url"
    else:
        raise_api_error("VALIDATION_FAILED", "kind is logo or music.")
        return {}
    if len(payload) > limit * 1024 * 1024:
        raise_api_error("VALIDATION_FAILED", f"Keep the {kind} under {limit} MB.")
    name = f"social/assets/{kind}-{hashlib.sha256(payload).hexdigest()[:16]}.{ext}"
    url = object_storage.save_bytes(name, payload, ctype)
    if url.startswith("local://"):
        raise_api_error("STORAGE_UPLOAD_FAILED", "Object storage refused the file — is MinIO up?")
    platform_settings.set_many({key: url}, updated_by=str(getattr(auth, "subject", "") or ""))
    return {"kind": kind, "url": url}


@router.delete("/social/asset")
def clear_social_asset(kind: str = Query(...), auth: AuthContext = Depends(OPERATORS)) -> dict[str, Any]:
    from ..services import platform_settings

    key = {"logo": "social_logo_url", "music": "social_music_url"}.get(kind)
    if not key:
        raise_api_error("VALIDATION_FAILED", "kind is logo or music.")
    platform_settings.set_many({key: ""}, updated_by=str(getattr(auth, "subject", "") or ""))
    return {"kind": kind, "url": None}


@router.get("/social/brand")
def social_brand(_: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import platform_settings, social

    return {**social.brand(), "voice": str(platform_settings.get("narration_voice", "") or ""),
            "rate": str(platform_settings.get("narration_rate", "-8%") or "-8%")}


class BrandUpdate(BaseModel):
    name: str | None = None
    handle: str | None = None
    website: str | None = None
    cta: str | None = None
    hook: str | None = None
    countdown: int | None = None
    hashtags: str | None = None
    bg_from: str | None = None
    bg_to: str | None = None
    accent: str | None = None
    text: str | None = None
    voice: str | None = None
    rate: str | None = None


@router.put("/social/brand")
def save_social_brand(payload: BrandUpdate, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """The look and voice of every video: brand, colours, hook, default voice."""
    import re as _re

    from ..services import platform_settings

    _may_make_videos(auth)
    keys = {"name": "social_brand_name", "handle": "social_handle", "website": "social_website", "cta": "social_cta",
            "hook": "social_hook", "countdown": "social_countdown_seconds", "hashtags": "social_hashtags",
            "bg_from": "social_bg_from", "bg_to": "social_bg_to", "accent": "social_accent", "text": "social_text",
            "voice": "narration_voice", "rate": "narration_rate"}
    values: dict[str, Any] = {}
    for field, key in keys.items():
        value = getattr(payload, field)
        if value is None:
            continue
        if field in ("bg_from", "bg_to", "accent", "text") and value and not _re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", str(value)):
            raise_api_error("VALIDATION_FAILED", f"{field} must be a hex colour such as #facc15.")
        if field == "voice" and value and not _re.fullmatch(r"[a-z]{2}-[A-Z]{2}-\w+", str(value)):
            raise_api_error("VALIDATION_FAILED", "Choose a voice from the list.")
        values[key] = value
    platform_settings.set_many(values, updated_by=str(getattr(auth, "subject", "") or ""))
    return social_brand(auth)


@router.get("/voices")
def voices(_: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """The voices a video can be narrated in — English and Kiswahili."""
    from ..services.math_engine.tts_service import available_voices

    return {"voices": available_voices()}


def _voice(voice: str) -> str:
    """A per-item voice, if it looks like one; else the default applies."""
    import re as _re

    return voice if _re.fullmatch(r"[a-z]{2}-[A-Z]{2}-\w+", voice or "") else ""


@router.get("/hand")
def hand_photo(_: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """The hand the whiteboard draws with: the uploaded photo, or none (the drawn hand)."""
    from ..services import platform_settings

    url = str(platform_settings.get("whiteboard_hand_image", "") or "")
    return {"image": url or None, "tip": str(platform_settings.get("whiteboard_hand_tip", "") or "") or None,
            "width": int(platform_settings.get("whiteboard_hand_width", 300) or 300)}


@router.post("/hand")
async def set_hand_photo(file: UploadFile | None = File(None), tip_x: float = Form(...), tip_y: float = Form(...),
                         width: int = Form(300), auth: AuthContext = Depends(OPERATORS)) -> dict[str, Any]:
    """A photo of a real hand holding a pen — a PNG cut out on a transparent
    background — and where its pen's tip is, in the photo's pixels. Sent
    without a file, it moves the tip or resizes the photo already in use."""
    import hashlib

    from ..infra.storage import object_storage
    from ..services import platform_settings, whiteboard

    values: dict[str, Any] = {"whiteboard_hand_tip": f"{tip_x:.1f},{tip_y:.1f}",
                              "whiteboard_hand_width": max(80, min(int(width), 900))}
    if file is not None:
        payload = await file.read()
        size = whiteboard.png_size(payload)
        if not size:
            raise_api_error("VALIDATION_FAILED", "Send a PNG — cut out on a transparent background.")
        if len(payload) > 6 * 1024 * 1024:
            raise_api_error("VALIDATION_FAILED", "Keep the hand photo under 6 MB.")
        name = f"whiteboard/hand-{hashlib.sha256(payload).hexdigest()[:16]}.png"
        url = object_storage.save_bytes(name, payload, "image/png")
        if url.startswith("local://"):
            raise_api_error("STORAGE_UPLOAD_FAILED", "Object storage refused the photo — is MinIO up?")
        values["whiteboard_hand_image"] = url
        w, h = size
        if not (0 <= tip_x <= w and 0 <= tip_y <= h):
            raise_api_error("VALIDATION_FAILED", f"The tip ({tip_x:.0f},{tip_y:.0f}) is outside the {w}×{h} photo.")
    elif not platform_settings.get("whiteboard_hand_image", ""):
        raise_api_error("VALIDATION_FAILED", "Upload a hand photo first.")
    platform_settings.set_many(values, updated_by=str(getattr(auth, "subject", "") or ""))
    whiteboard._hand_bytes.cache_clear()
    return hand_photo(auth)


@router.delete("/hand")
def clear_hand_photo(auth: AuthContext = Depends(OPERATORS)) -> dict[str, Any]:
    """Back to the drawn hand."""
    from ..services import platform_settings

    platform_settings.set_many({"whiteboard_hand_image": "", "whiteboard_hand_tip": ""},
                               updated_by=str(getattr(auth, "subject", "") or ""))
    return hand_photo(auth)


def walkthrough_html(data: dict[str, Any], *, title: str = "", voice: str = "en-KE", autoplay: bool = True) -> str:
    payload = json.dumps(data).replace("</", "<\\/")
    return _PAGE.replace("__TITLE__", html.escape(title or "Walkthrough")) \
        .replace("__DATA__", payload).replace("__VOICE__", html.escape(voice)) \
        .replace("__AUTOPLAY__", "true" if autoplay else "false")


_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>__TITLE__</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"></script>
<style>
 :root{--ink:#14213d;--accent:#1f7a5c;--warn:#b5651d;--bg:#fbfaf6}
 body{margin:0;background:var(--bg);color:var(--ink);font:20px/1.45 Georgia,serif;display:flex;flex-direction:column;min-height:100vh}
 #stage{flex:1;display:flex;align-items:center;justify-content:center;padding:24px;text-align:center}
 .card{max-width:960px;width:100%}
 .big{font-size:42px;font-family:"Cambria Math","STIX Two Math",Georgia,serif;letter-spacing:.02em}
 .op{background:#ffe9a8;border-radius:6px;padding:0 6px}
 .why{margin-top:18px;color:#3b4a6b;font-style:italic}
 .opt{display:inline-block;border:2px solid var(--ink);border-radius:10px;padding:8px 18px;margin:6px;font-size:26px}
 .opt.ok{border-color:var(--accent);background:#e3f4ec}.opt.no{border-color:var(--warn);background:#fbeee2}
 #bar{display:flex;gap:10px;align-items:center;padding:10px 16px;background:#fff;border-top:1px solid #ddd;font:15px system-ui,sans-serif}
 #say{flex:1;color:#333}
 button{font:inherit;padding:6px 14px;border-radius:8px;border:1px solid #bbb;background:#fff;cursor:pointer}
 svg text{font-family:system-ui,sans-serif}
</style></head><body>
<div id="stage"><div class="card" id="card"></div></div>
<div id="bar"><button id="play">▶ Play</button><button id="prev">◀</button><button id="next">▶▶</button>
<span id="count"></span><span id="say"></span></div>
<script>
const DATA = __DATA__; const VOICE = "__VOICE__"; const AUTOPLAY = __AUTOPLAY__;
const card = document.getElementById("card"), sayEl = document.getElementById("say");
let i = 0, playing = false;

function esc(s){return String(s??"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]))}
function plain(s){return esc(String(s??"").replace(/\$([^$]*)\$/g,"$1").replace(/\\times/g,"×").replace(/\\div/g,"÷").replace(/\\left|\\right/g,"").replace(/\\[a-z]+/g,"").replace(/[{}]/g,""))}

function numberLine(spec, upto, highlightFrom, highlightTo){
  const W=900,H=180,x0=40,x1=W-40,lo=spec.min,hi=spec.max,X=v=>x0+(v-lo)*(x1-x0)/(hi-lo);
  let s=`<svg viewBox="0 0 ${W} ${H}" width="100%"><line x1="${x0}" y1="120" x2="${x1}" y2="120" stroke="#14213d" stroke-width="3"/>`;
  for(let v=lo; v<=hi; v+=spec.tick){s+=`<line x1="${X(v)}" y1="112" x2="${X(v)}" y2="128" stroke="#14213d"/>`;
    if((v-lo)%(spec.tick*(hi-lo>40?5:1))===0) s+=`<text x="${X(v)}" y="150" text-anchor="middle" font-size="14">${v}</text>`;}
  const pts=spec.points.slice(0,upto+1);
  pts.forEach((p,k)=>{ if(k>0){const a=X(pts[k-1]),b=X(p),m=(a+b)/2;
    s+=`<path class="arc${k}" d="M${a},110 Q${m},${30} ${b},110" fill="none" stroke="${k===upto?'#1f7a5c':'#9fb4c7'}" stroke-width="3"/>
       <text x="${m}" y="${40}" text-anchor="middle" font-size="16" fill="#1f7a5c">${spec.moves[k-1]>0?'+':''}${spec.moves[k-1]}</text>`;}});
  const at=pts[pts.length-1];
  s+=`<circle id="dot" cx="${X(at)}" cy="120" r="10" fill="#1f7a5c"/><text x="${X(at)}" y="95" text-anchor="middle" font-size="18" font-weight="bold">${at}</text></svg>`;
  return s;
}

function fractionBars(spec, phase){
  const bar=(n,d,color,y)=>{let s="";const w=760/d;for(let k=0;k<d;k++)s+=`<rect x="${70+k*w}" y="${y}" width="${w}" height="40" fill="${k<n?color:'#fff'}" stroke="#14213d"/>`;return s;};
  const [a,b]=spec.first,[c,d]=spec.second; const L=spec.common;
  let s=`<svg viewBox="0 0 900 260" width="100%">`;
  if(phase==="start"){s+=bar(a,b,"#9bd3b8",30)+bar(c,d,"#f4c27a",110);}
  else{s+=bar(spec.first_as[0],L,"#9bd3b8",30)+bar(spec.second_as[0],L,"#f4c27a",110);
    if(phase==="result"){const [rn,rd]=spec.result; s+=`<text x="450" y="230" text-anchor="middle" font-size="30" font-weight="bold">${rn}/${rd}</text>`;}}
  return s+`</svg>`;
}

function balanceSvg(spec, upto){
  const moves=spec.moves.slice(0,upto).map(m=>`${m.op} ${m.value}`).join("  ");
  return `<svg viewBox="0 0 900 260" width="100%"><polygon points="450,200 430,240 470,240" fill="#14213d"/>
   <line id="beam" x1="150" y1="200" x2="750" y2="200" stroke="#14213d" stroke-width="6"/>
   <rect x="160" y="120" width="250" height="70" rx="10" fill="#e3f4ec" stroke="#1f7a5c"/><text x="285" y="165" text-anchor="middle" font-size="30">${esc(spec.left)}</text>
   <rect x="490" y="120" width="250" height="70" rx="10" fill="#e3f4ec" stroke="#1f7a5c"/><text x="615" y="165" text-anchor="middle" font-size="30">${esc(spec.right)}</text>
   ${moves?`<text x="450" y="60" text-anchor="middle" font-size="24" fill="#b5651d">both sides: ${esc(moves)}</text>`:""}</svg>`;
}

function render(scene){
  const s=scene, k=s.scene; let h="";
  if(k==="title") h=`${s.context?`<div class="why">${plain(s.context)}</div>`:""}<div class="big" style="font-size:30px">${plain(s.text)}</div>`;
  else if(k==="setup") h=`<div class="why">The situation as one calculation</div><div class="big">${plain(s.expression)}</div>`;
  else if(k==="rewrite"){const st=s.step; h=`<div class="big" id="before">${plain(st.before)}</div>
     <div class="big" style="margin-top:14px"><span class="op">${st.left} ${st.op} ${st.right}</span> = <b>${st.result}</b></div>
     <div class="big" id="after" style="margin-top:14px;color:#1f7a5c">= ${plain(st.after)}</div><div class="why">${esc(st.why)}</div>`;}
  else if(k==="number_line_start") h=numberLine(s.spec,0);
  else if(k==="number_line_jump") h=numberLine(s.spec, s.spec.points.indexOf(s.to)>0?s.spec.points.indexOf(s.to):s.spec.points.length-1)+`<div class="why">${s.move>0?"+":""}${s.move}</div>`;
  else if(k==="fraction_bars") h=fractionBars(s.spec,s.phase);
  else if(k==="balance_start") h=balanceSvg(s.spec,0);
  else if(k==="balance_move") h=balanceSvg(s.spec, s.spec.moves.indexOf(s.move)+1)+`<div class="why">${esc(s.move.why)}</div>`;
  else if(k==="balance_done") h=`<div class="big">${esc(s.spec.variable)} = ${esc(s.spec.target)}</div>`;
  else if(k==="answer") h=`<div class="opt ok">${s.option?esc(s.option)+". ":""}${plain(s.text)}</div>`;
  else if(k==="trap") h=`<div class="opt no">${esc(s.option)}. ${plain(s.text)}</div>`;
  card.innerHTML=h;
  gsap.from(card.children,{y:24,opacity:0,duration:.6,stagger:.15,ease:"power2.out"});
  if(k==="rewrite"){gsap.from("#after",{opacity:0,x:-30,delay:.9,duration:.6});}
  if(k==="number_line_jump"){const arcs=card.querySelectorAll("path");const last=arcs[arcs.length-1];
     if(last){const len=last.getTotalLength();last.style.strokeDasharray=len;gsap.fromTo(last,{strokeDashoffset:len},{strokeDashoffset:0,duration:1.1});}
     gsap.from("#dot",{scale:0,transformOrigin:"center",delay:1,duration:.4});}
  if(k==="balance_move") gsap.fromTo("#beam",{rotation:-4,transformOrigin:"450px 200px"},{rotation:0,duration:1.2,ease:"elastic.out(1,.4)"});
}

function pickVoice(){const vs=speechSynthesis.getVoices();return vs.find(v=>v.lang===VOICE)||vs.find(v=>v.lang.startsWith(VOICE.slice(0,2)))||null;}
function speak(text, done){
  sayEl.textContent=text;
  if(!("speechSynthesis" in window)){setTimeout(done, Math.max(2500, text.split(" ").length*380));return;}
  speechSynthesis.cancel(); const u=new SpeechSynthesisUtterance(text); const v=pickVoice(); if(v) u.voice=v; u.rate=.95;
  u.onend=()=>setTimeout(done,500); u.onerror=()=>setTimeout(done,1500); speechSynthesis.speak(u);
}
function show(n){i=Math.max(0,Math.min(DATA.scenes.length-1,n));document.getElementById("count").textContent=`${i+1}/${DATA.scenes.length}`;render(DATA.scenes[i]);
  if(playing) speak(DATA.scenes[i].say, ()=>{ if(!playing) return; if(i<DATA.scenes.length-1) show(i+1); else {playing=false;document.getElementById("play").textContent="▶ Play";}});
  else sayEl.textContent=DATA.scenes[i].say;}
document.getElementById("play").onclick=()=>{playing=!playing;document.getElementById("play").textContent=playing?"❚❚ Pause":"▶ Play";if(playing) show(i); else speechSynthesis.cancel();};
document.getElementById("next").onclick=()=>{speechSynthesis.cancel();show(i+1)};
document.getElementById("prev").onclick=()=>{speechSynthesis.cancel();show(i-1)};
show(0); if(AUTOPLAY){ /* browsers need a gesture before speaking; the first click starts it */ }
</script></body></html>"""


# ── scheduling and performance ───────────────────────────────────────────────

@router.get("/social/export.zip")
def export_social(grade: str = Query(...), subject: str = Query(...), sub_strand: str = Query(""),
                  start: str = Query("", description="First posting day, YYYY-MM-DD (default tomorrow)"),
                  per_day: int = Query(1, ge=1, le=6), times: str = Query("19:00", description="e.g. 07:00,19:00"),
                  platforms: str = Query("tiktok,instagram,youtube"), record: bool = Query(True),
                  auth: AuthContext = Depends(ANY)):
    """Every finished post in the scope as one zip — videos, thumbnails and
    captions in posting order with a schedule.csv — and the plan written to
    the performance tracker."""
    import os
    from datetime import date, timedelta

    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask

    from ..services import social_export

    _may_make_videos(auth)
    try:
        first = date.fromisoformat(start) if start else date.today() + timedelta(days=1)
    except ValueError:
        raise_api_error("VALIDATION_FAILED", "start is a date such as 2026-10-20.")
        return None
    slots = [t.strip() for t in times.split(",") if t.strip()]
    if not slots or not all(__import__("re").fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", t) for t in slots):
        raise_api_error("VALIDATION_FAILED", "times are 24-hour times such as 07:00,19:00.")
    path, count = social_export.export_zip(grade, subject, sub_strand, start=first, per_day=per_day, times=slots,
                                           platforms=[p.strip().lower() for p in platforms.split(",") if p.strip()],
                                           record=record, created_by=str(getattr(auth, "subject", "") or ""))
    if not count:
        raise_api_error("NOT_FOUND", "No finished social videos in this scope yet — make them first.")
    name = f"social-{social_export._slug(sub_strand or subject)}-{first:%Y%m%d}-{count}posts.zip"
    return FileResponse(path, media_type="application/zip", filename=name,
                        background=BackgroundTask(lambda: os.path.exists(path) and os.remove(path)))


class BookAhead(BaseModel):
    grade: str
    subject: str
    sub_strand: str = ""
    days: int = 25
    low: int = 5             # videos a day, at least …
    high: int = 15           # … and at most
    platforms: list[str] = []
    total: int = 0           # this many videos over the days (0: as many as low–high gives)
    ready_only: bool = False  # only videos already made
    dry: bool = False        # show the plan, book nothing


@router.post("/social/book")
def book_social(payload: BookAhead, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Keep the next weeks booked for the poster: a random number of videos
    each day at random times, videos not made yet queued for rendering.
    Running it again tops the calendar up; no question is booked twice."""
    from ..services import social_export

    _may_make_videos(auth)
    if not (1 <= payload.days <= 62) or not (1 <= payload.low <= 30) or not (1 <= payload.high <= 30) \
            or not (0 <= payload.total <= 1000):
        raise_api_error("VALIDATION_FAILED", "Days are 1–62; videos a day are 1–30; a total is up to 1000.")
    try:
        return social_export.book_ahead(payload.grade, payload.subject, payload.sub_strand, days=payload.days,
                                        low=payload.low, high=payload.high,
                                        platforms=[p.strip().lower() for p in payload.platforms if p.strip()] or None,
                                        dry=payload.dry, created_by=str(getattr(auth, "subject", "") or ""),
                                        total=payload.total, ready_only=payload.ready_only)
    except ValueError as exc:
        raise_api_error("VALIDATION_FAILED", str(exc))
        return {}


# ── a month at a time ────────────────────────────────────────────────────────

def _platform_list(raw: str | list[str]) -> list[str]:
    items = raw if isinstance(raw, list) else str(raw or "").split(",")
    return [p.strip().lower() for p in items if p.strip()]


@router.get("/social/month")
def social_month(year: int = Query(..., ge=2024, le=2100), month: int = Query(..., ge=1, le=12),
                 per_day: int = Query(10, ge=1, le=30), platforms: str = Query("facebook"),
                 auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """The month as a calendar: per day what is booked, already on the
    platform, posted — and the room left for `per_day` videos."""
    from ..services import social_export

    _may_make_videos(auth)
    return social_export.month_view(year, month, platforms=_platform_list(platforms), per_day=per_day)


class BookMonth(BaseModel):
    grade: str = ""
    subject: str
    sub_strand: str = ""
    year: int = Field(ge=2024, le=2100)
    month: int = Field(ge=1, le=12)
    per_day: int = Field(10, ge=1, le=30)
    gap_min: int = Field(30, ge=5, le=240)       # minutes between posts, at least …
    gap_max: int = Field(60, ge=5, le=480)       # … and at most
    platforms: list[str] = ["facebook"]
    ready_only: bool = False
    dry: bool = False


@router.post("/social/book-month")
def book_social_month(payload: BookMonth, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Fill the month's open room, each post 30–60 minutes from the next."""
    from ..services import social_export

    _may_make_videos(auth)
    if payload.gap_max < payload.gap_min:
        raise_api_error("VALIDATION_FAILED", "The longest gap must be at least the shortest.")
    try:
        return social_export.book_month(payload.grade, payload.subject, payload.sub_strand, year=payload.year,
                                        month=payload.month, per_day=payload.per_day, gap_min=payload.gap_min,
                                        gap_max=payload.gap_max, platforms=_platform_list(payload.platforms),
                                        ready_only=payload.ready_only, dry=payload.dry,
                                        created_by=str(getattr(auth, "subject", "") or ""))
    except ValueError as exc:
        raise_api_error("VALIDATION_FAILED", str(exc))
        return {}


class AutoBook(BaseModel):
    enabled: bool
    per_day: int = Field(10, ge=1, le=30)
    days: int = Field(30, ge=1, le=62)
    scopes: list[str] = []          # "grade|subject"


@router.get("/social/auto-book")
def auto_book_status(auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import social_export

    _may_make_videos(auth)
    r = social_export.auto_book_rules()
    return {**r, "scopes": ["|".join(x for x in sc if x) for sc in r["scopes"]],
            "booked_before": ["|".join(x for x in sc if x) for sc in social_export._scopes_booked_before()]}


@router.put("/social/auto-book")
def auto_book_settings(payload: AutoBook, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Turn Auto-book on or off, and say how much and from where. Turning it
    on books at once."""
    from ..services import platform_settings, social_export

    _may_make_videos(auth)
    scopes = [s.strip() for s in payload.scopes if "|" in s and s.strip()][:12]
    platform_settings.set_many({"poster_auto_book": payload.enabled, "poster_auto_book_per_day": payload.per_day,
                                "poster_auto_book_days": payload.days, "poster_auto_book_scopes": scopes or ""},
                               updated_by=str(getattr(auth, "subject", "") or ""))
    out = social_export.auto_book() if payload.enabled else {"posts": 0}
    return {"enabled": payload.enabled, "booked": out}


@router.post("/social/auto-book/now")
def auto_book_now(auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Top the calendar up now, Auto-book on or not."""
    from ..services import social_export

    _may_make_videos(auth)
    return social_export.auto_book(force=True)


class TeacherNow(BaseModel):
    mode: Literal["female", "male", "alternate", "classroom"] = "alternate"
    limit: int = Field(60, ge=1, le=500)
    pause_lessons: bool = True


@router.post("/social/teacher-now")
def teacher_now(payload: TeacherNow, auth: AuthContext = Depends(require_roles("admin"))) -> dict[str, Any]:
    """Teacher videos first: the teacher on, the lesson videos paused, the
    booked posts' videos queued again with the teacher, soonest first."""
    from ..services import teacher

    return teacher.render_now(payload.mode, limit=payload.limit, pause_lessons=payload.pause_lessons,
                              by=str(getattr(auth, "subject", "") or ""))


class LessonsResume(BaseModel):
    target: int = Field(200, ge=0, le=1000)


@router.post("/social/lessons-resume")
def lessons_resume(payload: LessonsResume, auth: AuthContext = Depends(require_roles("admin"))) -> dict[str, Any]:
    from ..services import teacher

    return {"video_daily_target": teacher.resume_lessons(payload.target, by=str(getattr(auth, "subject", "") or ""))}


class LivePerDay(BaseModel):
    live_per_day: int = Field(ge=0, le=30)


@router.put("/social/live-per-day")
def set_live_per_day(payload: LivePerDay, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """How many finished, unbooked videos the poster also posts live a day."""
    from ..services import platform_settings

    _may_make_videos(auth)
    platform_settings.set_many({"poster_live_per_day": payload.live_per_day},
                               updated_by=str(getattr(auth, "subject", "") or ""))
    return {"live_per_day": payload.live_per_day}


# ── photo cards ──────────────────────────────────────────────────────────────

def _card_states(q: dict[str, Any]) -> dict[str, Any]:
    from ..services import social_cards

    out = {}
    for step in social_cards.STEPS:
        st = social_cards.status(str(q["question_id"]), step, q)
        out[step] = {"status": st["status"], "url": st.get("url")}
    return out


@router.get("/social/cards")
def social_cards_library(grade: str = Query(...), subject: str = Query(...), sub_strand: str = Query(""),
                         limit: int = Query(40, ge=1, le=120), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Each question in a scope with its three cards — teaser, question,
    answer — made or not, with a preview of each that is."""
    from ..infra.db import fetch_all

    _may_make_videos(auth)
    pool = _bank(grade, subject, sub_strand, limit)
    ids = [str(q.get("question_id")) for q in pool]
    busy = {r["q"] for r in (fetch_all("""SELECT payload->>'artifact_id' AS q FROM jobs WHERE kind = 'social_card'
                                          AND status IN ('queued', 'running') AND payload->>'artifact_id' = ANY(:ids)""",
                                       {"ids": ids}) or [])}
    items = []
    for q in pool:
        try:
            cards = _card_states(q)
        except Exception as exc:  # noqa: BLE001
            logger.info("Cards of %s: %s", q.get("question_id"), exc)
            continue
        made = sum(1 for c in cards.values() if c["status"] == "ready")
        items.append({"question_id": q.get("question_id"), "question_text": str(q.get("question_text") or "")[:200],
                      "sub_strand": (q.get("curriculum") or {}).get("sub_strand"), "has_figure": _has_figure(q),
                      "cards": cards, "status": "ready" if made == 3 else "making" if q.get("question_id") in busy
                      else "partial" if made else "none"})
    return {"items": items, "ready": sum(1 for i in items if i["status"] == "ready")}


class MakeCards(BaseModel):
    grade: str
    subject: str
    sub_strand: str = ""
    limit: int = Field(default=40, ge=1, le=200)
    figures_only: bool = False


@router.post("/social/cards")
def make_social_cards(payload: MakeCards, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Make the cards the questions in a scope do not have yet."""
    from ..services import social_cards

    _may_make_videos(auth)
    pool = _bank(payload.grade, payload.subject, payload.sub_strand, payload.limit)
    if payload.figures_only:
        pool = [q for q in pool if _has_figure(q)]
    counts: dict[str, int] = {}
    for q in pool:
        try:
            st = social_cards.enqueue(str(q["question_id"]), queued_by=str(getattr(auth, "subject", "") or "cards"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not queue the cards of %s: %s", q.get("question_id"), exc)
            st = {"status": "failed"}
        counts[st.get("status", "failed")] = counts.get(st.get("status", "failed"), 0) + 1
    return {"counts": counts}


@router.post("/items/{question_id}/cards")
def make_question_cards(question_id: str, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import social_cards

    _may_make_videos(auth)
    return social_cards.enqueue(question_id, queued_by=str(getattr(auth, "subject", "") or "cards"))


@router.get("/social/photo-posts")
def photo_posts(days_back: int = Query(3, ge=0, le=60), limit: int = Query(200, ge=1, le=1000),
                auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """The photo posts: what is booked from now on, and what went out lately —
    each with its card's preview, its time and how it went."""
    from ..infra.db import fetch_all
    from ..services import social_cards

    _may_make_videos(auth)
    rows = fetch_all("""SELECT p.post_id, p.question_id, p.platform, p.step, p.scheduled_for, p.posted_at, p.status,
                               p.attempts, p.last_error, p.url, LEFT(COALESCE(q.content->>'question_text', ''), 160) AS question_text
                        FROM social_posts p LEFT JOIN question_dna q ON q.question_id = p.question_id
                        WHERE p.format = 'photo' AND (p.posted_at IS NULL OR p.posted_at > NOW() - make_interval(days => :d))
                        ORDER BY COALESCE(p.posted_at, p.scheduled_for) LIMIT :n""", {"d": days_back, "n": limit}) or []
    loaded: dict[str, dict[str, Any]] = {}
    out = []
    for r in rows:
        qid = str(r["question_id"])
        try:
            if qid not in loaded:
                loaded[qid] = _one(qid)
            card = social_cards.status(qid, str(r["step"]), loaded[qid])
        except Exception:  # noqa: BLE001
            card = {"status": "none"}
        out.append({**{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()},
                    "card_status": card["status"], "card_url": card.get("url")})
    upcoming = [p for p in out if not p["posted_at"]]
    return {"posts": out, "upcoming": len(upcoming), "posted": len(out) - len(upcoming),
            "cards_missing": sum(1 for p in upcoming if p["card_status"] != "ready")}


class BookSeries(BaseModel):
    grade: str
    subject: str
    sub_strand: str = ""
    days: int = 7
    photos: int | None = None     # cards a day (default: Settings → Auto-post, 8)
    videos: int | None = None     # videos a day (default 8)
    platform: str = "facebook"
    dry: bool = False


@router.post("/social/book-series")
def book_social_series(payload: BookSeries, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Book days of series: each question's "Can you solve this?" card, the
    question, the answer, then its walkthrough video, spread through the day
    with single videos — up to 8 photos and 8 videos a day."""
    from ..services import social_export

    _may_make_videos(auth)
    if not (1 <= payload.days <= 31) or not (0 <= (payload.photos or 0) <= 16) or not (0 <= (payload.videos or 0) <= 16):
        raise_api_error("VALIDATION_FAILED", "Days are 1–31; photos and videos a day are 0–16 each.")
    try:
        return social_export.book_series(payload.grade, payload.subject, payload.sub_strand, days=payload.days,
                                         photos=payload.photos, videos=payload.videos,
                                         platform=payload.platform.strip().lower() or "facebook", dry=payload.dry,
                                         created_by=str(getattr(auth, "subject", "") or ""))
    except ValueError as exc:
        raise_api_error("VALIDATION_FAILED", str(exc))
        return {}


@router.get("/social/posts")
def social_posts(grade: str = Query(""), subject: str = Query(""), sub_strand: str = Query(""),
                 platform: str = Query(""), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Where each video went and how it did, with platforms and topics compared."""
    _may_make_videos(auth)            # production tools: file links and posts
    from ..services import social_export

    posts = social_export.list_posts(grade, subject, sub_strand, platform)
    return {"posts": posts, "summary": social_export.summary(posts), "platforms": list(social_export.PLATFORMS)}


class PostUpdate(BaseModel):
    post_id: str | None = None
    question_id: str | None = None
    platform: str | None = None
    url: str | None = None
    notes: str | None = None
    posted: bool | None = None
    posted_at: str | None = None
    scheduled_for: str | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    follows: int | None = None
    watch_pct: float | None = None


@router.post("/social/posts")
def save_social_post(payload: PostUpdate, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Record that a video went out on a platform, or update its link and numbers."""
    from ..services import social_export

    _may_make_videos(auth)
    try:
        return social_export.save_post(payload.model_dump(exclude_none=True), created_by=str(getattr(auth, "subject", "") or ""))
    except ValueError as exc:
        raise_api_error("VALIDATION_FAILED", str(exc))
        return {}


@router.delete("/social/posts/{post_id}")
def delete_social_post(post_id: str, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import social_export

    _may_make_videos(auth)
    social_export.delete_post(post_id)
    return {"deleted": post_id}


# ── the browser poster ───────────────────────────────────────────────────────
#
# The poster service (poster/ at the repo root) runs a real browser the owner
# logs into once through its shared screen; it asks here what to publish and
# reports back. The rules — 30 a day at most, a cap per platform, a gap
# between posts, posting hours — are applied here, never in the browser.

def _poster_call(method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 8.0) -> Any:
    import os

    import httpx

    base = os.getenv("POSTER_URL", "http://social-poster:6090").rstrip("/")
    token = os.getenv("POSTER_TOKEN", "")
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.request(method, base + path, json=body, headers={"X-Poster-Token": token})
        return r.json() if "json" in r.headers.get("content-type", "") else r.content
    except Exception as exc:  # noqa: BLE001
        return {"online": False, "error": f"The poster is not reachable: {str(exc)[:160]}"}


@router.get("/poster/next")
def poster_next(platform: str = Query(""), post_id: str = Query(""), dry: bool = Query(False),
                share: Literal["", "feed", "groups"] = Query(""), groups: list[str] = Query(default=[]),
                poster_id: str = Query(""), schedule: bool = Query(False),
                auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """The one post the browser may publish now, or why there is none. A dry
    run takes the next queued post for a platform, rules aside, since it
    publishes nothing. `share` with `dry`: a post-now button (feed only, or
    feed and groups — the next in turn, or the `groups` picked)."""
    from ..services import social_export

    _may_make_videos(auth)
    why = social_export.standing_by(poster_id)
    if why:
        return {"post": None, "reason": why, "standby": True}
    if schedule:                      # "Schedule now": the next booking to Facebook's scheduler, at once
        return social_export.schedule_next()
    return social_export.next_for_poster(platform=platform, post_id=post_id, dry=dry, share=share, groups=groups)


@router.get("/poster/comments/next")
def poster_comments_next(poster_id: str = Query(""), check: bool = Query(False),
                         auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """The next comment step the poster should make under a post that is out
    (`check`: the newest post, for a dry run)."""
    from ..services import social_export

    _may_make_videos(auth)
    if social_export.standing_by(poster_id):
        return {"job": None, "reason": "standing by"}
    return social_export.comments_next(check=check)


class CommentResult(BaseModel):
    post_id: str
    stage: Literal["first", "later", "boost", "measure"]
    ok: bool
    error: str = ""
    url: str = ""
    metrics: dict[str, int] | None = None     # views, reactions, comments, shares as read on the post


@router.post("/poster/comments/result")
def poster_comments_result(payload: CommentResult, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import social_export

    _may_make_videos(auth)
    return social_export.comments_result(payload.post_id, stage=payload.stage, ok=payload.ok, error=payload.error,
                                         url=payload.url, metrics=payload.metrics)


class CommentSwitch(BaseModel):
    enabled: bool
    delay_seconds: int = Field(60, ge=0, le=86400)


@router.put("/social/comments")
def social_comments_switch(payload: CommentSwitch, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Question in the caption and the rest in comments — on or off."""
    from ..services import platform_settings

    _may_make_videos(auth)
    platform_settings.set_many({"poster_comment_thread": payload.enabled, "poster_answer_delay_seconds": payload.delay_seconds},
                               updated_by=str(getattr(auth, "subject", "") or ""))
    return {"enabled": payload.enabled, "delay_seconds": payload.delay_seconds}


class CommentBackfill(BaseModel):
    days: int = Field(7, ge=1, le=60)


@router.post("/social/comments/backfill")
def social_comments_backfill(payload: CommentBackfill, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Comment the same way under the posts already out."""
    from ..services import social_export

    _may_make_videos(auth)
    return {"queued": social_export.comments_backfill(payload.days)}


# ── videos rendered on the owner's Mac ───────────────────────────────────────

@router.post("/render/claim")
def render_claim(worker: str = Query("mac", max_length=80), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """A render helper takes the next queued video, with everything needed to draw it."""
    from ..services import remote_render

    _may_make_videos(auth)
    return remote_render.claim(worker)


class RenderBeat(BaseModel):
    stage: str = ""
    pct: float = 0.0


@router.post("/render/{job_id}/heartbeat")
def render_heartbeat(job_id: str, payload: RenderBeat, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import remote_render

    _may_make_videos(auth)
    return {"ok": remote_render.heartbeat(job_id, payload.stage, payload.pct)}


@router.post("/render/{job_id}/done")
async def render_done(job_id: str, video: UploadFile = File(...), thumbnail: UploadFile | None = File(None),
                      seconds: float = Form(0.0), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """The helper's finished MP4 (and thumbnail), stored as the server would have."""
    from ..services import remote_render

    _may_make_videos(auth)
    body = await video.read()
    if len(body) > 300_000_000:
        raise_api_error("VALIDATION_FAILED", "That video is too large.")
    thumb = await thumbnail.read() if thumbnail is not None else None
    try:
        return remote_render.done(job_id, body, thumb, seconds)
    except ValueError as exc:
        raise_api_error("VALIDATION_FAILED", str(exc))
        return {}


class RenderFailed(BaseModel):
    error: str = ""
    worker: str = ""


@router.post("/render/{job_id}/failed")
def render_failed(job_id: str, payload: RenderFailed, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import remote_render

    _may_make_videos(auth)
    return remote_render.fail(job_id, payload.error, worker=payload.worker)


# ── liking back, and the posts that get comments ─────────────────────────────

@router.get("/poster/engage/next")
def poster_engage_next(poster_id: str = Query(""), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """The next like-back step: read a post's comments, or like a person's posts."""
    from ..services import engage, social_export

    _may_make_videos(auth)
    if social_export.standing_by(poster_id):
        return {"action": None, "reason": "standing by"}
    return engage.next_action()


class EngageResult(BaseModel):
    kind: Literal["scan", "like_person"]
    target: str
    likes: int = Field(0, ge=0, le=100)
    people: list[dict[str, str]] = []
    error: str = ""


@router.post("/poster/engage/result")
def poster_engage_result(payload: EngageResult, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import engage

    _may_make_videos(auth)
    return engage.record(payload.kind, target=payload.target, likes=payload.likes, people=payload.people, error=payload.error)


@router.get("/social/engage")
def social_engage(auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from datetime import datetime, timezone

    from ..services import engage

    _may_make_videos(auth)
    t = engage.today(datetime.now(timezone.utc))
    return {**engage.rules(), **{k: v for k, v in t.items() if not k.startswith("_")}}


class EngageSettings(BaseModel):
    enabled: bool
    per_day: int = Field(40, ge=1, le=300)
    per_person: int = Field(2, ge=1, le=5)


@router.put("/social/engage")
def social_engage_settings(payload: EngageSettings, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import platform_settings

    _may_make_videos(auth)
    platform_settings.set_many({"engage_enabled": payload.enabled, "engage_likes_per_day": payload.per_day,
                                "engage_likes_per_person": payload.per_person},
                               updated_by=str(getattr(auth, "subject", "") or ""))
    return payload.model_dump()


@router.get("/social/insights")
def social_insights(days: int = Query(21, ge=1, le=90), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Each post's numbers as last read, the weakest first, and the loop's day."""
    from datetime import datetime, timedelta, timezone

    from ..infra.db import fetch_all, fetch_one
    from ..services import social_export

    _may_make_videos(auth)
    rows = fetch_all("""SELECT p.post_id, p.posted_at, p.views, p.likes AS reactions, p.comments, p.shares, p.score,
                               p.boost_index, p.metrics_at, p.comments_state,
                               LEFT(COALESCE(q.content->>'question_text', ''), 120) AS question_text
                        FROM social_posts p LEFT JOIN question_dna q ON q.question_id = p.question_id
                        WHERE p.platform = 'facebook' AND p.handed_at IS NOT NULL AND p.posted_at <= NOW()
                          AND p.posted_at >= NOW() - (:d * INTERVAL '1 day')
                        ORDER BY p.score NULLS FIRST, p.posted_at DESC LIMIT 200""", {"d": days}) or []
    for r in rows:
        for k, v in list(r.items()):
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat()
    now = datetime.now(timezone.utc)
    day = now.astimezone(social_export.EAT).replace(hour=0, minute=0, second=0, microsecond=0)
    today = fetch_one("SELECT COUNT(*) AS n FROM social_posts WHERE boost_last_at >= :d", {"d": day}) or {}
    return {**social_export.boost_rules(), "boosts_today": int(today.get("n") or 0), "posts": rows,
            "measured": sum(1 for r in rows if r.get("metrics_at"))}


class BoostSettings(BaseModel):
    enabled: bool
    per_day: int = Field(40, ge=1, le=300)
    hours: int = Field(3, ge=1, le=48)


@router.put("/social/insights")
def social_insights_settings(payload: BoostSettings, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import platform_settings

    _may_make_videos(auth)
    platform_settings.set_many({"engage_boost": payload.enabled, "engage_boosts_per_day": payload.per_day,
                                "engage_boost_hours": payload.hours}, updated_by=str(getattr(auth, "subject", "") or ""))
    return payload.model_dump()


@router.get("/social/comments/posts")
def social_comment_posts(days: int = Query(14, ge=1, le=60), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Your posts that are out, with where their comment thread stands."""
    from ..services import engage

    _may_make_videos(auth)
    return {"posts": engage.recent_posts(days)}


class CommentQueue(BaseModel):
    post_ids: list[str] = Field(default_factory=list, max_length=200)


@router.post("/social/comments/queue")
def social_comment_queue(payload: CommentQueue, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """These posts get the comment thread: the poster finds each one and comments."""
    from ..services import engage

    _may_make_videos(auth)
    return {"queued": engage.queue_comments(payload.post_ids)}


class PosterResult(BaseModel):
    post_id: str
    ok: bool
    url: str = ""
    error: str = ""
    dry_run: bool = False
    scheduled: bool = False      # handed to the platform's scheduler
    groups: list[str] = []       # shared to these groups too
    destinations: list[str] = [] # where else on the platform: reel, feed, story


@router.post("/poster/result")
def poster_result(payload: PosterResult, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import social_export

    _may_make_videos(auth)
    return social_export.record_attempt(payload.post_id, ok=payload.ok, url=payload.url, error=payload.error,
                                        dry_run=payload.dry_run, scheduled=payload.scheduled, groups=payload.groups,
                                        destinations=payload.destinations)


class PosterState(BaseModel):
    platform: str
    logged_in: bool
    note: str = ""


@router.post("/poster/state")
def poster_state(payload: PosterState, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import social_export

    _may_make_videos(auth)
    social_export.set_login_state(payload.platform.lower(), payload.logged_in, payload.note)
    return {"platform": payload.platform, "logged_in": payload.logged_in}


@router.get("/poster/overview")
def poster_overview(auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Rules, today's count, login state per platform, the queue, the last
    attempts, and the poster's own live status — the Mac poster's heartbeat
    when it has checked in, else the server poster's."""
    import os

    from ..services import platform_settings, social_export

    _may_make_videos(auth)
    pulled = social_export.pull_poster()
    if pulled:
        live, view = pulled, ""
    else:
        public = str(platform_settings.get("public_base_url") or "").rstrip("/")
        view = os.getenv("POSTER_VIEW_URL", "") or (
            f"{public}/poster/vnc.html?path=poster/websockify&autoconnect=1&resize=scale" if public else "")
        live = _poster_call("GET", "/status", timeout=4.0)
        live = live if isinstance(live, dict) else {"online": False}
        live.setdefault("mode", "server")
    return {**social_export.poster_overview(), "live": live, "view_url": view}


class PosterCommand(BaseModel):
    action: str          # login | check | dry_run | run_now | pause | resume | groups
    platform: str = ""
    post_id: str = ""
    # run_now: {"share": "feed" | "groups", "groups": [names picked, at most 5]}
    options: dict[str, Any] = {}


@router.post("/poster/command")
def poster_command(payload: PosterCommand, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """To the Mac poster's queue when it is checking in; straight to the
    server poster otherwise. A quick command waits a few seconds for its
    answer; a dry run reports through the overview when it is done."""
    import time

    from ..services import social_export

    _may_make_videos(auth)
    if payload.action not in ("login", "check", "dry_run", "run_now", "schedule_now", "comments_check", "engage_check",
                              "pause", "resume", "groups"):
        raise_api_error("VALIDATION_FAILED", "Unknown poster action.")
    options: dict[str, Any] = {}
    if payload.action == "schedule_now":
        options = {"count": max(1, min(int((payload.options or {}).get("count") or 5), 30))}
    share = str((payload.options or {}).get("share") or "")
    if payload.action == "run_now" and share:
        if share not in ("feed", "groups"):
            raise_api_error("VALIDATION_FAILED", "Share to \"feed\" or \"groups\".")
        picked = [str(g)[:200] for g in ((payload.options or {}).get("groups") or []) if str(g).strip()]
        if len(picked) > social_export.MAX_GROUPS_PER_POST:
            raise_api_error("VALIDATION_FAILED", f"Pick at most {social_export.MAX_GROUPS_PER_POST} groups for one post.")
        options = {"share": share, "groups": picked}
    if social_export.pull_poster():
        command_id = social_export.queue_command(payload.action, payload.platform, payload.post_id,
                                                 by=str(getattr(auth, "subject", "") or ""), options=options)
        if payload.action in ("login", "pause", "resume", "check", "groups"):
            for _ in range(40 if payload.action == "groups" else 24 if payload.action == "check" else 8):
                time.sleep(1.0)
                done = social_export.command_result(command_id)
                if done is not None:
                    return done
        return {"ok": True, "queued": command_id,
                "message": "Sent to the poster on your Mac — it picks commands up within a few seconds."}
    out = _poster_call("POST", f"/{payload.action}", {"platform": payload.platform, "post_id": payload.post_id,
                                                      "options": options},
                       timeout=15.0)
    return out if isinstance(out, dict) else {"ok": True}


@router.get("/poster/shot/{name}")
def poster_shot(name: str, auth: AuthContext = Depends(ANY)):
    """A screenshot the poster took — a dry run's last step, or a failure."""
    import re as _re

    from fastapi.responses import Response as _Response

    from ..infra.storage import object_storage

    _may_make_videos(auth)
    if not _re.fullmatch(r"[\w.-]+\.png", name):
        raise_api_error("VALIDATION_FAILED", "Not a screenshot name.")
    stored = object_storage.read_bytes(f"poster/shots/{name}")
    if stored:
        return _Response(content=stored, media_type="image/png")
    out = _poster_call("GET", f"/shots/{name}")
    if isinstance(out, (bytes, bytearray)):
        return _Response(content=bytes(out), media_type="image/png")
    raise_api_error("NOT_FOUND", "No such screenshot.")
    return None


# ── the owner's groups ───────────────────────────────────────────────────────

class FoundGroups(BaseModel):
    platform: str = "facebook"
    names: list[str] = []


@router.post("/poster/groups/found")
def poster_groups_found(payload: FoundGroups, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """The poster reports the groups it found in the platform's picker."""
    from ..services import social_export

    _may_make_videos(auth)
    return {"groups": social_export.save_found_groups(payload.platform, payload.names[:500])}


@router.get("/poster/groups")
def poster_groups(platform: str = Query("facebook"), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import social_export

    _may_make_videos(auth)
    return {"groups": social_export.list_groups(platform)}


class PickGroups(BaseModel):
    platform: str = "facebook"
    enabled: list[str] = []


@router.put("/poster/groups")
def poster_pick_groups(payload: PickGroups, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Which groups may get a share — the owner ticks the ones that welcome it."""
    from ..services import social_export

    _may_make_videos(auth)
    return {"groups": social_export.set_groups(payload.platform, payload.enabled)}


# ── the Mac poster's side: it asks, the server answers ───────────────────────

class Heartbeat(BaseModel):
    poster_id: str
    status: dict[str, Any] = {}


class MacLinkRequest(BaseModel):
    minutes: int = Field(default=60, ge=5, le=1440)


@router.post("/poster/mac-link")
def poster_mac_link(request: Request, payload: MacLinkRequest | None = None,
                    auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """A one-time link to set the poster up on another Mac: paste the command
    in that Mac's Terminal. The installer it fetches carries a new key for
    this account, so nothing has to be copied across."""
    import secrets

    from ..infra.db import execute
    from ..services import platform_settings, poster_installer

    from ..services import rate_limit

    _may_make_videos(auth)
    rate_limit.hit("link_owner", auth.subject)
    minutes = (payload or MacLinkRequest()).minutes
    token = secrets.token_urlsafe(24)
    execute("""INSERT INTO download_links (token, what, params, created_by, expires_at)
               VALUES (:token, 'poster', '{}'::jsonb, :by, NOW() + (:minutes || ' minutes')::interval)""",
            {"token": token, "by": auth.subject, "minutes": str(minutes)})
    url = f"{platform_settings.public_base_url(request)}/api/v1/play/poster/mac-installer/{token}"
    file = f"/tmp/{poster_installer.FILENAME}"
    return {"url": url, "expires_in_minutes": minutes, "single_use": True,
            "command": f'curl -fsSL "{url}" -o {file} && bash {file}',
            "note": "Anyone with this link can install a poster on your account once before it expires. "
                    "Paste it only into the other Mac's Terminal."}


@router.get("/poster/mac-installer/{token}")
def poster_mac_installer(token: str, request: Request) -> Response:
    """The Mac poster as one file, fetched with a link from the console. No
    sign-in: the link is the credential — once, and only while it lasts."""
    import datetime as _dt

    from ..infra.db import execute, fetch_one
    from ..services import platform_settings, poster_installer
    from .agent import _mint_key

    row = fetch_one("SELECT * FROM download_links WHERE token = :token AND what = 'poster'", {"token": token})
    if not row or row.get("used_at") is not None:
        raise_api_error("NOT_FOUND", "This link has been used or does not exist. Make a new one in the console.")
    expires = row.get("expires_at")
    if expires is not None and expires < _dt.datetime.now(tz=expires.tzinfo):
        raise_api_error("NOT_FOUND", "This link has expired. Make a new one in the console.")
    src = poster_installer.source_dir()
    try:
        poster_installer.tarball(src)
    except FileNotFoundError as exc:
        raise_api_error("NOT_FOUND", f"{exc} Mount the repo's poster/ folder into the API container (docker-compose.yml).")
    execute("UPDATE download_links SET used_at = NOW() WHERE token = :token AND used_at IS NULL", {"token": token})
    maker = AuthContext(subject=str(row.get("created_by") or "link"), role="operator", auth_type="link")
    # The poster's own role: the poster endpoints, nothing else in the platform.
    key = _mint_key(maker, label="poster on another Mac (link)", role="poster")
    body = poster_installer.build(src, platform_settings.public_base_url(request), api_key=key)
    return Response(body, media_type="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="{poster_installer.FILENAME}"', "Cache-Control": "no-store"})


@router.post("/poster/heartbeat")
def poster_heartbeat(payload: Heartbeat, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import social_export

    _may_make_videos(auth)
    social_export.heartbeat(payload.poster_id, {**payload.status, "mode": payload.status.get("mode") or "local"})
    return {"ok": True}


@router.post("/poster/commands/next")
def poster_take_command(poster_id: str = Query(""), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import social_export

    _may_make_videos(auth)
    if social_export.standing_by(poster_id):
        return {"command": None, "standby": True}   # the console's buttons are for the active poster
    return {"command": social_export.take_command()}


class CommandDone(BaseModel):
    result: dict[str, Any] = {}


@router.post("/poster/commands/{command_id}/done")
def poster_command_done(command_id: int, payload: CommandDone, auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import social_export

    _may_make_videos(auth)
    social_export.finish_command(command_id, payload.result)
    return {"ok": True}


@router.post("/poster/shots")
async def poster_upload_shot(file: UploadFile = File(...), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """A screenshot from the Mac poster, kept so the console can show it."""
    import os as _os
    import re as _re

    from ..infra.storage import object_storage

    _may_make_videos(auth)
    name = _os.path.basename(file.filename or "")
    if not _re.fullmatch(r"[\w.-]+\.png", name):
        raise_api_error("VALIDATION_FAILED", "Not a screenshot name.")
    payload = await file.read()
    if payload[:8] != b"\x89PNG\r\n\x1a\n" or len(payload) > 8 * 1024 * 1024:
        raise_api_error("VALIDATION_FAILED", "Send a PNG under 8 MB.")
    object_storage.save_bytes(f"poster/shots/{name}", payload, "image/png")
    return {"name": name}
