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


def test_the_classroom_is_the_default_and_off_leaves_the_cut_unchanged(monkeypatch) -> None:
    from app.services import platform_settings

    monkeypatch.setattr(platform_settings, "get", lambda k, d=None: d)
    assert teacher.mode() == "classroom" and teacher.students_setting() is None
    assert teacher.gender_for("q1", "off") == ""
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
    assert "WebGLRenderer" in with_t and seen["voice"].startswith("en-")
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


def test_the_realistic_teachers_ship_with_their_licence_and_load_in_the_page() -> None:
    from app.services import whiteboard

    folder = whiteboard.STATIC / "teachers"
    for g in ("female", "male"):
        glb = (folder / f"{g}.glb").read_bytes()
        assert glb[:4] == b"glTF" and len(glb) < 6_000_000, "a binary glTF, a few MB"
    assert "MIT License" in (folder / "LICENSE-Rocketbox.txt").read_text()
    page = whiteboard.page(DATA, render=True, social={"hook": "x", "teacher": {"gender": "male", "mouth": [], "fps": 30}})
    assert "window.TEACHER_GLB" in page and "GLTFLoader" in page
    # And the first frame waits for the model to load.
    assert "__teacherReady" in (whiteboard.STATIC / "whiteboard.js").read_text()


def test_every_social_video_opens_on_a_cover_that_differs_by_question() -> None:
    from app.services import whiteboard

    b = {"name": "CBC Maths", "cover": True}
    covers = [social.cover_for({"question_id": f"q{n}", "question_text": "What is 2 + 3?",
                                "options": [{"id": "A", "text": "5"}], "curriculum": {"grade": "grade-9", "subject": "Mathematics"}}, b)
              for n in range(12)]
    assert len({(c["bg_from"], c["hook"]) for c in covers}) > 4, "the look and the hook change"
    assert covers[3] == social.cover_for({"question_id": "q3", "question_text": "What is 2 + 3?",
                                         "options": [{"id": "A", "text": "5"}], "curriculum": {"grade": "grade-9", "subject": "Mathematics"}}, b)
    assert covers[0]["tag"] == "GRADE 9 · MATHEMATICS" and covers[0]["choices"] == ["A) 5"]
    # The lead-in makes room for it, on the board and in the voice's timing alike.
    page = whiteboard.page(DATA, render=True, social={"hook": "x", "cover": covers[0]})
    assert '"lead": 1.3' in page and "__onCover" in page
    assert whiteboard._starts([2.0], whiteboard.LEAD + whiteboard.COVER)[0] == 1.3
    assert '"lead": 0.3' in whiteboard.page(DATA, render=True, social={"hook": "x"})


# ── the classroom: a teacher, two students, one of them answers ─────────────

def test_each_question_gets_its_own_classroom_the_same_every_time() -> None:
    casts = [teacher.cast_for(f"q{n}", "classroom", 2, take=0) for n in range(40)]
    assert casts[7] == teacher.cast_for("q7", "classroom", 2, take=0), "a render of the same take draws the same class"
    assert len({c["teacher"]["model"] for c in casts}) > 1, "the teacher changes"
    assert len({c["s1"]["name"] for c in casts}) > 3, "and so does the student who answers"
    for c in casts:
        assert set(c) == {"teacher", "s1", "s2"} and c["s1"]["model"] != c["s2"]["model"]
        assert c["s1"]["model"].startswith("student_") and (whiteboard_teachers() / f"{c['teacher']['model']}.glb").exists()
        older = next(t for t in teacher.TEACHERS if t["model"] == c["teacher"]["model"])["older"]
        assert c["teacher"]["voice"].endswith("|-6Hz|-7%") == older, "an older teacher speaks lower and slower"
        assert "|+" in c["s1"]["voice"] or c["s1"]["voice"] == "en-US-AnaNeural", "a young voice answers"
    names = {n for s in teacher.STUDENTS for n in s["names"]}
    assert {"Juma", "Kamau", "Nekesa", "Wanjiku"} <= names


def whiteboard_teachers() -> Path:
    from app.services import whiteboard

    return whiteboard.STATIC / "teachers"


def test_the_teacher_asks_the_student_answers_and_the_viewer_is_asked_about_the_student() -> None:
    cast = teacher.cast_for("q1")
    name = cast["s1"]["name"]
    scenes = social.script(DATA, {"question_id": "q1"}, _brand(teacher="classroom"))["scenes"]
    who = {s["scene"]: s["speaker"] for s in scenes}
    assert who["title"] == "teacher" and who["step"] == "s1" and who["answer"] == "s1" and who["outro"] == "teacher"
    step = next(s for s in scenes if s["scene"] == "step")
    assert step["voice"] == cast["s1"]["voice"] and step["caption"].startswith(f"{name}: ")
    check = next(s for s in scenes if s["scene"] == "check")
    assert check["say"] == f"Did {name} get it right? Tell us in the comments!"
    assert all(s["voice"] == cast["teacher"]["voice"] for s in scenes if s["speaker"] == "teacher")


def test_the_figure_is_on_the_board_before_the_pause() -> None:
    data = {"question_id": "q1", "scenes": [{"scene": "title", "say": "Find x."}, {"scene": "figure", "say": "", "svg": "<svg/>"},
                                            {"scene": "step", "say": "Add."}]}
    kinds = [s["scene"] for s in social.script(data, {}, _brand())["scenes"]]
    assert kinds.index("figure") < kinds.index("countdown") < kinds.index("step")


def test_the_classroom_frame_carries_every_actor_and_the_page_loads_each_model() -> None:
    from app.services import whiteboard

    frame = social._teacher_frame({"question_id": "q1"}, {**_brand(teacher="classroom"), "students": 2})["teacher"]
    assert frame["mode"] == "classroom" and [c["id"] for c in frame["cast"]] == ["teacher", "s1", "s2"]
    page = whiteboard.page(DATA, render=True, social={"hook": "x", "teacher": {**frame, "mouth": [], "fps": 30}})
    assert "window.TEACHER_GLBS" in page
    for c in frame["cast"]:
        assert f'"{c["id"]}"' in page


def test_a_voice_can_carry_its_pitch_and_pace(monkeypatch) -> None:
    import importlib
    import sys
    import types

    tts_service = importlib.import_module("app.services.math_engine.tts_service")

    got = {}

    class Communicate:
        def __init__(self, text, voice, rate, pitch):
            got.update(voice=voice, rate=rate, pitch=pitch)

        async def stream(self):
            yield {"type": "audio", "data": b"x" * 64}

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=Communicate))
    monkeypatch.setattr(tts_service, "_point_edge_at_current_host", lambda: None)
    monkeypatch.setattr(tts_service, "_rate", lambda: "+0%")
    tts_service.TtsService()._edge("Hello", "en-KE-ChilembaNeural|+45Hz|+7%")
    assert got == {"voice": "en-KE-ChilembaNeural", "rate": "+7%", "pitch": "+45Hz"}
    tts_service.TtsService()._edge("Hello", "en-KE-AsiliaNeural")
    assert got == {"voice": "en-KE-AsiliaNeural", "rate": "+0%", "pitch": "+0Hz"}


def test_a_figure_question_shows_its_figure_on_the_cover_and_beside_the_working(monkeypatch) -> None:
    from app.services import whiteboard

    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><line x1="0" y1="0" x2="10" y2="10"/></svg>'
    monkeypatch.setattr(whiteboard, "figure_scene", lambda q: {"scene": "figure", "svg": svg, "title": "", "say": ""})
    q = {"question_id": "q1", "question_text": "Find x.", "diagram": {"diagram_id": "d1"}}
    cover = social.cover_for(q, _brand())
    assert cover["figure"].startswith("data:image/svg+xml;base64,")
    assert social.cover_for({**q, "diagram": None}, _brand())["figure"] == ""
    page = whiteboard.page({"question_id": "q1", "scenes": [{"scene": "title", "say": "x"}, {"scene": "figure", "svg": svg, "say": ""}]},
                           render=True, social={"hook": "x", "cover": cover})
    assert 'id="sc-fig"' in page and "__onFigure" in page and "has-fig" in page
    assert "__coverReady" in (whiteboard.STATIC / "whiteboard.js").read_text()


def test_every_video_deals_its_own_cast_and_a_choice_narrows_it() -> None:
    counts = {len(teacher.cast_for(f"q{n}", "classroom", None, take=0)) - 1 for n in range(60)}
    assert counts == {0, 1, 2}, "no students, one or two — a different number from video to video"
    takes = {teacher.signature(teacher.cast_for("q1", "classroom", 2, take=k)) for k in range(8)}
    assert len(takes) > 4, "making it again deals a new cast"
    older = {teacher.cast_for(f"q{n}", "teacher_older_m", 0, take=0)["teacher"]["model"] for n in range(10)}
    assert older == {"teacher_older_m"}
    women = {teacher.cast_for(f"q{n}", "female", 1, take=0)["teacher"]["gender"] for n in range(20)}
    assert women == {"female"}
    alone = teacher.cast_for("q1", "male_young", 0, take=0)
    assert set(alone) == {"teacher"} and alone["teacher"]["x"] == 0.0, "alone, the teacher stands in the middle"


def test_a_new_cast_is_a_new_video(monkeypatch) -> None:
    from app.services import whiteboard

    monkeypatch.setattr(whiteboard, "cache_key", lambda data, voice, fps=30: "board")
    one = {**_brand(teacher="classroom"), "cast": teacher.cast_for("q1", "classroom", 2, take=0)}
    two = {**_brand(teacher="classroom"), "cast": teacher.cast_for("q1", "classroom", 2, take=3)}
    assert social.cache_key(DATA, "v", one, "female") != social.cache_key(DATA, "v", two, "female")


@pytest.mark.skipif(not __import__("os").getenv("CBC_TEST_PHASE2_DATABASE_URL"), reason="needs an empty Postgres")
def test_a_choice_made_in_play_is_kept_and_each_make_again_is_a_new_take(monkeypatch) -> None:
    import os

    from sqlalchemy import create_engine, text

    from app.infra import db as infra
    from app.services import platform_settings

    engine = create_engine(os.environ["CBC_TEST_PHASE2_DATABASE_URL"])
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    monkeypatch.setattr(infra, "get_engine", lambda: engine)
    monkeypatch.setattr(platform_settings, "_load", lambda: {})
    infra.run_migrations()
    try:
        assert teacher.choice("q1") == {"take": 0, "teacher": "", "students": None}
        first = teacher.cast_for("q1", "classroom", 2)
        teacher.choose("q1", teacher="teacher_older_f", students=1)
        assert teacher.choice("q1") == {"take": 1, "teacher": "teacher_older_f", "students": 1}
        assert teacher.signature(teacher.cast_for("q1", "classroom", 2)) != teacher.signature(first)
        with pytest.raises(ValueError):
            teacher.choose("q1", students=5)
    finally:
        engine.dispose()
