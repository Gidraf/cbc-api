from unittest import mock

from app.services import play_engine as P
from app.services import social as S
from app.services import whiteboard as W

Q = {"question_id": "q1", "question_text": "A diver at $-18$ m rises 12 m, drops 5 m, then rises 8 m. Where is she?",
     "expression": "-18 + 12 - 5 + 8",
     "curriculum": {"grade": "grade-9", "subject": "Mathematics", "sub_strand": "Integers"},
     "options": [{"id": "A", "text": "$-3$ m", "is_correct": True, "distractor_rationale": "Each move in turn."},
                 {"id": "B", "text": "$3$ m", "distractor_rationale": "Ignores the minus."}]}
BRAND = {"name": "Mwalimu Maths", "handle": "@mwalimumaths", "website": "cbc.gidraf.dev",
         "cta": "Follow for a new question every day", "countdown": 5, "hashtags": "#MathsWithMwalimu",
         "logo_url": "", "music_url": ""}


def test_the_cut_hooks_counts_down_solves_and_signs_off():
    s = S.script(P.walkthrough(Q), Q, BRAND)
    kinds = [x["scene"] for x in s["scenes"]]
    assert kinds[:2] == ["title", "countdown"] and kinds[-2:] == ["answer", "outro"]
    assert "trap" not in kinds and "setup" not in kinds          # short: no wrong options, no restating
    assert s["scenes"][0]["say"].startswith("Can you solve this?")
    assert s["scenes"][1]["hold"] == 5 and s["scenes"][1]["say"] == ""
    assert s["scenes"][-2]["say"] == "So the answer is A: negative 3 metres."
    assert "at mwalimumaths" in s["scenes"][-1]["say"] and s["scenes"][-1]["handle"] == "@mwalimumaths"


def test_the_post_is_the_question_and_the_working():
    post = S.post_text(Q, P.walkthrough(Q), BRAND)
    assert post.startswith("🧮 Can you solve this? (Grade 9 · Mathematics · Integers)")
    assert "A diver at -18 m rises 12 m" in post and "A) -3 m" in post and "B) 3 m" in post
    assert "⏸️ Pause and try" in post and "✅ Answer: A) -3 m" in post
    assert "2. Start at -18 on the number line." in post and "+12: move 12 right to -6." in post
    assert "Why: Each move in turn." in post and "@mwalimumaths" in post and "cbc.gidraf.dev" in post
    assert "#Grade9Maths" in post and "#KJSEA" in post and "#Integers" in post and "#MathsWithMwalimu" in post


def test_the_post_shows_maths_as_a_phone_does():
    assert S.display(r"Work out $\frac{3}{4} \times 8 \div 2$ at $45^\circ$") == "Work out 3/4 × 8 ÷ 2 at 45°"


def test_a_handle_is_said_as_a_person_says_it():
    assert S.spoken_handle("@cbc_maths") == "at cbc maths"
    assert S.spoken_handle("@KCSE.revision") == "at K C S E dot revision"


def test_a_new_brand_is_a_new_video():
    s = S.script(P.walkthrough(Q), Q, BRAND)
    assert S.cache_key(s, "v", BRAND) != S.cache_key(s, "v", {**BRAND, "music_url": "http://m/x.mp3"})


def test_the_frame_carries_the_hook_brand_and_board():
    payload = {"hook": "Can you solve this?", "tag": "Grade 9 · Integers", "brand": "Mwalimu <Maths>",
               "handle": "@m", "website": "w.dev", "countdown": 5, "logo": None, "music_url": ""}
    doc = W.page(S.script(P.walkthrough(Q), Q, BRAND), social=payload, render=True)
    assert 'class="social render"' in doc and 'id="sc-caption"' in doc and 'id="wb"' in doc
    assert "Mwalimu &lt;Maths&gt;" in doc and '"social": {"hook"' in doc and "music_url" not in doc


def test_ticks_and_music_are_mixed_under_the_voice(tmp_path):
    a, t, m = tmp_path / "a.mp3", tmp_path / "t.wav", tmp_path / "m.mp3"
    for f in (a, t, m):
        f.write_bytes(b"x")
    with mock.patch("subprocess.run") as run:
        run.return_value.returncode = 0
        W._mux("ffmpeg", tmp_path / "v.mp4", [(a, 2.0)], [0.3], 20.0, tmp_path / "o.mp4",
               extras=[(t, 5.0), (t, 6.0)], music=m)
    args = run.call_args[0][0]
    graph = args[args.index("-filter_complex") + 1]
    assert "adelay=5000|5000" in graph and "adelay=6000|6000" in graph
    assert "volume=0.10" in graph and "amix=inputs=4" in graph and "-stream_loop" in args


def test_the_countdown_is_silent_and_exactly_as_long_as_set(tmp_path):
    scenes = [{"scene": "title", "say": "Hi."}, {"scene": "countdown", "hold": 5, "say": ""}]
    with mock.patch.object(W, "speak_all", return_value=[(b"x", 1.5), (None, 2.4)]):
        got = W.narrate(scenes, "v", tmp_path)
    assert got[1] == (None, 5.0) and got[0][1] == 1.5


def test_social_is_a_queue_kind():
    import app.routes.curriculum  # noqa: F401
    from app.services import job_queue

    assert "social" in job_queue.known_kinds()
