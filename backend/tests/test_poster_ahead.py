"""Handing videos to Facebook's own scheduler ahead of time, 100 in a week,
and a rotating share to the owner's groups — never spammy."""
import random
from datetime import date, datetime, timedelta, timezone

from app.services import social_export as X

EAT = timezone(timedelta(hours=3))
NOW = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)          # 12:00 in Nairobi
RULES = {"enabled": True, "daily_cap": 30, "platform_cap": 15, "min_gap_minutes": 20,
         "hours": {"start": "06:00", "end": "22:00"}, "platforms": ["facebook", "tiktok"],
         "ahead_platforms": ["facebook"], "ahead_days": 28, "group_shares_per_day": 2, "group_rest_days": 7}


def row(pid, platform, at):
    return {"post_id": pid, "platform": platform, "question_id": f"q-{pid}", "attempts": 0, "scheduled_for": at}


def test_due_posts_go_first_then_facebook_uploads_ahead_soonest_first():
    rows = [row("due", "tiktok", NOW - timedelta(minutes=5)),
            row("soon", "facebook", NOW + timedelta(minutes=10)),        # too close to schedule: waits, then live
            row("tomorrow", "facebook", NOW + timedelta(days=1)),
            row("tiktok-later", "tiktok", NOW + timedelta(days=1)),      # no scheduler: waits for its time
            row("week", "facebook", NOW + timedelta(days=7)),
            row("too-far", "facebook", NOW + timedelta(days=40))]
    out = X.work_order(NOW, RULES, rows)
    assert [r["post_id"] for r in out] == ["due", "tomorrow", "week"]
    assert not out[0].get("ahead") and out[1]["ahead"] and out[2]["ahead"]


def test_an_upload_ahead_is_not_held_by_the_platform_cap_but_the_day_cap_holds():
    ahead = [{**row("t", "facebook", NOW + timedelta(days=2)), "ahead": True}]
    full_platform = [{"platform": "facebook"}] * 15
    assert X.decide(NOW, RULES, posted_today=full_platform, last_posted_at=None, candidates=ahead, logged_out=set())[0]
    assert X.decide(NOW, RULES, posted_today=[{"platform": "facebook"}] * 30, last_posted_at=None,
                    candidates=ahead, logged_out=set())[0] is None
    assert X.decide(NOW, RULES, posted_today=[], last_posted_at=NOW - timedelta(minutes=5),
                    candidates=ahead, logged_out=set())[0] is None                       # the gap still holds


def test_a_hundred_videos_in_a_week_spread_at_random():
    for seed in range(20):
        counts = X.day_counts(random.Random(seed), 7, 5, 15, total=100)
        assert sum(counts) == 100 and all(5 <= c <= 15 for c in counts)
    assert sum(X.day_counts(random.Random(1), 7, 5, 15, total=200)) == 105             # as many as fit
    assert X.day_counts(random.Random(1), 3, 5, 15, total=6) == [2, 2, 2] or sum(X.day_counts(random.Random(1), 3, 5, 15, total=6)) == 6


def test_the_rules_keep_the_scheduler_window_and_let_group_sharing_be_off(monkeypatch):
    from app.services import platform_settings

    vals = {"poster_ahead_days": 90, "poster_group_shares_per_day": 0}
    monkeypatch.setattr(platform_settings, "get", lambda k, d=None: vals.get(k, d))
    r = X.poster_rules()
    assert r["ahead_days"] == 29 and r["group_shares_per_day"] == 0 and r["ahead_platforms"] == ["facebook"]


def _db(monkeypatch, shared_times, group):
    from app.infra import db

    calls = []
    monkeypatch.setattr(db, "fetch_all", lambda sql, p=None: [{"t": t} for t in shared_times])
    monkeypatch.setattr(db, "fetch_one", lambda sql, p=None: calls.append(p) or ({"name": group} if group else None))
    return calls


def test_two_group_shares_a_day_one_each_half(monkeypatch):
    morning = datetime(2026, 10, 21, 8, 0, tzinfo=EAT)
    evening = datetime(2026, 10, 21, 19, 0, tzinfo=EAT)
    _db(monkeypatch, [], "Mathematics")
    assert X.groups_for("facebook", morning, RULES) == ["Mathematics"]
    _db(monkeypatch, [morning], "Mathematics")
    assert X.groups_for("facebook", datetime(2026, 10, 21, 11, 0, tzinfo=EAT), RULES) == []     # morning taken
    calls = _db(monkeypatch, [morning], "CBE RESOURCES HUB")
    assert X.groups_for("facebook", evening, RULES) == ["CBE RESOURCES HUB"]
    assert calls[0]["cut"] == evening - timedelta(days=7)                                        # rested a week
    _db(monkeypatch, [morning, evening], "x")
    assert X.groups_for("facebook", datetime(2026, 10, 21, 20, 0, tzinfo=EAT), RULES) == []      # two a day
    assert X.groups_for("tiktok", morning, RULES) == []
    assert X.groups_for("facebook", morning, {**RULES, "group_shares_per_day": 0}) == []


def test_no_group_is_free_so_no_share(monkeypatch):
    _db(monkeypatch, [], None)
    assert X.groups_for("facebook", datetime(2026, 10, 21, 8, 0, tzinfo=EAT), RULES) == []


def test_a_post_handed_to_the_scheduler_is_marked_scheduled_and_its_group_rested(monkeypatch):
    from app.infra import db

    seen = []
    monkeypatch.setattr(db, "execute", lambda sql, p=None: seen.append((sql, p)))
    monkeypatch.setattr(db, "fetch_one", lambda sql, p=None: {"platform": "facebook", "posted_at": NOW + timedelta(days=3)})
    out = X.record_attempt("sp1", ok=True, scheduled=True, groups=["Mathematics"])
    assert out["scheduled"] and out["groups"] == ["Mathematics"]
    sql, p = seen[0]
    assert "COALESCE(scheduled_for, NOW())" in sql and "handed_at = NOW()" in sql and p["st"] == "scheduled"
    assert "poster_groups" in seen[1][0] and seen[1][1]["n"] == "Mathematics" and seen[1][1]["t"] == NOW + timedelta(days=3)
    seen.clear()
    X.record_attempt("sp2", ok=True)
    assert "COALESCE(posted_at, NOW())" in seen[0][0] and seen[0][1]["st"] == "posted" and len(seen) == 1


def _poster_world(monkeypatch, rows, groups_answers):
    from app.infra import db
    from app.services import social, whiteboard

    seen = []
    answers = list(groups_answers)
    monkeypatch.setattr(X, "poster_rules", lambda: RULES)
    monkeypatch.setattr(X, "groups_for", lambda platform, at, rules: answers.pop(0) if answers else [])
    monkeypatch.setattr(db, "fetch_all", lambda sql, p=None: rows if "status IN" in sql else [])
    monkeypatch.setattr(db, "fetch_one", lambda sql, p=None: {"t": None})
    monkeypatch.setattr(db, "execute", lambda sql, p=None: seen.append((sql, p)))
    monkeypatch.setattr(social, "status", lambda qid, q=None, voice="": {"status": "ready", "url": "u", "post": "c"})
    monkeypatch.setattr(social, "brand", lambda: {})
    monkeypatch.setattr(whiteboard, "load", lambda qid: {"question_text": "2 + 2"})
    return seen


def test_a_post_picked_for_a_group_share_is_kept_back_and_the_next_is_scheduled(monkeypatch):
    # Facebook refuses to schedule a reel that is shared to a group.
    first_, second = NOW + timedelta(days=1), NOW + timedelta(days=1, hours=2)
    seen = _poster_world(monkeypatch, [row("a", "facebook", first_), row("b", "facebook", second)],
                         [["Mathematics"], []])
    post = X.next_for_poster(NOW)["post"]
    assert post["post_id"] == "b" and post["schedule_at"] == second.astimezone(EAT).isoformat() and post["groups"] == []
    assert any("SET groups" in sql and p["id"] == "a" for sql, p in seen)          # a is reserved for its share
    assert any("poster_groups" in sql and p["n"] == "Mathematics" and p["t"] == first_ for sql, p in seen)


def test_a_reserved_post_goes_out_live_at_its_time_with_its_group(monkeypatch):
    due = {**row("a", "facebook", NOW - timedelta(minutes=2)), "groups": ["Mathematics"]}
    _poster_world(monkeypatch, [due], [])
    post = X.next_for_poster(NOW)["post"]
    assert post["post_id"] == "a" and post["schedule_at"] == "" and post["groups"] == ["Mathematics"]


def test_a_reserved_post_is_never_handed_to_the_scheduler(monkeypatch):
    later = {**row("a", "facebook", NOW + timedelta(days=2)), "groups": ["Mathematics"]}
    _poster_world(monkeypatch, [later], [])
    assert X.next_for_poster(NOW)["post"] is None


def test_uploads_ahead_leave_room_for_the_days_live_shares():
    ahead = [{**row("t", "facebook", NOW + timedelta(days=2)), "ahead": True}]
    live = [row("l", "facebook", NOW - timedelta(minutes=1))]
    actions = [{"platform": "facebook"}] * 28
    assert X.decide(NOW, RULES, posted_today=actions, last_posted_at=None, candidates=ahead, logged_out=set(),
                    live_today=[])[0] is None
    assert X.decide(NOW, RULES, posted_today=actions, last_posted_at=None, candidates=live, logged_out=set(),
                    live_today=[])[0]["post_id"] == "l"
    # the platform cap counts what goes live today, not uploads for later days
    assert X.decide(NOW, RULES, posted_today=[{"platform": "facebook"}] * 20, last_posted_at=None, candidates=live,
                    logged_out=set(), live_today=[{"platform": "facebook"}] * 3)[0]["post_id"] == "l"


def test_summary_counts_only_what_has_gone_out():
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    posts = [{"platform": "facebook", "posted_at": past, "views": 10}, {"platform": "facebook", "posted_at": future, "views": 0}]
    s = X.summary(posts)
    assert s["overall"]["posts"] == 1 and s["overall"]["planned"] == 1
