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
            {"t": now - timedelta(hours=3), "id": pid})
    assert se.recheck_scheduled(now) == 1
    r = fetch_one("SELECT comments_state, comments_attempts FROM social_posts WHERE post_id = :id", {"id": pid})
    assert r == {"comments_state": "pending", "comments_attempts": 0}
    assert se.recheck_scheduled(now) == 0
    # A reel due a day ago is far down the profile: not looked for again.
    execute("UPDATE social_posts SET posted_at = :t, comments_state = 'failed' WHERE post_id = :id",
            {"t": now - timedelta(days=1), "id": pid})
    assert se.recheck_scheduled(now) == 0


@needs_db
def test_a_reel_lost_long_ago_is_never_sent_out_again(db) -> None:
    from app.infra.db import execute, fetch_one

    now = datetime.now(timezone.utc)
    pid = _booked("long-ago", now + timedelta(hours=1))
    se.record_attempt(pid, ok=True, scheduled=True)
    execute("UPDATE social_posts SET posted_at = :t WHERE post_id = :id", {"t": now - timedelta(days=2), "id": pid})
    se.comments_result(pid, stage="first", ok=False, error="Could not find the post on the profile.", now=now)
    r = fetch_one("SELECT status, handed_at, notes, comments_state FROM social_posts WHERE post_id = :id", {"id": pid})
    assert r["status"] == "scheduled" and r["handed_at"] and r["notes"] == se.SCHEDULER_UNVERIFIED
    assert r["comments_state"] == "failed"


@needs_db
def test_old_posts_without_a_link_do_not_hold_up_the_comments(db, monkeypatch) -> None:
    from app.infra.db import execute, fetch_one

    now = datetime.now(timezone.utc).replace(hour=9)          # noon in Nairobi, inside posting hours
    db["poster_comment_thread"] = True
    monkeypatch.setattr(social, "status", lambda qid, q=None, **k: {"thread": {"find": qid, "first": ["a"], "later": ["b"]},
                                                                    "status": "ready"})
    old = _post("old-nolink", now - timedelta(days=4), 10)
    fresh = _post("fresh-nolink", now - timedelta(hours=2), 10)
    linked = _post("linked", now - timedelta(days=4), 10)
    execute("UPDATE social_posts SET comments_state = 'pending', comments_next_at = posted_at, url = '' WHERE post_id IN (:a, :b)",
            {"a": old, "b": fresh})
    execute("""UPDATE social_posts SET comments_state = 'pending', comments_next_at = posted_at,
               url = 'https://facebook.com/reel/9' WHERE post_id = :c""", {"c": linked})
    assert se._give_up_unfindable(now) == 1
    assert fetch_one("SELECT comments_state FROM social_posts WHERE post_id = :id", {"id": old})["comments_state"] == "failed"
    # Straight after a profile search that failed, the next turn is a post with its link.
    execute("UPDATE social_posts SET comments_error = 'Could not find the post on the profile.', updated_at = :t WHERE post_id = :id",
            {"t": now - timedelta(minutes=2), "id": old})
    assert se._searched_in_vain(now)
    job = se.comments_next(now).get("job") or {}
    assert job.get("post_id") == linked
    assert not se._searched_in_vain(now + timedelta(minutes=10))


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


@needs_db
def test_one_question_shows_its_videos_posts_comments_and_numbers(db, monkeypatch) -> None:
    from types import SimpleNamespace

    from app.infra.db import execute
    from app.routes import play
    from app.services import whiteboard

    q = {"question_id": "lib-q", "question_text": "What is 7 × 8?", "options": [{"id": "A", "text": "56", "is_correct": True}],
         "curriculum": {"grade": "grade-9", "subject": "Mathematics", "sub_strand": "Integers"}}
    monkeypatch.setattr(whiteboard, "load", lambda qid: q)
    monkeypatch.setattr(social, "status", lambda qid, q=None, **k: {"status": "ready", "url": "https://x/v.mp4", "teacher": "female"})
    pid = _post("lib-q", NOW - timedelta(days=1), 120)
    execute("UPDATE social_posts SET url = 'https://facebook.com/reel/7' WHERE post_id = :id", {"id": pid})
    execute("INSERT INTO post_insights (post_id, at, views, reactions, comments, shares) VALUES (:p, :t, 120, 4, 9, 1)",
            {"p": pid, "t": NOW})
    execute("INSERT INTO campaign_log (post_id, at, kind, ok) VALUES (:p, :t, 'comment', TRUE), (:p, :t, 'comment', TRUE)",
            {"p": pid, "t": NOW})
    execute("""INSERT INTO question_videos (question_id, kind, video_key, object_name, made_at)
               VALUES ('lib-q', 'social', 'abc', 'social/lib-q/abc.mp4', :t)""", {"t": NOW})
    out = play.library_question("lib-q", auth=SimpleNamespace(role="admin"))
    assert out["question_text"] == "What is 7 × 8?" and out["sub_strand"] == "Integers"
    assert out["current_video"]["status"] == "ready" and out["videos"][0]["kind"] == "social"
    post = out["posts"][0]
    assert post["url"] == "https://facebook.com/reel/7" and post["campaign"]["comment"]["ok"] == 2
    assert post["daily"][0]["views"] == 120
    assert play.library_question("lib-q", auth=SimpleNamespace(role="student"))["posts"] == [], "the team's numbers only"


@needs_db
def test_an_older_video_is_posted_while_the_new_one_is_made(db, monkeypatch) -> None:
    from app.infra.db import execute
    from app.infra.storage import object_storage
    from app.services import whiteboard

    q = {"question_id": "old-vid", "question_text": "What is 9 − 4?", "options": [{"id": "A", "text": "5", "is_correct": True}],
         "curriculum": {"grade": "grade-9", "subject": "Mathematics"}}
    monkeypatch.setattr(whiteboard, "load", lambda qid: q)
    monkeypatch.setattr(object_storage, "object_exists", lambda name: name == "social/old-vid/oldkey.mp4")
    execute("""INSERT INTO question_videos (question_id, kind, video_key, object_name, made_at)
               VALUES ('old-vid', 'social', 'oldkey', 'social/old-vid/oldkey.mp4', NOW())""")
    st = social.status("old-vid", q)
    assert st["status"] == "ready" and st["older"] and st["url"].endswith("social/old-vid/oldkey.mp4") and not st["marketing"]
    assert social.status("old-vid", q, older=False)["status"] != "ready", "the factory still makes the new one"
    assert social.status("old-vid", q, legacy=False)["status"] != "ready"
    db["social_serve_older"] = False
    assert social.status("old-vid", q)["status"] != "ready", "off: only current videos are posted"


@needs_db
def test_posts_seen_on_the_profile_get_their_links_and_their_comments(db, monkeypatch) -> None:
    from app.infra.db import execute, fetch_one
    from app.services import whiteboard

    now = datetime.now(timezone.utc)
    texts = {"rq1": "A farmer in Nakuru plants 120 seedlings in 8 equal rows. How many seedlings are in each row of the farm?",
             "rq2": "Calculate the time taken in hours to fill the storage tank if all three pipes are opened together.",
             "rq3": "Name the gas plants take in during photosynthesis when the sun is out over the shamba today."}
    monkeypatch.setattr(whiteboard, "load", lambda qid: {"question_id": qid, "question_text": texts[qid]})
    ids = {}
    for k, qid in enumerate(texts):
        ids[qid] = _booked(qid, now + timedelta(hours=1))
        se.record_attempt(ids[qid], ok=True, scheduled=True)
        execute("UPDATE social_posts SET posted_at = :t, comments_state = 'failed' WHERE post_id = :id",
                {"t": now - timedelta(days=3 + k), "id": ids[qid]})
    assert se.reconcile_due(now)
    job = se.reconcile_job(now)
    assert job["stage"] == "reconcile" and not se.reconcile_due(now), "one deep scroll every few hours"
    seen = [
        # the opening folded behind "See more": found by its end
        {"url": "https://www.facebook.com/reel/111/", "text": "CBC Grade 9 … How many seedlings are in each row of the farm? 👇 The choices are in the comments"},
        # its middle
        {"url": "https://www.facebook.com/reel/222/", "text": "Pipes! … the time taken in hours to fill the storage tank if all three … See more"},
        {"url": "https://www.facebook.com/reel/333/", "text": "Someone else's post about football results this weekend in Nairobi"},
    ]
    got = se.reconcile_result(seen, now)
    assert got["matched"] == 2 and got["left"] == 1
    r = fetch_one("SELECT url, status, notes, comments_state, comments_attempts FROM social_posts WHERE post_id = :id",
                  {"id": ids["rq1"]})
    assert r == {"url": "https://www.facebook.com/reel/111/", "status": "posted", "notes": se.SCHEDULER_CONFIRMED,
                 "comments_state": "pending", "comments_attempts": 0}
    assert fetch_one("SELECT url FROM social_posts WHERE post_id = :id", {"id": ids["rq2"]})["url"].endswith("/222/")
    assert fetch_one("SELECT url FROM social_posts WHERE post_id = :id", {"id": ids["rq3"]})["url"] == ""
    assert se.reconcile_result(seen, now)["matched"] == 0, "a link already taken is not given twice"


def test_a_question_is_also_found_by_its_middle_and_end() -> None:
    q = "A farmer in Nakuru plants 120 seedlings in 8 equal rows. How many seedlings are in each row of the farm?"
    assert social.snippets(q) == ["seedlings in 8 equal rows. How many seedlings", "seedlings are in each row of the farm?"]
    assert social.snippets("Too short to cut") == []


@needs_db
def test_the_devices_page_says_which_mac_needs_the_update(db, monkeypatch) -> None:
    from app.routes import play
    from app.services import poster_installer

    monkeypatch.setattr(poster_installer, "code_hash", lambda: "new")
    se.heartbeat("mac-new", {"machine": {"hash": "new"}})
    se.heartbeat("mac-old", {"machine": {"hash": "old"}})
    se.heartbeat("mac-older", {"machine": {}})            # from before Macs said their code
    got = {p["poster_id"]: p["update"] for p in play.devices(auth=None)["posters"]}
    assert got["mac-new"] == "current" and got["mac-old"] == "behind" and got["mac-older"] == "behind"


@needs_db
def test_the_photo_series_is_booked_before_the_days_reels(db, monkeypatch) -> None:
    from app.infra.db import fetch_all
    from app.services import social_cards, whiteboard

    monkeypatch.setattr(whiteboard, "load", lambda qid: {"question_id": qid, "curriculum": {"grade": "grade-9"}})
    monkeypatch.setattr(social_cards, "enqueue", lambda qid, **k: {"status": "queued"})
    rules = {**se.poster_rules(), "photos_per_day": 8, "min_gap_minutes": 100, "platforms": ["facebook"],
             "hours": {"start": "06:00", "end": "22:00"}}
    monkeypatch.setattr(se, "poster_rules", lambda: rules)
    tomorrow = (datetime.now(se.EAT) + timedelta(days=1)).date()
    at = lambda h, m=0: datetime.combine(tomorrow, se.time(h, m), tzinfo=se.EAT)       # noqa: E731
    for qid, t in (("early", at(7)), ("mid", at(14)), ("late", at(18)), ("night", at(20))):
        _booked(qid, t)
    got = se.attach_series(datetime.now(timezone.utc), days=3)
    assert got["series"] == 2, "8 photos a day: two series"
    steps = {(r["question_id"], r["step"]): r["scheduled_for"] for r in fetch_all(
        "SELECT question_id, step, scheduled_for FROM social_posts WHERE format = 'photo'") or []}
    # 07:00 has no room before it (the teaser would be before 06:00): the next two reels get theirs.
    assert ("early", "question") not in steps
    assert [s for (q, s) in sorted(steps, key=lambda k: steps[k]) if q == "mid"] == ["teaser", "question", "kicd", "answer"]
    assert steps[("mid", "answer")] == at(12, 20) and steps[("mid", "teaser")] == at(7, 20)
    assert ("late", "kicd") in steps and ("night", "teaser") not in steps
    assert se.attach_series(datetime.now(timezone.utc), days=3)["series"] == 0, "booked once"


@needs_db
def test_the_first_comments_carry_the_question_card_and_the_kicd_page(db, monkeypatch) -> None:
    from app.infra.db import execute
    from app.services import social_cards, whiteboard

    db["poster_comment_thread"] = True
    now = datetime.now(timezone.utc).replace(hour=9)
    monkeypatch.setattr(se, "reconcile_due", lambda now: False)
    monkeypatch.setattr(whiteboard, "load", lambda qid: {"question_id": qid, "curriculum": {"grade": "grade-9", "subject": "Mathematics",
                                                                                            "sub_strand": "Integers"}})
    monkeypatch.setattr(social, "status", lambda qid, q=None, **k: {"status": "ready", "thread": {
        "find": "x", "first": ["Choices:\nA) 5", "🤔 Can you solve it?"], "later": ["✅ Answer: A) 5", "💡 How…"]}})
    monkeypatch.setattr(social_cards, "status", lambda qid, step, q=None: {"status": "ready", "url": f"https://x/{step}.jpg"})
    monkeypatch.setattr(social_cards, "enqueue", lambda qid, **k: {"status": "ready"})
    monkeypatch.setattr(social_cards, "design_row", lambda q: {"sub_strand_name": "Integers", "source_pages": [12, 13]})
    pid = _post("cards-q", now - timedelta(minutes=30), 0)
    execute("""UPDATE social_posts SET comments_state = 'pending', comments_next_at = :t, url = 'https://facebook.com/reel/5'
               WHERE post_id = :id""", {"t": now - timedelta(minutes=5), "id": pid})
    job = se.comments_next(now)["job"]
    assert job["stage"] == "first" and len(job["comments"]) == 3
    assert job["images"] == ["https://x/question.jpg", "", "https://x/kicd.jpg"]
    assert "KICD curriculum design" in job["comments"][2] and "pages 12–13" in job["comments"][2]
    se.comments_result(pid, stage="first", ok=True, now=now)
    later = se.comments_next(now + timedelta(minutes=5))["job"]
    assert later["stage"] == "later" and later["images"] == ["", "https://x/answer.jpg"]
