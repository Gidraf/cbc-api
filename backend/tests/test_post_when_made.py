"""Post now on a question whose video is not made: made ahead of the queue, then posted the moment it is ready."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import social_export as X

NOW = datetime(2026, 10, 23, 9, 0, tzinfo=timezone.utc)


def _row(**kw):
    return {"post_id": "p", "handed_at": None, "posted_at": None, "created_by": X.POST_NOW, "scheduled_for": NOW, **kw}


def test_a_post_now_waiting_for_its_video_goes_out_when_it_is_made(monkeypatch) -> None:
    import app.infra.db as db

    sent = []
    monkeypatch.setattr(X, "pull_poster", lambda: {"device": "mac"})
    monkeypatch.setattr(X, "queue_command", lambda *a, **kw: sent.append((a, kw)) or 7)
    monkeypatch.setattr(db, "fetch_one", lambda sql, p: _row())
    assert X.hand_when_made("q1", now=NOW + timedelta(minutes=6)) == 7
    assert sent[0][0][0] == "run_now"


def test_bookings_and_old_or_posted_ones_are_left_alone(monkeypatch) -> None:
    import app.infra.db as db

    monkeypatch.setattr(X, "pull_poster", lambda: {"device": "mac"})
    monkeypatch.setattr(X, "queue_command", lambda *a, **kw: 1)
    for row in (_row(created_by="auto-book"), _row(handed_at=NOW), _row(posted_at=NOW),
                _row(scheduled_for=NOW - timedelta(hours=13)), _row(scheduled_for=NOW + timedelta(days=2))):
        monkeypatch.setattr(db, "fetch_one", lambda sql, p, r=row: r)
        assert X.hand_when_made("q1", now=NOW) is None
    monkeypatch.setattr(db, "fetch_one", lambda sql, p: None)
    assert X.hand_when_made("q1", now=NOW) is None


def test_without_the_mac_poster_the_server_poster_takes_it_in_its_round(monkeypatch) -> None:
    import app.infra.db as db

    monkeypatch.setattr(X, "pull_poster", lambda: None)
    monkeypatch.setattr(db, "fetch_one", lambda sql, p: _row())
    assert X.hand_when_made("q1", now=NOW) is None
