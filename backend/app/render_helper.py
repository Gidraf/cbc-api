"""Render the server's queued videos on this Mac, and send them back.

    python -m app.render_helper          (poster/mac/install-render.sh runs it at login)

Reads CBC_API_URL and CBC_API_KEY (the poster's, ~/.cbc/poster/.env). Each
slot asks the server for the next queued video, draws it here with the same
code the server uses — the Mac's Chrome and its GPU, a video in about two
minutes instead of fifteen — and uploads the MP4 and thumbnail. While it
draws it sends a heartbeat, so the server knows the job is alive.

No database here: what the server would read from it (the voice's pace, the
hand, the music, the frame) comes with the job. Narration is cached in
~/.cbc/render/cache, so a voice said once is not asked for again.

RENDER_SLOTS (default 2) is how many videos draw at once.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s render %(message)s")
log = logging.getLogger("render")

HOME = Path(os.getenv("RENDER_HOME", os.path.expanduser("~/.cbc/render")))
CACHE = HOME / "cache"
WORKER = f"mac-{socket.gethostname().split('.')[0]}"[:60]


def _load_env() -> None:
    """The poster's settings file, if the environment does not say."""
    env = Path(os.path.expanduser("~/.cbc/poster/.env"))
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _api() -> tuple[str, dict[str, str]]:
    return os.environ["CBC_API_URL"].rstrip("/"), {"X-API-Key": os.environ["CBC_API_KEY"]}


# ── this machine, without the server's database or storage ───────────────────

_files: dict[str, Path] = {}
_files_lock = threading.Lock()


def _local_storage() -> None:
    """Storage on disk: narration cached across jobs, outputs collected per job."""
    from app.infra import storage

    CACHE.mkdir(parents=True, exist_ok=True)
    s = storage.object_storage

    def path(name: str) -> Path:
        return CACHE / name.replace("/", "__")

    s.object_exists = lambda name: name.startswith("narration/") and path(name).exists()
    s.read_bytes = lambda name: path(name).read_bytes() if path(name).exists() else None

    def save_bytes(name: str, payload: bytes, mime: str = "application/octet-stream") -> str:
        p = path(name)
        p.write_bytes(payload)
        with _files_lock:
            _files[name] = p
        return f"file://{p}"

    s.save_bytes = save_bytes
    s.save_text = lambda name, text: save_bytes(name, text.encode())
    from app.services import platform_settings

    platform_settings._load = lambda: {}             # no database: environment and defaults


def _real_chrome() -> None:
    """Playwright's own Chromium is not installed on a Mac; its Chrome is."""
    import playwright.sync_api as psa

    original = psa.BrowserType.launch

    def launch(self: Any, *a: Any, **k: Any) -> Any:
        k.setdefault("channel", os.getenv("RENDER_CHANNEL", "chrome"))
        # The Mac has a GPU: let Chrome use it instead of software WebGL.
        k["args"] = [x for x in (k.get("args") or []) if x not in ("--disable-gpu", "--use-angle=swiftshader")]
        return original(self, *a, **k)

    psa.BrowserType.launch = launch


# ── one job ──────────────────────────────────────────────────────────────────

def _teacher_models(spec: dict[str, Any]) -> None:
    """Any teacher's model the job names and this Mac lacks, fetched from the
    server: teachers added there since this helper was installed still appear."""
    from app.services import whiteboard

    teacher = (spec.get("social") or {}).get("teacher") or {}
    models = [c.get("model") for c in teacher.get("cast") or []] or ([teacher.get("gender")] if teacher.get("gender") else [])
    folder = whiteboard.STATIC / "teachers"
    base, headers = _api()
    for model in [m for m in models if m]:
        path = folder / f"{model}.glb"
        if path.exists():
            continue
        log.info("Fetching the teacher model %s from the server", model)
        r = httpx.get(f"{base}/api/v1/play/render/teachers/{model}.glb", headers=headers, timeout=120)
        r.raise_for_status()
        if r.content[:4] != b"glTF":
            raise RuntimeError(f"The server's model {model} is not a glTF file")
        tmp = path.with_suffix(".part")
        tmp.write_bytes(r.content)
        tmp.replace(path)


def _render(spec: dict[str, Any], progress: Any) -> dict[str, Any]:
    import base64

    from app.services import whiteboard

    _teacher_models(spec)

    os.environ["TTS_RATE"] = spec.get("rate") or "+0%"
    whiteboard.hand = lambda: spec.get("hand")
    music = base64.b64decode(spec["music"]) if spec.get("music") else b""

    def music_file(folder: Path, url: str) -> Path | None:
        if not music:
            return None
        p = folder / "music.mp3"
        p.write_bytes(music)
        return p

    whiteboard._music_file = music_file
    return whiteboard.render(spec["data"], title=spec.get("title") or "", voice=spec["voice"], progress=progress,
                             social=spec.get("social"), prefix=spec["prefix"], key=spec["key"])


def run_one(client: httpx.Client) -> bool:
    """Take a job, draw it, send it. False when the queue was empty."""
    base, headers = _api()
    r = client.post(f"{base}/api/v1/play/render/claim", params={"worker": WORKER}, headers=headers, timeout=120)
    r.raise_for_status()
    got = r.json()
    job = got.get("job")
    if not job:
        return False
    job_id, spec = job["job_id"], got["spec"]
    log.info("Job %s: %s for %s", job_id, spec["kind"], spec["question_id"])
    state = {"stage": "voice", "pct": 0.0, "stop": False}

    def beat() -> None:
        while not state["stop"]:
            try:
                client.post(f"{base}/api/v1/play/render/{job_id}/heartbeat", headers=headers, timeout=30,
                            json={"stage": state["stage"], "pct": state["pct"]})
            except Exception as exc:  # noqa: BLE001
                log.info("Heartbeat for %s missed: %s", job_id, type(exc).__name__)
            for _ in range(20):
                if state["stop"]:
                    return
                time.sleep(1)

    weights = {"voice": (0, 10), "draw": (10, 85), "mux": (85, 95), "save": (95, 100)}

    def progress(stage: str, n: int = 0, total: int = 0) -> None:
        lo, hi = weights.get(stage, (state["pct"], state["pct"]))
        state["stage"], state["pct"] = stage, round(lo + (hi - lo) * (n / total if total else 0), 1)

    hb = threading.Thread(target=beat, daemon=True)
    hb.start()
    started = time.time()
    try:
        made = _render(spec, progress)
        prefix, qid, key = spec["prefix"], spec["question_id"], spec["key"]
        with _files_lock:
            video = _files.pop(f"{prefix}/{qid}/{key}.mp4", None)
            thumb = _files.pop(f"{prefix}/{qid}/{key}.jpg", None)
        if not video or not video.exists():
            raise RuntimeError("the render finished without a video file")
        files = {"video": (video.name, video.read_bytes(), "video/mp4")}
        if thumb and thumb.exists():
            files["thumbnail"] = (thumb.name, thumb.read_bytes(), "image/jpeg")
        for attempt in range(4):
            try:
                up = client.post(f"{base}/api/v1/play/render/{job_id}/done", headers=headers, files=files,
                                 data={"seconds": str(made.get("seconds") or 0)}, timeout=600)
                up.raise_for_status()
                break
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if attempt == 3 or (isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500):
                    raise
                time.sleep(5 * (attempt + 1))
        log.info("Job %s done in %.0f s (%s s of video)", job_id, time.time() - started, made.get("seconds"))
        for p in (video, thumb):
            if p and p.exists():
                p.unlink()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Job %s failed: %s", job_id, exc)
        try:
            client.post(f"{base}/api/v1/play/render/{job_id}/failed", headers=headers, timeout=60,
                        json={"error": f"{type(exc).__name__}: {exc}"[:900], "worker": WORKER})
        except Exception:  # noqa: BLE001
            pass
        return True
    finally:
        state["stop"] = True


def idle_seconds() -> float | None:
    """How long since anyone touched this Mac's keyboard or mouse."""
    import re
    import subprocess

    try:
        out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, timeout=10).stdout
        m = re.search(r'"HIDIdleTime" = (\d+)', out)
        return int(m.group(1)) / 1e9 if m else None
    except Exception:  # noqa: BLE001
        return None


_hours = {"at": 0.0, "schedule": None, "said": ""}
_hours_lock = threading.Lock()


def may_work(client: httpx.Client) -> tuple[bool, str]:
    """The owner's working hours for the Macs (Play → Auto-post), read every minute."""
    from datetime import datetime

    from app.services import render_hours

    with _hours_lock:
        if _hours["schedule"] is None or time.time() - _hours["at"] > 60:
            try:
                base, headers = _api()
                r = client.get(f"{base}/api/v1/play/render/schedule", headers=headers, timeout=30)
                r.raise_for_status()
                _hours["schedule"] = render_hours.clean(r.json())
            except Exception:  # noqa: BLE001
                _hours["schedule"] = _hours["schedule"] or render_hours.clean("")   # an older server: always
            _hours["at"] = time.time()
        ok, why = render_hours.allowed(_hours["schedule"], datetime.now(), idle_seconds())
        said = "" if ok else why
        if said != _hours["said"]:
            log.info("Working hours: %s", "rendering" if ok else f"resting — {why}")
            _hours["said"] = said
    return ok, why


def slot(n: int) -> None:
    with httpx.Client() as client:
        while True:
            try:
                if not may_work(client)[0]:
                    time.sleep(60)                   # outside the working hours: look again in a minute
                    continue
                if not run_one(client):
                    time.sleep(30)                   # nothing queued: look again in half a minute
            except Exception as exc:  # noqa: BLE001
                log.warning("Slot %d: %s — trying again in a minute", n, type(exc).__name__)
                time.sleep(60)


def main() -> None:
    _load_env()
    if not os.getenv("CBC_API_URL") or not os.getenv("CBC_API_KEY"):
        raise SystemExit("CBC_API_URL and CBC_API_KEY are needed (the poster's ~/.cbc/poster/.env has them).")
    _local_storage()
    _real_chrome()
    slots = max(1, min(int(os.getenv("RENDER_SLOTS", "2") or 2), 6))
    log.info("Render helper %s → %s, %d at once", WORKER, os.environ["CBC_API_URL"], slots)
    threads = [threading.Thread(target=slot, args=(k + 1,), daemon=True) for k in range(slots)]
    for t in threads:
        t.start()
        time.sleep(5)
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
