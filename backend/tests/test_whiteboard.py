import re
from pathlib import Path
from unittest import mock

from app.services import play_engine as P
from app.services import whiteboard as W

DIVER = {"question_id": "q1", "question_text": "A diver at $-18$ m rises 12 m, drops 5 m, rises 8 m. Where is she?",
         "expression": "-18 + 12 - 5 + 8", "curriculum": {"grade": "Grade 7", "subject": "Mathematics"},
         "options": [{"id": "A", "text": "$-3$ m", "is_correct": True, "distractor_rationale": "Each move is added."},
                     {"id": "B", "text": "$3$ m", "distractor_rationale": "Ignores the minus on the start."}]}


def test_the_board_draws_every_scene_the_engine_writes():
    # A scene the board has no builder for is a silent gap in the video.
    engine = (W.STATIC / "whiteboard.js").read_text()
    builders = set(re.findall(r"^    (\w+)\(s, at, dur\) \{", engine, re.M))
    source = Path(P.__file__).read_text()
    scenes = set(re.findall(r'"scene": "(\w+)"', source))
    assert scenes and scenes <= builders, scenes - builders


def test_the_page_is_self_contained():
    data = P.walkthrough(DIVER)
    live = W.page(data, title="Diver", voice="en-KE")
    assert "<script src=" not in live           # GSAP inlined: works offline, renders headless
    assert "gsap" in live and "window.WB_DATA" in live and "__wb.toggle()" in live
    assert "</script" not in live.split("window.WB_DATA = ", 1)[1].split(";</script>", 1)[0]
    render = W.page(data, render=True, durations=[2.0] * len(data["scenes"]))
    assert 'class="render"' in render and "__wb.toggle()" not in render
    assert '"durations": [2.0' in render


def test_a_changed_item_is_a_new_video():
    a = P.walkthrough(DIVER)
    b = P.walkthrough({**DIVER, "expression": "-18 + 12 - 5 + 9"})
    assert W.cache_key(a, "v") == W.cache_key(a, "v")
    assert W.cache_key(a, "v") != W.cache_key(b, "v") != W.cache_key(a, "other")


def test_voices_start_where_the_board_starts_each_scene():
    # Mirrors whiteboard.js: 0.3 s lead-in, then each scene plus a 0.4 s gap.
    assert [round(t, 6) for t in W._starts([2.0, 3.0, 1.5])] == [0.3, 2.7, 6.1]


def test_the_voice_is_laid_where_each_scene_begins(tmp_path):
    a, b = tmp_path / "a.mp3", tmp_path / "b.mp3"
    a.write_bytes(b"x"), b.write_bytes(b"x")
    with mock.patch("subprocess.run") as run:
        run.return_value.returncode = 0
        W._mux("ffmpeg", tmp_path / "v.mp4", [(a, 2.0), (None, 1.0), (b, 3.0)], [0.3, 2.7, 4.1], 9.5,
               tmp_path / "out.mp4")
    args = run.call_args[0][0]
    graph = args[args.index("-filter_complex") + 1]
    assert "adelay=300|300" in graph and "adelay=4100|4100" in graph and "amix=inputs=2" in graph
    assert args[args.index("-t") + 1] == "9.50"


def test_a_ready_video_is_not_made_twice():
    with mock.patch.object(W, "load", return_value=DIVER), \
         mock.patch("app.infra.storage.object_storage.object_exists", return_value=True), \
         mock.patch("app.services.job_queue.enqueue") as enqueue:
        got = W.enqueue("q1")
    assert got["status"] == "ready" and got["url"].endswith(".mp4") and not enqueue.called


def test_an_item_is_queued_once_per_question():
    job = mock.Mock(job_id="job_1")
    with mock.patch.object(W, "load", return_value=DIVER), \
         mock.patch("app.infra.storage.object_storage.object_exists", return_value=False), \
         mock.patch("app.infra.db.fetch_one", return_value=None), \
         mock.patch("app.services.job_queue.start_worker"), \
         mock.patch("app.services.job_queue.enqueue", return_value=job) as enqueue:
        got = W.enqueue("q1", queued_by="t")
    assert got == {**got, "status": "queued", "job_id": "job_1"}
    kind, grade, subject, payload = enqueue.call_args[0]
    assert (kind, grade, subject) == ("video", "Grade 7", "Mathematics")
    assert payload["artifact_id"] == "q1"


def test_the_job_renders_and_reports_the_url():
    with mock.patch.object(W, "load", return_value=DIVER), \
         mock.patch.object(W, "render", return_value={"url": "http://m/v.mp4", "seconds": 30.0, "key": "k",
                                                      "cached": False}) as render:
        got = W.run_job({"payload": {"question_id": "q1"}})
    assert got["status"] == "done" and got["url"] == "http://m/v.mp4"
    assert render.call_args.kwargs["voice"].startswith("en-")


def test_rendering_says_what_is_missing():
    import pytest

    with mock.patch.object(W, "ffmpeg_binary", return_value=None), pytest.raises(RuntimeError, match="ffmpeg"):
        W.render(P.walkthrough(DIVER))


def test_video_is_a_queue_kind():
    import app.routes.curriculum  # noqa: F401  registers the handlers
    from app.services import job_queue

    assert "video" in job_queue.known_kinds()
