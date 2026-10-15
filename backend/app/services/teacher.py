"""The teacher in the social cut: who presents, in which voice, and the
sound of the video's moods.

Setting `social_teacher` (Settings → Social): off · female · male ·
alternate (by question, half and half). A female teacher speaks with the
Kenyan woman's voice, a male teacher with the Kenyan man's — the face and
the voice always agree.

The page draws the teacher (static/teacher.js); this module gives it what a
browser cannot measure frame by frame: how loud the voice is at each moment
(`mouth_envelopes`), so the lips move with the very audio the MP4 carries.

Moods are sound too (`mood_tracks`): a low, pulsing bed under the question
and the countdown, a bright plucked one from the answer on, and a chime as
the answer lands — made with ffmpeg, so there is no music to license. A
track the owner uploaded (Settings → Social → music) is used instead of the
beds.
"""
from __future__ import annotations

import array
import hashlib
import logging
import math
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger("cbc-teacher")

VERSION = "t1"
VOICES = {"female": "en-KE-AsiliaNeural", "male": "en-KE-ChilembaNeural"}
CHECK_LINE = "Did you get it right? Tell me in the comments!"
CHECK_CAPTION = "Did you get it right? Comment ✅ or ❌"


def mode() -> str:
    from . import platform_settings

    try:
        value = str(platform_settings.get("social_teacher", "off") or "off").strip().lower()
    except Exception:  # noqa: BLE001
        value = "off"
    return value if value in ("female", "male", "alternate") else "off"


def gender_for(question_id: str, how: str | None = None) -> str:
    """'' when there is no teacher; else 'female' or 'male'."""
    how = mode() if how is None else how
    if how == "off":
        return ""
    if how == "alternate":
        return "female" if int(hashlib.sha256(question_id.encode()).hexdigest(), 16) % 2 == 0 else "male"
    return how


def voice_for(gender: str) -> str:
    return VOICES.get(gender, "")


# ── the mouth ────────────────────────────────────────────────────────────────

def _loudness(ffmpeg: str, source: Path | bytes, fps: int) -> list[float]:
    """Root-mean-square loudness of the audio, `fps` values a second."""
    rate = 8000
    args = [ffmpeg, "-v", "error", "-i", "pipe:0" if isinstance(source, bytes) else str(source),
            "-ac", "1", "-ar", str(rate), "-f", "s16le", "pipe:1"]
    done = subprocess.run(args, input=source if isinstance(source, bytes) else None, capture_output=True, timeout=120)
    if done.returncode:
        return []
    pcm = array.array("h")
    pcm.frombytes(done.stdout[: len(done.stdout) // 2 * 2])
    step = max(1, rate // fps)
    out = []
    for k in range(0, len(pcm), step):
        chunk = pcm[k:k + step]
        out.append(math.sqrt(sum(v * v for v in chunk) / max(1, len(chunk))))
    return out


def mouth_envelopes(ffmpeg: str, sources: list[Path | bytes | None], fps: int) -> list[list[float]]:
    """Per scene, how open the mouth is (0–1) at each frame: loudness made
    relative to the whole video's, eased so the lips open fast and close a
    little slower, as speech does."""
    raw = [(_loudness(ffmpeg, s, fps) if s else []) for s in sources]
    flat = sorted(v for env in raw for v in env if v > 0)
    if not flat:
        return [[] for _ in sources]
    top = flat[min(len(flat) - 1, int(len(flat) * 0.95))] or 1.0
    floor = top * 0.08
    out = []
    for env in raw:
        eased, level = [], 0.0
        for v in env:
            target = max(0.0, min(1.0, (v - floor) / (top - floor))) if v > floor else 0.0
            level += (target - level) * (0.65 if target > level else 0.35)
            eased.append(round(level, 2))
        out.append(eased)
    return out


# ── the sound of the moods ───────────────────────────────────────────────────

def _synth(ffmpeg: str, out: Path, expr: str, seconds: float, fade: float = 0.6) -> Path | None:
    seconds = max(0.5, seconds)
    graph = (f"aevalsrc='{expr}':s=44100:d={seconds:.2f},"
             f"afade=t=in:d={min(fade, seconds / 3):.2f},afade=t=out:st={max(0.0, seconds - fade):.2f}:d={fade:.2f}")
    done = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", graph, "-ac", "2", str(out)],
                          capture_output=True, timeout=120)
    if done.returncode:
        logger.warning("Could not make %s: %s", out.name, done.stderr.decode(errors="ignore")[-200:])
        return None
    return out


TENSE = ("0.05*sin(2*PI*55*t)*(0.6+0.4*sin(2*PI*0.5*t))+0.035*sin(2*PI*82.41*t)"
         "+0.02*sin(2*PI*110*t)*(0.5+0.5*sin(2*PI*2*t))"
         "+0.12*sin(2*PI*58*t)*exp(-22*mod(t,1))+0.08*sin(2*PI*58*t)*exp(-22*mod(t+0.72,1))")
LIVELY = ("0.06*sin(2*PI*t*if(lt(mod(t,1),0.25),523.25,if(lt(mod(t,1),0.5),659.25,if(lt(mod(t,1),0.75),783.99,1046.5))))"
          "*exp(-9*mod(t,0.25))"
          "+0.035*sin(2*PI*t*if(lt(mod(t,2),1),130.81,174.61))*(0.7+0.3*sin(2*PI*2*t))")
CHIME = ("0.11*sin(2*PI*523.25*t)*exp(-3.5*t)+0.09*sin(2*PI*659.25*t)*exp(-3.5*t)"
         "+0.08*sin(2*PI*783.99*t)*exp(-3.5*t)+0.05*sin(2*PI*1046.5*t)*exp(-5*t)")


def mood_tracks(ffmpeg: str, folder: Path, scenes: list[dict[str, Any]], starts: list[float], total: float,
                *, beds: bool = True) -> list[tuple[Path, float]]:
    """(file, when) for the mood sounds: the tense bed from the question to
    the end of the countdown, the bright bed from the answer to the end, and
    a chime as the answer lands. `beds=False` (an uploaded track plays)
    keeps only the chime."""
    kinds = [str(s.get("scene") or "") for s in scenes]
    out: list[tuple[Path, float]] = []
    if beds and "title" in kinds:
        a = starts[kinds.index("title")]
        after = [k for k, s in enumerate(kinds) if k > kinds.index("title") and s not in ("title", "countdown")]
        b = starts[after[0]] if after else total
        made = _synth(ffmpeg, folder / "mood_tense.wav", TENSE, b - a + 0.4)
        if made:
            out.append((made, a))
    if "answer" in kinds:
        a = starts[kinds.index("answer")]
        chime = _synth(ffmpeg, folder / "mood_chime.wav", CHIME, 1.6, fade=0.3)
        if chime:
            out.append((chime, a + 0.2))
        if beds:
            made = _synth(ffmpeg, folder / "mood_lively.wav", LIVELY, total - a, fade=1.2)
            if made:
                out.append((made, a))
    return out


# ── switching over ───────────────────────────────────────────────────────────

def render_now(how: str = "alternate", *, limit: int = 60, pause_lessons: bool = True, by: str = "") -> dict[str, Any]:
    """Teacher videos first: turn the teacher on, pause the lesson videos
    (the queued ones are cancelled and the daily batch set to 0), and queue
    the booked posts' videos again with the teacher — soonest post first, at
    the front of the render queue. Posts already handed to a platform keep
    the video the platform has."""
    from ..infra.db import execute, fetch_all, fetch_one
    from . import platform_settings, social
    from .whiteboard import JOB_KIND as LESSON

    if how not in ("female", "male", "alternate"):
        raise ValueError("The teacher is female, male or alternate.")
    platform_settings.set_many({"social_teacher": how}, updated_by=by or "teacher-now")
    out: dict[str, Any] = {"teacher": how, "lessons_cancelled": 0, "daily_target_was": None}
    if pause_lessons:
        out["daily_target_was"] = int(platform_settings.get("video_daily_target", 200) or 0)
        platform_settings.set_many({"video_daily_target": 0}, updated_by=by or "teacher-now")
        row = fetch_one("SELECT COUNT(*) AS n FROM jobs WHERE kind = :k AND status = 'queued'", {"k": LESSON}) or {}
        execute("UPDATE jobs SET status = 'cancelled', finished_at = NOW() WHERE kind = :k AND status = 'queued'",
                {"k": LESSON})
        out["lessons_cancelled"] = int(row.get("n") or 0)
    rows = fetch_all("""SELECT question_id, MIN(scheduled_for) AS first FROM social_posts
                        WHERE COALESCE(format, 'video') = 'video' AND posted_at IS NULL AND handed_at IS NULL
                          AND status IN ('planned', 'failed') AND scheduled_for IS NOT NULL
                        GROUP BY question_id ORDER BY first LIMIT :n""", {"n": max(1, int(limit))}) or []
    queued, already, failed = 0, 0, []
    for r in rows:
        try:
            st = social.enqueue(str(r["question_id"]), queued_by=by or "teacher-now", fresh=True, priority=8)
            if st.get("status") == "queued":
                queued += 1
            elif st.get("status") in ("ready", "running"):
                already += 1
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{r['question_id']}: {str(exc)[:120]}")
    return {**out, "booked_videos": len(rows), "queued": queued, "already_with_teacher": already, "failed": failed[:5]}


def resume_lessons(target: int = 200, *, by: str = "") -> int:
    """Back to the daily lesson videos after the switch."""
    from . import platform_settings

    platform_settings.set_many({"video_daily_target": max(0, int(target))}, updated_by=by or "teacher-now")
    return max(0, int(target))
