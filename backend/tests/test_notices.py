"""The owner is emailed video news: every 100 finished, and unposted ones piling up."""
from __future__ import annotations

import inspect
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.services import mailer, notices

DB = os.getenv("CBC_TEST_PHASE2_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB, reason="set CBC_TEST_PHASE2_DATABASE_URL to an empty Postgres database")
NOW = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)


def test_renders_run_in_the_worker_not_in_the_api() -> None:
    """Rendering in the API's own process starved it: the poster's calls timed out."""
    from app.services import social, social_cards, whiteboard

    for fn in (social.enqueue, whiteboard.enqueue, social_cards.enqueue):
        src = inspect.getsource(fn)
        assert "job_queue.dispatch(job.job_id)" in src and "start_worker()" not in src, fn.__module__


@pytest.fixture()
def db(monkeypatch):
    from sqlalchemy import create_engine, text

    from app.infra import db as infra
    from app.services import platform_settings

    engine = create_engine(DB)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    monkeypatch.setattr(infra, "get_engine", lambda: engine)
    settings = {"notify_email": "owner@example.org", "notify_every_videos": 100, "notify_surplus_at": 20}
    monkeypatch.setattr(platform_settings, "_load", lambda: settings)
    infra.run_migrations()
    sent = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html_body="": sent.append((to, subject, text)) or True)
    yield sent
    engine.dispose()


def _videos(n: int, at: datetime, start: int = 0) -> None:
    from app.infra.db import execute

    for k in range(start, start + n):
        execute("INSERT INTO question_videos (question_id, kind, video_key, object_name, made_at) VALUES (:q, 'social', 'k', 'o', :t)",
                {"q": f"q{k}", "t": at})


@needs_db
def test_the_first_check_sets_the_start_and_100_new_videos_send_the_news(db) -> None:
    _videos(150, NOW - timedelta(days=2))                       # the backlog: never emailed as "new"
    assert notices.video_news(NOW)["sent"] == ["videos_waiting"], "but 150 waiting is a pile-up"
    db.clear()
    _videos(99, NOW + timedelta(minutes=30), start=1000)
    assert "videos_made" not in notices.video_news(NOW + timedelta(hours=1))["sent"]
    _videos(1, NOW + timedelta(minutes=40), start=2000)
    out = notices.video_news(NOW + timedelta(hours=2))
    assert "videos_made" in out["sent"]
    to, subject, text = next(m for m in db if "new videos are ready" in m[1])
    assert to == "owner@example.org" and subject == "100 new videos are ready" and "finished videos are not booked" in text
    assert "videos_made" not in notices.video_news(NOW + timedelta(hours=3))["sent"], "counted afresh from there"


@needs_db
def test_the_pile_up_email_comes_at_most_once_a_day(db) -> None:
    _videos(25, NOW - timedelta(hours=1))
    assert "videos_waiting" in notices.video_news(NOW)["sent"]
    assert "videos_waiting" not in notices.video_news(NOW + timedelta(hours=5))["sent"]
    assert "videos_waiting" in notices.video_news(NOW + timedelta(hours=21))["sent"]


@needs_db
def test_no_address_no_email(db, monkeypatch) -> None:
    from app.services import platform_settings

    monkeypatch.setattr(platform_settings, "_load", lambda: {})
    _videos(300, NOW)
    assert notices.video_news(NOW) == {"sent": [], "reason": "No address set."}
