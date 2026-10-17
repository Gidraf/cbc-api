"""The working of a walkthrough as Manim animation, laid on the board.

The maths engine already decides every step — the part done next, its
result, the line after it, a number line's jumps, a balance's moves, the
bars of two fractions. app/manim_board.py animates those steps with Manim,
from the engine's data alone: no model writes code, so a clip costs nothing
but the render.

A render with Manim available (and Settings → Animate the working with
Manim on):

  1. finds the runs of scenes Manim draws (a calculation, a number line, a
     balance, fraction bars — and the answer that follows them);
  2. renders each run as one clip, every beat exactly as long as its
     narration (and the 0.4 s after it), so the clip keeps time with the
     voice;
  3. the board draws nothing in those scenes, and the clip is laid over the
     board's own box — the whole frame, or the board inside the vertical
     social frame, its rounded corners kept.

The question, the figure, the countdown and the teacher stay the
whiteboard's: Manim takes only the working. Without Manim (or LaTeX) the
board draws everything as before.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("cbc-manim")

GAP = 0.4                 # the board's pause after each scene (whiteboard._starts)
KINDS = {"setup", "rewrite", "number_line_start", "number_line_jump", "balance_start", "balance_move",
         "balance_done", "fraction_bars"}
BOARD = Path(__file__).resolve().parent.parent / "manim_board.py"
# Where the board sits in each frame: (x, y, width, height, corner radius).
BOX_PLAIN = (0, 0, 1280, 720, 0)
BOX_SOCIAL = (40, 470, 960, 540, 22)


def enabled() -> bool:
    from . import platform_settings

    try:
        on = bool(platform_settings.get("whiteboard_manim", True))
    except Exception:  # noqa: BLE001
        on = True
    return on and available()


def available() -> bool:
    """Manim importable here, and LaTeX to set its maths."""
    try:
        import manim  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return bool(shutil.which("latex") and shutil.which("dvisvgm"))


def runs(scenes: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """[start, end) of each run of scenes Manim animates; an answer straight
    after a run closes it on the same board."""
    out: list[tuple[int, int]] = []
    k = 0
    while k < len(scenes):
        if scenes[k].get("scene") in KINDS and _usable(scenes[k]):
            a = k
            while k < len(scenes) and scenes[k].get("scene") in KINDS and _usable(scenes[k]):
                k += 1
            if k < len(scenes) and scenes[k].get("scene") == "answer":
                k += 1
            if any(scenes[i].get("scene") not in ("setup", "answer") for i in range(a, k)):   # no working: the board's
                out.append((a, k))
        else:
            k += 1
    return out


def _usable(sc: dict[str, Any]) -> bool:
    kind = sc.get("scene")
    if kind == "rewrite":
        step = sc.get("step") or {}
        return all(k in step for k in ("before", "after", "left", "op", "right", "result"))
    if kind.startswith("number_line"):
        return isinstance(sc.get("spec"), dict) and "min" in sc["spec"]
    if kind.startswith("balance"):
        return isinstance(sc.get("spec"), dict) and "states" in sc["spec"]
    if kind == "fraction_bars":
        return isinstance(sc.get("spec"), dict) and "common" in sc["spec"]
    return kind == "setup" and bool(sc.get("expression"))


def render_run(scenes: list[dict[str, Any]], seconds: list[float], folder: Path, fps: int) -> Path | None:
    """One run as an MP4 (1280×720), each beat `seconds[i]` long. None if it fails."""
    beats = [{**{k: v for k, v in sc.items() if k not in ("say", "caption")}, "seconds": round(s, 3)}
             for sc, s in zip(scenes, seconds)]
    spec = {"beats": beats}
    tag = hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()[:12]
    work = folder / f"manim-{tag}"
    work.mkdir(parents=True, exist_ok=True)
    (work / "spec.json").write_text(json.dumps(spec, default=str))
    cmd = [sys.executable, "-m", "manim", "-r", "1280,720", "--fps", str(fps), "--disable_caching",
           "--media_dir", str(work), "-o", "clip.mp4", "-v", "WARNING", str(BOARD), "Board"]
    try:
        done = subprocess.run(cmd, cwd=work, env={**os.environ, "MANIM_SPEC": str(work / "spec.json")},
                              capture_output=True, timeout=900)
    except subprocess.TimeoutExpired:
        logger.warning("Manim took too long; the board draws this run.")
        return None
    clips = list(work.rglob("clip.mp4"))
    if done.returncode or not clips:
        logger.warning("Manim could not draw this run: %s", done.stderr.decode(errors="ignore")[-600:])
        return None
    return clips[0]


def plan(scenes: list[dict[str, Any]], durations: list[float], starts: list[float],
         folder: Path, fps: int) -> tuple[list[dict[str, Any]], list[tuple[Path, float, float]]]:
    """The scenes with the Manim ones marked (the board skips them), and each
    clip with when it starts and ends."""
    marked = [dict(sc) for sc in scenes]
    clips: list[tuple[Path, float, float]] = []
    for a, b in runs(scenes):
        seconds = [durations[i] + GAP for i in range(a, b)]
        clip = render_run(scenes[a:b], seconds, folder, fps)
        if not clip:
            continue
        for i in range(a, b):
            marked[i]["manim"] = True
        clips.append((clip, starts[a], starts[a] + sum(seconds)))
    return marked, clips


def overlay(ffmpeg: str, video: Path, clips: list[tuple[Path, float, float]], box: tuple[int, int, int, int, int],
            out: Path) -> bool:
    """Lay each clip on the board's box of `video`, at its time. False if ffmpeg fails."""
    if not clips:
        return False
    x, y, w, h, r = box
    args = [ffmpeg, "-y", "-loglevel", "error", "-i", str(video)]
    for clip, _, _ in clips:
        args += ["-i", str(clip)]
    mask_at = None
    if r:
        # Rounded corners, as the board has: an alpha mask, cut once.
        mask = out.parent / f"mask-{w}x{h}-{r}.png"
        if not mask.exists():
            inside = (f"if(lt(X,{r})*lt(Y,{r}),lte(hypot({r}-X,{r}-Y),{r}),"
                      f"if(gt(X,W-{r})*lt(Y,{r}),lte(hypot(X-(W-{r}),{r}-Y),{r}),"
                      f"if(lt(X,{r})*gt(Y,H-{r}),lte(hypot({r}-X,Y-(H-{r})),{r}),"
                      f"if(gt(X,W-{r})*gt(Y,H-{r}),lte(hypot(X-(W-{r}),Y-(H-{r})),{r}),1))))")
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=black:s={w}x{h}",
                            "-frames:v", "1", "-vf", f"format=gray,geq=lum='255*{inside}'", str(mask)],
                           capture_output=True, timeout=60)
        if mask.exists():
            args += ["-loop", "1", "-i", str(mask)]
            mask_at = len(clips) + 1
    chains, last = [], "0:v"
    if mask_at:
        chains.append(f"[{mask_at}:v]format=gray,split={len(clips)}" + "".join(f"[m{n}]" for n in range(1, len(clips) + 1)))
    for n, (_, start, end) in enumerate(clips, start=1):
        shaped = f"[{n}:v]scale={w}:{h},format=rgba,setpts=PTS-STARTPTS+{start:.3f}/TB"
        if mask_at:
            chains.append(f"{shaped}[s{n}]")
            chains.append(f"[s{n}][m{n}]alphamerge[c{n}]")
        else:
            chains.append(f"{shaped}[c{n}]")
        chains.append(f"[{last}][c{n}]overlay={x}:{y}:eof_action=pass:shortest=0:"
                      f"enable='between(t,{start:.3f},{end:.3f})'[v{n}]")
        last = f"v{n}"
    args += ["-filter_complex", ";".join(chains), "-map", f"[{last}]", "-t", f"{_duration(ffmpeg, video):.3f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(out)]
    done = subprocess.run(args, capture_output=True, timeout=900)
    if done.returncode:
        logger.warning("Could not lay the Manim clips on the board: %s", done.stderr.decode(errors="ignore")[-400:])
        return False
    return True


def _duration(ffmpeg: str, video: Path) -> float:
    probe = shutil.which("ffprobe") or str(Path(ffmpeg).with_name("ffprobe"))
    try:
        out = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                             capture_output=True, timeout=60)
        return float(out.stdout.decode().strip() or 0) or 3600.0
    except Exception:  # noqa: BLE001
        return 3600.0

