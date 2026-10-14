"""Booking the next weeks for the poster: a random few videos a day at random
times, inside the rules, never the same question twice, topped up on re-runs."""
import random
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services import social_export as X

EAT = timezone(timedelta(hours=3))
RULES = {"enabled": True, "daily_cap": 30, "platform_cap": 15, "min_gap_minutes": 20,
         "hours": {"start": "06:00", "end": "22:00"}, "platforms": ["facebook", "tiktok"],
         "ahead_platforms": [], "ahead_days": 28, "group_shares_per_day": 0, "group_rest_days": 7}
DAYS = [date(2026, 10, 14) + timedelta(days=i) for i in range(25)]


def _minutes(t: datetime) -> int:
    t = t.astimezone(EAT)
    return t.hour * 60 + t.minute


def test_a_days_times_are_random_inside_the_hours_and_never_closer_than_the_gap():
    seen = set()
    for seed in range(30):
        times = X.day_times(random.Random(seed), DAYS[0], 15, RULES)
        assert len(times) == 15 and times == sorted(times)
        assert all(6 * 60 <= _minutes(t) <= 22 * 60 - 15 for t in times)
        assert all((b - a) >= timedelta(minutes=20) for a, b in zip(times, times[1:]))
        assert all(t.astimezone(EAT).date() == DAYS[0] for t in times)
        seen.add(_minutes(times[0]))
    assert len(seen) > 20          # not the same clock every day


def test_the_hours_hold_only_so_many():
    tight = {**RULES, "hours": {"start": "18:00", "end": "20:00"}}
    assert len(X.day_times(random.Random(1), DAYS[0], 50, tight)) == (120 - 15) // 22 + 1


def test_each_day_gets_between_five_and_fifteen_videos_each_on_every_platform():
    videos = [f"q{i}" for i in range(500)]
    cal = X.lay_out(random.Random(7), DAYS, videos, ["facebook"], RULES, low=5, high=15)
    assert len(cal) == 25
    counts = [d["videos"] for d in cal]
    assert all(5 <= n <= 15 for n in counts) and len(set(counts)) > 3      # it varies
    used = [p["question_id"] for d in cal for p in d["posts"]]
    assert len(used) == len(set(used))                                      # never twice
    two = X.lay_out(random.Random(7), DAYS[:3], videos, ["facebook", "tiktok"], RULES, low=5, high=10)
    for d in two:
        by_q: dict[str, set] = {}
        for p in d["posts"]:
            by_q.setdefault(p["question_id"], set()).add(p["platform"])
        assert all(v == {"facebook", "tiktok"} for v in by_q.values())
        assert len(d["posts"]) <= 30


def test_running_out_of_questions_ends_the_calendar_early():
    cal = X.lay_out(random.Random(3), DAYS, [f"q{i}" for i in range(12)], ["facebook"], RULES, low=5, high=5)
    assert [d["videos"] for d in cal] == [5, 5, 2]


def test_the_caps_bound_videos_a_day():
    assert X.videos_a_day_limit({**RULES, "platform_cap": 8}, ["facebook"]) == 8
    assert X.videos_a_day_limit(RULES, ["facebook", "tiktok"]) == 15
    assert X.videos_a_day_limit(RULES, ["facebook", "tiktok", "youtube"]) == 10


@pytest.fixture
def world(monkeypatch):
    from app.infra import db
    from app.services import platform_settings, question_dna, question_rows, social

    w = {"last": None, "booked": set(), "planned": [], "queued": [], "ready": set()}
    bank = [{"question_id": f"q{i}", "status": "draft", "curriculum": {"grade": "grade-9", "subject": "Mathematics"}}
            for i in range(400)]
    w["ready"] = {f"q{i}" for i in range(0, 400, 2)}
    monkeypatch.setattr(platform_settings, "get", lambda k, d=None: {"poster_platform_cap": 15}.get(k, d))
    monkeypatch.setattr(db, "fetch_one", lambda sql, params=None: {"t": w["last"]})
    monkeypatch.setattr(db, "fetch_all", lambda sql, params=None: (
        [{"question_id": q} for q in w["booked"]] if "DISTINCT question_id" in sql else
        [{"platform": "facebook"}] if "poster_state" in sql else []))
    monkeypatch.setattr(question_dna.question_dna_service, "list_questions", lambda **kw: bank)
    monkeypatch.setattr(question_rows, "flatten_all", lambda rows: rows)
    monkeypatch.setattr(social, "status", lambda qid, q=None, voice="": {
        "status": "ready" if qid in w["ready"] else "none", "scenes": 4})
    monkeypatch.setattr(social, "enqueue", lambda qid, **kw: w["queued"].append(qid))
    monkeypatch.setattr(X, "_plan_post", lambda q, platform, at, by: w["planned"].append((q["question_id"], platform, at)))
    return w


def test_booking_fills_the_next_25_days_and_queues_the_videos_not_made_yet(world):
    out = X.book_ahead("grade-9", "Mathematics", today=date(2026, 10, 13), seed=1)
    assert out["first_day"] == "2026-10-14" and out["last_day"] == "2026-11-07" and len(out["days"]) == 25
    assert out["platforms"] == ["facebook"]                         # the one logged in
    assert all(5 <= d["videos"] <= 15 for d in out["days"])
    assert len(world["planned"]) == out["posts"] and out["posts"] == out["videos"]
    assert len(world["queued"]) == out["to_render"] and not set(world["queued"]) & world["ready"]
    first_day = [q for q, _, at in world["planned"] if at.astimezone(EAT).date() == date(2026, 10, 14)]
    assert all(q in world["ready"] for q in first_day)               # finished videos go first


def test_a_dry_run_books_nothing(world):
    out = X.book_ahead("grade-9", "Mathematics", today=date(2026, 10, 13), seed=1, dry=True)
    assert out["booked"] is False and out["posts"] > 0
    assert world["planned"] == [] and world["queued"] == []


def test_running_again_tops_up_after_the_last_booked_day(world):
    world["last"] = datetime(2026, 10, 27, 19, 0, tzinfo=EAT)        # two weeks in
    world["booked"] = {f"q{i}" for i in range(100)}
    out = X.book_ahead("grade-9", "Mathematics", today=date(2026, 10, 13), seed=2)
    assert out["first_day"] == "2026-10-28" and out["last_day"] == "2026-11-07"
    assert not {q for q, _, _ in world["planned"]} & world["booked"]


def test_nothing_to_add_when_already_booked_far_enough(world):
    world["last"] = datetime(2026, 11, 10, 9, 0, tzinfo=EAT)
    out = X.book_ahead("grade-9", "Mathematics", today=date(2026, 10, 13), seed=2)
    assert out["days"] == [] and "Already booked through" in out["notes"][0] and world["planned"] == []


def test_asking_for_more_than_the_caps_allow_says_so(world, monkeypatch):
    from app.services import platform_settings

    monkeypatch.setattr(platform_settings, "get", lambda k, d=None: 8 if k == "poster_platform_cap" else d)
    out = X.book_ahead("grade-9", "Mathematics", today=date(2026, 10, 13), seed=3, dry=True)
    assert all(5 <= d["videos"] <= 8 for d in out["days"]) and "At most 8 videos a day" in out["notes"][0]


def test_the_poster_passes_over_a_post_whose_video_is_not_made(monkeypatch):
    from app.infra import db
    from app.services import social, whiteboard

    at = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
    due = [{"post_id": "a", "platform": "facebook", "question_id": "slow", "attempts": 0, "scheduled_for": at},
           {"post_id": "b", "platform": "facebook", "question_id": "done", "attempts": 0, "scheduled_for": at}]
    monkeypatch.setattr(X, "poster_rules", lambda: {**RULES, "platforms": ["facebook"]})
    monkeypatch.setattr(db, "fetch_all", lambda sql, params=None: due if "status IN" in sql else [])
    monkeypatch.setattr(db, "fetch_one", lambda sql, params=None: {"t": None})
    monkeypatch.setattr(social, "status", lambda qid, q=None, voice="": (
        {"status": "ready", "url": "https://x/v.mp4", "post": "caption"} if qid == "done" else {"status": "queued"}))
    monkeypatch.setattr(social, "brand", lambda: {"hook": "Try it!"})
    monkeypatch.setattr(whiteboard, "load", lambda qid: {"question_text": "2 + 2"})
    out = X.next_for_poster(datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc))
    assert out["post"]["post_id"] == "b"
