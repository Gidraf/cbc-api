"""The Macs' working hours, and the job that gives every question its social video."""
from __future__ import annotations

import os
from datetime import datetime

import pytest

from app.services import render_hours as h

MON, TUE, WED, SAT, SUN = (datetime(2026, 10, d, 12, 0) for d in (19, 20, 21, 24, 25))


def at(day: datetime, hhmm: str) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return day.replace(hour=hour, minute=minute)


def test_each_day_follows_its_own_rule() -> None:
    s = h.clean({"days": {"mon": {"mode": "hours", "from": "18:00", "to": "23:00"},
                          "tue": {"mode": "hours", "from": "22:00", "to": "06:00"},
                          "wed": {"mode": "idle"}, "sun": {"mode": "off"}}, "idle_minutes": 15})
    assert h.allowed(s, at(MON, "19:00"), None)[0] and not h.allowed(s, at(MON, "09:00"), None)[0]
    assert h.allowed(s, at(TUE, "03:00"), None)[0] and not h.allowed(s, at(TUE, "12:00"), None)[0], "past midnight"
    assert h.allowed(s, WED, 15 * 60)[0] and not h.allowed(s, WED, 60)[0], "only once nobody has used it for 15 minutes"
    assert not h.allowed(s, WED, None)[0], "cannot tell: rests"
    assert not h.allowed(s, SUN, None)[0] and h.allowed(s, SAT, None)[0], "a day not set: always"


def test_a_broken_schedule_means_always() -> None:
    for raw in ("", "{not json", {"days": {"mon": {"mode": "dance", "from": "25:00"}}, "idle_minutes": "x"}):
        s = h.clean(raw)
        assert all(d["mode"] in h.MODES for d in s["days"].values()) and s["idle_minutes"] == 10
    assert h.clean({"days": {"mon": {"mode": "hours", "from": "25:00", "to": "7pm"}}})["days"]["mon"]["from"] == "18:00"


DB = os.getenv("CBC_TEST_PHASE2_DATABASE_URL", "")


@pytest.mark.skipif(not DB, reason="needs an empty Postgres")
def test_the_job_queues_social_videos_for_questions_without_and_never_floods(monkeypatch) -> None:
    from sqlalchemy import create_engine, text

    from app.infra import db as infra
    from app.services import platform_settings, social, video_factory

    engine = create_engine(DB)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    monkeypatch.setattr(infra, "get_engine", lambda: engine)
    monkeypatch.setattr(platform_settings, "_load", lambda: {"social_daily_target": 100})
    infra.run_migrations()
    try:
        monkeypatch.setattr(video_factory, "social_candidates", lambda n: [f"q{k}" for k in range(n)])
        asked = []
        monkeypatch.setattr(social, "enqueue", lambda qid, **k: asked.append(qid) or {"status": "queued"})
        out = video_factory.top_up_social()
        assert out["queued_now"] == video_factory.BATCH and len(asked) == video_factory.BATCH
        monkeypatch.setattr(video_factory, "social_pending", lambda: video_factory.SOCIAL_QUEUE)
        assert video_factory.top_up_social()["queued_now"] == 0, "30 waiting: nothing more until they are made"
    finally:
        engine.dispose()
