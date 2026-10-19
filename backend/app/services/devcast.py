"""Devcast: the developer cut — code typed in a VS Code (Dark+) frame, a
terminal, and the result in a Word or Excel window, narrated with captions.

For the LinkedIn series on building with the API (services/devcast_series.py).
A script is a list of scenes:

* ``title``    kicker, text, sub
* ``code``     file, lang (js|ts|py|vba|bash|json|xml|gs), code, highlight
               (1-based lines), prefilled (lines already there), typed
* ``terminal`` cmd, output (lines)
* ``word``     file, doc (blocks: h | p | q+n+marks | eq | opts | box+locked |
               table | result | img), pane (title, fields, timer [from, to],
               progress [n, of], lines, button), reveal
* ``excel``    file, rows, select, formula, sheet, widths, header, reveal
* ``points``   title, items
* ``outro``    text, cta, handle, website

Every scene has ``say``, the narration. It reuses the whiteboard pipeline:
the same voice, frame capture and ffmpeg mux, on the same render lane.
"""
from __future__ import annotations

import copy
import hashlib
import html
import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("cbc-devcast")

JOB_KIND = "devcast"
PREFIX = "devcast"
VERSION = "dc1"          # bump when the frame draws differently: old videos re-render
SIZES = {"square": (1080, 1080), "portrait": (1080, 1350), "landscape": (1920, 1080)}
SCENES = ("title", "code", "terminal", "word", "excel", "points", "outro")
LANGS = ("js", "ts", "py", "vba", "bash", "sh", "json", "xml", "html", "gs")
MAX_SCENES = 24
MAX_SAY = 600
MAX_CODE = 6000


def _slug(text: str, n: int = 60) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:n]


def validate(script: dict[str, Any]) -> dict[str, Any]:
    """The script as it will be drawn, or ValueError saying what is wrong."""
    if not isinstance(script, dict):
        raise ValueError("A script is an object with scenes.")
    scenes = script.get("scenes")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= MAX_SCENES:
        raise ValueError(f"A script has 1–{MAX_SCENES} scenes.")
    fmt = str(script.get("format") or "square")
    if fmt not in SIZES:
        raise ValueError(f"format is one of {', '.join(SIZES)}.")
    out = []
    for n, sc in enumerate(scenes, start=1):
        if not isinstance(sc, dict) or sc.get("scene") not in SCENES:
            raise ValueError(f"Scene {n}: scene is one of {', '.join(SCENES)}.")
        if len(str(sc.get("say") or "")) > MAX_SAY:
            raise ValueError(f"Scene {n}: keep the narration under {MAX_SAY} characters.")
        if sc["scene"] == "code":
            if not str(sc.get("code") or "").strip():
                raise ValueError(f"Scene {n}: a code scene needs code.")
            if len(str(sc["code"])) > MAX_CODE:
                raise ValueError(f"Scene {n}: keep the code under {MAX_CODE} characters.")
            if str(sc.get("lang") or "js") not in LANGS:
                raise ValueError(f"Scene {n}: lang is one of {', '.join(LANGS)}.")
        if sc["scene"] == "terminal" and len(sc.get("output") or []) > 40:
            raise ValueError(f"Scene {n}: show at most 40 lines of output.")
        out.append(copy.deepcopy(sc))
    sid = _slug(script.get("id") or script.get("title") or "devcast") or "devcast"
    return {"id": sid, "title": str(script.get("title") or sid)[:140], "format": fmt, "scenes": out}


def _brand() -> dict[str, str]:
    """The developer account's handle and site (Settings: devcast_handle,
    devcast_website), else the main brand's."""
    from . import platform_settings
    from .social import brand

    try:
        b = brand()
        handle = str(platform_settings.get("devcast_handle", "") or "").strip() or b.get("handle") or ""
        website = str(platform_settings.get("devcast_website", "") or "").strip() or b.get("website") or ""
    except Exception:  # noqa: BLE001
        return {"handle": "", "website": ""}
    if handle and not handle.startswith("@"):
        handle = "@" + handle
    return {"handle": handle, "website": website}


def _repo() -> str:
    from . import platform_settings

    try:
        return str(platform_settings.get("devcast_repo", "") or "cbc-api")
    except Exception:  # noqa: BLE001
        return "cbc-api"


def page(script: dict[str, Any], *, render: bool = False, durations: list[float] | None = None,
         audio: list[str | None] | None = None, autoplay: bool = False) -> str:
    """One self-contained page: the frame, the engine and the script."""
    from .whiteboard import _asset, _script

    s = validate(script)
    w, h = SIZES[s["format"]]
    payload = {"scenes": s["scenes"], "durations": durations or [], "audio": audio or [], "size": [w, h],
               "brand": _brand(), "repo": _repo()}
    chrome = "" if render else _CONTROLS.replace("__AUTOPLAY__", "true" if autoplay else "false")
    # The script goes in last, so nothing in it is taken for a placeholder.
    return (_PAGE.replace("__CONTROLS__", chrome)
            .replace("__TITLE__", html.escape(s["title"]))
            .replace("__W__", str(w)).replace("__H__", str(h))
            .replace("__BODY_CLASS__", f"{s['format']} {'render' if render else 'live'}")
            .replace("__ENGINE__", _script(_asset("devcast.js")))
            .replace("__DATA__", json.dumps(payload).replace("</", "<\\/")))


def default_voice() -> str:
    from . import platform_settings
    from .math_engine.tts_service import voice_for

    try:
        return str(platform_settings.get("devcast_voice", "") or "") or voice_for("")
    except Exception:  # noqa: BLE001
        return voice_for("")


def live_page(script: dict[str, Any], voice: str = "", *, voiced: bool = True, autoplay: bool = False) -> str:
    """The page for the console, voiced by the server as the MP4 will be."""
    import base64

    from .whiteboard import speak_all

    s = validate(script)
    if not voiced:
        return page(s, autoplay=autoplay)
    clips = speak_all(s["scenes"], voice or default_voice())
    audio = ["data:audio/mpeg;base64," + base64.b64encode(a).decode() if a else None for a, _ in clips]
    return page(s, durations=[round(d, 3) for _, d in clips], audio=audio, autoplay=autoplay)


def cache_key(script: dict[str, Any], voice: str) -> str:
    from . import platform_settings
    from .whiteboard import FPS

    s = validate(script)
    look = [str(platform_settings.get(k, "") or "") for k in ("narration_rate", "devcast_repo", "social_handle",
                                                                "social_website", "devcast_handle", "devcast_website")]
    blob = json.dumps({"v": VERSION, "scenes": s["scenes"], "format": s["format"], "voice": voice, "fps": FPS,
                       "look": look}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


def _names(sid: str, key: str) -> tuple[str, str]:
    return f"{PREFIX}/{sid}/{key}.mp4", f"{PREFIX}/{sid}/{key}.jpg"


def render(script: dict[str, Any], *, voice: str = "", progress: Any = None) -> dict[str, Any]:
    """Speak, draw and encode one devcast. Returns {url, thumbnail_url, seconds, key}."""
    from ..infra.storage import object_storage
    from ..settings import settings
    from . import whiteboard as wb

    ffmpeg = wb.ffmpeg_binary()
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed on this worker — rebuild the image (it is in the Dockerfile).")
    s = validate(script)
    voice = voice or default_voice()
    key = cache_key(s, voice)
    name, thumb_name = _names(s["id"], key)
    if object_storage.object_exists(name):
        return {"url": wb.public_url(name), "thumbnail_url": wb.public_url(thumb_name), "key": key, "cached": True}
    tick = progress or (lambda *_a, **_k: None)
    with tempfile.TemporaryDirectory(prefix="dc-") as tmp:
        folder = Path(tmp)
        tick("voice", 0, len(s["scenes"]))
        spoken = wb.narrate(s["scenes"], voice, folder)
        durations = [round(d, 3) for _, d in spoken]
        starts = wb._starts(durations)
        doc = page(s, render=True, durations=durations)
        video = folder / "screen.mp4"
        # The first scene, settled: the title card makes the thumbnail.
        seconds, thumb = wb._capture((getattr(settings, "playwright_cdp_url", "") or "").strip(), doc, video, ffmpeg,
                                     wb.FPS, tick, size=SIZES[s["format"]], selector="#dc",
                                     thumb_at=starts[0] + durations[0] * 0.8)
        final = folder / "final.mp4"
        tick("mux", 0, 1)
        wb._mux(ffmpeg, video, spoken, starts, seconds, final)
        tick("save", 0, 1)
        url = object_storage.save_bytes(name, final.read_bytes(), "video/mp4")
        if url.startswith("local://"):
            raise RuntimeError("The video was made but object storage refused it — is MinIO up?")
        out = {"url": url, "seconds": round(seconds, 1), "key": key, "cached": False}
        if thumb:
            out["thumbnail_url"] = object_storage.save_bytes(thumb_name, thumb, "image/jpeg")
    logger.info("Devcast %s: %.1fs, %s", s["id"], seconds, name)
    return out


def status(script: dict[str, Any], voice: str = "") -> dict[str, Any]:
    """Ready (a URL), queued, running, failed (why), or none."""
    from ..infra.db import fetch_one
    from ..infra.storage import object_storage
    from .whiteboard import public_url

    s = validate(script)
    voice = voice or default_voice()
    key = cache_key(s, voice)
    name, thumb_name = _names(s["id"], key)
    out: dict[str, Any] = {"id": s["id"], "key": key, "scenes": len(s["scenes"]), "format": s["format"]}
    if object_storage.object_exists(name):
        thumb = public_url(thumb_name) if object_storage.object_exists(thumb_name) else None
        return {**out, "status": "ready", "url": public_url(name), "thumbnail_url": thumb}
    job = fetch_one("SELECT job_id, status, error FROM jobs WHERE kind = :kind AND payload->>'artifact_id' = :aid "
                    "ORDER BY created_at DESC LIMIT 1", {"kind": JOB_KIND, "aid": f"{s['id']}:{key}"})
    if job and str(job.get("status")) in ("queued", "running"):
        return {**out, "status": str(job["status"]), "job_id": job["job_id"]}
    if job and str(job.get("status")) == "failed":
        return {**out, "status": "failed", "job_id": job["job_id"], "error": str(job.get("error") or "")[:400]}
    return {**out, "status": "none"}


def enqueue(script: dict[str, Any], *, voice: str = "", queued_by: str = "") -> dict[str, Any]:
    """Queue one devcast unless it is already made or being made."""
    from . import job_queue

    s = validate(script)
    voice = voice or default_voice()
    now = status(s, voice)
    if now["status"] in ("ready", "queued", "running"):
        return now
    job = job_queue.enqueue(JOB_KIND, "", "devcast", {"artifact_id": f"{s['id']}:{now['key']}", "script": s,
                                                      "voice": voice},
                            sub_strand=s["id"], queued_by=queued_by or "devcast")
    job_queue.start_worker()
    return {**now, "status": "queued", "job_id": job.job_id}


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    from . import run_log
    from .job_queue import Live

    payload = dict(job.get("payload") or {})
    s = validate(payload.get("script") or {})
    run_log.step("Script", f"{len(s['scenes'])} scenes · {s['format']}")
    live = Live(str(job.get("job_id") or ""))
    made = render(s, voice=str(payload.get("voice") or ""), progress=live)
    live.done()
    run_log.step("Saved", made["url"])
    return {"status": "done", "id": s["id"], **made}


_CONTROLS = """<div class="bar">
 <button onclick="__dc.prev()">⟨</button>
 <button id="dc-play" onclick="__dc.toggle()">▶ Play</button>
 <button onclick="__dc.next()">⟩</button>
 <span id="dc-count"></span>
</div>
<script>(function(){var d=document.getElementById("dc"),s=Math.min(1,(innerWidth-24)/__W__);
d.style.transform="scale("+s+")";d.style.marginBottom=(__H__*(s-1))+"px";})();
window.__ready.then(function(){ if (__AUTOPLAY__) __dc.play(); });</script>"""

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
 :root{--ui:Inter,"Segoe UI",system-ui,sans-serif;--mono:"JetBrains Mono","Cascadia Code","DejaVu Sans Mono",monospace;--accent:#007acc}
 html,body{margin:0;background:#0b0d12;color:#cccccc;font-family:var(--ui)}
 body.live{padding:16px 0}
 #dc{position:relative;width:__W__px;height:__H__px;overflow:hidden;background:#1e1e1e;display:flex;flex-direction:column;margin:0 auto}
 body.live #dc{transform-origin:top center;box-shadow:0 10px 40px rgba(0,0,0,.6);border-radius:10px}
 .titlebar{height:44px;flex:none;background:#1f1f1f;border-bottom:1px solid #2b2b2b;display:flex;align-items:center;padding:0 16px;gap:16px;font-size:16px;color:#9d9d9d}
 .lights{display:flex;gap:8px}.lights i{width:13px;height:13px;border-radius:50%;background:#ff5f57;display:block}
 .lights i:nth-child(2){background:#febc2e}.lights i:nth-child(3){background:#28c840}
 #dc-wt{flex:1;text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .badge{color:#e5e5e5;font-weight:600}
 .main{flex:1;display:flex;min-height:0;position:relative}
 .activity{width:58px;flex:none;background:#181818;border-right:1px solid #2b2b2b;display:flex;flex-direction:column;align-items:center;padding-top:10px;gap:22px}
 .activity i{width:26px;height:26px;border:2.5px solid #858585;border-radius:5px;display:block;opacity:.8}
 .activity i.on{border-color:#e7e7e7}.activity i:nth-child(2){border-radius:50%}
 .side{width:300px;flex:none;background:#181818;border-right:1px solid #2b2b2b;font-size:17px;display:none}
 body.landscape .side{display:block}
 .side h4{margin:0;padding:12px 18px;font-size:13px;letter-spacing:.08em;color:#9d9d9d;font-weight:600}
 .file{padding:5px 18px 5px 28px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#cccccc}
 .file.on{background:#37373d;color:#fff}
 .col{flex:1;display:flex;flex-direction:column;min-width:0;position:relative}
 #dc-tabs{height:46px;flex:none;background:#181818;display:flex;overflow:hidden;border-bottom:1px solid #2b2b2b}
 .tab{padding:0 22px;display:flex;align-items:center;gap:10px;font-size:17px;color:#9d9d9d;background:#181818;border-right:1px solid #2b2b2b;white-space:nowrap}
 .tab.on{background:#1e1e1e;color:#fff;box-shadow:inset 0 2px 0 var(--accent)}
 .dot{width:11px;height:11px;border-radius:3px;display:inline-block;background:#888;flex:none}
 .dot.js{background:#f1e05a}.dot.py{background:#3572a5}.dot.vba{background:#867db1}.dot.bash{background:#89e051}
 .dot.json{background:#cbcb41}.dot.xml{background:#e44b23}.dot.vs{background:#007acc}
 #dc-crumbs{height:30px;flex:none;padding:0 22px;display:flex;align-items:center;gap:8px;font-size:15px;color:#a9a9a9}
 #dc-crumbs b{color:#6b6b6b;font-weight:400}
 #dc-editor{flex:1;min-height:0;display:flex;font-family:var(--mono);font-size:var(--fs,24px);line-height:var(--lh,37px);overflow:hidden;padding-top:6px;font-variant-ligatures:none}
 .gutter{width:78px;flex:none;text-align:right;padding-right:22px;color:#6e7681;box-sizing:border-box}
 .ln.cur{color:#cccccc}
 .code{flex:1;min-width:0;white-space:pre;color:#d4d4d4}
 .line{height:var(--lh,37px);padding-left:6px;border-left:3px solid transparent}
 .line.hl{background:rgba(38,79,120,.55);border-left-color:#3794ff}
 .caret{display:inline-block;width:2px;height:1.1em;background:#aeafad;vertical-align:-0.18em;margin-left:1px}
 .kw{color:#569cd6}.kc{color:#c586c0}.st{color:#ce9178}.nu{color:#b5cea8}.cm{color:#6a9955;font-style:italic}
 .fn{color:#dcdcaa}.ty{color:#4ec9b0}.id{color:#9cdcfe}.pr{color:#9cdcfe}.pu{color:#d4d4d4}.tg{color:#569cd6}
 .welcome{margin:auto;text-align:center;color:#6e7681;font-family:var(--ui);font-size:22px;line-height:2}
 .welcome .logo{font-size:44px;font-weight:800;color:#3c3c3c;margin-bottom:20px}
 kbd{font-family:var(--ui);background:#2b2b2b;border-radius:4px;padding:2px 8px;margin-left:10px;color:#9d9d9d}
 #dc-panel{height:44%;flex:none;border-top:1px solid #2b2b2b;background:#181818;display:none;flex-direction:column}
 #dc-panel.full{position:absolute;inset:0;height:auto;border-top:0;z-index:2}
 .ptabs{height:40px;flex:none;display:flex;gap:26px;padding:0 22px;align-items:center;font-size:14px;letter-spacing:.06em;color:#9d9d9d}
 .ptabs .on{color:#e7e7e7;border-bottom:1px solid #e7e7e7;padding:9px 0}
 #dc-term{flex:1;min-height:0;overflow:hidden;padding:4px 22px;font-family:var(--mono);font-size:22px;line-height:34px;white-space:pre-wrap;overflow-wrap:anywhere;color:#cccccc;font-variant-ligatures:none}
 .pa{color:#23d18b;font-weight:700}.pc{color:#29b8db;font-weight:700}.pb{color:#3b8eea}.pg{color:#f14c4c}
 .ok{color:#23d18b}.bad{color:#f14c4c}
 .status{height:32px;flex:none;background:var(--accent);color:#fff;display:flex;align-items:center;gap:24px;padding:0 16px;font-size:15px}
 .status .r{margin-left:auto;display:flex;gap:24px}
 #dc-cap{height:118px;flex:none;background:#111318;border-top:1px solid #2b2b2b;display:flex;align-items:center;justify-content:center;padding:0 40px;text-align:center}
 #dc-cap span{font-size:34px;line-height:1.3;font-weight:600;color:#fff}
 body.landscape #dc-cap{height:100px}
 #dc-app,#dc-stage{position:absolute;left:0;right:0;top:44px;bottom:150px;z-index:5;display:none}
 body.landscape #dc-app,body.landscape #dc-stage{bottom:132px}
 #dc-app{padding:26px;transform-origin:center;background:rgba(0,0,0,.35)}
 .win{height:100%;display:flex;flex-direction:column;border-radius:10px;overflow:hidden;box-shadow:0 18px 60px rgba(0,0,0,.6);background:#f3f3f3;color:#1f1f1f;font-family:"Segoe UI",var(--ui)}
 .wtb{height:42px;flex:none;display:flex;align-items:center;gap:16px;padding:0 14px;color:#fff;font-size:16px}
 .word .wtb{background:#185abd}.excel .wtb{background:#107c41}
 .ribbon{height:40px;flex:none;display:flex;gap:22px;align-items:center;padding:0 18px;background:#fff;border-bottom:1px solid #d6d6d6;font-size:15px;color:#424242;white-space:nowrap;overflow:hidden}
 .ribbon .on{font-weight:600;border-bottom:3px solid #185abd;padding:8px 0}.excel .ribbon .on{border-color:#107c41}
 .ribbon .addin{margin-left:auto;background:#e8f0fe;color:#185abd;border-radius:6px;padding:5px 12px;font-weight:600}
 .wbody{flex:1;min-height:0;display:flex}
 .pagewrap{flex:1;min-width:0;background:#e6e6e6;padding:22px;overflow:hidden}
 .page{background:#fff;height:100%;box-sizing:border-box;padding:40px 48px;box-shadow:0 1px 4px rgba(0,0,0,.15);font-family:Calibri,Carlito,"Segoe UI",sans-serif;font-size:24px;line-height:1.45;overflow:hidden}
 .page h1{font-size:30px;color:#185abd;margin:0 0 14px;font-weight:600}
 .page p{margin:0 0 12px}.q{margin:0 0 12px}.mk{color:#666;font-size:20px}
 .eq{font-family:"Cambria Math","STIX Two Math","Latin Modern Math",serif;font-size:32px;text-align:center;margin:12px 0 16px;font-style:italic}
 .opts{margin:0 0 12px 8px;padding-left:36px}.opts li{margin:4px 0}
 .cc{border:2px solid #2b7cd3;border-radius:3px;padding:20px 14px 12px;position:relative;min-height:36px;margin:8px 0 14px}
 .cc i{color:#888}.cct{position:absolute;top:-14px;left:8px;background:#2b7cd3;color:#fff;font-size:15px;padding:1px 8px;border-radius:3px}
 .cc.locked{border-color:#888;background:#f4f4f4}.cc.locked .cct{background:#888}
 .page table{border-collapse:collapse;width:100%;font-size:21px;margin:8px 0 14px}
 .page th,.page td{border:1px solid #bfbfbf;padding:6px 10px;text-align:left}.page th{background:#dbe5f1}
 .res{font-size:30px;font-weight:700;color:#107c41;border:2px solid #107c41;border-radius:8px;padding:14px;text-align:center;margin:10px 0}
 .img{border:2px dashed #b0b0b0;border-radius:8px;padding:30px;text-align:center;color:#777;margin:8px 0 14px}
 .pane{width:330px;flex:none;background:#fff;border-left:1px solid #d6d6d6;padding:18px 20px;box-sizing:border-box;font-size:18px;overflow:hidden}
 body.square .pane,body.portrait .pane{width:290px}
 .ph{font-weight:700;font-size:20px;color:#185abd;margin-bottom:14px}
 .pane label{display:block;color:#666;font-size:15px;margin-top:8px}
 .pane .in{border:1px solid #c8c8c8;border-radius:4px;padding:6px 10px;margin-top:4px}
 .timer{font-size:46px;font-weight:800;text-align:center;margin:20px 0 10px;color:#1f1f1f;font-variant-numeric:tabular-nums}
 .timer.low{color:#c50f1f}
 .prog{height:10px;background:#e5e5e5;border-radius:5px;overflow:hidden}.prog i{display:block;height:100%;background:#185abd}
 .pl{font-size:15px;color:#666;margin-top:6px}
 .pane p{margin:12px 0 0;font-size:17px}
 .btn{margin-top:18px;background:#185abd;color:#fff;text-align:center;border-radius:6px;padding:10px;font-weight:600}
 .fbar{height:38px;flex:none;display:flex;align-items:center;gap:12px;background:#fff;border-bottom:1px solid #d6d6d6;padding:0 10px;font-size:17px}
 .fbar .nm{width:80px;border-right:1px solid #d6d6d6;color:#424242}.fbar .fx{color:#888;font-style:italic}
 .fbar .fv{font-family:var(--mono);font-size:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .grid{flex:1;min-height:0;overflow:hidden;background:#fff}
 .grid table{border-collapse:collapse;width:100%;table-layout:fixed;font-size:19px}
 .grid th{background:#f3f3f3;color:#555;font-weight:400;border:1px solid #d9d9d9;height:30px;font-size:15px}
 .grid th.corner{width:44px}.grid tr th:first-child{width:44px}
 .grid td{border:1px solid #e1e1e1;height:42px;padding:0 8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .grid td.hd{font-weight:700;background:#e8f3ec}.grid td.ok{background:#c6efce;color:#006100;font-weight:700}
 .grid td.bad{background:#ffc7ce;color:#9c0006;font-weight:700}.grid td.sel{outline:3px solid #107c41;outline-offset:-2px}
 .sheets{height:34px;flex:none;display:flex;gap:2px;background:#f3f3f3;border-top:1px solid #d6d6d6;font-size:15px}
 .sheets span{padding:7px 18px;color:#555}.sheets .on{background:#fff;color:#107c41;font-weight:600;border-bottom:3px solid #107c41}
 #dc-stage{align-items:center;justify-content:center;background:radial-gradient(1200px 600px at 30% 20%,#0e3a5c 0%,#1e1e1e 60%);padding:60px;box-sizing:border-box}
 .st{max-width:100%;text-align:left}
 .kick{font-family:var(--mono);color:#4fc1ff;font-size:26px;margin-bottom:20px}
 .st h1{font-size:66px;line-height:1.12;margin:0;color:#fff;font-weight:800}
 body.landscape .st h1{font-size:78px}
 .st h1 .caret{width:6px;background:#4fc1ff}
 .sub{margin-top:24px;font-size:30px;color:#c5c5c5;line-height:1.35}
 .md{width:100%}.mdh{font-family:var(--mono);color:#569cd6;font-size:40px;font-weight:700;margin-bottom:26px}
 .md ul{list-style:none;margin:0;padding:0}
 .md li{font-size:32px;line-height:1.35;margin:0 0 20px;color:#fff;opacity:.12;display:flex;gap:18px}
 .md li.on{opacity:1}.bul{font-family:var(--mono);color:#4ec9b0;flex:none}
 .out{text-align:center;width:100%}.out h1{font-size:58px}
 .cta{display:inline-block;margin-top:30px;background:#007acc;color:#fff;font-size:30px;font-weight:700;border-radius:10px;padding:14px 30px}
 .who{margin-top:34px;font-family:var(--mono);font-size:32px;color:#4fc1ff}.web{margin-top:10px;font-size:24px;color:#9d9d9d}
 .bar{width:__W__px;max-width:100%;margin:12px auto;display:flex;gap:8px;align-items:center;font-family:var(--ui)}
 .bar button{font:inherit;padding:6px 14px;border-radius:6px;border:1px solid #3c3c3c;background:#252526;color:#ddd;cursor:pointer}
 .bar span{color:#9d9d9d;font-size:14px}
</style></head><body class="__BODY_CLASS__">
<div id="dc">
 <div class="titlebar"><span class="lights"><i></i><i></i><i></i></span><span id="dc-wt"></span><span class="badge" id="dc-badge"></span></div>
 <div class="main">
  <div class="activity"><i class="on"></i><i></i><i></i><i></i></div>
  <div class="side"><h4>EXPLORER</h4><div id="dc-files"></div></div>
  <div class="col">
   <div id="dc-tabs"></div><div id="dc-crumbs"></div><div id="dc-editor"></div>
   <div id="dc-panel"><div class="ptabs"><span>PROBLEMS</span><span>OUTPUT</span><span class="on">TERMINAL</span><span>PORTS</span></div><div id="dc-term"></div></div>
  </div>
 </div>
 <div id="dc-cap"></div>
 <div class="status"><span>⎇ main</span><span>⊗ 0 ⚠ 0</span><span class="r"><span id="dc-pos"></span><span>UTF-8</span><span id="dc-lang"></span></span></div>
 <div id="dc-app"></div><div id="dc-stage"></div>
</div>
<script>window.DC_DATA = __DATA__;</script>
<script>(function(){var b=(window.DC_DATA.brand||{}).handle;var e=document.getElementById("dc-badge");if(e)e.textContent=b||"";})();</script>
<script>__ENGINE__</script>
__CONTROLS__
</body></html>"""
