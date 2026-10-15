"""The teacher in the social cut: off by default, a voice that matches the
face, a question back to the viewer, and videos already made left alone."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.services import social, teacher


def _brand(**over):
    b = {"hook": "Can you solve this?", "bg_from": "#000000", "bg_to": "#000000", "accent": "#ffffff", "text": "#ffffff",
         "name": "CBC Maths", "handle": "@cbc", "website": "cbc.example", "cta": "Follow", "countdown": 3,
         "hashtags": "", "logo_url": "", "music_url": "", "teacher": "off"}
    return {**b, **over}


DATA = {"question_id": "q1", "scenes": [{"scene": "title", "say": "What is 2 + 3?"}, {"scene": "step", "say": "Add."},
                                        {"scene": "answer", "say": "Five.", "text": "5"}]}


def test_off_by_default_and_the_cut_is_unchanged(monkeypatch) -> None:
    from app.services import platform_settings

    monkeypatch.setattr(platform_settings, "get", lambda k, d=None: d)
    assert teacher.mode() == "off" and teacher.gender_for("q1") == ""
    kinds = [s["scene"] for s in social.script(DATA, {}, _brand())["scenes"]]
    assert "check" not in kinds


def test_with_a_teacher_the_viewer_is_asked_before_the_end() -> None:
    kinds = [s["scene"] for s in social.script(DATA, {}, _brand(teacher="female"))["scenes"]]
    assert kinds[-2:] == ["check", "outro"]


def test_the_voice_matches_the_face() -> None:
    assert teacher.voice_for("female") == "en-KE-AsiliaNeural"
    assert teacher.voice_for("male") == "en-KE-ChilembaNeural"
    picks = {teacher.gender_for(f"q{n}", "alternate") for n in range(20)}
    assert picks == {"female", "male"}
    assert teacher.gender_for("q7", "alternate") == teacher.gender_for("q7", "alternate"), "the same every time"


def test_a_video_without_a_teacher_keeps_its_key(monkeypatch) -> None:
    from app.services import whiteboard

    monkeypatch.setattr(whiteboard, "cache_key", lambda data, voice, fps=30: "board")
    plain = social.cache_key(DATA, "v", _brand())
    assert social.cache_key(DATA, "v", _brand(), "") == plain
    assert social.cache_key(DATA, "v", _brand(), "female") != plain
    assert social.cache_key(DATA, "v", _brand(), "female") != social.cache_key(DATA, "v", _brand(), "male")


def test_turning_the_teacher_on_does_not_unmake_what_was_made(monkeypatch) -> None:
    from app.infra import storage
    from app.services import whiteboard

    monkeypatch.setattr(social, "brand", lambda: _brand(teacher="female"))
    monkeypatch.setattr(whiteboard, "_script_for", lambda q, voice="": (DATA, voice or "en-KE-AsiliaNeural", "t"))
    monkeypatch.setattr(whiteboard, "public_url", lambda n: "/" + n)
    old_key = social._prepare({"question_id": "q1"}, teacher_mode="off")[5]
    have = {f"social/q1/{old_key}.mp4"}
    monkeypatch.setattr(storage.object_storage, "object_exists", lambda n: n in have)
    st = social.status("q1", {"question_id": "q1"})
    assert st["status"] == "ready" and old_key in st["url"] and st["teacher"] == "" and st["teacher_pending"]
    # Asked to make it fresh, it is not "ready": the teacher's video is still to make.
    from app.infra import db

    monkeypatch.setattr(db, "fetch_one", lambda q, p=None: None)
    fresh = social.status("q1", {"question_id": "q1"}, legacy=False)
    assert fresh["status"] != "ready" and fresh["teacher"] == "female"


def test_the_preview_can_show_a_teacher_whatever_the_setting(monkeypatch) -> None:
    from app.services import whiteboard

    monkeypatch.setattr(social, "brand", lambda: _brand())                       # the setting: off
    monkeypatch.setattr(whiteboard, "_script_for", lambda q, voice="": (DATA, voice or "en-KE-AsiliaNeural", "t"))
    monkeypatch.setattr(whiteboard, "speak_all", lambda scenes, voice: [(None, 2.0) for _ in scenes])
    seen = {}
    real_page = whiteboard.page
    monkeypatch.setattr(whiteboard, "page", lambda data, **k: seen.update(k) or real_page(data, **k))
    with_t = social.live_page({"question_id": "q1"}, teacher_mode="male")
    assert "WebGLRenderer" in with_t and seen["voice"].startswith("en-KE")
    assert any(s["scene"] == "check" for s in social._prepare({"question_id": "q1"}, teacher_mode="male")[1]["scenes"])
    plain = social.live_page({"question_id": "q1"})
    assert "WebGLRenderer" not in plain


def test_the_page_carries_the_teacher_only_when_asked() -> None:
    from app.services import whiteboard

    with_t = whiteboard.page(DATA, render=True, social={"hook": "x", "teacher": {"gender": "female", "mouth": [], "fps": 30}})
    without = whiteboard.page(DATA, render=True, social={"hook": "x"})
    assert "THREE" in with_t and "__onTime" in with_t
    assert "teacher.js" not in without and "WebGLRenderer" not in without


needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")


@needs_ffmpeg
def test_the_mouth_follows_the_loudness(tmp_path: Path) -> None:
    import subprocess

    ff = shutil.which("ffmpeg")
    clip = tmp_path / "say.wav"     # half a second of quiet, then half a second of tone
    subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "aevalsrc='if(lt(t,0.5),0,0.5*sin(2*PI*220*t))':s=16000:d=1",
                    str(clip)], check=True)
    env = teacher.mouth_envelopes(ff, [clip, None], 30)
    assert env[1] == [] and 28 <= len(env[0]) <= 32
    assert max(env[0][:12]) == 0 and max(env[0][20:]) > 0.8


@needs_ffmpeg
def test_moods_are_made_for_the_question_and_the_answer(tmp_path: Path) -> None:
    ff = shutil.which("ffmpeg")
    scenes = [{"scene": "title"}, {"scene": "countdown"}, {"scene": "step"}, {"scene": "answer"}, {"scene": "outro"}]
    starts = [0.3, 4.0, 7.0, 12.0, 16.0]
    tracks = teacher.mood_tracks(ff, tmp_path, scenes, starts, 20.0)
    names = {p.name: at for p, at in tracks}
    assert names == {"mood_tense.wav": 0.3, "mood_chime.wav": 12.2, "mood_lively.wav": 12.0}
    only_chime = teacher.mood_tracks(ff, tmp_path, scenes, starts, 20.0, beds=False)
    assert [p.name for p, _ in only_chime] == ["mood_chime.wav"], "an uploaded track replaces the beds"


def test_the_command_registers_the_jobs_and_leaves_rendering_to_the_api() -> None:
    """Run in its own process, the queue there knew no job kinds ("'social'
    is not a job this queue can run. Known: .") — and a worker started there
    would die with the command."""
    import inspect

    from app import admin_tools

    source = inspect.getsource(admin_tools.teacher_now)
    assert "from .routes import curriculum" in source
    assert "job_queue.start_worker = lambda: False" in source


def test_the_lips_take_the_shape_of_the_words() -> None:
    assert teacher.spoken_words("18 divided by 3") == ["eighteen", "divided", "by", "three"]
    assert teacher.word_visemes("mama")[0] == "M" and "O" in teacher.word_visemes("book")
    assert teacher.word_visemes("five").startswith("F")
    env = [0.0] * 5 + [0.8] * 30 + [0.0] * 6 + [0.7] * 25 + [0.0] * 4
    shapes = teacher.visemes("Hello my friend", env)
    assert len(shapes) == len(env)
    assert shapes[:5] == "XXXXX" and shapes[-4:] == "XXXX", "silence is a closed mouth"
    assert "M" in shapes and "F" in shapes, "m closes the lips, f puts them to the teeth"
    assert shapes.index("M") < shapes.index("F"), "in the order they are said"
