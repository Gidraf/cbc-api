"""Photo + video series: a question in steps through the day."""
from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone

import pytest

from app.services import social_export as X

DB = os.getenv("CBC_TEST_PHASE2_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB, reason="set CBC_TEST_PHASE2_DATABASE_URL to an empty Postgres database")
EAT = timezone(timedelta(hours=3))


def test_eight_photos_and_eight_videos_make_two_full_series_and_six_videos():
    shape = X.series_shape(8, 8)
    assert shape.count(X.SERIES_FULL) == 2 and shape.count(X.SERIES_SHORT) == 0      # 4 cards each: 8 = two series
    assert shape.count(("walkthrough",)) == 6
    assert sum(len(r) for r in shape) == 16
    assert X.series_shape(6, 2).count(X.SERIES_SHORT) == 1, "the 2 cards left make a short series"
    photos = sum(1 for r in shape for s in r if s != "walkthrough")
    assert photos == 8
    assert X.series_shape(0, 4) == [("walkthrough",)] * 4
    assert X.series_shape(3, 0) == []                     # a card series always ends with its video


def test_a_series_keeps_its_order_through_the_day():
    rng = random.Random(7)
    runs = [[("a", s) for s in X.SERIES_FULL], [("b", s) for s in X.SERIES_SHORT]] + [[(f"v{i}", "walkthrough")] for i in range(5)]
    for seed in range(20):
        day = X.interleave(random.Random(seed), runs)
        assert len(day) == len(X.SERIES_FULL) + len(X.SERIES_SHORT) + 5
        for q, steps in (("a", X.SERIES_FULL), ("b", X.SERIES_SHORT)):
            assert [s for qq, s in day if qq == q] == list(steps)
    orders = {tuple(X.interleave(random.Random(s), runs)) for s in range(10)}
    assert len(orders) > 1, "random, not the same day every day"
    del rng


def _rules(**kw):
    base = {"enabled": True, "hours": {"start": "06:00", "end": "22:00"}, "daily_cap": 30, "min_gap_minutes": 55,
            "platform_cap": 16, "platforms": ["facebook"], "group_shares_per_day": 0, "photos_per_day": 8,
            "videos_per_day": 8}
    base.update(kw)
    return base


def test_photos_and_videos_have_their_own_daily_caps():
    now = datetime(2026, 10, 20, 12, 0, tzinfo=EAT)
    eight_photos = [{"platform": "facebook", "format": "photo"}] * 8
    photo = {"post_id": "p", "platform": "facebook", "format": "photo"}
    video = {"post_id": "v", "platform": "facebook", "format": "video"}
    chosen, why = X.decide(now, _rules(), posted_today=eight_photos, last_posted_at=None, candidates=[photo, video],
                           logged_out=set(), live_today=eight_photos)
    assert chosen is video                                   # photos are done for today; videos are not
    chosen, why = X.decide(now, _rules(), posted_today=eight_photos, last_posted_at=None, candidates=[photo],
                           logged_out=set(), live_today=eight_photos)
    assert chosen is None and "8 photos" in why


def test_a_card_is_never_handed_to_facebooks_scheduler():
    now = datetime(2026, 10, 20, 8, 0, tzinfo=EAT)
    later = now + timedelta(days=3)
    rows = [{"post_id": "p", "platform": "facebook", "format": "photo", "scheduled_for": later},
            {"post_id": "v", "platform": "facebook", "format": "video", "scheduled_for": later}]
    out = X.work_order(now, _rules(ahead_platforms=["facebook"], ahead_days=28), rows)
    assert [r["post_id"] for r in out] == ["v"]


@pytest.fixture()
def db(monkeypatch):
    from sqlalchemy import create_engine, text

    from app.infra import db as infra
    from app.services import platform_settings

    engine = create_engine(DB)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    monkeypatch.setattr(infra, "get_engine", lambda: engine)
    monkeypatch.setattr(platform_settings, "_load", lambda: {"poster_enabled": True, "poster_min_gap_minutes": 55})
    infra.run_migrations()
    yield engine
    engine.dispose()


@needs_db
def test_a_week_of_series_is_booked_in_order(db, monkeypatch):
    import json

    from sqlalchemy import text

    from app.services import social, social_cards

    with db.begin() as c:
        for i in range(60):
            content = {"question_text": f"{i} + 1?", "correct_answer": str(i + 1), "question_type": "short_answer"}
            if i % 3 == 0:
                content["diagram"] = {"diagram_id": f"d{i}"}
            c.execute(text("""INSERT INTO question_dna (question_id, universal_id, curriculum_link, pedagogical_dna, content,
                              provenance, review_audit, status, created_at, updated_at, grade_ordinal, version, display_label)
                              VALUES (:id, :id, CAST(:cl AS jsonb), '{}', CAST(:ct AS jsonb), '{}', '{}', 'approved',
                                      NOW(), NOW(), 11, 1, :id)"""),
                      {"id": f"q{i:02d}", "cl": json.dumps({"grade": "grade-9", "subject": "Mathematics"}), "ct": json.dumps(content)})
    monkeypatch.setattr(social, "status", lambda qid, q=None, voice="": {"status": "ready", "scenes": 5, "url": "u"})
    cards, videos = [], []
    monkeypatch.setattr(social_cards, "enqueue", lambda qid, queued_by="": cards.append(qid) or {"status": "queued"})
    monkeypatch.setattr(social, "enqueue", lambda qid, queued_by="", **k: videos.append(qid) or {"status": "queued"})
    out = X.book_series("Grade 9", "Mathematics", days=3, seed=1, created_by="gidraf")
    assert out["booked"] and len(out["days"]) == 3
    assert out["photos"] == 24 and out["videos"] == 24 and out["questions"] == 3 * 8
    with db.connect() as c:         # closed, so the next test can reset the schema
        rows = c.execute(text("SELECT question_id, format, step, scheduled_for FROM social_posts ORDER BY scheduled_for")).mappings().all()
    assert len(rows) == 48
    for qid in {r["question_id"] for r in rows if r["format"] == "photo"}:
        steps = [r["step"] for r in rows if r["question_id"] == qid]
        assert steps in (list(X.SERIES_FULL), list(X.SERIES_SHORT)), steps
    gaps = [(b["scheduled_for"] - a["scheduled_for"]).total_seconds() / 60 for a, b in zip(rows, rows[1:])
            if a["scheduled_for"].date() == b["scheduled_for"].date()]
    assert min(gaps) >= 55
    series_qs = {r["question_id"] for r in rows if r["format"] == "photo"}
    assert set(cards) == series_qs and not videos               # videos were ready; cards queued for series only
    first_series = [r["question_id"] for r in rows if r["step"] in ("teaser", "question")][:2]
    assert all(int(q[1:]) % 3 == 0 for q in first_series), "questions with a figure go first"
    again = X.book_series("Grade 9", "Mathematics", days=1, seed=2)
    assert again["first_day"] > out["last_day"]                  # tops up after the last booked day


@needs_db
def test_the_poster_gets_the_card_and_its_caption(db, monkeypatch):
    from sqlalchemy import text

    from app.services import social_cards, whiteboard

    q = {"question_id": "q1", "question_text": "What is -5 + 8?", "correct_answer": "3", "curriculum": {"grade": "grade-9"},
         "options": []}
    monkeypatch.setattr(whiteboard, "load", lambda qid: q)
    monkeypatch.setattr(social_cards, "status", lambda qid, step, qq=None: {"status": "ready", "url": f"https://x/{step}.jpg"})
    now = datetime.now(timezone.utc)
    with db.begin() as c:
        c.execute(text("""INSERT INTO social_posts (post_id, question_id, platform, scheduled_for, format, step)
                          VALUES ('p1', 'q1', 'facebook', :t, 'photo', 'answer')"""), {"t": now - timedelta(minutes=1)})
    post = X.next_for_poster(dry=True, platform="facebook")["post"]
    assert post["format"] == "photo" and post["step"] == "answer" and post["image_url"] == "https://x/answer.jpg"
    assert post["video_url"] == "" and post["groups"] == [] and post["schedule_at"] == ""
    assert "The answer: 3" in post["caption"] and "walkthrough video is coming next" in post["caption"]


def test_captions_tease_ask_then_answer(monkeypatch):
    q = {"question_id": "q1", "question_text": "What is $-5 + 8$?", "correct_answer": "3", "options": [],
         "curriculum": {"grade": "grade-9", "subject": "Mathematics", "sub_strand": "Integers"}}
    b = {"hook": "Can you solve this?", "cta": "Follow", "handle": "", "website": "", "hashtags": ""}
    from app.services import social_cards

    monkeypatch.setattr(social_cards, "_working", lambda qq, limit=3: ["Start at -5.", "Move 8 to the right."])
    teaser, ask, answer = (social_cards.caption(q, s, b) for s in social_cards.STEPS)
    assert "Can you solve this?" in teaser and "-5 + 8" not in teaser          # no question yet
    assert "-5 + 8" in ask and "3" not in ask.split("Drop")[0].replace("-5 + 8", "")
    assert "The answer: 3" in answer and "Move 8 to the right." in answer


@needs_db
def test_the_photo_schedule_shows_each_post_with_its_card(db, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    from app.main import app
    from app.routes import play
    from app.services import social_cards
    from app.services.auth import AuthContext, get_auth_context

    monkeypatch.setattr(play, "_one", lambda qid, owner="": {"question_id": qid, "question_text": "2+2?"})
    monkeypatch.setattr(social_cards, "status", lambda qid, step, q=None: {"status": "ready", "url": f"https://x/{qid}-{step}.jpg"}
                        if step != "answer" else {"status": "none"})
    now = datetime.now(timezone.utc)
    with db.begin() as c:
        for pid, step, at, posted in (("p1", "teaser", now + timedelta(hours=1), None), ("p2", "answer", now + timedelta(hours=3), None),
                                      ("p3", "question", now - timedelta(hours=5), now - timedelta(hours=5)),
                                      ("v1", "walkthrough", now + timedelta(hours=4), None)):
            c.execute(text("""INSERT INTO social_posts (post_id, question_id, platform, scheduled_for, posted_at, format, step)
                              VALUES (:p, 'q1', 'facebook', :t, :posted, :f, :s)"""),
                      {"p": pid, "t": at, "posted": posted, "f": "video" if step == "walkthrough" else "photo", "s": step})
    app.dependency_overrides[get_auth_context] = lambda: AuthContext("gidraf", "admin", "bearer")
    try:
        out = TestClient(app).get("/api/v1/play/social/photo-posts").json()
    finally:
        app.dependency_overrides.pop(get_auth_context, None)
    assert [p["post_id"] for p in out["posts"]] == ["p3", "p1", "p2"]           # photos only, in time order
    assert out["upcoming"] == 2 and out["posted"] == 1 and out["cards_missing"] == 1
    p1 = next(p for p in out["posts"] if p["post_id"] == "p1")
    assert p1["card_url"] == "https://x/q1-teaser.jpg" and p1["card_status"] == "ready"


def test_the_card_library_says_what_is_made(monkeypatch):
    from fastapi.testclient import TestClient

    from app.infra import db
    from app.main import app
    from app.routes import play
    from app.services import social_cards
    from app.services.auth import AuthContext, get_auth_context

    monkeypatch.setattr(play, "_bank", lambda g, s, ss, limit: [{"question_id": "q1", "question_text": "A?", "curriculum": {}},
                                                               {"question_id": "q2", "question_text": "B?", "curriculum": {},
                                                                "diagram": {"diagram_id": "d"}}])
    monkeypatch.setattr(db, "fetch_all", lambda sql, p=None: [{"q": "q2"}])          # q2's cards are being made
    monkeypatch.setattr(social_cards, "status", lambda qid, step, q=None: {"status": "ready", "url": f"u/{step}"} if qid == "q1" else {"status": "none"})
    app.dependency_overrides[get_auth_context] = lambda: AuthContext("gidraf", "admin", "bearer")
    try:
        out = TestClient(app).get("/api/v1/play/social/cards", params={"grade": "grade-9", "subject": "Mathematics"}).json()
    finally:
        app.dependency_overrides.pop(get_auth_context, None)
    rows = {r["question_id"]: r for r in out["items"]}
    assert rows["q1"]["status"] == "ready" and rows["q1"]["cards"]["answer"]["url"] == "u/answer"
    assert rows["q2"]["status"] == "making" and rows["q2"]["has_figure"] and out["ready"] == 1


def test_post_now_for_one_booked_post_carries_its_id(monkeypatch):
    import asyncio
    import importlib
    import sys

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2] / "poster"))
    try:
        main = importlib.import_module("poster.__main__")
    except Exception as exc:  # noqa: BLE001 — the poster needs playwright; skip where it is not installed
        pytest.skip(f"poster not importable here: {exc}")
    asked = {}

    async def next_post(**kw):
        asked.update(kw)
        return {"post": {"post_id": "p9", "platform": "facebook", "format": "photo"}}

    async def publish(post, dry_run):
        return {"ok": True, "post_id": post["post_id"], "dry_run": dry_run}

    monkeypatch.setattr(main.cbc, "next_post", next_post)
    monkeypatch.setattr(main, "publish", publish)
    out = asyncio.run(main.run("run_now", "facebook", "p9", None))
    assert out == {"ok": True, "post_id": "p9", "dry_run": False} and asked["post_id"] == "p9" and asked["dry"] is True
