"""Sound effects for a rendered video: the page's own list of sounds
(window.__sfx — a whoosh as an electron flies, a pop as it lands, fizzing,
drips, chimes) synthesised into one track, the same recipes as static/sfx.js,
so a video sounds as the live page does. Pure Python: no files, no licences.
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Any

RATE = 22050
MASTER = 0.32


def _env(n: int, attack: float, peak: float) -> list[float]:
    a = max(1, int(attack * RATE))
    out = []
    for i in range(n):
        if i < a:
            out.append(peak * (0.0001 * (peak / 0.0001) ** (i / a)) / peak if peak > 0.0002 else 0.0)
        else:
            k = (i - a) / max(1, n - a)
            out.append(peak * (0.0001 / peak) ** k if peak > 0.0002 else 0.0)
    return out


def _tone(kind: str, f0: float, f1: float, dur: float, peak: float, attack: float = 0.005) -> list[float]:
    n = int((dur + attack) * RATE)
    env = _env(n, attack, peak)
    out, phase = [], 0.0
    ratio = max(20.0, f1) / f0
    for i in range(n):
        f = f0 * ratio ** min(1.0, i / max(1, dur * RATE))
        phase += 2 * math.pi * f / RATE
        x = math.sin(phase)
        if kind == "square":
            x = 1.0 if x >= 0 else -1.0
        elif kind == "triangle":
            x = 2 / math.pi * math.asin(x)
        elif kind == "sawtooth":
            x = ((phase / math.pi) % 2) - 1
        out.append(x * env[i])
    return out


def _noise(n: int, seed: int = 7) -> list[float]:
    s, out = seed, []
    for _ in range(n):
        s = (s * 16807) % 2147483647
        out.append((s / 2147483647) * 2 - 1)
    return out


def _hiss(kind: str, f0: float, f1: float, dur: float, peak: float, attack: float = 0.01, q: float = 1.0) -> list[float]:
    """Noise through a filter whose frequency sweeps f0 → f1 (a biquad, as WebAudio's)."""
    n = int((dur + attack) * RATE)
    env = _env(n, attack, peak)
    src = _noise(n)
    out = []
    x1 = x2 = y1 = y2 = 0.0
    ratio = max(30.0, f1) / f0
    b0 = b1 = b2 = a1 = a2 = 0.0
    for i in range(n):
        if i % 32 == 0:
            f = min(RATE * 0.45, f0 * ratio ** min(1.0, i / max(1, dur * RATE)))
            w = 2 * math.pi * f / RATE
            alpha = math.sin(w) / (2 * q)
            cw = math.cos(w)
            if kind == "lowpass":
                b0, b1, b2 = (1 - cw) / 2, 1 - cw, (1 - cw) / 2
            elif kind == "highpass":
                b0, b1, b2 = (1 + cw) / 2, -(1 + cw), (1 + cw) / 2
            else:
                b0, b1, b2 = alpha, 0.0, -alpha
            a0 = 1 + alpha
            a1, a2 = -2 * cw / a0, (1 - alpha) / a0
            b0, b1, b2 = b0 / a0, b1 / a0, b2 / a0
        x = src[i]
        y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, x, y1, y
        out.append(y * env[i])
    return out


def _layer(*parts: tuple[float, list[float]]) -> list[float]:
    """Sounds laid over each other, each `offset` seconds in."""
    n = max(int(o * RATE) + len(p) for o, p in parts)
    out = [0.0] * n
    for o, p in parts:
        s = int(o * RATE)
        for i, v in enumerate(p):
            out[s + i] += v
    return out


def recipe(kind: str, k: float = 1.0, p: float = 1.0) -> list[float]:
    """One sound — the same recipes as static/sfx.js."""
    if kind == "whoosh":
        return _hiss("bandpass", 300 * p, 2600 * p, 0.55, 0.9 * k, 0.25, 1.4)
    if kind == "ding":
        return _layer((0, _tone("sine", 1320 * p, 1310 * p, 1.1, 0.5 * k)), (0, _tone("sine", 2640 * p, 2630 * p, 0.7, 0.18 * k)))
    if kind == "chime":
        return _layer(*[(i * 0.09, _tone("sine", f * p, f * p, 0.9, 0.35 * k)) for i, f in enumerate((1047, 1319, 1568))])
    if kind == "zap":
        return _layer((0, _hiss("highpass", 3000, 1200, 0.16, 0.5 * k, 0.003)), (0, _tone("sawtooth", 1800 * p, 300 * p, 0.18, 0.18 * k)))
    if kind == "snap":
        return _layer((0, _hiss("highpass", 2500, 2500, 0.04, 0.8 * k, 0.002)), (0, _tone("sine", 160 * p, 70 * p, 0.18, 0.7 * k)))
    if kind == "thud":
        return _tone("sine", 95 * p, 48 * p, 0.35, 0.9 * k)
    if kind == "fizz":
        return _hiss("highpass", 5000, 7000, 1.2, 0.18 * k, 0.15)
    if kind == "drip":
        return _tone("sine", 1250 * p, 560 * p, 0.07, 0.5 * k)
    if kind == "sparkle":
        return _layer(*[(i * 0.07, _tone("sine", (2200 + i * 380) * p, (2200 + i * 380) * p, 0.25, 0.16 * k)) for i in range(4)])
    if kind == "flame":
        return _hiss("lowpass", 380, 260, 1.4, 0.45 * k, 0.3)
    if kind == "click":
        return _tone("square", 1800 * p, 1700 * p, 0.025, 0.25 * k, 0.001)
    if kind == "riser":
        return _layer((0, _hiss("bandpass", 200 * p, 3000 * p, 1.6, 0.5 * k, 1.4, 2)), (0, _tone("sine", 220 * p, 880 * p, 1.6, 0.12 * k, 1.4)))
    if kind == "tick":
        return _tone("triangle", 1500 * p, 1500 * p, 0.05, 0.35 * k)
    return _tone("sine", 900 * p, 260 * p, 0.12, 0.8 * k)          # pop


def track(events: list[dict[str, Any]], seconds: float, path: Path) -> Path | None:
    """All the sounds at their times, one mono WAV as long as the video."""
    evs = [e for e in events if isinstance(e, dict) and 0 <= float(e.get("t") or 0) < seconds][:2000]
    if not evs:
        return None
    n = int(seconds * RATE) + RATE
    mix = [0.0] * n
    cache: dict[tuple[str, float, float], list[float]] = {}
    for e in evs:
        key = (str(e.get("kind") or "pop"), round(float(e.get("gain") or 1), 2), round(float(e.get("pitch") or 1), 2))
        if key not in cache:
            cache[key] = recipe(*key)
        s = int(float(e["t"]) * RATE)
        for i, v in enumerate(cache[key]):
            if s + i < n:
                mix[s + i] += v * MASTER
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32000)) for v in mix))
    return path
