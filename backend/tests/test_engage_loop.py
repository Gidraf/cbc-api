"""Keeping posts engaged: up to twenty comments a question, added to quiet posts, weakest first."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.services import social
from app.services import social_export as se

DB = os.getenv("CBC_TEST_PHASE2_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB, reason="set CBC_TEST_PHASE2_DATABASE_URL to an empty Postgres database")
NOW = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)      # noon in Nairobi
B = {"hook": "Can you solve this?", "name": "CBC Maths", "handle": "@cbc", "website": "cbc.example", "cta": "Follow",
     "hashtags": "", "countdown": 3, "teacher": "off"}
Q = {"question_id": "q1", "question_text": "What is $2 + 3$?",
     "options": [{"id": "A", "text": "4", "distractor_rationale": "That adds one too few."},
                 {"id": "B", "text": "5", "is_correct": True},
                 {"id": "C", "text": "6", "distractor_rationale": "That counts the 2 twice."}],
     "curriculum": {"grade": "grade-9", "subject": "Mathematics", "sub_strand": "Integers"}}
DATA = {"scenes": [{"scene": "answer", "option": "B", "text": "5"}]}


def test_a_question_carries_up_to_twenty_comments_in_order(monkeypatch) -> None:
    monkeypatch.setattr(social, "_curriculum_row", lambda q: {
        "strand_name": "Numbers", "sub_strand_name": "Integers", "source_pages": [23, 24],
        "slos": [{"text": "add integers"}], "key_inquiry_questions": ["Where do we use integers?"],
        "core_competencies": ["critical thinking"], "values": ["responsibility"]})
    monkeypatch.setattr(social, "_similar", lambda q: {"question_text": "What is 4 + 1?", "options": [{"id": "A", "text": "5"}]})
    lib = social.comment_library(Q, DATA, B)
    assert lib[0].startswith("Choices:") and "Can you solve it?" in lib[1] and lib[2] == "✅ Answer: B) 5"
    assert lib[4] == "📘 From the KICD Grade 9 Mathematics curriculum design — Numbers › Integers (pages 23–24)."
    assert lib[5] == "🎯 What this question tests: add integers"
    assert "❌ Why not A) 4? That adds one too few." in lib and "❌ Why not C) 6? That counts the 2 twice." in lib
    assert any(c.startswith("🔁 Try a similar one: What is 4 + 1?") for c in lib)
    assert any("Tag a friend" in c for c in lib) and len(lib) <= 20


def test_the_answer_step_tries_the_link_then_finds_the_post_by_its_words() -> None:
    import inspect
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "poster"))
    from poster.flows import fb_comments

    src = inspect.getsource(fb_comments.open_post)
    # A reel's own page may hide its comment box: then, by its words on the profile.
    assert 'find_post(page, find, url)' in src and 'find_post(page, find, "", also=also)' in src
    assert "open_post(" in inspect.getsource(fb_comments.comment)
    assert fb_comments.parse_insights("Plays\n1.2K\nReactions\n3")["views"] == 1200


@pytest.fixture()
def db(monkeypatch):
    from sqlalchemy import create_engine, text

    from app.infra import db as infra
    from app.services import platform_settings

    engine = create_engine(DB)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    monkeypatch.setattr(infra, "get_engine", lambda: engine)
    settings = {"engage_boost": True, "engage_boosts_per_day": 2, "engage_boost_hours": 3}
    monkeypatch.setattr(platform_settings, "_load", lambda: settings)
    monkeypatch.setattr(social, "status", lambda qid, q=None, **k: {"thread": {"find": "What is", "find_also": []}})
    monkeypatch.setattr(se, "_extras", lambda qid: ["📘 KICD", "🎯 tests", "❌ why not A"])
    infra.run_migrations()
    yield settings
    engine.dispose()


def _post(qid: str, state: str = "done", hours_ago: float = 5) -> str:
    from app.infra.db import execute

    se._plan_post({"question_id": qid, "curriculum": {}}, "facebook", NOW - timedelta(hours=hours_ago), "me")
    pid = se._post_id(qid, "facebook")
    execute("UPDATE social_posts SET posted_at = :t, handed_at = :t, comments_state = :s WHERE post_id = :id",
            {"t": NOW - timedelta(hours=hours_ago), "s": state, "id": pid})
    return pid


@needs_db
def test_quiet_posts_get_their_next_comment_and_improving_ones_are_left(db) -> None:
    from app.infra.db import fetch_one

    pid = _post("q1")
    job = se.comments_next(NOW)["job"]
    assert job["stage"] == "measure" and job["post_id"] == pid, "never read: read it"
    out = se.comments_result(pid, stage="measure", ok=True, metrics={"views": 100, "reactions": 2, "comments": 4}, now=NOW)
    assert out["boost"], "the first extra comment follows the thread"
    job = se.comments_next(NOW + timedelta(minutes=1))["job"]
    assert job["stage"] == "boost" and job["comments"] == ["📘 KICD"]
    se.comments_result(pid, stage="boost", ok=True, now=NOW + timedelta(minutes=2),
                       metrics={"views": 100, "reactions": 2, "comments": 5})
    row = fetch_one("SELECT comments_state, boost_index, score FROM social_posts WHERE post_id = :id", {"id": pid})
    assert row["comments_state"] == "done" and row["boost_index"] == 1
    # Three hours on: improving → left alone; quiet → the next comment.
    later = NOW + timedelta(hours=3, minutes=5)
    assert not se.comments_result(pid, stage="measure", ok=True, now=later,
                                  metrics={"views": 900, "reactions": 30, "comments": 12})["boost"]
    much_later = later + timedelta(hours=3, minutes=5)
    assert se.comments_result(pid, stage="measure", ok=True, now=much_later,
                              metrics={"views": 900, "reactions": 30, "comments": 12})["boost"]
    assert se.comments_next(much_later + timedelta(minutes=1))["job"]["comments"] == ["🎯 tests"]


@needs_db
def test_the_day_has_a_cap_and_a_post_stops_when_its_comments_run_out(db, monkeypatch) -> None:
    from app.infra.db import execute, fetch_one

    monkeypatch.setattr(se, "reconcile_due", lambda now: False)      # these posts have no links: no deep scroll here

    a, b, c = _post("a"), _post("b"), _post("c")
    execute("UPDATE social_posts SET boost_last_at = :t", {"t": NOW - timedelta(hours=1)})       # two given today
    execute("UPDATE social_posts SET boost_last_at = NULL WHERE post_id = :id", {"id": c})
    assert not se.comments_result(c, stage="measure", ok=True, metrics={"views": 1}, now=NOW)["boost"], "cap of 2 reached"
    execute("UPDATE social_posts SET comments_state = 'boost', comments_next_at = :t, boost_index = 3 WHERE post_id = :id",
            {"t": NOW - timedelta(minutes=1), "id": a})
    assert se.comments_next(NOW)["job"] is None
    assert fetch_one("SELECT comments_state FROM social_posts WHERE post_id = :id", {"id": a})["comments_state"] == "complete"


@needs_db
def test_the_weakest_post_is_read_first(db) -> None:
    from app.infra.db import execute

    strong, weak = _post("strong"), _post("weak")
    execute("UPDATE social_posts SET metrics_at = :t, score = 50 WHERE post_id = :id", {"t": NOW - timedelta(hours=4), "id": strong})
    execute("UPDATE social_posts SET metrics_at = :t, score = 1 WHERE post_id = :id", {"t": NOW - timedelta(hours=4), "id": weak})
    assert se.comments_next(NOW)["job"]["post_id"] == weak


@needs_db
def test_a_due_answer_goes_before_other_posts_first_comments(db) -> None:
    from app.infra.db import execute

    old = _post("old", state="pending", hours_ago=30)          # queued from the backlog, long due
    fresh = _post("fresh", state="part", hours_ago=1)          # its choices went up a minute ago
    execute("UPDATE social_posts SET comments_next_at = :t WHERE post_id = :id", {"t": NOW - timedelta(hours=30), "id": old})
    execute("UPDATE social_posts SET comments_next_at = :t WHERE post_id = :id", {"t": NOW - timedelta(minutes=1), "id": fresh})
    job = se.comments_next(NOW)["job"]
    assert job["post_id"] == fresh and job["stage"] == "later"


def test_the_post_insights_page_is_read_as_facebook_shows_it() -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "poster"))
    from poster.flows import fb_comments

    # As the page reads: labels over their numbers up top, numbers over their labels under Engagement.
    page = ("Post insights\nViews over time\n20\n15\nViews\n22\nViewers\n7\nAverage views per viewer\n2.6\n"
            "6 Engagement\ufeff\n2\nReactions\n0\nClicks\n4\nComments\n0\nShares\nReaction by type\n0")
    got = fb_comments.parse_insights(page)
    assert got == {"views": 22, "viewers": 7, "reactions": 2, "comments": 4, "shares": 0, "engagement": 6}


@needs_db
def test_groups_are_found_then_joined_biggest_first_a_few_a_day(db) -> None:
    from app.infra.db import fetch_one
    from app.services import engage

    db.update({"groups_auto_find": True, "groups_keywords": "CBC Grade 9, KJSEA", "groups_join_per_day": 2,
               "groups_min_members": 1000, "engage_enabled": False})
    act = engage.next_action(NOW)["action"]
    assert act == {"kind": "find_groups", "keyword": "CBC Grade 9", "limit": 30}
    engage.record("find_groups", target="CBC Grade 9", now=NOW, groups=[
        {"name": "Grade 9 Maths Kenya", "url": "https://www.facebook.com/groups/g9maths/?ref=x", "members": 54000, "privacy": "public"},
        {"name": "CBC Parents", "url": "https://www.facebook.com/groups/cbcparents/", "members": 120000, "privacy": "private"},
        {"name": "Tiny group", "url": "https://www.facebook.com/groups/tiny/", "members": 40},
        {"name": "Already in", "url": "https://www.facebook.com/groups/mine/", "members": 9000, "joined": True},
    ])
    mine = fetch_one("SELECT status, enabled FROM poster_groups WHERE name = 'Already in'")
    assert mine == {"status": "member", "enabled": True}, "a group the owner is in is ticked for the shares"
    act = engage.next_action(NOW + timedelta(minutes=1))["action"]
    assert act["kind"] == "join_group" and act["name"] == "CBC Parents", "the biggest first"
    engage.record("join_group", target=act["url"], result="needs_answers", now=NOW + timedelta(minutes=1))
    assert engage.next_action(NOW + timedelta(minutes=10))["action"] is None, "40 minutes between joins"
    act = engage.next_action(NOW + timedelta(minutes=45))["action"]
    assert act["name"] == "Grade 9 Maths Kenya"
    engage.record("join_group", target=act["url"], result="member", now=NOW + timedelta(minutes=45))
    assert fetch_one("SELECT status, enabled FROM poster_groups WHERE name = 'Grade 9 Maths Kenya'") == {"status": "member", "enabled": True}
    assert engage.next_action(NOW + timedelta(hours=3))["action"] is None, "2 a day, and the tiny group is never joined"
    assert engage.next_action(NOW + timedelta(days=1))["action"]["keyword"] == "KJSEA", "the next keyword, the next search"
    over = engage.groups_overview()
    assert over["counts"] == {"member": 2, "requested": 0, "needs_answers": 1, "found": 1}


@needs_db
def test_the_scan_carries_what_it_needs_to_reply_and_remembers_the_replies(db, monkeypatch) -> None:
    from app.services import engage, whiteboard

    db.update({"engage_enabled": True, "engage_replies_per_day": 30, "groups_auto_find": False})
    monkeypatch.setattr(whiteboard, "load", lambda qid: {"question_id": qid, "options": [{"id": "B", "text": "$12$", "is_correct": True}]})
    pid = _post("rq")
    act = engage.next_action(NOW)["action"]
    assert act["kind"] == "scan" and act["reply"]["letter"] == "B" and act["reply"]["answer"] == "12"
    assert "{name}" in act["reply"]["say"]["correct"] and act["reply"]["skip"] == []
    engage.record("scan", target=pid, now=NOW, replied=["k1", "k2"])
    assert sorted(engage.reply_plan({"post_id": pid, "question_id": "rq"}, NOW)["skip"]) == ["k1", "k2"]

