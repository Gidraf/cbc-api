"""Booking a month at a time, and live posts when there is a chance.

The calendar and booking run against a real Postgres (CBC_TEST_PHASE2_DATABASE_URL,
an empty database); the spacing needs none.
"""
from __future__ import annotations

import os
import random
from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.services import social_export as se

DB = os.getenv("CBC_TEST_PHASE2_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB, reason="set CBC_TEST_PHASE2_DATABASE_URL to an empty Postgres database")
EAT = se.EAT
RULES = {"hours": {"start": "06:00", "end": "22:00"}, "min_gap_minutes": 20}


def test_posts_are_30_to_60_minutes_apart_inside_the_hours() -> None:
    times = se.spaced_times(random.Random(1), date(2026, 11, 3), 10, RULES, gap_min=30, gap_max=60)
    assert len(times) == 10
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:])]
    assert all(29.5 <= g <= 60.5 for g in gaps), gaps
    assert all(time(6, 0) <= t.astimezone(EAT).time() <= time(21, 45) for t in times)


def test_new_posts_keep_clear_of_what_the_day_already_has() -> None:
    day = date(2026, 11, 3)
    taken = [datetime.combine(day, time(h, 0), tzinfo=EAT) for h in (7, 9, 11, 13)]
    times = se.spaced_times(random.Random(2), day, 12, RULES, gap_min=30, gap_max=45, taken=taken)
    for t in times:
        assert all(abs((t - x).total_seconds()) >= 30 * 60 for x in taken), t


def test_a_day_holds_only_what_fits() -> None:
    short = {"hours": {"start": "18:00", "end": "21:00"}, "min_gap_minutes": 20}
    times = se.spaced_times(random.Random(3), date(2026, 11, 3), 30, short, gap_min=30, gap_max=60)
    assert 3 <= len(times) <= 6


def test_the_gap_is_never_below_the_posters_own() -> None:
    times = se.spaced_times(random.Random(4), date(2026, 11, 3), 5, {**RULES, "min_gap_minutes": 40},
                            gap_min=10, gap_max=10)
    assert all((b - a).total_seconds() >= 40 * 60 for a, b in zip(times, times[1:]))


def test_months_have_their_days() -> None:
    assert len(se.month_days(2026, 2)) == 28 and len(se.month_days(2028, 2)) == 29
    assert se.month_days(2026, 12)[-1] == date(2026, 12, 31)


# ── against the database ─────────────────────────────────────────────────────

@pytest.fixture()
def db(monkeypatch):
    from sqlalchemy import create_engine, text

    from app.infra import db as infra
    from app.services import platform_settings

    engine = create_engine(DB)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    monkeypatch.setattr(infra, "get_engine", lambda: engine)
    settings = {"poster_enabled": True, "poster_platforms": ["facebook"], "poster_min_gap_minutes": 20}
    monkeypatch.setattr(platform_settings, "_load", lambda: settings)
    infra.run_migrations()
    yield settings
    engine.dispose()


def _questions(n: int) -> dict[str, dict]:
    return {f"q{i}": {"question_id": f"q{i}", "curriculum": {"grade": "Grade 9", "subject": "Mathematics",
                                                             "sub_strand": "Integers"}} for i in range(n)}


NOW = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)      # 12:00 in Nairobi


@needs_db
def test_the_month_shows_room_and_booking_fills_only_the_room(db, monkeypatch) -> None:
    from app.infra.db import fetch_all
    from app.services import social

    qs = _questions(400)
    monkeypatch.setattr(se, "_unbooked", lambda g, s, ss, need, ready_only=False:
                        (list(qs)[:need], {k: "ready" for k in list(qs)[:need]}, qs))
    monkeypatch.setattr(social, "enqueue", lambda *a, **k: None)
    # Something on the 20th already: 4 booked.
    for i, h in enumerate((8, 10, 12, 14)):
        se._plan_post({"question_id": f"old{i}", "curriculum": {}}, "facebook",
                      datetime(2026, 10, 20, h, 0, tzinfo=EAT), "earlier")

    view = se.month_view(2026, 10, per_day=10, now=NOW)
    days = {d["date"]: d for d in view["days"]}
    assert days["2026-10-15"]["free"] == 0 and not days["2026-10-15"]["bookable"], "today is not booked into"
    assert days["2026-10-20"]["booked"] == 4 and days["2026-10-20"]["free"] == 6
    assert days["2026-10-16"]["free"] == 10
    assert view["open_days"] == 16 and view["free"] == 15 * 10 + 6

    plan = se.book_month("Grade 9", "Mathematics", year=2026, month=10, per_day=10, dry=True, now=NOW, seed=1)
    assert plan["posts"] == 156 and not plan["booked"]
    assert not fetch_all("SELECT 1 FROM social_posts WHERE created_by = 'me'"), "a preview books nothing"

    out = se.book_month("Grade 9", "Mathematics", year=2026, month=10, per_day=10, now=NOW, seed=1, created_by="me")
    assert out["booked"] and out["posts"] == 156
    after = {d["date"]: d for d in se.month_view(2026, 10, per_day=10, now=NOW)["days"]}
    assert all(d["free"] == 0 for d in after.values())
    assert after["2026-10-20"]["booked"] == 10
    again = se.book_month("Grade 9", "Mathematics", year=2026, month=10, per_day=10, now=NOW, seed=2)
    assert again["posts"] == 0 and "full" in again["notes"][0]


@needs_db
def test_days_beyond_facebooks_window_say_when_they_reach_it(db) -> None:
    view = se.month_view(2026, 12, per_day=10, now=NOW)
    days = {d["date"]: d for d in view["days"]}
    assert view["facebook_until"] == "2026-11-12"
    assert days["2026-12-01"]["to_platform_on"] == "2026-11-03"


@needs_db
def test_a_live_extra_posts_a_finished_unbooked_video_while_the_day_allows(db, monkeypatch) -> None:
    from app.infra.db import execute
    from app.services import social, whiteboard

    db["poster_live_per_day"] = 2
    se._no_extra_until["t"] = 0.0
    execute("INSERT INTO question_videos (question_id, kind, video_key, object_name) VALUES ('made1', 'social', 'k', 'o')")
    execute("INSERT INTO question_videos (question_id, kind, video_key, object_name) VALUES ('made2', 'social', 'k', 'o')")
    monkeypatch.setattr(social, "status", lambda qid, q=None: {"status": "ready", "url": "u", "post": "p"})
    monkeypatch.setattr(whiteboard, "load", lambda qid: {"question_id": qid, "curriculum": {}})
    rules = se.poster_rules()
    post, st = se.live_extra(NOW, rules)
    assert post and post["created_by"] == se.LIVE_EXTRA and post["platform"] == "facebook"
    se.record_attempt(post["post_id"], ok=True)
    execute("UPDATE social_posts SET handed_at = :t WHERE post_id = :id", {"t": NOW, "id": post["post_id"]})
    assert se.live_extra(NOW, rules)[0] is None, "the gap since the last post holds the next"
    later = NOW + timedelta(minutes=30)
    second, _ = se.live_extra(later, rules)
    assert second and second["question_id"] != post["question_id"]
    se.record_attempt(second["post_id"], ok=True)
    execute("UPDATE social_posts SET handed_at = :t WHERE post_id = :id", {"t": later, "id": second["post_id"]})
    assert se.live_extra(later + timedelta(hours=1), rules)[0] is None, "two a day, as set"


@needs_db
def test_live_extras_are_off_unless_asked(db) -> None:
    se._no_extra_until["t"] = 0.0
    assert se.live_extra(NOW, se.poster_rules()) == (None, {})


@needs_db
def test_teacher_now_pauses_lessons_and_queues_the_soonest_booked_videos_first(db, monkeypatch) -> None:
    from app.infra.db import execute, fetch_one
    from app.services import platform_settings, social, teacher

    written = {}
    monkeypatch.setattr(platform_settings, "set_many", lambda values, updated_by="": written.update(values) or values)
    execute("""INSERT INTO jobs (job_id, kind, grade, subject, status, payload, queued_by)
               VALUES ('L1', 'video', '', '', 'queued', '{}'::jsonb, 'daily')""")
    for n, day in enumerate((5, 2, 9)):
        se._plan_post({"question_id": f"b{n}", "curriculum": {}}, "facebook",
                      datetime(2026, 11, day, 10, 0, tzinfo=EAT), "me")
    se._plan_post({"question_id": "gone", "curriculum": {}}, "facebook", datetime(2026, 11, 1, 10, 0, tzinfo=EAT), "me")
    execute("UPDATE social_posts SET handed_at = NOW() WHERE question_id = 'gone'")      # Facebook has it already
    queued = []
    monkeypatch.setattr(social, "enqueue", lambda qid, **k: queued.append((qid, k["fresh"], k["priority"])) or {"status": "queued"})

    out = teacher.render_now("alternate", limit=10)
    assert written["social_teacher"] == "alternate" and written["video_daily_target"] == 0
    assert out["lessons_cancelled"] == 1
    assert fetch_one("SELECT status FROM jobs WHERE job_id = 'L1'")["status"] == "cancelled"
    assert [q for q, _, _ in queued] == ["b1", "b0", "b2"], "the soonest post first; a handed one is left alone"
    assert all(fresh and prio > 0 for _, fresh, prio in queued)


@needs_db
def test_auto_book_keeps_the_next_days_full_across_months_and_never_repeats(db, monkeypatch) -> None:
    from app.infra.db import fetch_all
    from app.services import social

    db.update({"poster_auto_book": True, "poster_auto_book_per_day": 3, "poster_auto_book_days": 30,
               "poster_auto_book_scopes": ["grade-9|Mathematics", "grade-9|Integrated Science"]})
    pools = {"Mathematics": [f"m{i}" for i in range(200)], "Integrated Science": [f"s{i}" for i in range(200)]}
    used: set[str] = set()

    def unbooked(g, subj, ss, need, ready_only=False):
        booked = {r["question_id"] for r in fetch_all("SELECT question_id FROM social_posts")}
        ids = [q for q in pools[subj] if q not in booked][:need]
        return ids, {q: "none" for q in ids}, {q: {"question_id": q, "curriculum": {"grade": g, "subject": subj}} for q in ids}

    monkeypatch.setattr(se, "_unbooked", unbooked)
    queued = []
    monkeypatch.setattr(social, "enqueue", lambda qid, **k: queued.append(qid))
    out = se.auto_book(now=NOW, seed=3)
    assert out["posts"] == 90 and out["to_render"] == 90, "30 days × 3, every video queued to render"
    rows = fetch_all("SELECT question_id, subject FROM social_posts")
    assert len({r["question_id"] for r in rows}) == 90, "no question twice"
    subjects = [r["subject"] for r in rows]
    assert subjects.count("Mathematics") == 45 and subjects.count("Integrated Science") == 45, "subjects mixed"
    again = se.auto_book(now=NOW, seed=4)
    assert again["posts"] == 0, "a full calendar is left alone"
    later = se.auto_book(now=NOW + timedelta(days=2), seed=5)
    assert later["posts"] == 6, "two new days at the far end"


@needs_db
def test_auto_book_off_books_nothing(db) -> None:
    assert se.auto_book(now=NOW)["posts"] == 0


@needs_db
def test_post_now_uses_a_new_question_and_leaves_the_bookings_alone(db, monkeypatch) -> None:
    from app.infra.db import execute
    from app.services import social, whiteboard

    se._plan_post({"question_id": "booked1", "curriculum": {}}, "facebook", NOW + timedelta(days=3), "me")
    execute("INSERT INTO question_videos (question_id, kind, video_key, object_name) VALUES ('fresh1', 'social', 'k', 'o')")
    monkeypatch.setattr(social, "status", lambda qid, q=None, **k: {"status": "ready", "url": "u", "post": "p", "teacher": "female"})
    monkeypatch.setattr(whiteboard, "load", lambda qid: {"question_id": qid, "question_text": "?", "curriculum": {}})
    out = se.next_for_poster(NOW, dry=True, share="feed")
    assert out["post"]["question_id"] == "fresh1"
    # The next press finds no new video, so it takes the booked one.
    execute("UPDATE social_posts SET posted_at = NOW(), handed_at = NOW() WHERE question_id = 'fresh1'")
    out = se.next_for_poster(NOW, dry=True, share="feed")
    assert out["post"]["question_id"] == "booked1"


@needs_db
def test_schedule_now_hands_the_soonest_ready_booking_within_the_window_and_the_limit(db, monkeypatch) -> None:
    from app.infra.db import execute
    from app.services import social, whiteboard

    db["poster_daily_cap"] = 2
    for qid, days in (("far", 40), ("soon", 2), ("later", 5), ("grp", 1)):
        se._plan_post({"question_id": qid, "curriculum": {}}, "facebook", NOW + timedelta(days=days), "me")
    execute("UPDATE social_posts SET groups = '[\"G\"]'::jsonb WHERE question_id = 'grp'")   # goes out live with a share
    monkeypatch.setattr(social, "status", lambda qid, q=None, **k: {"status": "ready", "url": "u", "post": "p", "teacher": ""})
    monkeypatch.setattr(whiteboard, "load", lambda qid: {"question_id": qid, "question_text": "?"})
    first = se.schedule_next(NOW)["post"]
    assert first["question_id"] == "soon" and first["schedule_at"]
    se.record_attempt(first["post_id"], ok=True, scheduled=True)
    execute("UPDATE social_posts SET handed_at = :t WHERE post_id = :id", {"t": NOW, "id": first["post_id"]})
    assert se.schedule_next(NOW)["post"]["question_id"] == "later", "beyond 29 days and group posts are skipped"
    execute("UPDATE social_posts SET handed_at = :t WHERE question_id = 'later'", {"t": NOW})
    out = se.schedule_next(NOW)
    assert out["post"] is None and "limit" in out["reason"]


@needs_db
def test_schedule_now_books_the_window_first_when_it_is_empty(db, monkeypatch) -> None:
    from app.services import social, whiteboard

    called = {}

    def fake_book(**k):
        called.update(k)
        se._plan_post({"question_id": "new1", "curriculum": {}}, "facebook", NOW + timedelta(days=3), "auto-book")
        return {"posts": 1}

    monkeypatch.setattr(se, "auto_book", fake_book)
    monkeypatch.setattr(social, "status", lambda qid, q=None, **k: {"status": "ready", "url": "u", "post": "p", "thread": {}})
    monkeypatch.setattr(whiteboard, "load", lambda qid: {"question_id": qid, "question_text": "?"})
    out = se.schedule_next(NOW)
    assert called["force"] and called["days"] == 28 and out["post"]["question_id"] == "new1"


THREAD_Q = {"question_id": "q1", "question_text": "What is $2 + 3$?",
            "options": [{"id": "A", "text": "4"}, {"id": "B", "text": "5", "is_correct": True}],
            "curriculum": {"grade": "grade-9", "subject": "Mathematics", "sub_strand": "Integers"}}
THREAD_DATA = {"scenes": [{"scene": "answer", "option": "B", "text": "5"}]}


def test_the_question_is_the_caption_and_the_rest_are_comments(monkeypatch) -> None:
    from app.services import social

    b = {"hook": "Can you solve this?", "name": "CBC Maths", "handle": "@cbc", "website": "cbc.example", "cta": "Follow",
         "hashtags": "", "countdown": 3, "teacher": "off"}
    t = social.thread(THREAD_Q, THREAD_DATA, b)
    assert t["caption"].startswith("What is 2 + 3?") and "choices are in the comments" in t["caption"]
    assert "A) 4" not in t["caption"], "the choices are not in the caption"
    assert t["first"][0].startswith("Choices:") and "A) 4" in t["first"][0] and "B) 5" in t["first"][0]
    assert "Can you solve it?" in t["first"][1]
    assert t["later"][0] == "✅ Answer: B) 5" and t["later"][1].startswith("✅ Answer: B) 5") and "Follow" in t["later"][1]
    assert t["find"] == "What is 2 + 3?"


@needs_db
def test_comments_go_up_in_two_steps_a_minute_apart_within_posting_hours(db, monkeypatch) -> None:
    from app.infra.db import fetch_one
    from app.services import social

    db.update({"poster_comment_thread": True, "poster_answer_delay_seconds": 60})
    monkeypatch.setattr(social, "status", lambda qid, q=None, **k: {"status": "ready", "url": "u", "post": "p",
                        "thread": {"caption": "c", "first": ["Choices", "Try"], "later": ["Ans", "Why"], "find": "What is"}})
    se._plan_post({"question_id": "q1", "curriculum": {}}, "facebook", NOW - timedelta(minutes=5), "me")
    pid = se._post_id("q1", "facebook")
    se.record_attempt(pid, ok=True)
    from app.infra.db import execute
    execute("UPDATE social_posts SET posted_at = :t WHERE post_id = :id", {"t": NOW - timedelta(minutes=2), "id": pid})
    execute("UPDATE social_posts SET comments_next_at = :t WHERE post_id = :id", {"t": NOW - timedelta(minutes=2), "id": pid})
    job = se.comments_next(NOW)["job"]
    assert job["stage"] == "first" and job["comments"] == ["Choices", "Try"] and job["find"] == "What is"
    se.comments_result(pid, stage="first", ok=True, now=NOW)
    assert se.comments_next(NOW)["job"] is None, "the answer waits its minute"
    job = se.comments_next(NOW + timedelta(seconds=95))["job"]
    assert job["stage"] == "later" and job["comments"] == ["Ans", "Why"]
    se.comments_result(pid, stage="later", ok=True, now=NOW + timedelta(seconds=95))
    assert fetch_one("SELECT comments_state FROM social_posts WHERE post_id = :id", {"id": pid})["comments_state"] == "done"
    night = datetime(2026, 10, 15, 21, 0, tzinfo=timezone.utc)          # midnight in Nairobi
    assert se.comments_next(night)["reason"] == "Outside posting hours."


@needs_db
def test_the_answer_comment_carries_its_card_made_in_time(db, monkeypatch) -> None:
    from app.infra.db import execute
    from app.services import social, social_cards, whiteboard

    db.update({"poster_comment_thread": True, "poster_answer_delay_seconds": 60})
    monkeypatch.setattr(social, "status", lambda qid, q=None, **k: {"status": "ready", "url": "u", "post": "p",
                        "thread": {"caption": "c", "first": ["Choices"], "later": ["Ans"], "find": "What is"}})
    monkeypatch.setattr(whiteboard, "load", lambda qid: {"question_id": qid})
    made = {"card": False, "queued": 0, "rendered": 0}

    def status(qid, step, q=None):
        return {"status": "ready", "url": "https://x/card.jpg"} if made["card"] else {"status": "none"}

    def render(qid, step, q=None):
        made["rendered"] += 1
        made["card"] = True
        return status(qid, step)

    monkeypatch.setattr(social_cards, "status", status)
    monkeypatch.setattr(social_cards, "render", render)
    monkeypatch.setattr(social_cards, "enqueue", lambda qid, **k: made.__setitem__("queued", made["queued"] + 1))
    se._plan_post({"question_id": "q1", "curriculum": {}}, "facebook", NOW - timedelta(minutes=5), "me")
    pid = se._post_id("q1", "facebook")
    se.record_attempt(pid, ok=True)
    execute("UPDATE social_posts SET posted_at = :t, comments_next_at = :t WHERE post_id = :id",
            {"t": NOW - timedelta(minutes=2), "id": pid})
    monkeypatch.setattr(social_cards, "design_row", lambda q: {})
    job = se.comments_next(NOW)["job"]
    # The choices go now with the question card (made then, if the queue has not), and
    # the rest — the answer card — is queued for the answer.
    assert job["images"][0] == "https://x/card.jpg" and made["rendered"] == 1 and made["queued"] == 1
    se.comments_result(pid, stage="first", ok=True, now=NOW)
    job = se.comments_next(NOW + timedelta(seconds=95))["job"]
    assert job["stage"] == "later" and job["image_url"] == "https://x/card.jpg" and job["images"] == ["https://x/card.jpg"]


@needs_db
def test_a_post_it_cannot_find_is_tried_again_then_given_up(db) -> None:
    from app.infra.db import execute, fetch_one

    se._plan_post({"question_id": "q2", "curriculum": {}}, "facebook", NOW - timedelta(minutes=5), "me")
    pid = se._post_id("q2", "facebook")
    execute("UPDATE social_posts SET comments_state = 'pending', comments_next_at = :t, posted_at = :t, handed_at = :t WHERE post_id = :id",
            {"t": NOW - timedelta(minutes=5), "id": pid})
    for _ in range(se.COMMENT_TRIES):
        se.comments_result(pid, stage="first", ok=False, error="not found", now=NOW)
    row = fetch_one("SELECT comments_state, comments_error FROM social_posts WHERE post_id = :id", {"id": pid})
    assert row["comments_state"] == "failed" and row["comments_error"] == "not found"


@needs_db
def test_posts_already_out_get_the_same_comments(db) -> None:
    from app.infra.db import execute

    for n, days in enumerate((1, 3, 20)):
        se._plan_post({"question_id": f"old{n}", "curriculum": {}}, "facebook", NOW - timedelta(days=days), "me")
    execute("UPDATE social_posts SET posted_at = scheduled_for, handed_at = scheduled_for")
    assert se.comments_backfill(7, now=NOW) == 2, "the last 7 days only"
    assert se.comments_backfill(7, now=NOW) == 0, "once"


@needs_db
def test_a_post_is_boosted_only_when_asked_and_its_outcome_lands_on_the_post(db, monkeypatch) -> None:
    from app.infra.db import execute, fetch_one
    from app.services import social

    monkeypatch.setattr(social, "status", lambda qid, q=None, **k: {"thread": {"find": "What is"}})
    se._plan_post({"question_id": "q1", "curriculum": {}}, "facebook", NOW - timedelta(minutes=5), "me")
    pid = se._post_id("q1", "facebook")
    with pytest.raises(ValueError):
        se.boost(pid)                                      # not out yet
    se.record_attempt(pid, ok=True)
    out = se.boost(pid, daily_ksh=200, days=5)
    assert out["total_ksh"] == 1000
    cmd = se.take_command()
    assert cmd["action"] == "boost" and cmd["options"]["daily_ksh"] == 200 and cmd["options"]["find"] == "What is"
    with pytest.raises(ValueError):
        se.boost(pid)                                      # already on its way
    se.finish_command(cmd["command_id"], {"ok": False, "unsure": True, "error": "check Ads Manager"})
    assert fetch_one("SELECT boost_state FROM social_posts WHERE post_id = :id", {"id": pid})["boost_state"] == "check"
    with pytest.raises(ValueError):
        se.boost(pid)                                      # may have gone through: never a silent second charge
    se.boost(pid, again=True)
    se.finish_command(se.take_command()["command_id"], {"ok": True})
    row = fetch_one("SELECT boost_state, boosted_at FROM social_posts WHERE post_id = :id", {"id": pid})
    assert row["boost_state"] == "boosted" and row["boosted_at"]


@needs_db
def test_relaunch_sets_the_posts_that_went_out_aside_and_keeps_the_booked(db, monkeypatch) -> None:
    from app.infra.db import fetch_one
    from app.services import teacher

    monkeypatch.setattr(teacher, "render_now", lambda *a, **k: {"queued": 3})
    for q, when in (("q1", NOW - timedelta(days=1)), ("q2", NOW + timedelta(days=2))):
        se._plan_post({"question_id": q, "curriculum": {}}, "facebook", when, "me")
    se.record_attempt(se._post_id("q1", "facebook"), ok=True)
    out = se.relaunch()
    assert out["archived_posts"] == 1 and out["queued"] == 3
    assert fetch_one("SELECT COUNT(*) AS n FROM social_posts WHERE question_id = 'q1'")["n"] == 0
    assert fetch_one("SELECT COUNT(*) AS n FROM social_posts WHERE question_id = 'q2'")["n"] == 1
    assert fetch_one("SELECT COUNT(*) AS n FROM social_posts_history WHERE question_id = 'q1'")["n"] == 1
