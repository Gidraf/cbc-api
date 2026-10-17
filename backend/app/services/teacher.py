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

VERSION = "t2"          # t2: the realistic Rocketbox teachers
VOICES = {"female": "en-KE-AsiliaNeural", "male": "en-KE-ChilembaNeural"}
CHECK_LINE = "Did you get it right? Tell me in the comments!"
CHECK_CAPTION = "Did you get it right? Comment ✅ or ❌"


# What a video's teacher can be: none; a classroom (any teacher, chosen per
# video); a woman or a man (young or older, chosen per video); one teacher in
# particular; or half and half by question.
PICKS = ("female_young", "male_young", "teacher_older_f", "teacher_older_m")
MODES = ("off", "classroom", "female", "male", "alternate") + PICKS


def mode() -> str:
    from . import platform_settings

    try:
        value = str(platform_settings.get("social_teacher", "classroom") or "classroom").strip().lower()
    except Exception:  # noqa: BLE001
        value = "classroom"
    return value if value in MODES else "classroom"


def students_setting() -> int | None:
    """How many students sit in: 0, 1 or 2 — or None, a different number each video."""
    from . import platform_settings

    try:
        value = str(platform_settings.get("social_students", "random") or "random").strip().lower()
    except Exception:  # noqa: BLE001
        value = "random"
    return int(value) if value in ("0", "1", "2") else None


def gender_for(question_id: str, how: str | None = None, students: int | None = None) -> str:
    """'' when there is no teacher; else 'female' or 'male'."""
    how = mode() if how is None else how
    if how == "off":
        return ""
    return cast_for(question_id, how, students)["teacher"]["gender"]


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

def render_now(how: str = "classroom", *, limit: int = 60, pause_lessons: bool = True, by: str = "") -> dict[str, Any]:
    """Teacher videos first: turn the teacher on, pause the lesson videos
    (the queued ones are cancelled and the daily batch set to 0), and queue
    the booked posts' videos again with the teacher — soonest post first, at
    the front of the render queue. Posts already handed to a platform keep
    the video the platform has."""
    from ..infra.db import execute, fetch_all, fetch_one
    from . import platform_settings, social
    from .whiteboard import JOB_KIND as LESSON

    if how not in MODES or how == "off":
        raise ValueError(f"The teacher is one of {', '.join(m for m in MODES if m != 'off')}.")
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


# ── the words on the lips ────────────────────────────────────────────────────
#
# Loudness alone opens and shuts the mouth like a puppet's. Each frame also
# gets a mouth SHAPE — a viseme — from the words being said: the words are
# laid over the stretches where the voice is sounding (pauses between them
# are where it is quiet), each word's frames shared by its sounds, and each
# sound drawn as the shape the lips make for it.
#
#   X rest   M m/b/p (lips together)   F f/v (lip on teeth)   O o/u/w (round)
#   E e/i/y (wide)   A a (open)   L l/t/d/n/th (tongue)   S s/z/sh/ch/j (teeth)
#   R r (a little round)   K k/g/h (open, back)

_DIGRAPHS = [("th", "L"), ("sh", "S"), ("ch", "S"), ("ph", "F"), ("oo", "O"), ("ee", "E"), ("ea", "E"),
             ("ou", "O"), ("ow", "O"), ("ai", "E"), ("ay", "E"), ("oa", "O"), ("qu", "K"), ("ck", "K"), ("ng", "K")]
_LETTER = {**{c: "A" for c in "a"}, **{c: "E" for c in "eiy"}, **{c: "O" for c in "ouw"}, **{c: "M" for c in "bmp"},
           **{c: "F" for c in "fv"}, "r": "R", **{c: "L" for c in "ltdn"}, **{c: "S" for c in "szxcj"},
           **{c: "K" for c in "kgqh"}}
_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen " \
        "seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _number_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])
    if n < 1000:
        return _ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " and " + _number_words(n % 100))
    if n < 1_000_000:
        return _number_words(n // 1000) + " thousand" + ("" if n % 1000 == 0 else " " + _number_words(n % 1000))
    return " ".join(_ONES[int(d)] for d in str(n))


def spoken_words(text: str) -> list[str]:
    """The words as the voice says them: digits read out, symbols dropped."""
    import re

    text = re.sub(r"(\d+)\.(\d+)", lambda m: f"{m.group(1)} point {' '.join(m.group(2))}", text or "")
    text = re.sub(r"\d+", lambda m: f" {_number_words(int(m.group(0)))} " if len(m.group(0)) < 7 else m.group(0), text)
    text = text.replace("%", " percent ").replace("=", " equals ").replace("+", " plus ")
    return [w for w in re.findall(r"[a-z']+", text.lower()) if w.strip("'")]


def word_visemes(word: str) -> str:
    """'square' → 'SKOER': one shape per sound, digraphs first."""
    out, k = [], 0
    w = word.replace("'", "")
    while k < len(w):
        pair = w[k:k + 2]
        hit = next((v for d, v in _DIGRAPHS if pair == d), None)
        if hit:
            out.append(hit)
            k += 2
            continue
        if w[k] == "e" and k == len(w) - 1 and len(w) > 2:   # a silent final e
            k += 1
            continue
        out.append(_LETTER.get(w[k], "L"))
        k += 1
    # A shape held across a doubled letter is one shape.
    return "".join(c for i, c in enumerate(out) if i == 0 or c != out[i - 1]) or "A"


def visemes(text: str, envelope: list[float], *, quiet: float = 0.06) -> str:
    """One shape per frame of a scene: the words laid over where the voice sounds."""
    n = len(envelope)
    if not n:
        return ""
    words = spoken_words(text)
    voiced = [k for k, v in enumerate(envelope) if v > quiet]
    frames = ["X"] * n
    if not words or not voiced:
        return "".join(frames)
    # Runs of sound, split where the voice drops for 3+ frames (a pause).
    runs: list[list[int]] = [[voiced[0]]]
    for k in voiced[1:]:
        (runs[-1].append(k) if k - runs[-1][-1] <= 3 else runs.append([k]))
    sounds = [word_visemes(w) for w in words]
    weights = [max(2, len(s)) for s in sounds]
    total = sum(weights)
    # Words share the sounding frames in order, in proportion to their length.
    flat = [k for run in runs for k in range(run[0], run[-1] + 1)]
    cursor = 0.0
    for shapes, wgt in zip(sounds, weights):
        a = int(round(cursor / total * len(flat)))
        cursor += wgt
        b = int(round(cursor / total * len(flat)))
        span = flat[a:b] or flat[min(a, len(flat) - 1):min(a, len(flat) - 1) + 1]
        for j, k in enumerate(span):
            frames[k] = shapes[min(len(shapes) - 1, j * len(shapes) // max(1, len(span)))]
    for k, v in enumerate(envelope):          # where the voice is silent, the lips rest
        if v <= quiet * 0.5:
            frames[k] = "X"
    return "".join(frames)


# ── the classroom: a teacher and two students ────────────────────────────────
#
# Mode "classroom" (Settings → Social → Teacher): the teacher reads the
# question, the class thinks through the countdown, one student works the
# solution in a young voice, and the teacher asks "Did Juma get it right?".
# Who teaches, who answers and in which voices is picked by the question, so
# every video differs and a video never changes.

TEACHERS = [
    {"model": "female", "gender": "female", "older": False},
    {"model": "male", "gender": "male", "older": False},
    {"model": "teacher_older_f", "gender": "female", "older": True},
    {"model": "teacher_older_m", "gender": "male", "older": True},
]
STUDENTS = [
    {"model": "student_boy", "gender": "male",
     "names": ["Juma", "Kamau", "Otieno", "Kiprop", "Baraka", "Wafula", "Mutua", "Omondi"]},
    {"model": "student_girl", "gender": "female",
     "names": ["Nekesa", "Wanjiku", "Amina", "Zainab", "Halima", "Fatuma", "Rehema", "Aisha"]},
]
TEACHER_VOICES = {"female": ["en-KE-AsiliaNeural", "en-NG-EzinneNeural", "en-ZA-LeahNeural", "en-TZ-ImaniNeural"],
                  "male": ["en-KE-ChilembaNeural", "en-NG-AbeoNeural", "en-ZA-LukeNeural", "en-TZ-ElimuNeural"]}
# Young voices: a Kenyan voice raised in pitch and a little quicker, or a child's voice.
STUDENT_VOICES = {"female": ["en-KE-AsiliaNeural|+30Hz|+6%", "en-US-AnaNeural", "en-TZ-ImaniNeural|+28Hz|+6%"],
                  "male": ["en-KE-ChilembaNeural|+45Hz|+7%", "en-NG-AbeoNeural|+45Hz|+7%", "en-TZ-ElimuNeural|+42Hz|+7%"]}
PLACES = {"teacher": {"x": -0.6, "ry": 0.3}, "s1": {"x": 0.32, "ry": -0.25}, "s2": {"x": 0.92, "ry": -0.4}}


def _model_exists(name: str) -> bool:
    from .whiteboard import STATIC

    return (STATIC / "teachers" / f"{name}.glb").exists()


def choice(question_id: str) -> dict[str, Any]:
    """What was asked for this question in Play (its teacher, its students) and
    which take it is on — each "make it again" is a new cast."""
    from ..infra.db import fetch_one

    try:
        row = fetch_one("SELECT take, teacher, students FROM social_casts WHERE question_id = :q",
                        {"q": question_id}) or {}
    except Exception:  # noqa: BLE001
        row = {}
    return {"take": int(row.get("take") or 0), "teacher": str(row.get("teacher") or ""),
            "students": row.get("students")}


def choose(question_id: str, *, teacher: str = "", students: int | None = None, new_take: bool = True) -> dict[str, Any]:
    """Keep a teacher and students for one question (empty: as Settings say), and
    deal a new cast."""
    from ..infra.db import execute

    if teacher and teacher not in MODES:
        raise ValueError(f"The teacher is one of {', '.join(MODES)}.")
    if students is not None and students not in (0, 1, 2):
        raise ValueError("Students are 0, 1 or 2.")
    execute("""INSERT INTO social_casts (question_id, take, teacher, students, updated_at)
               VALUES (:q, :t, :teacher, :s, NOW())
               ON CONFLICT (question_id) DO UPDATE SET take = social_casts.take + :t, teacher = :teacher,
                      students = :s, updated_at = NOW()""",
            {"q": question_id, "t": 1 if new_take else 0, "teacher": teacher, "s": students})
    return choice(question_id)


def cast_for(question_id: str, how: str | None = None, students: int | None = None, *,
             take: int | None = None) -> dict[str, Any]:
    """Who is in this question's video: the teacher, and up to two students (s1
    answers) — their models, names and voices. `how` narrows the teacher
    (a classroom: anyone); `students` fixes how many (None: dealt per video)."""
    how = mode() if how is None else how
    take = choice(question_id)["take"] if take is None else take
    n = int(hashlib.sha256((f"class:{question_id}" + (f":{take}" if take else "")).encode()).hexdigest(), 16)
    teachers = [t for t in TEACHERS if _model_exists(t["model"])] or TEACHERS[:2]
    if how in PICKS:
        teachers = [t for t in teachers if t["model"] == {"female_young": "female", "male_young": "male"}.get(how, how)] or teachers
    elif how in ("female", "male"):
        teachers = [t for t in teachers if t["gender"] == how] or teachers
    elif how == "alternate":
        g = "female" if int(hashlib.sha256(question_id.encode()).hexdigest(), 16) % 2 == 0 else "male"
        teachers = [t for t in teachers if t["gender"] == g] or teachers
    t = teachers[n % len(teachers)]
    tv = TEACHER_VOICES[t["gender"]][(n // 7) % len(TEACHER_VOICES[t["gender"]])]
    if t["older"]:
        tv = f"{tv}|-6Hz|-7%"
    count = students if students in (0, 1, 2) else (2, 2, 1, 1, 0)[(n // 23) % 5]
    pool = [s for s in STUDENTS if _model_exists(s["model"])]
    answering = pool[(n // 11) % len(pool)] if pool and count >= 1 else None
    other = next((s for s in pool if s is not answering), None) if count >= 2 else None
    # Alone, the teacher stands in the middle; with students, to one side.
    place = PLACES["teacher"] if answering else {"x": 0.0, "ry": 0.0}
    cast = {"teacher": {"id": "teacher", "model": t["model"], "gender": t["gender"], "voice": tv, **place}}
    if answering:
        cast["s1"] = {"id": "s1", "model": answering["model"], "gender": answering["gender"],
                      "name": answering["names"][(n // 13) % len(answering["names"])],
                      "voice": STUDENT_VOICES[answering["gender"]][(n // 17) % len(STUDENT_VOICES[answering["gender"]])],
                      **(PLACES["s1"] if other else {"x": 0.55, "ry": -0.3})}
    if other:
        cast["s2"] = {"id": "s2", "model": other["model"], "gender": other["gender"],
                      "name": other["names"][(n // 19) % len(other["names"])], **PLACES["s2"]}
    return cast


def signature(cast: dict[str, Any]) -> str:
    """The cast in a few characters, for a video's key: a new cast is a new video."""
    return "|".join(f"{c['id']}={c['model']}:{c.get('name', '')}:{c.get('voice', '')}" for c in cast.values())


STUDENT_SCENES = {"setup", "rewrite", "step", "working", "answer", "number_line_start", "number_line_jump",
                  "balance_move", "fraction_bars", "figure_read"}


def classroom_script(scenes: list[dict[str, Any]], cast: dict[str, Any]) -> list[dict[str, Any]]:
    """Who says each scene: the teacher asks, the student answers, the teacher checks."""
    s1 = cast.get("s1")
    out = []
    for sc in scenes:
        sc = dict(sc)
        kind = str(sc.get("scene") or "")
        if s1 and kind in STUDENT_SCENES:
            sc["speaker"], sc["voice"] = "s1", s1["voice"]
            if sc.get("say"):
                sc["caption"] = f"{s1['name']}: {sc.get('caption') or sc['say']}"
        else:
            sc["speaker"], sc["voice"] = "teacher", cast["teacher"]["voice"]
        if kind == "check" and s1:
            sc["say"] = f"Did {s1['name']} get it right? Tell us in the comments!"
            sc["caption"] = f"Did {s1['name']} get it right? Comment ✅ or ❌"
        out.append(sc)
    return out
