"""Liking back the people who comment, and choosing which posts get comments."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.services import engage

DB = os.getenv("CBC_TEST_PHASE2_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB, reason="set CBC_TEST_PHASE2_DATABASE_URL to an empty Postgres database")
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)      # noon in Nairobi


def test_profile_links_are_tidied_and_profile_ids_kept() -> None:
    assert engage.profile_url("https://web.facebook.com/jane.doe?comment_id=12&__tn__=R") == "https://www.facebook.com/jane.doe"
    assert engage.profile_url("https://www.facebook.com/profile.php?id=10001234&ref=x") == "https://www.facebook.com/profile.php?id=10001234"
    for bad in ("https://www.facebook.com/groups/abc", "https://www.facebook.com/reel/1", "https://example.com/x", ""):
        assert engage.profile_url(bad) == ""


@pytest.fixture()
def db(monkeypatch):
    from sqlalchemy import create_engine, text

    from app.infra import db as infra
    from app.services import platform_settings, social

    engine = create_engine(DB)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    monkeypatch.setattr(infra, "get_engine", lambda: engine)
    settings = {"engage_enabled": True, "engage_likes_per_day": 10, "engage_likes_per_person": 2}
    monkeypatch.setattr(platform_settings, "_load", lambda: settings)
    monkeypatch.setattr(social, "status", lambda qid, q=None, **k: {"thread": {"find": "What is two plus three"}})
    infra.run_migrations()
    yield settings
    engine.dispose()


def _posted(qid: str, ago: timedelta) -> str:
    from app.infra.db import execute
    from app.services import social_export as se

    se._plan_post({"question_id": qid, "curriculum": {}}, "facebook", NOW - ago, "me")
    pid = se._post_id(qid, "facebook")
    execute("UPDATE social_posts SET posted_at = :t, handed_at = :t WHERE post_id = :id", {"t": NOW - ago, "id": pid})
    return pid


@needs_db
def test_it_reads_a_post_then_likes_each_new_commenter_within_the_day(db) -> None:
    pid = _posted("q1", timedelta(hours=2))
    act = engage.next_action(NOW)["action"]
    assert act["kind"] == "scan" and act["post_id"] == pid and act["find"] == "What is two plus three"
    engage.record("scan", target=pid, likes=3, now=NOW,
                  people=[{"name": "Jane", "url": "https://web.facebook.com/jane?x=1"}, {"name": "Bad", "url": "https://x.com/y"}])
    assert engage.next_action(NOW + timedelta(seconds=30))["action"] is None, "paced: a minute or more between actions"
    later = NOW + timedelta(minutes=5)
    act = engage.next_action(later)["action"]
    assert act == {"kind": "like_person", "url": "https://www.facebook.com/jane", "name": "Jane", "count": 2}
    engage.record("like_person", target=act["url"], likes=2, now=later)
    assert engage.next_action(later + timedelta(minutes=5))["reason"].startswith("Every recent post was read"), \
        "Jane is done and the post was read: nothing to do until it is read again"
    assert engage.today(later)["likes"] == 5


@needs_db
def test_it_stops_at_the_days_number_and_outside_posting_hours(db) -> None:
    _posted("q1", timedelta(hours=2))
    engage.record("scan", target="x", likes=10, now=NOW - timedelta(minutes=10))
    assert "likes are given" in engage.next_action(NOW)["reason"]
    db["engage_likes_per_day"] = 50
    night = datetime(2026, 10, 16, 21, 0, tzinfo=timezone.utc)
    assert engage.next_action(night)["reason"] == "Outside posting hours."
    db["engage_enabled"] = False
    assert engage.next_action(NOW)["reason"] == "Liking back is off."


@needs_db
def test_chosen_posts_get_the_comment_thread(db) -> None:
    from app.infra.db import fetch_all

    a, b = _posted("q1", timedelta(hours=3)), _posted("q2", timedelta(hours=4))
    assert engage.queue_comments([a], now=NOW) == 1
    states = {r["post_id"]: r["comments_state"] for r in fetch_all("SELECT post_id, comments_state FROM social_posts")}
    assert states == {a: "pending", b: ""}
    assert engage.queue_comments([a], now=NOW) == 0, "already on its way"
    assert {p["post_id"] for p in engage.recent_posts(14, now=NOW)} == {a, b}
