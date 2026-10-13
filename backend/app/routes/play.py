"""Play: every question as a game, a simulator and a narrated walkthrough.

Open to every signed-in role — the studio's `user` included — because this
is what a school buys alongside the papers. The specs come from the play
engine; every number in them comes from the maths engine.
"""
from __future__ import annotations

import html
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..errors import raise_api_error
from ..services.auth import AuthContext, require_roles

logger = logging.getLogger("cbc-play")
router = APIRouter(prefix="/api/v1/play", tags=["Play"])

ANY = require_roles("admin", "operator", "reviewer", "developer", "user")
_HIDDEN = ("needs_review", "rejected", "superseded")


def _bank(grade: str, subject: str, sub_strand: str, limit: int) -> list[dict[str, Any]]:
    from ..services import question_rows
    from ..services.question_dna import question_dna_service

    rows = question_dna_service.list_questions(grade=grade or None, subject=subject or None,
                                               sub_strand=sub_strand or None, limit=limit)
    return [q for q in question_rows.flatten_all(rows) if str(q.get("status") or "") not in _HIDDEN]


def _one(question_id: str) -> dict[str, Any]:
    from ..services import question_rows
    from ..services.question_dna import question_dna_service

    try:
        return question_rows.flatten(question_dna_service.get_question(question_id))
    except Exception:  # noqa: BLE001
        raise_api_error("NOT_FOUND", f"No question {question_id}.")
    return {}


@router.get("/items")
def playable_items(grade: str = Query(""), subject: str = Query(""), sub_strand: str = Query(""),
                   kind: str = Query("", description="number_line | balance | bodmas | fraction_bar | choice"),
                   limit: int = Query(200, ge=1, le=1000),
                   _: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Items in a scope with the kind each plays as — what a game picker lists."""
    from ..services import play_engine

    out = []
    counts: dict[str, int] = {}
    for q in _bank(grade, subject, sub_strand, limit):
        play = play_engine.spec_for(q)
        primary = play.get("primary") or {}
        k = primary.get("kind")
        if not k or (kind and k != kind):
            continue
        counts[k] = counts.get(k, 0) + 1
        out.append({"question_id": q.get("question_id"), "question_text": q.get("question_text"),
                    "sub_strand": (q.get("curriculum") or {}).get("sub_strand"), "kind": k,
                    "also_choice": bool(play.get("choice")) and k != "choice",
                    "key_agrees": play.get("key_agrees"), "status": q.get("status")})
    return {"items": out, "counts": counts}


@router.get("/items/{question_id}")
def play_item(question_id: str, _: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """One item: its game/simulator spec and its walkthrough scenes."""
    from ..services import play_engine

    q = _one(question_id)
    return {"question": {k: q.get(k) for k in ("question_id", "question_text", "stimulus_context", "question_type",
                                               "diagram", "curriculum")},
            "play": play_engine.spec_for(q),
            "walkthrough": play_engine.walkthrough(q, grade=str((q.get("curriculum") or {}).get("grade") or ""))}


@router.get("/session")
def game_session(grade: str = Query(...), subject: str = Query(...), sub_strand: str = Query(""),
                 mode: str = Query("mixed", description="mixed | choice | number_line | balance | bodmas | fraction_bar"),
                 count: int = Query(10, ge=1, le=50), seed: str = Query(""),
                 _: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """A round: `count` items played as `mode`, shuffled by `seed`."""
    import random

    from ..services import play_engine

    pool = _bank(grade, subject, sub_strand, 600)
    random.Random(seed or None).shuffle(pool)
    items = play_engine.session(pool, mode=mode, count=count)
    if not items:
        raise_api_error("NOT_FOUND", f"Nothing in the bank plays as '{mode}' for this scope yet.")
    return {"mode": mode, "count": len(items), "items": items}


class CheckRequest(BaseModel):
    expected: Any
    given: Any


@router.post("/check")
def check(payload: CheckRequest, _: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Whether a learner's typed value is the value: 3/4, 0.75 and 6/8 agree."""
    from ..services import play_engine

    return {"correct": play_engine.check_answer(payload.expected, payload.given)}


@router.get("/items/{question_id}/walkthrough.html")
def walkthrough_page(question_id: str, voice: str = Query("en-KE"), autoplay: bool = Query(True),
                     _: AuthContext = Depends(ANY)) -> HTMLResponse:
    """A self-playing walkthrough, for a projector or a share link: GSAP
    animates each scene while the device's voice reads it, and the next
    scene starts when the sentence ends."""
    from ..services import play_engine

    q = _one(question_id)
    data = play_engine.walkthrough(q)
    return HTMLResponse(walkthrough_html(data, title=str(q.get("question_text") or "")[:80], voice=voice,
                                         autoplay=autoplay))


@router.get("/items/{question_id}/whiteboard.html")
def whiteboard_page(question_id: str, autoplay: bool = Query(False), voice: str = Query(""),
                    _: AuthContext = Depends(ANY)) -> HTMLResponse:
    """The item worked on a whiteboard: a marker writes each line, circles
    the side sum, draws the number line or the scale, boxes the answer and
    strikes out the trap — voiced by the server in the console's chosen
    voice, the same as the MP4. Self-contained, so it works offline on a
    projector."""
    from ..services import whiteboard

    q = _one(question_id)
    data, voice, title = whiteboard._script_for(q, _voice(voice))
    return HTMLResponse(whiteboard.live_page(data, title=title, voice=voice, autoplay=autoplay))


@router.get("/items/{question_id}/video")
def video_status(question_id: str, voice: str = Query(""), _: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """The MP4 for this item: ready (with its URL), queued, running, failed or none."""
    from ..services import whiteboard

    return whiteboard.status(question_id, _one(question_id), _voice(voice))


def _may_make_videos(auth: AuthContext) -> None:
    """Rendering is minutes of server time per video, so for now only an
    admin, or someone named in Settings → Video makers, may start one."""
    from ..services import platform_settings

    raw = platform_settings.get("video_makers", ["gidraf"]) or []
    names = raw if isinstance(raw, list) else str(raw).replace(";", ",").split(",")
    makers = {str(m).strip().lower() for m in names if str(m).strip()}
    if auth.role == "admin" or str(auth.subject or "").lower() in makers:
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
                limit: int = Query(60, ge=1, le=300), _: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Every item in a scope with its video's state — the content library."""
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
def social_page(question_id: str, voice: str = Query(""), _: AuthContext = Depends(ANY)) -> HTMLResponse:
    """The vertical cut, live and voiced — what the post's video will be."""
    from ..services import social

    return HTMLResponse(social.live_page(_one(question_id), _voice(voice)))


@router.get("/items/{question_id}/social")
def social_status(question_id: str, voice: str = Query(""), _: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """The social post for this item: its video, thumbnail and post text, or where they are."""
    from ..services import social

    return social.status(question_id, _one(question_id), _voice(voice))


@router.post("/items/{question_id}/social")
def make_social(question_id: str, voice: str = Query(""), auth: AuthContext = Depends(ANY)) -> dict[str, Any]:
    from ..services import social

    _may_make_videos(auth)
    _one(question_id)
    return social.enqueue(question_id, queued_by=str(getattr(auth, "subject", "") or "social"), voice=_voice(voice))


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


@router.get("/social")
def list_socials(grade: str = Query(...), subject: str = Query(...), sub_strand: str = Query(""),
                 limit: int = Query(60, ge=1, le=300), _: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Every item in a scope with its social post — ready to download and paste."""
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


@router.get("/social/posts")
def social_posts(grade: str = Query(""), subject: str = Query(""), sub_strand: str = Query(""),
                 platform: str = Query(""), _: AuthContext = Depends(ANY)) -> dict[str, Any]:
    """Where each video went and how it did, with platforms and topics compared."""
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
