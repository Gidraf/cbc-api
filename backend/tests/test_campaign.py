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


@needs_db
def test_a_command_for_one_mac_goes_to_that_mac_only(db) -> None:
    general = se.queue_command("check")
    mine = se.queue_command("login", "facebook", target="office-mini")
    got = se.take_command("office-mini", active=False)
    assert got["command_id"] == mine and got["action"] == "login", "its own command, though it is not the posting Mac"
    assert se.take_command("office-mini", active=False) is None, "the general ones are for the posting Mac"
    assert se.take_command("main-mac", active=True)["command_id"] == general


@needs_db
def test_each_mac_keeps_its_days_and_can_be_named_or_forgotten(db, monkeypatch) -> None:
    from app.routes import play
    from app.services import platform_settings

    monkeypatch.setattr(platform_settings, "set_many", lambda values, **_: db.update(
        {k: v for k, v in values.items()}) or values)

    se.heartbeat("mac-a", {"today": {"day": "2026-10-18", "posts": 2, "comments": 30}})
    se.heartbeat("mac-a", {"today": {"day": "2026-10-19", "posts": 1}})
    se.heartbeat("mac-a", {"today": {"day": "2026-10-19", "posts": 4, "comments": 12}})     # the day's last count wins
    days = se.device_history("mac-a", "poster", days=3650)
    assert [d["day"] for d in days] == ["2026-10-18", "2026-10-19"] and days[1] == {"day": "2026-10-19", "posts": 4, "comments": 12}
    play.name_device("mac-a", play.DeviceName(name="Studio Mac"), auth=None)
    assert se.device_names() == {"mac-a": "Studio Mac"}
    assert next(p for p in play.devices(auth=None)["posters"] if p["poster_id"] == "mac-a")["name"] == "Studio Mac"
    play.forget_device("mac-a", kind="poster", auth=None)
    assert not [p for p in play.devices(auth=None)["posters"] if p["poster_id"] == "mac-a"]
    assert se.device_history("mac-a", "poster", days=3650) == [] and se.device_names() == {}


def _booked(qid: str, at: datetime) -> str:
    se._plan_post({"question_id": qid, "curriculum": {}}, "facebook", at, "me")
    return se._post_id(qid, "facebook")


@needs_db
def test_a_scheduled_reel_is_confirmed_on_the_profile_or_goes_out_live(db) -> None:
    from app.infra.db import fetch_one

    db["poster_comment_thread"] = True
    now = datetime.now(timezone.utc)
    row = lambda pid: fetch_one("SELECT * FROM social_posts WHERE post_id = :id", {"id": pid})   # noqa: E731

    # "Facebook did not confirm the scheduled reel": taken as scheduled, never handed over again.
    lost = _booked("lost", now + timedelta(days=2))
    out = se.record_attempt(lost, ok=False, error="Facebook did not confirm the scheduled reel.")
    r = row(lost)
    assert out["unconfirmed"] and r["status"] == "scheduled" and r["platform_scheduled"] and r["handed_at"]
    assert r["comments_state"] == "pending" and r["comments_next_at"] == r["scheduled_for"] + timedelta(minutes=3)

    # Found by its first comment: confirmed.
    found = _booked("found", now + timedelta(hours=1))
    se.record_attempt(found, ok=True, scheduled=True)
    se.comments_result(found, stage="first", ok=True, url="https://facebook.com/reel/1", now=now + timedelta(hours=1, minutes=4))
    assert row(found)["status"] == "posted" and row(found)["notes"] == se.SCHEDULER_CONFIRMED

    # Not on the profile: looked for every half hour (not a spent try) until two hours on, then out live.
    gone = _booked("gone", now + timedelta(hours=1))
    se.record_attempt(gone, ok=True, scheduled=True)
    due = row(gone)["posted_at"]
    for k in range(4):                 # 3, 33, 63 and 93 minutes after its time
        se.comments_result(gone, stage="first", ok=False, error="Could not find the post on the profile — it may not be out yet.",
                           now=due + timedelta(minutes=3 + 30 * k))
    r = row(gone)
    assert r["status"] == "scheduled" and r["comments_attempts"] == 0 and r["comments_state"] == "pending"
    later = due + timedelta(hours=2, minutes=5)
    se.comments_result(gone, stage="first", ok=False, error="Could not find the post on the profile.", now=later)
    r = row(gone)
    assert r["status"] == "planned" and r["handed_at"] is None and not r["platform_scheduled"]
    assert r["scheduled_for"] == later and r["notes"] == se.SCHEDULER_MISSED and "goes out live" in r["last_error"]

    # One lost and one found: still trusted. A second lost, none found: posts go out live.
    assert se.scheduler_trust(later)["trusted"]
    from app.infra.db import execute

    execute("UPDATE social_posts SET notes = '' WHERE post_id = :id", {"id": found})
    other = _booked("gone2", now + timedelta(hours=1))
    se.record_attempt(other, ok=True, scheduled=True)
    se.comments_result(other, stage="first", ok=False, error="Could not find the post on the profile.", now=later)
    trust = se.scheduler_trust(later)
    assert not trust["trusted"] and trust["missed"] == 2 and "live" in trust["note"]


@needs_db
def test_reels_already_given_up_on_are_looked_for_again(db) -> None:
    from app.infra.db import execute, fetch_one

    now = datetime.now(timezone.utc)
    pid = _booked("old", now + timedelta(hours=1))
    se.record_attempt(pid, ok=True, scheduled=True)
    execute("UPDATE social_posts SET posted_at = :t, comments_state = 'failed', comments_attempts = 4 WHERE post_id = :id",
            {"t": now - timedelta(days=1), "id": pid})
    assert se.recheck_scheduled(now) == 1
    r = fetch_one("SELECT comments_state, comments_attempts FROM social_posts WHERE post_id = :id", {"id": pid})
    assert r == {"comments_state": "pending", "comments_attempts": 0}
    assert se.recheck_scheduled(now) == 0


@needs_db
def test_post_now_takes_a_picked_question_but_never_one_already_out(db, monkeypatch) -> None:
    from app.infra.db import fetch_one
    from app.services import whiteboard

    now = datetime.now(timezone.utc)
    monkeypatch.setattr(whiteboard, "load", lambda qid: {"question_id": qid, "curriculum": {}})
    made = {"ready-q": "ready"}
    queued: list[str] = []
    monkeypatch.setattr(social, "status", lambda qid, q=None, **k: {"status": made.get(qid, "none")})
    monkeypatch.setattr(social, "enqueue", lambda qid, **k: queued.append(qid) or {"status": "queued"})

    got = se.post_question("ready-q", now=now)
    assert got["ok"] and fetch_one("SELECT scheduled_for FROM social_posts WHERE post_id = :id",
                                   {"id": got["post_id"]})["scheduled_for"] == now
    fresh = se.post_question("new-q", now=now)
    assert not fresh["ok"] and fresh["making"] and queued == ["new-q"], "no video yet: made first"

    sched = _booked("sched-q", now + timedelta(days=3))
    se.record_attempt(sched, ok=True, scheduled=True)
    made["sched-q"] = "ready"
    refused = se.post_question("sched-q", now=now)
    assert not refused["ok"] and "already scheduled on Facebook" in refused["error"]
