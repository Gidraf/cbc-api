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


def test_edge_speaks_through_the_host_microsoft_still_answers():
    import importlib

    import edge_tts.communicate as communicate
    import edge_tts.constants as constants

    T = importlib.import_module("app.services.math_engine.tts_service")
    legacy = f"wss://{constants.BASE_URL}/edge/v1?TrustedClientToken={constants.TRUSTED_CLIENT_TOKEN}"
    with mock.patch.object(communicate, "WSS_URL", legacy), mock.patch.object(constants, "WSS_URL", legacy):
        T._point_edge_at_current_host()
        assert communicate.WSS_URL.startswith("wss://api.msedgeservices.com/")
        assert constants.TRUSTED_CLIENT_TOKEN in communicate.WSS_URL


def test_the_console_chooses_the_voice_and_its_pace():
    import importlib

    T = importlib.import_module("app.services.math_engine.tts_service")
    chosen = {"narration_voice": "en-US-AvaMultilingualNeural", "narration_rate": "-10"}
    with mock.patch("app.services.platform_settings.get", side_effect=lambda k, d=None: chosen.get(k, d)):
        assert T.voice_for("Mathematics") == "en-US-AvaMultilingualNeural"
        assert T.voice_for("Kiswahili") == "sw-KE-ZuriNeural"     # a Kiswahili lesson keeps a Kiswahili voice
        assert T._rate() == "-10%"
    with mock.patch("app.services.platform_settings.get", side_effect=lambda k, d=None: {"narration_rate": "fast"}.get(k, d)):
        assert T._rate() == "+0%"


def _png(w, h):
    import struct
    import zlib

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    raw = b"".join(b"\x00" + b"\x00\x00\x00\x00" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_a_hand_photo_is_inlined_with_its_pen_tip():
    import base64

    png = _png(40, 60)
    assert W.png_size(png) == (40, 60) and W.png_size(b"GIF89a" + b"0" * 30) is None
    vals = {"whiteboard_hand_image": "data:image/png;base64," + base64.b64encode(png).decode(),
            "whiteboard_hand_tip": "8,12", "whiteboard_hand_width": 250}
    W._hand_bytes.cache_clear()
    with mock.patch("app.services.platform_settings.get", side_effect=lambda k, d=None: vals.get(k, d)):
        doc = W.page(P.walkthrough(DIVER), render=True)
        photo_key = W.cache_key(P.walkthrough(DIVER), "v")
    assert '"hand": {"src": "data:image/png;base64,' in doc and '"tip_x": 8.0' in doc and '"width": 250' in doc
    with mock.patch("app.services.platform_settings.get", side_effect=lambda k, d=None: d):
        # No photo: the ✍🏿 emoji, its pen's tip where the artwork has it.
        assert '"src": "data:image/svg+xml;base64,' in W.page(P.walkthrough(DIVER), render=True)
        assert W.cache_key(P.walkthrough(DIVER), "v") != photo_key          # a new hand is a new video
    drawn = {"whiteboard_hand_style": "drawn"}
    with mock.patch("app.services.platform_settings.get", side_effect=lambda k, d=None: drawn.get(k, d)):
        assert '"hand"' not in W.page(P.walkthrough(DIVER), render=True)    # the drawn hand


def test_the_console_hears_the_servers_voice_not_the_devices():
    clips = [(b"ID3voice", 2.5)] * len(P.walkthrough(DIVER)["scenes"])
    with mock.patch.object(W, "speak_all", return_value=clips):
        doc = W.live_page(P.walkthrough(DIVER), title="Diver", voice="en-KE-AsiliaNeural")
    assert '"audio": ["data:audio/mpeg;base64,' in doc and '"durations": [2.5' in doc
    assert '"voice": "en-KE"' in doc


def test_a_sentence_is_spoken_once():
    calls = []

    def speak_bytes(self, text, voice=""):
        calls.append(text)
        return b"x" * 12000

    with mock.patch("app.services.math_engine.tts_service.TtsService.speak_bytes", speak_bytes), \
         mock.patch("app.infra.storage.object_storage.object_exists", return_value=False), \
         mock.patch("app.infra.storage.object_storage.save_bytes", return_value="u") as saved, \
         mock.patch.object(W, "_probe_seconds", return_value=2.0):
        W._SPOKEN.clear()
        assert W.speak("Hello class.", "en-KE-AsiliaNeural") == (b"x" * 12000, 2.0)
        assert W.speak("Hello class.", "en-KE-AsiliaNeural")[1] == 2.0
    assert len(calls) == 1 and saved.call_args[0][0].startswith("narration/")


def test_a_second_unknown_never_takes_a_topic_down():
    q = {"question_text": "Find k if the line $y = kx + 3$ passes through $(2, 7)$.", "expression": "2k + 3 = kx + 7"}
    assert P.spec_for(q) is not None and P.walkthrough(q)["scenes"]


def test_every_walkthrough_shows_working_before_the_answer():
    q = {"question_text": r"Simplify $\frac{p^7 \times p^4}{p^6}$.",
         "model_answer": r"Product rule: $p^7 \times p^4 = p^{11}$. Quotient rule: $p^{11} \div p^6 = p^5$. Option B is correct.",
         "options": [{"id": "A", "text": "$p^{17}$"}, {"id": "B", "text": "$p^5$", "is_correct": True}]}
    scenes = P.walkthrough(q)["scenes"]
    kinds = [s["scene"] for s in scenes]
    assert kinds[:3] == ["title", "working", "working"] and "answer" in kinds
    assert all("Option B" not in s.get("text", "") for s in scenes)
    page = W.page(P.walkthrough(q), render=True)
    assert "\\\\frac" not in page.split("window.WB_DATA = ", 1)[1].split(";</script>", 1)[0]   # the board writes p¹¹, not \\frac


def test_only_admins_and_named_makers_make_videos():
    from app.errors import ApiError
    from app.routes.play import _may_make_videos
    from app.services.auth import AuthContext

    with mock.patch("app.services.platform_settings.get", side_effect=lambda k, d=None: ["gidraf"] if k == "video_makers" else d):
        _may_make_videos(AuthContext(subject="gidraf", role="user", auth_type="session"))
        _may_make_videos(AuthContext(subject="someone", role="admin", auth_type="session"))
        import pytest
        with pytest.raises(ApiError):
            _may_make_videos(AuthContext(subject="someone", role="operator", auth_type="session"))


def test_files_are_linked_at_the_domain_not_the_ip():
    from app.infra import storage
    from app.settings import settings

    with mock.patch.object(settings, "minio_public_base_url", "http://5.78.137.59:6500"), \
         mock.patch("app.services.platform_settings.get", side_effect=lambda k, d=None: "https://cbc.gidraf.dev" if k == "public_base_url" else d):
        assert storage.public_object_url("videos/q/k.mp4") == f"https://cbc.gidraf.dev/api/v1/assets/{settings.minio_bucket}/videos/q/k.mp4"
        assert storage.legacy_asset_base() == f"http://5.78.137.59:6500/{settings.minio_bucket}"
