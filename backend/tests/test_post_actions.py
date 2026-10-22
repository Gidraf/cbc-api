"""A post's own controls in the Library: reschedule, cancel, post now / again, find its link, comment or
share now, and campaigns pinned to posts (two at a time) until their goal in views."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import social
from app.services import social_export as se

from tests.test_campaign import NOW, _post, db, needs_db  # noqa: F401 — the fixture

_ = db


def _booked(qid: str, at: datetime) -> str:
    se._plan_post({"question_id": qid, "curriculum": {}}, "facebook", at, "auto-book")
    return se._post_id(qid, "facebook")


@needs_db
def test_a_booked_post_can_be_moved_or_unbooked(db) -> None:  # noqa: F811
    from app.infra.db import fetch_one

    pid = _booked("q1", NOW - timedelta(hours=3))                       # missed: its time has passed
    later = NOW + timedelta(days=1)
    assert se.post_action(pid, "reschedule", at=later, now=NOW)["ok"]
    assert fetch_one("SELECT scheduled_for FROM social_posts WHERE post_id = :id", {"id": pid})["scheduled_for"] == later
    assert se.post_action(pid, "cancel", now=NOW)["ok"]
    assert fetch_one("SELECT 1 AS x FROM social_posts WHERE post_id = :id", {"id": pid}) is None
    out = _post("q2", NOW - timedelta(days=1), 10)
    assert not se.post_action(out, "cancel", now=NOW)["ok"] and not se.post_action(out, "reschedule", at=later, now=NOW)["ok"]


@needs_db
def test_post_again_keeps_the_old_post_in_its_history(db, monkeypatch) -> None:  # noqa: F811
    from app.infra.db import fetch_one

    pid = _post("q3", NOW - timedelta(days=2), 400)
    monkeypatch.setattr(se, "post_question", lambda qid, **k: {"ok": True, "post_id": "new"})
    r = se.post_action(pid, "repost", now=NOW)
    assert r["ok"] and r["send"]
    assert fetch_one("SELECT views FROM social_posts_history WHERE post_id = :id", {"id": pid})["views"] == 400
    assert fetch_one("SELECT 1 AS x FROM social_posts WHERE post_id = :id", {"id": pid}) is None


@needs_db
def test_share_and_comment_now_go_before_the_campaign(db, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(se, "_campaign_items", lambda qid: [{"text": f"{qid} comment {k}"} for k in range(40)])
    monkeypatch.setattr(social, "status", lambda qid, q=None, **k: {"thread": {"find": qid}})
    monkeypatch.setattr(se, "groups_for", lambda platform, at, rules, audience="learners": ["Group A", "Group B"])
    db["campaign_enabled"] = False                                     # off — what is asked for now still goes
    pid = _post("q4", NOW - timedelta(days=1), 30)
    assert se.post_action(pid, "share_now", now=NOW)["ok"]
    job = se.campaign_next(NOW + timedelta(minutes=1))["job"]
    assert job["stage"] == "share" and job["post_id"] == pid and job["groups"] == ["Group A", "Group B"]
    assert se.post_action(pid, "comment_now", now=NOW)["ok"]
    job = se.campaign_next(NOW + timedelta(minutes=2))["job"]
    assert job["stage"] == "campaign" and job["comments"] == ["q4 comment 4"]
    assert se.campaign_next(NOW + timedelta(minutes=3))["job"] is None    # taken once, not again
    db["campaign_enabled"] = True


@needs_db
def test_two_campaigns_at_a_time_each_until_its_goal(db, monkeypatch) -> None:  # noqa: F811
    from app.infra.db import execute

    monkeypatch.setattr(se, "_campaign_items", lambda qid: [{"text": f"{qid} comment {k}"} for k in range(40)])
    monkeypatch.setattr(social, "status", lambda qid, q=None, **k: {"thread": {"find": qid}})
    monkeypatch.setattr(se, "groups_for", lambda platform, at, rules, audience="learners": ["Group A"])
    db["campaign_enabled"] = False
    a, b, c = (_post(q, NOW - timedelta(days=1), 100) for q in ("qa", "qb", "qc"))
    assert se.post_action(a, "campaign_start", goal=1000, now=NOW)["ok"]
    assert se.post_action(b, "campaign_start", goal=1000, now=NOW)["ok"]
    assert "2 campaigns" in se.post_action(c, "campaign_start", now=NOW)["error"]
    first = se.campaign_next(NOW + timedelta(minutes=1))["job"]
    assert first["post_id"] == a and first["stage"] == "share", "a new campaign is shared to groups first"
    se.campaign_result(a, stage="share", ok=True, now=NOW + timedelta(minutes=1), groups=["Group A"])
    nxt = se.campaign_next(NOW + timedelta(minutes=2))["job"]
    assert nxt["post_id"] == b and nxt["stage"] == "share"
    se.campaign_result(b, stage="share", ok=True, now=NOW + timedelta(minutes=2), groups=["Group A"])
    then = se.campaign_next(NOW + timedelta(minutes=5))["job"]
    assert then["post_id"] == a and then["stage"] == "campaign", "then comments, the shares done for now"
    execute("UPDATE social_posts SET views = 1200 WHERE post_id = :id", {"id": a})
    assert se.campaign_next(NOW + timedelta(minutes=9))["job"]["post_id"] == b, "the goal reached: it ends"
    assert [r["post_id"] for r in se.campaigns_running()] == [b]
    assert se.post_action(c, "campaign_start", now=NOW)["ok"], "a place is free again"
    db["campaign_enabled"] = True


@needs_db
def test_find_its_link_starts_a_profile_scan(db) -> None:  # noqa: F811
    from app.infra.db import execute

    pid = _post("q5", NOW - timedelta(days=1), 10)
    execute("UPDATE social_posts SET url = '' WHERE post_id = :id", {"id": pid})
    assert not se.reconcile_due(NOW)
    assert se.post_action(pid, "find_link", now=NOW)["ok"]
    assert se.reconcile_due(NOW)
    se.reconcile_job(NOW)
    assert not se.reconcile_due(NOW + timedelta(minutes=1))
