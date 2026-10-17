"""Marketing videos: the 3D teacher walks teachers, parents and students
through the real console — sign up, set a paper, take it online, share the
link, see the marks.

The screens are the console's own (backend/scripts/promo_shots.py takes them
with sample data; static/promo holds them and where each call-out is). Each
becomes a "screen" scene on the board: the screen slides in and the hand
rings what to press while the teacher says what it does. The cut is the
social one — vertical, the cover first, captions, the teacher (or the
classroom) below, the brand's end card — so it posts like any other video.

    python -m app.admin_tools promo-video --audience teachers
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

PREFIX = "promo"
SHOTS = Path(__file__).resolve().parent.parent / "static" / "promo"

# Each storyboard: the hook, then (screen, line) in order, then the call to act.
STORYBOARDS: dict[str, dict[str, Any]] = {
    "teachers": {
        "hook": "Set your exam in 2 minutes",
        "intro": "Teachers! Here is how to set a full CBC exam, print it with its marking scheme, "
                 "and test your class online — all in two minutes.",
        "steps": [
            ("signup", "Create a free account. Choose parent or teacher, add your email, and you are in. Your first ten questions are free."),
            ("start", "Pick the grade, the subject and the term. Name the paper what your school calls it, and open the studio."),
            ("paper", "Fill it from the question bank. Every question follows the KICD curriculum, with figures where they help."),
            ("print", "Download the paper, the marking scheme and an answer booklet. Or put it online with one click."),
            ("test", "Make an online test. Each student gets their own questions, in their own order. Copy the link and share it on WhatsApp."),
            ("student_start", "Your students open the link on any phone, type their name, and begin. No account needed."),
            ("results", "Every test is marked as they hand in. Written answers come to you with the marking scheme."),
        ],
        "cta": "Start free today",
    },
    "parents": {
        "hook": "Practice tests for your child",
        "intro": "Parents! Want to know how your child is really doing? Set a CBC practice test at home in minutes.",
        "steps": [
            ("signup", "Sign up free as a parent. Add your email, choose a password, and you are in."),
            ("start", "Choose your child's grade and subject — Mathematics, English, Science — and open the studio."),
            ("paper", "The paper fills itself from checked questions that follow what your child learns in class."),
            ("print", "Print it with the marking scheme, so you can mark it together. Or send it to their phone as a test."),
            ("student_test", "Your child answers on a phone or a laptop, one question at a time."),
            ("student_result", "The score comes the moment they hand in, with the right answers and how to work them out."),
        ],
        "cta": "Try it free",
    },
    "students": {
        "hook": "Got a test link? Do this",
        "intro": "Got a test link from your teacher? Here is exactly what to do, so you never lose a mark to the app.",
        "steps": [
            ("student_start", "Open the link, type your full name, and press Begin. You do not need an account."),
            ("student_test", "Answer each question. Tap a choice, or type your answer. The clock at the top shows the time left."),
            ("student_result", "Hand in, and see your score straight away — with the answers, and a video that shows how to solve each one."),
        ],
        "cta": "Practise more for free",
        "student": True,
    },
}


def audiences() -> list[str]:
    return list(STORYBOARDS)


def _shots() -> dict[str, Any]:
    try:
        return json.loads((SHOTS / "shots.json").read_text())
    except (OSError, ValueError):
        return {}


def _image(name: str) -> str:
    p = SHOTS / f"{name}.png"
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode() if p.exists() else ""


def script(audience: str, b: dict[str, Any]) -> dict[str, Any]:
    """The video as whiteboard scenes: the hook, each screen with its line, the end card."""
    if audience not in STORYBOARDS:
        raise ValueError(f"The audience is one of {', '.join(STORYBOARDS)}.")
    sb, boxes = STORYBOARDS[audience], _shots()
    scenes: list[dict[str, Any]] = [{"scene": "title", "text": sb["hook"], "say": sb["intro"], "caption": sb["intro"]}]
    for name, line in sb["steps"]:
        img = _image(name)
        if not img:
            continue
        scenes.append({"scene": "screen", "img": img, "box": (boxes.get(name) or {}).get("box") or [0, 0, 0, 0],
                       "say": line, "caption": line, "shot": name})
    who = b.get("handle") or b.get("name") or ""
    site = b.get("website") or ""
    scenes.append({"scene": "outro", "name": b.get("name") or "", "handle": b.get("handle") or "", "website": site,
                   "cta": sb["cta"], "say": f"{sb['cta']} at {site or who}.", "caption": f"{sb['cta']}: {site or who}"})
    return {"question_id": f"promo-{audience}", "kind": "promo", "scenes": scenes}


def _cast(data: dict[str, Any], audience: str, how: str) -> dict[str, Any]:
    """In the classroom, the student reads what a student does; the teacher the rest."""
    from . import teacher

    if how != "classroom":
        return data
    cast = teacher.cast_for(data["question_id"])
    student_lines = STORYBOARDS[audience].get("student") or False
    for sc in data["scenes"]:
        by_student = cast.get("s1") and (student_lines or str(sc.get("shot") or "").startswith("student_")) \
            and sc["scene"] == "screen"
        who = cast["s1"] if by_student else cast["teacher"]
        sc["speaker"], sc["voice"] = ("s1" if by_student else "teacher"), who["voice"]
        if by_student and sc.get("caption"):
            sc["caption"] = f"{who['name']}: {sc['caption']}"
    return data


def render(audience: str = "teachers", *, how: str = "classroom", progress: Any = None) -> dict[str, Any]:
    """Make one marketing video; returns its url, thumbnail and key."""
    from . import drive_store, social, teacher, whiteboard

    b = {**social.brand(), "teacher": how}
    data = _cast(script(audience, b), audience, how)
    q = {"question_id": data["question_id"], "question_text": STORYBOARDS[audience]["intro"], "curriculum": {}}
    framing = social.frame_payload(q, b)
    if framing.get("cover"):
        framing["cover"].update({"hook": STORYBOARDS[audience]["hook"], "question": STORYBOARDS[audience]["intro"],
                                 "choices": [], "tag": "CBC EXAMS · FREE TO START"})
    framing["hook"] = STORYBOARDS[audience]["hook"]
    gender = teacher.gender_for(data["question_id"], how) or "female"
    voice = (teacher.cast_for(data["question_id"])["teacher"]["voice"] if how == "classroom" else teacher.voice_for(gender))
    key = hashlib.sha256(json.dumps([data, voice, framing.get("teacher")], sort_keys=True, default=str).encode()).hexdigest()[:20]
    made = whiteboard.render(data, title=STORYBOARDS[audience]["hook"], voice=voice, progress=progress, social=framing,
                             prefix=PREFIX, key=key)
    try:
        drive_store.copy_now(f"{PREFIX}/{data['question_id']}/{key}.mp4", f"{PREFIX}/{data['question_id']}/{key}.jpg")
    except Exception:  # noqa: BLE001
        pass
    return {**made, "audience": audience, "key": key}
