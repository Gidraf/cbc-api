import csv
import io
import zipfile
from datetime import date
from unittest import mock

from app.services import social_export as X


def test_posts_are_spread_over_days_and_times():
    when = X.plan(5, start=date(2026, 10, 20), per_day=2, times=["07:00", "19:00"])
    assert [f"{w:%m-%d %H:%M}" for w in when] == ["10-20 07:00", "10-20 19:00", "10-21 07:00", "10-21 19:00", "10-22 07:00"]
    assert when[0].utcoffset().total_seconds() == 3 * 3600   # East Africa Time


def _post(n):
    q = {"question_id": f"q{n}", "curriculum": {"grade": "grade-9", "subject": "Mathematics", "sub_strand": "Integers"}}
    return {"question_id": f"q{n}", "status": "ready", "url": f"https://x/api/v1/assets/cbc-assets/social/q{n}/k.mp4",
            "thumbnail_url": f"https://x/api/v1/assets/cbc-assets/social/q{n}/k.jpg", "post": f"Caption {n}", "question": q}


def test_the_zip_holds_videos_captions_and_a_schedule():
    planned = []
    with mock.patch.object(X, "ready_posts", return_value=[_post(1), _post(2), _post(3)]), \
         mock.patch("app.infra.storage.object_storage.read_bytes", side_effect=lambda name: b"bytes:" + name.encode()), \
         mock.patch.object(X, "_plan_post", side_effect=lambda q, p, at, by: planned.append((q["question_id"], p))):
        path, count = X.export_zip("grade-9", "Mathematics", "Integers", start=date(2026, 10, 20), per_day=1,
                                   times=["19:00"], platforms=["tiktok", "youtube"])
    assert count == 3
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        assert {"schedule.csv", "README.txt"} <= names
        assert "videos/001_2026-10-20_1900_integers.mp4" in names and "captions/003_2026-10-22_1900_integers.txt" in names
        rows = list(csv.DictReader(io.StringIO(zf.read("schedule.csv").decode())))
    assert [r["date"] for r in rows] == ["2026-10-20", "2026-10-21", "2026-10-22"]
    assert rows[0]["platforms"] == "tiktok youtube" and rows[1]["caption"] == "Caption 2"
    assert len(planned) == 6   # each post planned on each platform for the tracker


def test_platforms_and_topics_are_compared_on_what_posted():
    posts = [
        {"platform": "tiktok", "sub_strand": "Integers", "posted_at": "x", "views": 1000, "likes": 80, "comments": 15, "shares": 5, "saves": 0, "follows": 12, "watch_pct": 60},
        {"platform": "tiktok", "sub_strand": "Integers", "posted_at": "x", "views": 3000, "likes": 200, "comments": 40, "shares": 10, "saves": 0, "follows": 30, "watch_pct": 40},
        {"platform": "youtube", "sub_strand": "Integers", "posted_at": "x", "views": 500, "likes": 20, "comments": 5, "shares": 0, "saves": 0, "follows": 1, "watch_pct": None},
        {"platform": "youtube", "sub_strand": "Indices", "posted_at": None, "views": 0, "likes": 0, "comments": 0, "shares": 0, "saves": 0, "follows": 0, "watch_pct": None},
    ]
    s = X.summary(posts)
    tt = s["by_platform"]["tiktok"]
    assert tt["posts"] == 2 and tt["views_per_post"] == 2000 and tt["engagement_rate"] == 8.75
    assert tt["follows_per_1000_views"] == 10.5 and tt["avg_watch_pct"] == 50
    assert s["by_platform"]["youtube"]["planned"] == 1 and s["overall"]["posts"] == 3
    assert s["top"][0]["views"] == 3000


from datetime import datetime, timedelta, timezone

RULES = {"enabled": True, "daily_cap": 30, "platform_cap": 8, "min_gap_minutes": 20,
         "hours": {"start": "06:00", "end": "22:00"}, "platforms": ["tiktok", "instagram", "youtube", "linkedin"]}
NOON = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)   # 12:00 in Nairobi
DUE = [{"post_id": "a", "platform": "tiktok"}, {"post_id": "b", "platform": "instagram"}]


def test_the_poster_gets_one_post_when_the_rules_allow():
    post, why = X.decide(NOON, RULES, posted_today=[], last_posted_at=None, candidates=DUE, logged_out=set())
    assert post["post_id"] == "a" and why == ""


def test_never_more_than_thirty_a_day_nor_too_close_together():
    full = [{"platform": "tiktok"}] * 30
    assert X.decide(NOON, RULES, posted_today=full, last_posted_at=None, candidates=DUE, logged_out=set())[0] is None
    post, why = X.decide(NOON, RULES, posted_today=[], last_posted_at=NOON - timedelta(minutes=5), candidates=DUE, logged_out=set())
    assert post is None and "16 min" in why


def test_outside_hours_or_switched_off_nothing_goes_out():
    night = datetime(2026, 10, 20, 20, 30, tzinfo=timezone.utc)   # 23:30 in Nairobi
    assert X.decide(night, RULES, posted_today=[], last_posted_at=None, candidates=DUE, logged_out=set())[0] is None
    assert X.decide(NOON, {**RULES, "enabled": False}, posted_today=[], last_posted_at=None, candidates=DUE, logged_out=set())[0] is None


def test_a_logged_out_or_full_platform_is_passed_over():
    post, _ = X.decide(NOON, RULES, posted_today=[], last_posted_at=None, candidates=DUE, logged_out={"tiktok"})
    assert post["post_id"] == "b"
    tiktok_full = [{"platform": "tiktok"}] * 8
    post, _ = X.decide(NOON, RULES, posted_today=tiktok_full, last_posted_at=None, candidates=DUE, logged_out=set())
    assert post["post_id"] == "b"
    post, why = X.decide(NOON, RULES, posted_today=[], last_posted_at=None, candidates=DUE, logged_out={"tiktok", "instagram"})
    assert post is None and "needs a login" in why


def test_the_cap_can_never_be_set_above_thirty():
    with mock.patch("app.services.platform_settings.get", side_effect=lambda k, d=None: 500 if k == "poster_daily_cap" else d):
        assert X.poster_rules()["daily_cap"] == 30
