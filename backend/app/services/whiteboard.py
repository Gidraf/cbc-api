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
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger("cbc-whiteboard")

STATIC = Path(__file__).resolve().parent.parent / "static"
VERSION = "wb2"          # bump when the board draws differently: old videos re-render
FPS = 20
WIDTH, HEIGHT = 1280, 720
MAX_SECONDS = 240


@lru_cache(maxsize=4)
def _asset(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _script(js: str) -> str:
    return js.replace("</script", "<\\/script")


def page(data: dict[str, Any], *, title: str = "", voice: str = "en-KE", durations: list[float] | None = None,
         render: bool = False, autoplay: bool = False) -> str:
    """The board for one walkthrough. `durations` (seconds per scene) come
    from the voice files when rendering; live, the board estimates them."""
    payload = {"scenes": data.get("scenes") or [], "seed": str(data.get("question_id") or title or "wb"),
               "voice": voice, "durations": durations or []}
    chrome = "" if render else _CONTROLS.replace("__AUTOPLAY__", "true" if autoplay else "false")
    return (_PAGE.replace("__TITLE__", html.escape(title or "Whiteboard"))
            .replace("__BODY_CLASS__", "render" if render else "live")
            .replace("__CONTROLS__", chrome)
            .replace("__GSAP__", _script(_asset("gsap.min.js")))
            .replace("__DATA__", json.dumps(payload).replace("</", "<\\/"))
            .replace("__ENGINE__", _script(_asset("whiteboard.js"))))


def cache_key(data: dict[str, Any], voice: str, fps: int = FPS) -> str:
    says = [s.get("say") for s in data.get("scenes") or []]
    blob = json.dumps({"v": VERSION, "scenes": data.get("scenes"), "says": says, "voice": voice, "fps": fps},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


def object_name(question_id: str, key: str) -> str:
    return f"videos/{question_id}/{key}.mp4"


def public_url(name: str) -> str:
    from ..settings import settings

    return f"{settings.minio_public_base_url}/{settings.minio_bucket}/{name}"


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


def narrate(scenes: list[dict[str, Any]], voice: str, folder: Path) -> list[tuple[Path | None, float]]:
    """One audio file per scene and how long it runs. A scene the voice
    could not speak keeps a reading-pace length and stays silent."""
    from .math_engine.tts_service import TtsService

    tts = TtsService(voice=voice)
    out: list[tuple[Path | None, float]] = []
    for n, scene in enumerate(scenes):
        text = str(scene.get("say") or "").strip()
        audio = tts.speak_bytes(text, voice) if text else None
        if audio:
            path = folder / f"say_{n:03d}.mp3"
            path.write_bytes(audio)
            out.append((path, max(1.2, _probe_seconds(path))))
        else:
            out.append((None, max(2.4, len(text.split()) / 2.6)))
    return out


def _starts(durations: list[float]) -> list[float]:
    """Where each scene's voice begins — the board's own arithmetic:
    a 0.3 s lead-in, then each scene plus the 0.4 s gap after it."""
    at, out = 0.3, []
    for d in durations:
        out.append(at)
        at += d + 0.4
    return out


def render(data: dict[str, Any], *, title: str = "", voice: str = "", subject: str = "",
           fps: int = FPS, progress: Any = None) -> dict[str, Any]:
    """Speak, draw and encode one walkthrough. Returns {url, seconds, key}."""
    from ..settings import settings
    from ..infra.storage import object_storage
    from .math_engine.tts_service import voice_for

    ffmpeg = ffmpeg_binary()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed on this worker — rebuild the image (it is in the Dockerfile).")
    cdp = (getattr(settings, "playwright_cdp_url", "") or "").strip()
    if not cdp:
        raise RuntimeError("No headless browser: set PLAYWRIGHT_CDP_URL (the browserless service).")
    scenes = data.get("scenes") or []
    if not scenes:
        raise RuntimeError("This item has no walkthrough to draw.")
    voice = voice or voice_for(subject)
    key = cache_key(data, voice, fps)
    qid = str(data.get("question_id") or "item")
    name = object_name(qid, key)
    if object_storage.object_exists(name):
        return {"url": public_url(name), "key": key, "cached": True}

    tick = progress or (lambda *_a, **_k: None)
    with tempfile.TemporaryDirectory(prefix="wb-") as tmp:
        folder = Path(tmp)
        tick("voice", 0, len(scenes))
        spoken = narrate(scenes, voice, folder)
        durations = [round(d, 3) for _, d in spoken]
        doc = page(data, title=title, voice=voice, durations=durations, render=True)
        video = folder / "board.mp4"
        seconds = _capture(cdp, doc, video, ffmpeg, fps, tick)
        final = folder / "final.mp4"
        _mux(ffmpeg, video, spoken, _starts(durations), seconds, final)
        url = object_storage.save_bytes(name, final.read_bytes(), "video/mp4")
        if url.startswith("local://"):
            raise RuntimeError("The video was made but object storage refused it — is MinIO up?")
    logger.info("Whiteboard video for %s: %.1fs, %s", qid, seconds, name)
    return {"url": url, "seconds": round(seconds, 1), "key": key, "cached": False}


# ── the queue ────────────────────────────────────────────────────────────────

JOB_KIND = "video"


def load(question_id: str) -> dict[str, Any]:
    from . import question_rows
    from .question_dna import question_dna_service

    return question_rows.flatten(question_dna_service.get_question(question_id))


def _script_for(q: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    """The walkthrough, the voice and the title for one stored item."""
    from . import play_engine
    from .math_engine.tts_service import voice_for

    link = q.get("curriculum") or {}
    data = play_engine.walkthrough(q, grade=str(link.get("grade") or ""))
    return data, voice_for(str(link.get("subject") or "")), str(q.get("question_text") or "")[:80]


def status(question_id: str, q: dict[str, Any] | None = None) -> dict[str, Any]:
    """The video for this item as it reads now: ready (a URL), being made
    (the job), failed (why), or none yet. A changed item is a new video —
    the key is over the script, so an edit never serves the old one."""
    from ..infra.db import fetch_one
    from ..infra.storage import object_storage

    q = q or load(question_id)
    data, voice, _ = _script_for(q)
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


def enqueue(question_id: str, *, queued_by: str = "", batch_id: str = "") -> dict[str, Any]:
    """Queue one item's video unless it is already made or being made."""
    from . import job_queue

    q = load(question_id)
    now = status(question_id, q)
    if now["status"] in ("ready", "queued", "running"):
        return now
    if not now["scenes"]:
        return {**now, "status": "skipped", "error": "Nothing to draw for this item."}
    link = q.get("curriculum") or {}
    job = job_queue.enqueue(
        JOB_KIND, str(link.get("grade") or ""), str(link.get("subject") or ""),
        # artifact_id keys the duplicate check: two items in one sub-strand
        # are two videos, not one queued twice.
        {"artifact_id": question_id, "question_id": question_id},
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
    data, voice, title = _script_for(q)
    run_log.step("Script", f"{len(data.get('scenes') or [])} scenes · {data.get('kind')} · {voice}")
    last = {"stage": ""}

    def tick(stage: str, n: int, total: int) -> None:
        if stage != last["stage"]:
            run_log.step({"voice": "Narrating", "draw": "Drawing"}.get(stage, stage), f"{total} to do")
            last["stage"] = stage
        elif stage == "draw" and n and n % (FPS * 20) == 0:
            run_log.step("Drawing", f"frame {n} of {total}")

    made = render(data, title=title, voice=voice, progress=tick)
    run_log.step("Saved", made["url"])
    return {"status": "done", "question_id": qid, **made}


def _capture(cdp: str, doc: str, out: Path, ffmpeg: str, fps: int, tick: Any) -> float:
    from playwright.sync_api import sync_playwright

    encoder = subprocess.Popen(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg",
         "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-r", str(fps), str(out)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    total = 0.0
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(cdp, timeout=30000)
            try:
                context = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
                pg = context.new_page()
                pg.set_content(doc, wait_until="load", timeout=60000)
                total = float(pg.evaluate("() => window.__ready"))
                total = min(total, MAX_SECONDS)
                frames = int(total * fps) + 1
                board = pg.locator("#wb")
                for f in range(frames):
                    pg.evaluate("t => window.__seek(t)", f / fps)
                    encoder.stdin.write(board.screenshot(type="jpeg", quality=88))  # type: ignore[union-attr]
                    if f % (fps * 2) == 0:
                        tick("draw", f, frames)
                context.close()
            finally:
                browser.close()
    finally:
        if encoder.stdin and not encoder.stdin.closed:
            encoder.stdin.close()
        err = encoder.stderr.read() if encoder.stderr else b""
        encoder.wait(timeout=600)
    if encoder.returncode:
        raise RuntimeError(f"ffmpeg could not encode the board: {err.decode(errors='ignore')[-400:]}")
    return total


def _mux(ffmpeg: str, video: Path, spoken: list[tuple[Path | None, float]], starts: list[float],
         seconds: float, out: Path) -> None:
    """Each scene's voice placed where its scene starts on the board."""
    voiced = [(p, s) for (p, _), s in zip(spoken, starts) if p]
    if not voiced:
        shutil.copyfile(video, out)
        return
    args = [ffmpeg, "-y", "-loglevel", "error", "-i", str(video)]
    for p, _ in voiced:
        args += ["-i", str(p)]
    chains = [f"[{k + 1}:a]adelay={int(s * 1000)}|{int(s * 1000)}[a{k}]" for k, (_, s) in enumerate(voiced)]
    mix = "".join(f"[a{k}]" for k in range(len(voiced)))
    graph = ";".join(chains) + f";{mix}amix=inputs={len(voiced)}:normalize=0:dropout_transition=0,apad[aout]"
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
