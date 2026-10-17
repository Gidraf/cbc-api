"""The marketing videos: the console's own screens, the teacher's lines, the end card."""
from __future__ import annotations

from app.services import promo, whiteboard

B = {"name": "CBC Maths", "handle": "@cbc", "website": "cbc.example", "cta": "Follow"}


def test_every_screen_a_storyboard_names_is_shipped_with_its_call_out() -> None:
    boxes = promo._shots()
    for audience, sb in promo.STORYBOARDS.items():
        for name, line in sb["steps"]:
            assert (promo.SHOTS / f"{name}.png").exists(), f"{audience}: {name}.png"
            x, y, w, h = boxes[name]["box"]
            assert w > 0 and h > 0 and 0 <= x <= 1280 and 0 <= y <= 720, f"{name}: the call-out is on the screen"
            assert line.endswith((".", "!")), "each line is said whole"


def test_the_script_opens_on_the_hook_shows_each_screen_and_ends_on_the_call_to_act() -> None:
    data = promo.script("teachers", B)
    kinds = [s["scene"] for s in data["scenes"]]
    assert kinds[0] == "title" and kinds[-1] == "outro" and kinds.count("screen") == len(promo.STORYBOARDS["teachers"]["steps"])
    screen = data["scenes"][1]
    assert screen["img"].startswith("data:image/png;base64,") and len(screen["box"]) == 4
    assert data["scenes"][-1]["say"] == "Start free today at cbc.example."


def test_in_the_classroom_a_student_says_what_a_student_does() -> None:
    data = promo._cast(promo.script("teachers", B), "teachers", "classroom")
    by = {s.get("shot"): s["speaker"] for s in data["scenes"]}
    assert by["signup"] == "teacher" and by["student_start"] == "s1"
    student = next(s for s in data["scenes"] if s.get("shot") == "student_start")
    assert ":" in student["caption"] and "|" in student["voice"] or student["voice"] == "en-US-AnaNeural"
    every = promo._cast(promo.script("students", B), "students", "classroom")
    assert all(s["speaker"] == "s1" for s in every["scenes"] if s["scene"] == "screen")


def test_the_board_draws_a_screen_and_rings_the_button() -> None:
    js = (whiteboard.STATIC / "whiteboard.js").read_text()
    assert "screen(s, at, dur)" in js and "(png|jpeg|webp);base64" in js
    page = whiteboard.page(promo.script("parents", B), render=True, social={"hook": "x"})
    assert '"scene": "screen"' in page
