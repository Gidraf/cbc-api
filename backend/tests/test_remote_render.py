"""Videos rendered on the owner's Mac, beside the server's own render worker."""
from __future__ import annotations

import os

import pytest

from app.services import remote_render

DB = os.getenv("CBC_TEST_PHASE2_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB, reason="set CBC_TEST_PHASE2_DATABASE_URL to an empty Postgres database")
VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"x" * 20_000


@pytest.fixture()
def db(monkeypatch):
    from sqlalchemy import create_engine, text

    from app.infra import db as infra
    from app.infra import storage
    from app.services import platform_settings, whiteboard

    engine = create_engine(DB)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    monkeypatch.setattr(infra, "get_engine", lambda: engine)
    monkeypatch.setattr(platform_settings, "_load", lambda: {})
    infra.run_migrations()
    saved = {}
    monkeypatch.setattr(storage.object_storage, "save_bytes", lambda n, b, m="": saved.setdefault(n, b) and f"/assets/{n}")
    monkeypatch.setattr(storage.object_storage, "save_text", lambda n, t: None)
    monkeypatch.setattr(whiteboard, "record_video", lambda *a, **k: None)
    monkeypatch.setattr(remote_render, "_spec", lambda job: {"kind": job["kind"], "question_id": "q1", "prefix": "social",
                                                            "key": "k1", "data": {}, "voice": "v"})
    yield saved
    engine.dispose()


def _job(job_id: str, priority: int = 0) -> None:
    from app.infra.db import execute

    execute("""INSERT INTO jobs (job_id, kind, status, payload) VALUES (:id, 'social', 'queued', CAST(:p AS jsonb))""",
            {"id": job_id, "p": '{"question_id": "q1"' + (f', "priority": {priority}' if priority else "") + "}"})


@needs_db
def test_the_mac_takes_the_most_urgent_video_and_it_is_never_taken_twice(db) -> None:
    from app.infra.db import fetch_one

    _job("a"); _job("b", priority=8)
    got = remote_render.claim("mac-test")
    assert got["job"]["job_id"] == "b" and got["spec"]["key"] == "k1"
    row = fetch_one("SELECT status, live FROM jobs WHERE job_id = 'b'")
    assert row["status"] == "running" and row["live"]["where"] == "mac"
    assert remote_render.claim("mac-test")["job"]["job_id"] == "a"
    assert remote_render.claim("mac-test")["job"] is None


@needs_db
def test_a_mac_render_does_not_take_the_servers_render_slot(db) -> None:
    from app.infra.db import fetch_one
    from app.services import job_queue

    _job("a"); _job("b")
    remote_render.claim("mac-test")                       # b or a, running on the Mac
    left = fetch_one("SELECT job_id FROM jobs WHERE status = 'queued'")["job_id"]
    assert not job_queue.scope_is_busy(left), "the server may still render one beside it"


@needs_db
def test_what_the_mac_sends_is_stored_under_the_servers_names(db) -> None:
    from app.infra.db import fetch_one

    _job("a")
    remote_render.claim("mac-test")
    with pytest.raises(ValueError):
        remote_render.done("a", b"not a video", None)
    out = remote_render.done("a", VIDEO, b"jpeg", 61.5)
    assert set(db) == {"social/q1/k1.mp4", "social/q1/k1.jpg"} and out["rendered_on"] == "mac-test"
    assert fetch_one("SELECT status FROM jobs WHERE job_id = 'a'")["status"] == "done"
    with pytest.raises(ValueError):
        remote_render.done("a", VIDEO, None)              # finished: not held any more


@needs_db
def test_a_failed_mac_render_goes_back_then_fails_for_good(db, monkeypatch) -> None:
    from app.infra.db import fetch_one
    from app.services import job_queue

    monkeypatch.setattr(job_queue, "dispatch", lambda job_id: "test")
    _job("a")
    for n in range(remote_render.TRIES):
        assert remote_render.claim("mac-test")["job"]["job_id"] == "a"
        out = remote_render.fail("a", "chrome crashed", worker="mac-test")
        assert out["status"] == ("failed" if n == remote_render.TRIES - 1 else "queued")
    assert "chrome crashed" in fetch_one("SELECT error FROM jobs WHERE job_id = 'a'")["error"]


@needs_db
def test_a_heartbeat_keeps_the_job_and_reports_progress(db) -> None:
    from app.infra.db import fetch_one

    _job("a")
    remote_render.claim("mac-test")
    assert remote_render.heartbeat("a", "draw", 42.0)
    assert fetch_one("SELECT live FROM jobs WHERE job_id = 'a'")["live"]["pct"] == 42.0
    assert not remote_render.heartbeat("nope", "draw", 1)
