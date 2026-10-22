"""Pictures of every step of a chemistry walkthrough — the lab bench
mid-reaction, the balanced equation with its level scale, the atoms
breaking apart and finding new partners, the electron mid-flight, the ions,
the lattice, the shared pairs and the real shape, each separation step
working — each with a line saying what it shows.

They go up as comments under the question's post (a thread that walks
through the whole reaction, picture by picture) and onto its photo cards (the
question card shows the set-up, the answer card the result). Photographed
once per question by the worker's Chromium (WebGL on, as for its video), at
the moment of each scene that tells most, and kept in object storage.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger("cbc-chem-stills")

PREFIX = "chem_stills"
VERSION = "s1"
MAX_STILLS = 14
LEAD = 0.3                                   # the board's first scene starts here (whiteboard.js build())


def _cap(x: str) -> str:
    return x[:1].upper() + x[1:] if x else x


def moments(scenes: list[dict[str, Any]], durations: list[float]) -> list[dict[str, Any]]:
    """Where in the walkthrough each picture is taken, and what it says.
    `role` is "step" (a comment), "setup" (the question card) or "result" (the answer card)."""
    out: list[dict[str, Any]] = []

    def add(i: int, f: float, caption: str, role: str = "step") -> None:
        out.append({"scene": scenes[i]["scene"], "index": i, "f": f, "caption": caption, "role": role})

    for i, s in enumerate(scenes):
        kind = s.get("scene")
        if kind == "chem_lab":
            obs = [o for o in (s.get("observations") or []) if o][:2]
            add(i, 0.3, "🔬 The set-up: " + " + ".join(r.get("name", "") for r in (s.get("reactants") or [])), "setup")
            add(i, 0.85, ("🔬 At the bench: " + "; ".join(obs) + ".") if obs and s.get("reacts", True)
                else "🔬 At the bench: no change — no reaction.")
        elif kind == "chem_series":
            add(i, 0.95, "📶 The reactivity series decides it: " + str(s.get("say") or "").replace("Look at the reactivity series. ", ""))
        elif kind == "chem_equation":
            add(i, 0.99, f"⚖️ Balanced: {s.get('equation')} — the same atoms on both sides, so the scale is level.", "result")
        elif kind == "chem_atoms":
            add(i, 0.36, "💥 Inside the reaction, atom by atom: the bonds break…")
            add(i, 0.6, "⚛️ …and every atom flies to new partners — each keeps its colour, so you can follow it.")
            tally = " · ".join(f"{n} {e}" for e, n in sorted((s.get("tally") or {}).items(), key=lambda x: -x[1]))
            add(i, 0.97, f"✅ {s.get('equation')}: atoms in = atoms out ({tally}). Atoms are only rearranged.", "result")
        elif kind == "chem_atom" and not s.get("short"):
            add(i, 0.95, f"⚛️ {_cap(str(s.get('name')))}: {s.get('protons')} protons, {s.get('neutrons')} neutrons and "
                         f"{s.get('electrons')} electrons, arranged {s.get('arrangement')}.", "result")
        elif kind == "chem_atom" and s.get("short") and s.get("slot") == 1:
            prev = scenes[i - 1] if i else {}
            add(i, 0.95, f"⚛️ Before they bond: {prev.get('name', '')} {prev.get('arrangement', '')} and "
                         f"{s.get('name')} {s.get('arrangement')}.", "setup")
        elif kind == "chem_ionic":
            m, n = s.get("metal") or {}, s.get("nonmetal") or {}
            moves = len(s.get("moves") or [])
            outer = (m.get("shells") or [1])[-1]
            add(i, 0.2, f"🔎 {_cap(str(m.get('name')))}'s outer electron{'s are' if outer > 1 else ' is'} far from the nucleus and "
                        f"shielded by the inner shells — held weakly. {_cap(str(n.get('name')))} pulls strongly.")
            add(i, 0.45, f"⚡ Electron transfer: {moves} electron{'s' if moves != 1 else ''} move from {m.get('name')} to "
                         f"{n.get('name')} (the gold electron keeps its colour).")
            add(i, 0.75, "➕➖ Now ions: opposite charges attract — the ionic bond.")
            add(i, 0.97, f"🧱 The ions build a giant lattice: {s.get('formula')}.", "result")
        elif kind == "chem_covalent":
            add(i, 0.55, f"🤝 Shared pairs: {s.get('shared_pairs')} covalent bond{'s' if s.get('shared_pairs') != 1 else ''} — "
                         "every atom now has a full outer shell.")
            add(i, 0.97, f"🧬 {s.get('formula')} in its real shape.", "result")
        elif kind == "chem_separation":
            steps = s.get("steps") or []
            add(i, 0.88, f"🧪 {s.get('name')}: {steps[0] if steps else ''}")
            out[-1]["method"] = s.get("method")
    steps = [m for m in out if m["role"] != "setup"]
    if len(steps) > MAX_STILLS:                         # keep the first, the last and an even spread between
        keep = {round(k * (len(steps) - 1) / (MAX_STILLS - 1)) for k in range(MAX_STILLS)}
        drop = {id(m) for k, m in enumerate(steps) if k not in keep}
        out = [m for m in out if id(m) not in drop]
    if not any(m["role"] == "result" for m in out) and steps:
        steps[-1]["role"] = "result"
    return out


def _plan(q: dict[str, Any]) -> tuple[dict[str, Any], list[float], list[dict[str, Any]], str]:
    from . import play_engine

    data = play_engine.walkthrough(q, grade=str((q.get("curriculum") or {}).get("grade") or ""))
    durations = [max(3.5, len(str(s.get("say") or "").split()) / 2.6) for s in data["scenes"]]
    ms = moments(data["scenes"], durations)
    key = hashlib.sha256((VERSION + json.dumps(data["scenes"], sort_keys=True, default=str)).encode()).hexdigest()[:14]
    return data, durations, ms, key


def object_name(question_id: str, key: str, k: int) -> str:
    return f"{PREFIX}/{question_id}/{key}-{k:02d}.jpg"


GRID = 4                                     # steps on one picture (and one animated picture)
FRAMES = 14                                  # frames of each step's animation in an animated picture


def _groups(ms: list[dict[str, Any]]) -> list[list[int]]:
    """The steps, in pictures of up to four (indices into the moments)."""
    steps = [k for k, m in enumerate(ms) if m["role"] != "setup"]
    if len(steps) < 2:
        return []
    n = -(-len(steps) // GRID)
    size = -(-len(steps) // n)                    # even pictures: 5 steps → 3 + 2, not 4 + 1
    return [steps[j:j + size] for j in range(0, len(steps), size)]


def grid_name(question_id: str, key: str, g: int, ext: str) -> str:
    return f"{PREFIX}/{question_id}/{key}-grid{g}.{ext}"


def status(question_id: str, q: dict[str, Any]) -> dict[str, Any]:
    """The stills, made or not: {status, stills: [{url, caption, role, scene}], grids: [{jpg, mp4, gif}]}."""
    if not isinstance(q.get("chemistry"), dict):
        return {"status": "none", "stills": [], "grids": [], "reason": "not a chemistry item"}
    from ..infra.storage import object_storage, public_object_url

    try:
        _, _, ms, key = _plan(q)
    except Exception as exc:  # noqa: BLE001
        return {"status": "none", "stills": [], "grids": [], "reason": str(exc)}
    stills, made, want = [], 0, 0
    for k, m in enumerate(ms):
        name = object_name(question_id, key, k)
        clip = name[:-4] + ".mp4"                       # the moment's run-up, moving (for an animated card)
        ok, has_clip = object_storage.object_exists(name), object_storage.object_exists(clip)
        made += ok + has_clip
        want += 2
        stills.append({**m, "object_name": name, "clip_name": clip, **({"url": public_object_url(name)} if ok else {}),
                       **({"clip": public_object_url(clip)} if has_clip else {})})
    grids = []
    for g, idx in enumerate(_groups(ms)):
        entry: dict[str, Any] = {"steps": idx}
        for ext in ("jpg", "mp4", "gif"):
            name = grid_name(question_id, key, g, ext)
            want += 1
            if object_storage.object_exists(name):
                made += 1
                entry[ext] = public_object_url(name)
            entry[f"{ext}_name"] = name
        grids.append(entry)
    return {"status": "ready" if want and made == want else "partial" if made else "none", "stills": stills, "grids": grids}


def _short(caption: str, limit: int = 150) -> str:
    """A step's words for a panel: whole sentences, not cut mid-word."""
    text = caption.split(": ", 1)[1] if caption.startswith("🧪") and ": " in caption else caption
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(". ", 1)[0]
    return (cut if len(cut) > 40 else text[:limit].rsplit(" ", 1)[0]) + ("." if not cut.endswith(".") else "")


def _grid_page(title: str, panels: list[dict[str, Any]], foot: str) -> str:
    """Up to four steps on one portrait picture: three or fewer as rows (the
    picture beside its words), four as a 2 × 2 grid. A bench or separation
    picture is cropped to its apparatus (its words are in the panel)."""
    import html as _h

    rows = len(panels) <= 3
    cells = "".join(
        f"<div class='cell'><div class='img {'crop' if p.get('crop') else ''}'><img id='p{k}' src='{p['src']}'>"
        f"<b class='n'>{p['n']}</b></div>"
        f"<div class='words'><div class='h'>{_h.escape(p['head'])}</div><div class='t'>{_h.escape(p['text'])}</div></div></div>"
        for k, p in enumerate(panels))
    text_px = 30 if len(panels) <= 2 else 27 if rows else 25
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
 *{{box-sizing:border-box}} html,body{{margin:0;width:1080px;height:1350px}}
 body{{background:linear-gradient(160deg,#1e3a8a,#0b1530);color:#fff;font-family:'Inter','Segoe UI',Arial,sans-serif;
      display:flex;flex-direction:column;padding:44px 40px 30px}}
 h1{{font-size:44px;line-height:1.15;margin:0 0 24px;font-weight:800}}
 .grid{{flex:1;display:grid;gap:22px;min-height:0;
        {'grid-template-rows:repeat(' + str(len(panels)) + ',1fr)' if rows else 'grid-template-columns:1fr 1fr;grid-template-rows:1fr 1fr'}}}
 .cell{{background:rgba(255,255,255,.08);border-radius:22px;padding:16px;display:flex;gap:18px;min-height:0;
        {'flex-direction:row;align-items:center' if rows else 'flex-direction:column'}}}
 .img{{position:relative;border-radius:14px;overflow:hidden;background:#fff;flex:none;
       {'width:52%;align-self:stretch' if rows else 'width:100%;aspect-ratio:4/3'}}}
 .img img{{width:100%;height:100%;object-fit:cover;display:block}} .img.crop img{{object-position:12% 60%}}
 .n{{position:absolute;left:10px;top:10px;background:#facc15;color:#111;border-radius:50%;width:50px;height:50px;
     display:grid;place-items:center;font-size:30px}}
 .words{{display:flex;flex-direction:column;gap:8px;min-width:0}}
 .h{{font-size:{text_px + 4}px;font-weight:800;color:#facc15}} .t{{font-size:{text_px}px;line-height:1.3}}
 .foot{{text-align:center;font-size:24px;opacity:.75;margin-top:16px}}
</style></head><body><h1>{_h.escape(title)}</h1><div class="grid">{cells}</div><div class="foot">{_h.escape(foot)}</div></body></html>"""


def render(question_id: str, q: dict[str, Any]) -> dict[str, Any]:
    """Photograph every still the walkthrough has, and its step pictures — up to
    four steps on one picture with their words, and the same picture animated
    (each panel playing its step; the words stay), as MP4 and GIF."""
    st = status(question_id, q)
    if st["status"] == "ready" or not st["stills"]:
        return st
    import base64
    import subprocess
    import tempfile
    from pathlib import Path

    from playwright.sync_api import sync_playwright

    from ..infra.storage import object_storage
    from .browser import LAUNCH_ARGS
    from .social import brand, brand_name
    from .whiteboard import WEBGL_ARGS, ffmpeg_binary, page

    data, durations, ms, _ = _plan(q)
    doc = page(data, title="still", voice="en-GB", durations=durations, render=True)
    todo = [s for s in st["stills"] if "url" not in s]
    clips_todo = [k for k, s in enumerate(st["stills"]) if "clip" not in s]
    grids_todo = [g for g in st["grids"] if not all(g.get(e) for e in ("jpg", "mp4", "gif"))]
    ffmpeg = ffmpeg_binary()
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, args=LAUNCH_ARGS + WEBGL_ARGS)
        except Exception:  # noqa: BLE001 — no bundled Chromium here (a Mac): the installed Chrome
            browser = p.chromium.launch(headless=True, channel="chrome", args=LAUNCH_ARGS + WEBGL_ARGS)
        try:
            pg = browser.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1).new_page()
            pg.set_content(doc, wait_until="domcontentloaded", timeout=60000)
            pg.evaluate("() => window.__ready")
            pg.evaluate("() => window.__hideHand && window.__hideHand()")
            box = pg.locator("#wb").bounding_box() or {"x": 0, "y": 0, "width": 1280, "height": 720}
            cdp = pg.context.new_cdp_session(pg)
            starts = pg.evaluate("() => [window.__starts || [], window.__total || 0]")

            def shot(m: dict[str, Any], f: float, scale: float = 1.0) -> bytes:
                # A moment of its scene, on the page's own clock (it times the scenes itself).
                st_, total = starts
                i = m["index"]
                a = st_[i] if i < len(st_) else 0
                b = st_[i + 1] if i + 1 < len(st_) else total
                pg.evaluate("t => window.__seek(t)", a + (b - a) * f)
                pg.wait_for_timeout(60)
                clip = {"x": box["x"], "y": box["y"], "width": box["width"], "height": box["height"], "scale": scale}
                return base64.b64decode(cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 84, "clip": clip})["data"])

            for s in todo:
                object_storage.save_bytes(s["object_name"], shot(s, s["f"]), "image/jpeg")
            # Each step's animation: frames across the run-up to its moment.
            needed = sorted({k for g in grids_todo for k in g["steps"]} | set(clips_todo))
            frames = {k: [shot(ms[k], max(0.04, ms[k]["f"] - 0.5) + (ms[k]["f"] - max(0.04, ms[k]["f"] - 0.5)) * j / (FRAMES - 1), 0.5)
                          for j in range(FRAMES)] for k in needed}
            for k in clips_todo if ffmpeg else []:
                with tempfile.TemporaryDirectory() as tmp:
                    out = Path(tmp) / "c.mp4"
                    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", "7", "-c:v", "mjpeg",
                                    "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                                    "-r", "14", str(out)], input=b"".join(frames[k]), capture_output=True, timeout=120, check=False)
                    if out.exists():
                        object_storage.save_bytes(st["stills"][k]["clip_name"], out.read_bytes(), "video/mp4")
            if grids_todo:
                b = brand()
                foot = " · ".join(x for x in (brand_name(b, q), b.get("website")) if x)
                title = str(q.get("question_text") or "")
                title = title if len(title) <= 90 else title[:88].rsplit(" ", 1)[0] + "…"
                sheet = browser.new_context(viewport={"width": 1080, "height": 1350}, device_scale_factor=1).new_page()
                uri = lambda jpeg: "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()  # noqa: E731
                for g in grids_todo:
                    total = len(_groups(ms))
                    head = lambda k: ms[k]["caption"].split(": ", 1)[0].lstrip("🧪⚖️💥⚛️✅🔎⚡➕➖🧱🤝🧬🔬📶 ").strip() or "Step"  # noqa: E731
                    order = [k for k, m in enumerate(ms) if m["role"] != "setup"]       # numbered across the pictures
                    panels = [{"src": uri(frames[k][-1]), "head": head(k), "text": _short(ms[k]["caption"]), "n": order.index(k) + 1,
                               "crop": ms[k]["scene"] in ("chem_separation", "chem_lab")} for k in g["steps"]]
                    label = f"{title}" + (f"  ({st['grids'].index(g) + 1} of {total})" if total > 1 else "")
                    sheet.set_content(_grid_page(label, panels, foot), wait_until="load")
                    object_storage.save_bytes(g["jpg_name"], sheet.screenshot(type="jpeg", quality=88), "image/jpeg")
                    if not ffmpeg:
                        continue
                    with tempfile.TemporaryDirectory() as tmp:
                        mp4, gif = Path(tmp) / "a.mp4", Path(tmp) / "a.gif"
                        enc = subprocess.Popen([ffmpeg, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", "7",
                                                "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                                                "-vf", "scale=1080:1350", "-r", "14", str(mp4)], stdin=subprocess.PIPE)
                        for _loop in range(2):                  # two loops, then it holds on the finished steps
                            for j in range(FRAMES):
                                for n, k in enumerate(g["steps"]):
                                    sheet.evaluate("([id, s]) => { document.getElementById(id).src = s; }", [f"p{n}", uri(frames[k][j])])
                                enc.stdin.write(sheet.screenshot(type="jpeg", quality=82))  # type: ignore[union-attr]
                        for _hold in range(10):
                            enc.stdin.write(sheet.screenshot(type="jpeg", quality=82))  # type: ignore[union-attr]
                        enc.stdin.close()  # type: ignore[union-attr]
                        enc.wait(timeout=300)
                        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(mp4), "-vf",
                                        "fps=7,scale=540:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse",
                                        "-loop", "0", str(gif)], capture_output=True, timeout=300, check=False)
                        if mp4.exists():
                            object_storage.save_bytes(g["mp4_name"], mp4.read_bytes(), "video/mp4")
                        if gif.exists():
                            object_storage.save_bytes(g["gif_name"], gif.read_bytes(), "image/gif")
        finally:
            browser.close()
    logger.info("Chemistry stills for %s: %d stills, %d step pictures made", question_id, len(todo), len(grids_todo))
    return status(question_id, q)


def comments(question_id: str, q: dict[str, Any]) -> list[dict[str, str]]:
    """The thread of pictures: the steps on one picture (and animated), then one comment per step."""
    st = status(question_id, q)
    out: list[dict[str, str]] = []
    grids = st.get("grids") or []
    n = len(grids)
    for g, grid in enumerate(grids):
        part = f" ({g + 1} of {n})" if n > 1 else ""
        if grid.get("jpg"):
            out.append({"text": f"🧩 Every step on one picture{part} — save it for revision.", "image_url": grid["jpg"]})
        if grid.get("gif"):
            out.append({"text": f"🎞️ The steps, animated{part}.", "image_url": grid["gif"]})
    out += [{"text": s["caption"], "image_url": s["url"]} for s in st["stills"] if s.get("url") and s["role"] != "setup"]
    return out


# What a question asks, and the step whose picture answers it.
_FOCUS_METHOD = {"layer": "separating_funnel", "first": "fractional_distillation", "residue": "filtration"}
_WHY_WORDS = (("magnet", "magnet"), ("heating", "sublimation"), ("crystallised", "crystallisation"),
              ("colours", "chromatography"), ("chromatograph", "chromatography"))


def pick_for(q: dict[str, Any], stills: list[dict[str, Any]], step: str,
             grids: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """The still a photo card shows: the set-up on the question card; on the
    answer card the step the question is about — the separating funnel for
    'which layer', the filtration for 'the residue', the reaction's equation
    for a balancing question — not simply the last step."""
    made = [s for s in stills if s.get("url")]
    if not made:
        return None
    if step == "question":
        return next((s for s in made if s["role"] == "setup"), None)
    chem = q.get("chemistry") if isinstance(q.get("chemistry"), dict) else {}
    focus = str(chem.get("focus") or (q.get("pedagogy") or {}).get("focus") or "")
    text = str(q.get("question_text") or "").lower()
    want = _FOCUS_METHOD.get(focus)
    if focus == "why":
        want = next((m for w, m in _WHY_WORDS if w in text), None)
    if focus == "order" and grids and grids[0].get("jpg"):
        return {"url": grids[0]["jpg"], "caption": "Every step", "role": "result", "scene": "grid"}
    if focus in ("method", "apparatus"):
        want = next((s.get("method") for s in made if s.get("method") and s.get("method") != "dissolve"), None)
    if want:
        hit = next((s for s in made if s.get("method") == want), None)
        if hit:
            return hit
    if chem.get("reactants") or chem.get("equation"):
        scene = "chem_lab" if focus == "observations" else "chem_equation" if focus in ("balancing", "equation") else ""
        hit = next((s for s in made if scene and s["scene"] == scene and s["role"] != "setup"), None)
        if hit:
            return hit
    if chem.get("bond") and focus == "bond_type":
        hit = next((s for s in made if "transfer" in s["caption"].lower() or "shared pairs" in s["caption"].lower()), None)
        if hit:
            return hit
    return next((s for s in made if s["role"] == "result"), made[-1])


def card_image(question_id: str, q: dict[str, Any], step: str, *, moving: bool = False) -> str:
    """The picture on a photo card ("" if none made yet); `moving`: its clip instead
    (the step playing, for an animated card) — "" when it has none."""
    try:
        st = status(question_id, q)
    except Exception:  # noqa: BLE001
        return ""
    s = pick_for(q, st["stills"], step, st.get("grids"))
    if moving:
        return str((s or {}).get("clip") or "")
    return s["url"] if s else ""
