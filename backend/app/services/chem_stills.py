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


def status(question_id: str, q: dict[str, Any]) -> dict[str, Any]:
    """The stills, made or not: {status, stills: [{url, caption, role, scene}]}."""
    if not isinstance(q.get("chemistry"), dict):
        return {"status": "none", "stills": [], "reason": "not a chemistry item"}
    from ..infra.storage import object_storage, public_object_url

    try:
        _, _, ms, key = _plan(q)
    except Exception as exc:  # noqa: BLE001
        return {"status": "none", "stills": [], "reason": str(exc)}
    stills, made = [], 0
    for k, m in enumerate(ms):
        name = object_name(question_id, key, k)
        ok = object_storage.object_exists(name)
        made += ok
        stills.append({**m, "object_name": name, **({"url": public_object_url(name)} if ok else {})})
    return {"status": "ready" if ms and made == len(ms) else "partial" if made else "none", "stills": stills}


def render(question_id: str, q: dict[str, Any]) -> dict[str, Any]:
    """Photograph every still the walkthrough has (those not made yet)."""
    st = status(question_id, q)
    if st["status"] == "ready" or not st["stills"]:
        return st
    import base64

    from playwright.sync_api import sync_playwright

    from ..infra.storage import object_storage
    from .browser import LAUNCH_ARGS
    from .whiteboard import WEBGL_ARGS, page

    data, durations, ms, _ = _plan(q)
    doc = page(data, title="still", voice="en-GB", durations=durations, render=True)
    todo = [s for s in st["stills"] if "url" not in s]
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
            clip = {"x": box["x"], "y": box["y"], "width": box["width"], "height": box["height"], "scale": 1}
            cdp = pg.context.new_cdp_session(pg)
            # Each picture at its moment of its scene, on the page's own clock (it times the scenes itself).
            starts = pg.evaluate("() => [window.__starts || [], window.__total || 0]")
            for s in todo:
                st_, total = starts
                i = s["index"]
                a = st_[i] if i < len(st_) else 0
                b = st_[i + 1] if i + 1 < len(st_) else total
                pg.evaluate("t => window.__seek(t)", a + (b - a) * s["f"])
                pg.wait_for_timeout(120)
                jpeg = base64.b64decode(cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 88, "clip": clip})["data"])
                object_storage.save_bytes(s["object_name"], jpeg, "image/jpeg")
        finally:
            browser.close()
    logger.info("Chemistry stills for %s: %d made", question_id, len(todo))
    return status(question_id, q)


def comments(question_id: str, q: dict[str, Any]) -> list[dict[str, str]]:
    """The thread of pictures: one comment per step, in order."""
    st = status(question_id, q)
    return [{"text": s["caption"], "image_url": s["url"]} for s in st["stills"] if s.get("url") and s["role"] != "setup"]


def card_image(question_id: str, q: dict[str, Any], role: str) -> str:
    """The still a photo card shows: the set-up on the question card, the result on the answer card ("" if none)."""
    try:
        st = status(question_id, q)
    except Exception:  # noqa: BLE001
        return ""
    pick = [s for s in st["stills"] if s.get("url") and s["role"] == role]
    return pick[0]["url"] if pick else ""
