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


def test_eight_photos_and_eight_videos_make_two_full_series_a_short_one_and_five_videos():
    shape = X.series_shape(8, 8)
    assert shape.count(X.SERIES_FULL) == 2 and shape.count(X.SERIES_SHORT) == 1
    assert shape.count(("walkthrough",)) == 5
    assert sum(len(r) for r in shape) == 16
    photos = sum(1 for r in shape for s in r if s != "walkthrough")
    assert photos == 8
    assert X.series_shape(0, 4) == [("walkthrough",)] * 4
    assert X.series_shape(3, 0) == []                     # a card series always ends with its video


def test_a_series_keeps_its_order_through_the_day():
    rng = random.Random(7)
    runs = [[("a", s) for s in X.SERIES_FULL], [("b", s) for s in X.SERIES_SHORT]] + [[(f"v{i}", "walkthrough")] for i in range(5)]
    for seed in range(20):
        day = X.interleave(random.Random(seed), runs)
        assert len(day) == 12
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
    rows = db.connect().execute(text("SELECT question_id, format, step, scheduled_for FROM social_posts ORDER BY scheduled_for")).mappings().all()
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
