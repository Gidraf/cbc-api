from datetime import date
from pathlib import Path

import pytest

from app.services import devcast as D
from app.services import devcast_series as S


def test_there_are_ten_series_of_thirty():
    assert len(S.SERIES) == 10
    assert all(len(s["episodes"]) == 30 for s in S.SERIES)
    ids = [e["id"] for e in S.episodes()]
    assert len(ids) == 300 == len(set(ids))


def test_every_series_shows_the_idea_the_code_and_the_finished_system():
    for s in S.SERIES:
        kinds = {k for k, _, _ in s["episodes"]}
        assert kinds == {"I", "D", "C", "B"}, s["id"]


def test_a_post_names_its_part_and_the_next_one():
    first = S.episodes("excel-vba-games")[3]
    assert "Part 4/30" in first["post"]
    assert "Follow for part 5: Parsing JSON in VBA" in first["post"]
    last = S.episodes("excel-vba-games")[-1]
    assert "What should I build next?" in last["post"]


def test_the_calendar_never_runs_one_series_all_day_and_keeps_to_the_slots():
    rows = S.calendar(date(2026, 11, 2), per_day=5)
    assert len(rows) == 300
    first_day = [r for r in rows if r["date"] == "2026-11-02"]
    assert len(first_day) == 5 and len({r["series"] for r in first_day}) == 5
    assert [r["time"] for r in first_day] == ["07:30", "12:30", "17:30", "20:00", "21:30"]
    assert rows[-1]["date"] == "2026-12-31"          # 300 posts at five a day is sixty days
    for s in S.SERIES:
        eps = [r["episode"] for r in rows if r["series"] == s["id"]]
        assert eps == list(range(1, 31))           # each series in its own order


@pytest.mark.parametrize("eid", sorted(S.SCRIPTS))
def test_the_written_scripts_are_valid_and_match_their_episode(eid):
    script = D.validate(S.SCRIPTS[eid])
    assert script["id"] == eid
    titles = {e["id"]: e["title"] for e in S.episodes()}
    assert script["title"] == titles[eid]


@pytest.mark.parametrize("eid", sorted(S.SCRIPTS))
def test_highlighted_lines_exist(eid):
    for sc in S.SCRIPTS[eid]["scenes"]:
        if sc["scene"] == "code":
            assert all(1 <= n <= len(sc["code"].split("\n")) for n in sc.get("highlight", []))


@pytest.mark.parametrize("bad, why", [
    ({"scenes": []}, "1–24 scenes"),
    ({"scenes": [{"scene": "dance", "say": "hi"}]}, "scene is one of"),
    ({"scenes": [{"scene": "code", "say": "hi"}]}, "needs code"),
    ({"scenes": [{"scene": "code", "code": "x", "lang": "cobol"}]}, "lang is one of"),
    ({"format": "tiktok", "scenes": [{"scene": "title"}]}, "format is one of"),
])
def test_a_bad_script_says_what_is_wrong(bad, why):
    with pytest.raises(ValueError, match=why):
        D.validate(bad)


def test_the_id_cannot_walk_out_of_its_folder():
    assert D.validate({"id": "../../etc/passwd", "scenes": [{"scene": "title"}]})["id"] == "etc-passwd"


def test_the_engine_draws_every_scene_the_service_accepts():
    engine = (Path(__file__).resolve().parents[1] / "app" / "static" / "devcast.js").read_text()
    for scene in D.SCENES:
        assert f'"{scene}"' in engine, scene


def test_the_page_is_self_contained_and_the_script_cannot_close_its_tag(monkeypatch):
    monkeypatch.setattr(D, "_brand", lambda: {"handle": "@dev", "website": "x.dev"})
    monkeypatch.setattr(D, "_repo", lambda: "cbc-api")
    script = {"id": "t", "scenes": [{"scene": "code", "code": "</script><script>alert(1)</script>", "say": "x"}]}
    live = D.page(script)
    assert "<script src=" not in live and "window.__seek" in live and "__dc.toggle()" in live
    data = live.split("window.DC_DATA = ", 1)[1].split(";</script>", 1)[0]
    assert "</script" not in data
    render = D.page(script, render=True, durations=[2.0])
    assert "__dc.toggle()" not in render and 'class="square render"' in render
    assert "width:1080px;height:1080px" in render
    wide = D.page({**script, "format": "landscape"}, render=True)
    assert "width:1920px;height:1080px" in wide


# ── posting to Facebook and LinkedIn ─────────────────────────────────────────

def test_facebook_gets_its_own_developer_caption():
    ep = S.episodes("excel-vba-games")[3]
    fb, li = ep["facebook_post"], ep["post"]
    assert fb != li and "Calling a REST API from VBA" in fb
    assert "#developers" in fb and "#VBA" in fb and "#developers" not in li
    assert "Follow for part 5: Parsing JSON in VBA" in fb


def test_the_poster_sees_a_written_episode_and_waits_for_an_unwritten_one(monkeypatch):
    monkeypatch.setattr(D, "status", lambda script, voice="": {"status": "ready", "url": "https://x/v.mp4"})
    ready = S.media("devcast:excel-vba-games-04", "facebook")
    assert ready["status"] == "ready" and "#developers" in ready["post"]
    assert ready["title"] == "Calling a REST API from VBA"
    assert S.media("devcast:excel-vba-games-05", "linkedin")["status"] == "none"
    assert S.media("devcast:nope-01", "facebook")["status"] == "none"


@pytest.fixture
def poster_db(monkeypatch):
    from app.infra import db

    seen = {"sql": [], "inserts": [], "booked": [], "last": None}

    def fetch_all(sql, params=None):
        seen["sql"].append((sql, params or {}))
        if "audience = 'developers'" in sql and "SELECT question_id, platform" in sql:
            return seen["booked"]
        return []

    def fetch_one(sql, params=None):
        seen["sql"].append((sql, params or {}))
        return None if "poster_groups" in sql else {"t": seen["last"]}

    monkeypatch.setattr(db, "fetch_all", fetch_all)
    monkeypatch.setattr(db, "fetch_one", fetch_one)
    monkeypatch.setattr(db, "execute", lambda sql, params=None: seen["inserts"].append(params))
    return seen


def test_a_developer_post_is_shared_only_to_developer_groups(poster_db):
    from datetime import datetime, timezone

    from app.services import social_export as X

    X.groups_for("facebook", datetime(2026, 11, 2, 9, tzinfo=timezone.utc), {"group_shares_per_day": 2},
                 "developers")
    picks = [p for sql, p in poster_db["sql"] if "FROM poster_groups" in sql]
    shares = [p for sql, p in poster_db["sql"] if "FROM social_posts" in sql]
    assert picks and picks[0]["a"] == "developers" and shares[0]["a"] == "developers"


def test_the_poster_hands_out_a_developer_post_with_its_caption_and_title(monkeypatch, poster_db):
    from datetime import datetime, timezone

    from app.services import social_export as X

    at = datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc)
    due = [{"post_id": "d1", "platform": "facebook", "question_id": "devcast:excel-vba-games-04",
            "audience": "developers", "attempts": 0, "scheduled_for": at}]
    rules = {"enabled": True, "daily_cap": 30, "platform_cap": 15, "min_gap_minutes": 20,
             "hours": {"start": "06:00", "end": "22:00"}, "platforms": ["facebook"], "ahead_platforms": [],
             "ahead_days": 28, "group_shares_per_day": 0, "group_rest_days": 7}
    monkeypatch.setattr(X, "poster_rules", lambda: rules)
    from app.infra import db

    monkeypatch.setattr(db, "fetch_all", lambda sql, params=None: due if "status IN" in sql else [])
    monkeypatch.setattr(D, "status", lambda script, voice="": {"status": "ready", "url": "https://x/v.mp4"})
    out = X.next_for_poster(datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc))
    post = out["post"]
    assert post["audience"] == "developers" and post["video_url"] == "https://x/v.mp4"
    assert post["title"] == "Calling a REST API from VBA" and "#developers" in post["caption"]


def test_booking_puts_written_episodes_on_both_platforms_a_gap_apart(monkeypatch, poster_db):
    from datetime import datetime, timedelta

    from app.services import social_export as X

    monkeypatch.setattr(X, "poster_rules", lambda: {"min_gap_minutes": 20})
    monkeypatch.setattr(D, "status", lambda script, voice="": {"status": "none", "key": "k"})
    queued = []
    monkeypatch.setattr(D, "enqueue", lambda script, **kw: queued.append(script["id"]))
    poster_db["last"] = datetime(2026, 11, 4, 20, 0, tzinfo=X.EAT)
    out = S.book(start=date(2026, 11, 2), per_day=2)
    assert out["episodes"] == len(S.SCRIPTS) and out["posts"] == 2 * len(S.SCRIPTS)
    assert out["waiting_for_scripts"] == 300 - len(S.SCRIPTS)
    first = [p for p in out["schedule"] if p["id"] == out["schedule"][0]["id"]]
    assert [p["platform"] for p in first] == ["linkedin", "facebook"]
    a, b = (datetime.fromisoformat(p["at"]) for p in first)
    assert b - a == timedelta(minutes=25) and a.date() == date(2026, 11, 5)     # after the last one booked
    rows = [p for p in poster_db["inserts"] if p and "qid" in p]
    assert len(rows) == out["posts"] and all(r["qid"].startswith("devcast:") for r in rows)
    assert sorted(queued) == sorted(S.SCRIPTS)


def test_booking_again_adds_only_what_is_new(monkeypatch, poster_db):
    from app.services import social_export as X

    monkeypatch.setattr(X, "poster_rules", lambda: {"min_gap_minutes": 20})
    monkeypatch.setattr(D, "status", lambda script, voice="": {"status": "ready", "key": "k"})
    poster_db["booked"] = [{"question_id": "devcast:" + eid, "platform": p} for eid in S.SCRIPTS
                           for p in ("linkedin", "facebook")]
    out = S.book(start=date(2026, 11, 2), dry=True)
    assert out["posts"] == 0 and out["booked"] is False


def test_the_learners_calendar_is_not_pushed_back_by_developer_posts():
    import inspect

    from app.services import social_export as X

    assert "audience = 'learners'" in inspect.getsource(X.book_ahead)
