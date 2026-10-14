"""Whiteboard videos: a question worked on a board by a marker, narrated.

The walkthrough scenes from the play engine are the script. `page()` builds
one self-contained HTML page — GSAP and the board engine inlined, no CDN —
that either plays live (the device's voice, scene by scene) or, in render
mode, waits to be stepped frame by frame. `render()` does the stepping:
each scene is spoken by the Kenyan neural voice, the board's timeline is
stretched to fit the speech, every frame is captured from the headless
browser, and ffmpeg lays the voice over the frames. The MP4 is stored once
per (scenes, voice, fps) and reused.
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger("cbc-whiteboard")

STATIC = Path(__file__).resolve().parent.parent / "static"
VERSION = "wb3"          # bump when the board draws differently: old videos re-render
FPS = 20
WIDTH, HEIGHT = 1280, 720
MAX_SECONDS = 240


@lru_cache(maxsize=4)
def _asset(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _script(js: str) -> str:
    return js.replace("</script", "<\\/script")


def png_size(payload: bytes) -> tuple[int, int] | None:
    """Width and height from a PNG's header — the only format a cut-out
    hand needs, and no imaging library to install for it."""
    if len(payload) < 24 or payload[:8] != b"\x89PNG\r\n\x1a\n" or payload[12:16] != b"IHDR":
        return None
    return int.from_bytes(payload[16:20], "big"), int.from_bytes(payload[20:24], "big")


@lru_cache(maxsize=4)
def _hand_bytes(url: str) -> bytes | None:
    import httpx

    try:
        if url.startswith("data:"):
            import base64

            return base64.b64decode(url.split(",", 1)[1])
        # One of our own stored files, whatever address it was linked at:
        # read it from storage rather than round the internet and back.
        from ..infra.storage import object_storage

        name = object_storage.object_name_of(url)
        if name and object_storage.object_exists(name):
            return object_storage.read_bytes(name) or None
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            got = client.get(url)
        return got.content if got.status_code == 200 else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch the hand photo %s: %s", url, exc)
        return None


def hand() -> dict[str, Any] | None:
    """The uploaded hand photo, ready to inline: {src, w, h, tip_x, tip_y,
    width}. None — the drawn hand — when there is none or it cannot be read.
    Inlined as a data URI so the headless renderer never fetches it."""
    import base64

    from . import platform_settings

    url = str(platform_settings.get("whiteboard_hand_image", "") or "").strip()
    payload = _hand_bytes(url) if url else None
    size = png_size(payload or b"")
    if not payload or not size:
        return emoji_hand(str(platform_settings.get("whiteboard_hand_style", "emoji-dark") or "emoji-dark"))
    try:
        tx, ty = (float(v) for v in str(platform_settings.get("whiteboard_hand_tip", "") or "").split(","))
    except ValueError:
        tx, ty = size[0] * 0.2, size[1] * 0.2
    width = int(platform_settings.get("whiteboard_hand_width", 300) or 300)
    return {"src": "data:image/png;base64," + base64.b64encode(payload).decode(), "w": size[0], "h": size[1],
            "tip_x": tx, "tip_y": ty, "width": max(80, min(width, 900)), "url": url}


# The writing-hand emoji (Noto, Apache 2.0 — see static/NOTICE-noto-emoji.txt),
# its pen's tip measured in the 128-unit artwork.
EMOJI_HANDS = {"emoji-dark": "hand_emoji_dark.svg", "emoji-medium-dark": "hand_emoji_medium_dark.svg"}
EMOJI_TIP = (11.2, 114.8)


def emoji_hand(style: str) -> dict[str, Any] | None:
    """✍🏿 or ✍🏾 as the hand; None for the drawn one."""
    import base64

    name = EMOJI_HANDS.get(style.strip().lower()) if style.strip().lower() != "drawn" else None
    if style.strip().lower() not in EMOJI_HANDS and style.strip().lower() != "drawn":
        name = EMOJI_HANDS["emoji-dark"]
    if not name:
        return None
    svg = _asset(name).encode()
    return {"src": "data:image/svg+xml;base64," + base64.b64encode(svg).decode(), "w": 128, "h": 128,
            "tip_x": EMOJI_TIP[0], "tip_y": EMOJI_TIP[1], "width": 250, "emoji": True}


_SHOWN = ("text", "context", "expression", "before", "after", "left", "right", "caption", "name", "handle", "cta")


def _written(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every field the board writes, in the symbols a hand writes — ¾, x²,
    ∛216, ≤, 45° — never `\\frac`. What is said is left alone."""
    import copy

    from .latex_text import to_unicode

    def walk(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {k: walk(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, key) for v in value]
        if isinstance(value, str) and key in _SHOWN:
            return to_unicode(value)
        return value

    return [walk(copy.deepcopy(sc)) if isinstance(sc, dict) else sc for sc in scenes]


def page(data: dict[str, Any], *, title: str = "", voice: str = "en-KE", durations: list[float] | None = None,
         render: bool = False, autoplay: bool = False, audio: list[str | None] | None = None,
         social: dict[str, Any] | None = None) -> str:
    """The board for one walkthrough. `durations` (seconds per scene) come
    from the voice files when rendering; live, the board estimates them.
    With `social`, the board sits in a vertical 1080×1920 frame with a
    hook, captions, a countdown and the brand (see services/social.py)."""
    payload = {"scenes": _written(data.get("scenes") or []), "seed": str(data.get("question_id") or title or "wb"),
               "voice": voice, "durations": durations or [], "audio": audio or []}
    if social:
        payload["social"] = {k: v for k, v in social.items() if k not in ("logo", "music_url")}
    try:
        photo = hand()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Hand photo unavailable, drawing the hand: %s", exc)
        photo = None
    if photo:
        payload["hand"] = {k: v for k, v in photo.items() if k != "url"}
    chrome = "" if render else _CONTROLS.replace("__AUTOPLAY__", "true" if autoplay else "false")
    template = _PAGE
    if social:
        from .social import frame

        template = frame(social)
    return (template.replace("__TITLE__", html.escape(title or "Whiteboard"))
            .replace("__BODY_CLASS__", ("social " if social else "") + ("render" if render else "live"))
            .replace("__CONTROLS__", chrome)
            .replace("__GSAP__", _script(_asset("gsap.min.js")))
            .replace("__DATA__", json.dumps(payload).replace("</", "<\\/"))
            .replace("__ENGINE__", _script(_asset("whiteboard.js"))))


def cache_key(data: dict[str, Any], voice: str, fps: int = FPS) -> str:
    from . import platform_settings

    says = [s.get("say") for s in data.get("scenes") or []]
    # A new hand photo, tip or size is a new video.
    look = [str(platform_settings.get(k, "") or "") for k in
            ("whiteboard_hand_image", "whiteboard_hand_tip", "whiteboard_hand_width", "whiteboard_hand_style",
             "narration_rate")]
    blob = json.dumps({"v": VERSION, "scenes": data.get("scenes"), "says": says, "voice": voice, "fps": fps,
                       "look": look}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


def object_name(question_id: str, key: str) -> str:
    return f"videos/{question_id}/{key}.mp4"


def public_url(name: str) -> str:
    from ..infra.storage import public_object_url

    return public_object_url(name)


def ffmpeg_binary() -> str | None:
    return shutil.which("ffmpeg")


def _probe_seconds(path: Path) -> float:
    probe = shutil.which("ffprobe")
    if not probe:
        # Without ffprobe, ~16 kB/s is what edge's 24 kHz mono mp3 runs at.
        return path.stat().st_size / 6000.0
    out = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, timeout=30)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return path.stat().st_size / 6000.0


_SPOKEN: dict[str, tuple[bytes, float]] = {}


def speak(text: str, voice: str) -> tuple[bytes | None, float]:
    """One sentence in this voice at the console's pace, and how long it
    runs. Spoken once: kept in this process and in object storage, so the
    live board and the MP4 share it and a second viewer waits for nothing."""
    from ..infra.storage import object_storage
    from .math_engine.tts_service import TtsService, _rate

    text = (text or "").strip()
    if not text:
        return None, 0.0
    try:
        rate = _rate()
    except Exception:  # noqa: BLE001
        rate = "+0%"
    from .speech_text import VERSION as SPEECH

    key = hashlib.sha256(f"v2|{SPEECH}|{voice}|{rate}|{text}".encode()).hexdigest()[:24]
    if key in _SPOKEN:
        return _SPOKEN[key]
    name = f"narration/{key}.mp3"
    audio = object_storage.read_bytes(name) if object_storage.object_exists(name) else b""
    fresh = not audio
    if fresh:
        # Microsoft drops the odd request when several arrive together; a
        # scene left silent would fall back to the viewer's device voice.
        import time

        for attempt in range(3):
            audio = TtsService(voice=voice).speak_bytes(text, voice) or b""
            if audio:
                break
            time.sleep(0.6 * (attempt + 1))
    if not audio:
        return None, max(2.4, len(text.split()) / 2.6)
    if fresh:
        audio = _trim(audio)
    seconds = _seconds_of(audio)
    if fresh:
        object_storage.save_bytes(name, audio, "audio/mpeg")
    if len(_SPOKEN) > 2000:
        _SPOKEN.clear()
    _SPOKEN[key] = (audio, seconds)
    return audio, seconds


def _trim(audio: bytes) -> bytes:
    """The voice without the half-second of air Microsoft puts either side
    of every clip — between scenes it added up to a second and a half of
    silence, which a feed scrolls past."""
    ffmpeg = ffmpeg_binary()
    if not ffmpeg:
        return audio
    cut = ("silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,areverse,"
           "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.12,areverse")
    with tempfile.TemporaryDirectory(prefix="say-") as tmp:
        src, dst = Path(tmp) / "in.mp3", Path(tmp) / "out.mp3"
        src.write_bytes(audio)
        done = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-af", cut, "-c:a", "libmp3lame",
                               "-b:a", "64k", "-ac", "1", str(dst)], capture_output=True, timeout=60)
        if done.returncode or not dst.exists() or dst.stat().st_size < 1000:
            return audio
        return dst.read_bytes()


def _seconds_of(audio: bytes) -> float:
    with tempfile.NamedTemporaryFile(suffix=".mp3") as f:
        f.write(audio)
        f.flush()
        return max(1.2, _probe_seconds(Path(f.name)))


def speak_all(scenes: list[dict[str, Any]], voice: str) -> list[tuple[bytes | None, float]]:
    """Every scene, four at a time — a walkthrough is ready in a few seconds."""
    from concurrent.futures import ThreadPoolExecutor

    says = [str(s.get("say") or "") for s in scenes]
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(lambda t: speak(t, voice), says))


def narrate(scenes: list[dict[str, Any]], voice: str, folder: Path) -> list[tuple[Path | None, float]]:
    """One audio file per scene and how long it runs. A scene the voice
    could not speak keeps a reading-pace length and stays silent."""
    out: list[tuple[Path | None, float]] = []
    for n, (audio, seconds) in enumerate(speak_all(scenes, voice)):
        if scenes[n].get("hold"):
            # A silent beat of a set length — the countdown.
            out.append((None, float(scenes[n]["hold"])))
            continue
        if audio:
            path = folder / f"say_{n:03d}.mp3"
            path.write_bytes(audio)
            out.append((path, seconds))
        else:
            out.append((None, seconds))
    return out


def live_page(data: dict[str, Any], *, title: str, voice: str, autoplay: bool = False) -> str:
    """The board for the console, voiced by the server — the same voice as
    the MP4 rather than whatever voice the viewer's device has. A scene the
    voice could not speak falls back to the device."""
    import base64

    clips = speak_all(data.get("scenes") or [], voice)
    audio = ["data:audio/mpeg;base64," + base64.b64encode(a).decode() if a else None for a, _ in clips]
    durations = [round(d, 3) for _, d in clips]
    lang = "-".join(voice.split("-")[:2]) or "en-KE"
    return page(data, title=title, voice=lang, durations=durations, audio=audio, autoplay=autoplay)


def _starts(durations: list[float]) -> list[float]:
    """Where each scene's voice begins — the board's own arithmetic:
    a 0.3 s lead-in, then each scene plus the 0.4 s gap after it."""
    at, out = 0.3, []
    for d in durations:
        out.append(at)
        at += d + 0.4
    return out


def render(data: dict[str, Any], *, title: str = "", voice: str = "", subject: str = "",
           fps: int = FPS, progress: Any = None, social: dict[str, Any] | None = None,
           prefix: str = "videos", key: str = "") -> dict[str, Any]:
    """Speak, draw and encode one walkthrough. Returns {url, seconds, key}
    — and, for a social cut, a thumbnail too."""
    from ..settings import settings
    from ..infra.storage import object_storage
    from .math_engine.tts_service import voice_for

    ffmpeg = ffmpeg_binary()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed on this worker — rebuild the image (it is in the Dockerfile).")
    cdp = (getattr(settings, "playwright_cdp_url", "") or "").strip()
    scenes = data.get("scenes") or []
    if not scenes:
        raise RuntimeError("This item has no walkthrough to draw.")
    voice = voice or voice_for(subject)
    key = key or cache_key(data, voice, fps)
    qid = str(data.get("question_id") or "item")
    name = f"{prefix}/{qid}/{key}.mp4"
    thumb_name = f"{prefix}/{qid}/{key}.jpg"
    if object_storage.object_exists(name):
        record_video(qid, prefix, key, name)
        return {"url": public_url(name), "key": key, "cached": True,
                **({"thumbnail_url": public_url(thumb_name)} if social else {})}

    tick = progress or (lambda *_a, **_k: None)
    size = (1080, 1920) if social else (WIDTH, HEIGHT)
    with tempfile.TemporaryDirectory(prefix="wb-") as tmp:
        folder = Path(tmp)
        tick("voice", 0, len(scenes))
        spoken = narrate(scenes, voice, folder)
        durations = [round(d, 3) for _, d in spoken]
        starts = _starts(durations)
        doc = page(data, title=title, voice=voice, durations=durations, render=True, social=social)
        thumb_at = None
        if social:
            # The question written out and the countdown at its first number.
            k = next((i for i, sc in enumerate(scenes) if sc.get("scene") == "countdown"), 0)
            thumb_at = starts[k] + 0.4
        video = folder / "board.mp4"
        seconds, thumb = _capture(cdp, doc, video, ffmpeg, fps, tick, size=size,
                                  selector="#social" if social else "#wb", thumb_at=thumb_at)
        extras: list[tuple[Path, float]] = []
        music = None
        if social:
            extras = _countdown_ticks(ffmpeg, folder, scenes, starts)
            music = _music_file(folder, social.get("music_url") or "")
        final = folder / "final.mp4"
        tick("mux", 0, 1)
        _mux(ffmpeg, video, spoken, starts, seconds, final, extras=extras, music=music)
        tick("save", 0, 1)
        url = object_storage.save_bytes(name, final.read_bytes(), "video/mp4")
        if url.startswith("local://"):
            raise RuntimeError("The video was made but object storage refused it — is MinIO up?")
        out = {"url": url, "seconds": round(seconds, 1), "key": key, "cached": False}
        if thumb:
            out["thumbnail_url"] = object_storage.save_bytes(thumb_name, thumb, "image/jpeg")
    logger.info("Whiteboard %s for %s: %.1fs, %s", "social cut" if social else "video", qid, seconds, name)
    record_video(qid, prefix, key, name)
    return out


def record_video(question_id: str, prefix: str, key: str, object_name: str) -> None:
    """Note that this question has a video (Play's filters and the daily job
    read it). Never fails a render."""
    if not question_id or question_id == "item":
        return
    try:
        from ..infra.db import execute

        execute("""INSERT INTO question_videos (question_id, kind, video_key, object_name, made_at)
                   VALUES (:q, :k, :key, :o, NOW())
                   ON CONFLICT (question_id, kind) DO UPDATE SET video_key = EXCLUDED.video_key,
                       object_name = EXCLUDED.object_name,
                       made_at = CASE WHEN question_videos.video_key = EXCLUDED.video_key
                                      THEN question_videos.made_at ELSE NOW() END""",
                {"q": question_id, "k": "lesson" if prefix == "videos" else prefix, "key": key, "o": object_name})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record the video of %s: %s", question_id, exc)


def _countdown_ticks(ffmpeg: str, folder: Path, scenes: list[dict[str, Any]],
                     starts: list[float]) -> list[tuple[Path, float]]:
    """A soft tick each second of the countdown, a brighter one as it ends."""
    tick, ding = folder / "tick.wav", folder / "ding.wav"
    for path, freq, dur, vol in ((tick, 1150, 0.06, 0.35), (ding, 1650, 0.22, 0.4)):
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"sine=frequency={freq}:duration={dur}", "-af",
                        f"volume={vol},afade=t=out:st={dur * 0.5}:d={dur * 0.5}", str(path)],
                       capture_output=True, timeout=60, check=True)
    out: list[tuple[Path, float]] = []
    for scene, start in zip(scenes, starts):
        if scene.get("scene") == "countdown":
            n = int(scene.get("hold") or 0)
            out += [(tick, start + k) for k in range(n)] + [(ding, start + n - 0.05)]
    return out


def _music_file(folder: Path, url: str) -> Path | None:
    if not url:
        return None
    payload = _hand_bytes(url)
    if not payload:
        return None
    path = folder / "music.mp3"
    path.write_bytes(payload)
    return path


# ── the queue ────────────────────────────────────────────────────────────────

JOB_KIND = "video"


def load(question_id: str) -> dict[str, Any]:
    from . import question_rows
    from .question_dna import question_dna_service

    return question_rows.flatten(question_dna_service.get_question(question_id))


MAX_FIGURE_BYTES = 400_000   # a figure bigger than this is a photo, not a drawing


def figure_scene(q: dict[str, Any]) -> dict[str, Any] | None:
    """The item's figure as a scene the marker draws, stroke by stroke —
    as the learner sees it (gaps left as gaps). None when the item has no
    figure, or it cannot be found: the video is still made, without it."""
    binding = q.get("diagram")
    if not isinstance(binding, dict) or not (binding.get("diagram_id") or binding.get("svg_markup")):
        return None
    try:
        from .question_paper import figure_markup, figures_for

        svg = figure_markup(q, figures_for([q]), answers=False).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("No figure for the video of %s: %s", q.get("question_id") or "?", exc)
        return None
    if not svg.startswith("<svg") or len(svg) > MAX_FIGURE_BYTES:
        return None
    title = re.sub(r"\s+", " ", str(binding.get("diagram_title") or "")).strip()
    say = "Look at the figure" + (f": {title}." if title else ".") + " Notice what it shows before we start."
    return {"scene": "figure", "svg": svg, "title": title, "say": say}


def with_figure(data: dict[str, Any], q: dict[str, Any]) -> dict[str, Any]:
    """The walkthrough with the figure drawn straight after the question."""
    scene = figure_scene(q)
    scenes = list(data.get("scenes") or [])
    if not scene or any(isinstance(sc, dict) and sc.get("scene") == "figure" for sc in scenes):
        return data
    at = 1 if scenes and isinstance(scenes[0], dict) and scenes[0].get("scene") == "title" else 0
    return {**data, "scenes": scenes[:at] + [scene] + scenes[at:]}


def _script_for(q: dict[str, Any], voice: str = "") -> tuple[dict[str, Any], str, str]:
    """The walkthrough, the voice and the title for one stored item. A voice
    named for this item overrides the console's default."""
    from . import play_engine
    from .math_engine.tts_service import voice_for

    link = q.get("curriculum") or {}
    data = play_engine.walkthrough(q, grade=str(link.get("grade") or ""))
    data = with_figure(data, q)
    return data, (voice or voice_for(str(link.get("subject") or ""))), str(q.get("question_text") or "")[:80]


def status(question_id: str, q: dict[str, Any] | None = None, voice: str = "") -> dict[str, Any]:
    """The video for this item as it reads now: ready (a URL), being made
    (the job), failed (why), or none yet. A changed item is a new video —
    the key is over the script, so an edit never serves the old one."""
    from ..infra.db import fetch_one
    from ..infra.storage import object_storage

    q = q or load(question_id)
    data, voice, _ = _script_for(q, voice)
    key = cache_key(data, voice)
    name = object_name(question_id, key)
    out: dict[str, Any] = {"question_id": question_id, "key": key, "scenes": len(data.get("scenes") or [])}
    if object_storage.object_exists(name):
        return {**out, "status": "ready", "url": public_url(name)}
    job = fetch_one(
        "SELECT job_id, status, error, result FROM jobs WHERE kind = :kind "
        "AND payload->>'artifact_id' = :qid ORDER BY created_at DESC LIMIT 1",
        {"kind": JOB_KIND, "qid": question_id})
    if job and str(job.get("status")) in ("queued", "running"):
        return {**out, "status": str(job["status"]), "job_id": job["job_id"]}
    if job and str(job.get("status")) == "failed":
        return {**out, "status": "failed", "job_id": job["job_id"], "error": str(job.get("error") or "")[:400]}
    return {**out, "status": "none"}


def enqueue(question_id: str, *, queued_by: str = "", batch_id: str = "", voice: str = "") -> dict[str, Any]:
    """Queue one item's video unless it is already made or being made."""
    from . import job_queue

    q = load(question_id)
    now = status(question_id, q, voice)
    if now["status"] in ("ready", "queued", "running"):
        return now
    if not now["scenes"]:
        return {**now, "status": "skipped", "error": "Nothing to draw for this item."}
    link = q.get("curriculum") or {}
    job = job_queue.enqueue(
        JOB_KIND, str(link.get("grade") or ""), str(link.get("subject") or ""),
        # artifact_id keys the duplicate check: two items in one sub-strand
        # are two videos, not one queued twice.
        {"artifact_id": question_id, "question_id": question_id, "voice": voice},
        strand=str(link.get("strand") or ""), sub_strand=str(link.get("sub_strand") or ""),
        batch_id=batch_id, queued_by=queued_by or "whiteboard")
    job_queue.start_worker()
    return {**now, "status": "queued", "job_id": job.job_id}


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    from . import run_log

    payload = dict(job.get("payload") or {})
    qid = str(payload.get("question_id") or payload.get("artifact_id") or "")
    if not qid:
        return {"status": "skipped", "reason": "no question_id"}
    q = load(qid)
    data, voice, title = _script_for(q, str(payload.get("voice") or ""))
    run_log.step("Script", f"{len(data.get('scenes') or [])} scenes · {data.get('kind')} · {voice}")
    last = {"stage": ""}
    from .job_queue import Live

    live = Live(str(job.get("job_id") or ""))
    live("script", 1, 1)

    def tick(stage: str, n: int, total: int) -> None:
        live(stage, n, total)
        if stage != last["stage"]:
            run_log.step({"voice": "Narrating", "draw": "Drawing"}.get(stage, stage), f"{total} to do")
            last["stage"] = stage
        elif stage == "draw" and n and n % (FPS * 20) == 0:
            run_log.step("Drawing", f"frame {n} of {total}")

    made = render(data, title=title, voice=voice, progress=tick)
    live.done()
    run_log.step("Saved", made["url"])
    return {"status": "done", "question_id": qid, **made}


def _capture(cdp: str, doc: str, out: Path, ffmpeg: str, fps: int, tick: Any, *,
             size: tuple[int, int] = (WIDTH, HEIGHT), selector: str = "#wb",
             thumb_at: float | None = None) -> tuple[float, bytes | None]:
    """Every frame of the page, piped into ffmpeg.

    A video is a minute or two of screenshots, longer than the browser
    service keeps a session: browserless closed it mid-capture ("Target
    page, context or browser has been closed") and not one video finished.
    So the image's own Chromium is used first — no session limit — and the
    service only when there is none; and a browser that goes away mid-way
    is reconnected and the capture resumes at the frame it reached, since
    the page draws any moment the same way."""
    from playwright.sync_api import sync_playwright

    from .browser import CONNECT_TIMEOUT_MS, LAUNCH_ARGS

    encoder = subprocess.Popen(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg",
         "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-r", str(fps), str(out)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    total = 0.0
    thumb: bytes | None = None
    frame = 0
    frames = 0
    attempts = 0
    try:
        with sync_playwright() as p:
            while True:
                browser = None
                try:
                    try:
                        browser = p.chromium.launch(headless=True, args=LAUNCH_ARGS)
                    except Exception as exc:  # noqa: BLE001
                        if not cdp:
                            raise
                        logger.info("No local Chromium (%s); using the browser service.", str(exc).splitlines()[0][:120])
                        browser = p.chromium.connect_over_cdp(cdp, timeout=CONNECT_TIMEOUT_MS)
                    context = browser.new_context(viewport={"width": size[0], "height": size[1]}, device_scale_factor=1)
                    pg = context.new_page()
                    pg.set_content(doc, wait_until="domcontentloaded", timeout=60000)  # fonts: __ready waits up to 2.5 s
                    total = min(float(pg.evaluate("() => window.__ready")), MAX_SECONDS)
                    frames = int(total * fps) + 1
                    box = pg.locator(selector).bounding_box() or {"x": 0, "y": 0, "width": size[0], "height": size[1]}
                    clip = {"x": box["x"], "y": box["y"], "width": box["width"], "height": box["height"]}
                    while frame < frames:
                        pg.evaluate("t => window.__seek(t)", frame / fps)
                        encoder.stdin.write(pg.screenshot(type="jpeg", quality=88, clip=clip,  # type: ignore[union-attr]
                                                          animations="disabled"))
                        if frame % (fps * 2) == 0:
                            tick("draw", frame, frames)
                        frame += 1
                    if thumb_at is not None:
                        pg.evaluate("t => window.__seek(t)", min(thumb_at, total))
                        thumb = pg.screenshot(type="jpeg", quality=90, clip=clip)
                    context.close()
                    break
                except Exception as exc:  # noqa: BLE001
                    attempts += 1
                    if attempts > 3 or "closed" not in str(exc).lower():
                        raise
                    logger.warning("Browser went away at frame %d of %d; reconnecting (%d).", frame, frames, attempts)
                finally:
                    try:
                        if browser is not None:
                            browser.close()
                    except Exception:  # noqa: BLE001
                        pass
    finally:
        if encoder.stdin and not encoder.stdin.closed:
            encoder.stdin.close()
        err = encoder.stderr.read() if encoder.stderr else b""
        encoder.wait(timeout=600)
    if encoder.returncode:
        raise RuntimeError(f"ffmpeg could not encode the board: {err.decode(errors='ignore')[-400:]}")
    return total, thumb


def _mux(ffmpeg: str, video: Path, spoken: list[tuple[Path | None, float]], starts: list[float],
         seconds: float, out: Path, *, extras: list[tuple[Path, float]] | tuple = (),
         music: Path | None = None) -> None:
    """Each scene's voice placed where its scene starts on the board; any
    extra sounds (the countdown's ticks) at their times; music, if any,
    quietly under all of it."""
    voiced = [(p, s) for (p, _), s in zip(spoken, starts) if p] + list(extras)
    if not voiced and not music:
        shutil.copyfile(video, out)
        return
    args = [ffmpeg, "-y", "-loglevel", "error", "-i", str(video)]
    for p, _ in voiced:
        args += ["-i", str(p)]
    chains = [f"[{k + 1}:a]adelay={int(s * 1000)}|{int(s * 1000)}[a{k}]" for k, (_, s) in enumerate(voiced)]
    labels = [f"[a{k}]" for k in range(len(voiced))]
    if music:
        args += ["-stream_loop", "-1", "-i", str(music)]
        m = len(voiced) + 1
        fade = max(0.0, seconds - 1.5)
        chains.append(f"[{m}:a]volume=0.10,afade=t=in:d=1,afade=t=out:st={fade:.2f}:d=1.5[mus]")
        labels.append("[mus]")
    graph = ";".join(chains) + f";{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,apad[aout]"
    args += ["-filter_complex", graph, "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac",
             "-b:a", "128k", "-t", f"{seconds:.2f}", "-movflags", "+faststart", str(out)]
    done = subprocess.run(args, capture_output=True, timeout=600)
    if done.returncode:
        raise RuntimeError(f"ffmpeg could not add the voice: {done.stderr.decode(errors='ignore')[-400:]}")


_CONTROLS = """<div class="bar">
 <button id="wb-prev" onclick="__wb.prev()">⟨</button>
 <button id="wb-play" onclick="__wb.toggle()">▶ Play</button>
 <button id="wb-next" onclick="__wb.next()">⟩</button>
 <span id="wb-count"></span>
 <p id="wb-say"></p>
</div>
<script>window.__ready.then(function(){ if (__AUTOPLAY__) __wb.play(); });</script>"""

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Patrick+Hand&display=swap" rel="stylesheet">
<style>
 html,body{margin:0;background:#e9e7e1;font-family:system-ui,sans-serif;color:#1b1f2a}
 body.render{background:#fdfdfb}
 body.render #wb{width:1280px;height:720px}
 body.live #wb{max-width:1100px;margin:16px auto 0;box-shadow:0 2px 12px rgba(0,0,0,.12);border-radius:8px;overflow:hidden}
 .bar{max-width:1100px;margin:10px auto;padding:0 16px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
 .bar button{font:inherit;padding:6px 14px;border-radius:6px;border:1px solid #c9c6bd;background:#fff;cursor:pointer}
 .bar span{color:#6b7280;font-size:14px}
 .bar p{flex-basis:100%;margin:6px 0 0;font-size:18px;line-height:1.45;min-height:2.9em}
</style></head><body class="__BODY_CLASS__">
<div id="wb"></div>
<script>__GSAP__</script>
<script>window.WB_DATA = __DATA__;</script>
<script>__ENGINE__</script>
__CONTROLS__
</body></html>"""
