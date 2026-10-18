"""The comment campaign: every post to the floor, then the best performers to the target, until the views goal."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.services import social
from app.services import social_export as se

DB = os.getenv("CBC_TEST_PHASE2_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB, reason="needs an empty Postgres")
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)      # noon in Nairobi


def test_a_post_can_carry_up_to_150_comments_none_repeated_with_kicd_credited(monkeypatch) -> None:
    from app.services import social_cards

    q = {"question_id": "q1", "question_text": "What is 2 + 3?", "options": [{"id": "A", "text": "5", "is_correct": True}],
         "curriculum": {"grade": "grade-9", "subject": "Mathematics", "sub_strand": "Integers"}}
    monkeypatch.setattr(social, "_curriculum_row", lambda qq: {"sub_strand_name": "Integers", "source_pages": [12, 13],
                        "slos": ["add integers", "subtract integers"], "key_inquiry_questions": ["Why do we use integers?"],
                        "core_competencies": ["critical thinking"], "values": ["responsibility"]})
    others = [{"question_id": f"o{k}", "question_text": f"Practice question {k}?", "status": "approved",
               "options": [{"id": "A", "text": "1"}, {"id": "B", "text": str(k), "is_correct": True}]} for k in range(80)]
    monkeypatch.setattr(social, "_practice", lambda qq, limit=75: others[:limit])
    monkeypatch.setattr(social_cards, "status", lambda qid, step, qq=None: {"status": "ready", "url": f"https://x/{step}.jpg"})
    items = social.campaign_comments(q, {"scenes": []}, {**social.brand(), "website": "https://cbc.example"})
    texts = [i["text"] for i in items]
    assert len(items) == social.CAMPAIGN_MAX and len(set(texts)) == len(texts), "150, none repeated"
    assert any(i.get("image_url") == "https://x/answer.jpg" for i in items), "the answer as a picture"
    kicd = [t for t in texts if "Learning outcome" in t]
    assert kicd and "© Kenya Institute of Curriculum Development" in kicd[0] and social.KICD_DESIGNS in kicd[0]
    p1 = next(k for k, t in enumerate(texts) if t.startswith("🔁 Practice 1 "))
    assert texts.index(next(t for t in texts if t.startswith("✅ Practice 1 answer"))) > p1 + 1, "the answer a comment later"


@pytest.fixture()
def db(monkeypatch):
    from sqlalchemy import create_engine, text

    from app.infra import db as infra
    from app.services import platform_settings

    engine = create_engine(DB)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    monkeypatch.setattr(infra, "get_engine", lambda: engine)
    settings = {"campaign_enabled": True, "campaign_floor": 6, "campaign_target": 10, "campaign_views_goal": 1000,
                "campaign_focus_posts": 2, "campaign_per_post_day": 5, "campaign_daily_limit": 300,
                "campaign_share": False, "poster_platforms": ["facebook"]}
    monkeypatch.setattr(platform_settings, "_load", lambda: settings)
    infra.run_migrations()
    yield settings
    engine.dispose()


def _post(qid: str, posted: datetime, views: int) -> str:
    from app.infra.db import execute

    se._plan_post({"question_id": qid, "curriculum": {}}, "facebook", posted, "me")
    pid = se._post_id(qid, "facebook")
    se.record_attempt(pid, ok=True)
    execute("""UPDATE social_posts SET posted_at = :t, comments_state = 'done', views = :v WHERE post_id = :id""",
            {"t": posted, "v": views, "id": pid})
    return pid


@needs_db
def test_the_floor_first_then_the_best_performers_until_the_views_goal(db, monkeypatch) -> None:
    from app.infra.db import execute

    monkeypatch.setattr(se, "_campaign_items", lambda qid: [{"text": f"{qid} comment {k}"} for k in range(40)])
    monkeypatch.setattr(social, "status", lambda qid, q=None, **k: {"thread": {"find": qid}})
    old = _post("old", NOW - timedelta(days=3), 50)
    star = _post("star", NOW - timedelta(days=1), 900)
    done = _post("done", NOW - timedelta(days=1), 5000)
    step = 0

    def next_job() -> dict:
        nonlocal step
        step += 1
        return se.campaign_next(NOW + timedelta(minutes=5 * step))["job"]

    got = se.campaign_next(NOW + timedelta(minutes=1))
    assert got["job"], got["reason"]
    first = got["job"]
    assert first["post_id"] == old and first["phase"] == "floor" and first["comments"] == ["old comment 4"], \
        "the oldest post first, past its thread's four"
    # Bring every post to the floor (6 = the thread's 4 and 2 more).
    execute("UPDATE social_posts SET campaign_index = 2")
    job = next_job()
    assert job["post_id"] == star and job["phase"] == "focus", "then the post with the most views a day"
    assert all(next_job()["post_id"] != done for _ in range(3)), "never past the views goal"
    se.campaign_result(star, stage="campaign", ok=True, now=NOW + timedelta(minutes=30))
    execute("UPDATE social_posts SET views = 1500 WHERE post_id = :id", {"id": star})
    later = se.campaign_next(NOW + timedelta(hours=2))["job"]          # past the pace after the last comment
    assert later["post_id"] == old, "the goal reached: the next best takes its place"


@needs_db
def test_the_day_has_a_limit_and_a_pace(db) -> None:
    from app.infra.db import execute

    db["campaign_daily_limit"] = 2
    execute("INSERT INTO campaign_log (post_id, at, kind, ok) VALUES ('p', :t, 'comment', TRUE), ('p', :t, 'comment', TRUE)",
            {"t": NOW})
    assert "Today's 2" in se.campaign_next(NOW + timedelta(minutes=10))["reason"]
    db["campaign_daily_limit"] = 300
    assert "Pacing" in se.campaign_next(NOW + timedelta(seconds=20))["reason"]
    db["campaign_enabled"] = False
    assert "off" in se.campaign_next(NOW)["reason"]


@needs_db
def test_the_devices_screen_shows_each_mac_its_accounts_and_its_day(db) -> None:
    from app.infra.db import execute, to_json
    from app.routes import play

    execute("""INSERT INTO poster_heartbeat (poster_id, status, seen_at) VALUES ('mac-a', CAST(:s AS jsonb), NOW())""",
            {"s": to_json({"started": 2.0, "busy": "Commenting", "machine": {"host": "studio-mac"},
                           "logins": {"facebook": {"logged_in": True, "account": "CBC Maths", "note": ""},
                                      "linkedin": {"logged_in": False, "note": "Log in on the screen."}},
                           "today": {"day": "2026-10-19", "posts": 3, "comments": 40}})})
    execute("""INSERT INTO poster_heartbeat (poster_id, status, seen_at) VALUES ('mac-b', '{}'::jsonb, NOW() - INTERVAL '2 days')""")
    play.render_helper_status(play.HelperStatus(worker="mac-c", resting="outside 18:00–23:59", today={"made": 7},
                                                jobs=[], slots=2, manim=True), auth=None)
    d = play.devices(auth=None)
    a = next(p for p in d["posters"] if p["poster_id"] == "mac-a")
    assert a["online"] and a["logins"]["facebook"]["account"] == "CBC Maths" and not a["logins"]["linkedin"]["logged_in"]
    assert a["today"]["comments"] == 40 and set(a["doing"]) == {"post", "comments", "likes"}
    assert not next(p for p in d["posters"] if p["poster_id"] == "mac-b")["online"], "seen two days ago: offline"
    h = d["helpers"][0]
    assert h["worker"] == "mac-c" and h["online"] and h["resting"].startswith("outside") and h["today"]["made"] == 7
