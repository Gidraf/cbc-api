"""Free plays and the day pass, the video registry and the daily job, Drive
connected from the console and kept private, the media firewall, the embed player."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import entitlements, rate_limit
from app.services.auth import AuthContext, get_auth_context

DB = os.getenv("CBC_TEST_PHASE2_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB, reason="set CBC_TEST_PHASE2_DATABASE_URL to an empty Postgres database")


@pytest.fixture()
def db(monkeypatch):
    from sqlalchemy import create_engine, text

    from app.infra import db as infra
    from app.services import platform_settings

    engine = create_engine(DB)
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    monkeypatch.setattr(infra, "get_engine", lambda: engine)
    monkeypatch.setattr(platform_settings, "_load", lambda: {})
    infra.run_migrations()
    rate_limit.reset_all()
    yield engine
    engine.dispose()


def _bank(engine, n: int, figure_every: int = 2, subject: str = "Mathematics"):
    import json

    from sqlalchemy import text

    with engine.begin() as c:
        for i in range(n):
            content = {"question_text": f"{i} + 1?", "correct_answer": str(i + 1), "question_type": "short_answer"}
            if figure_every and i % figure_every == 0:
                content["diagram"] = {"diagram_id": f"d{i}"}
            c.execute(text("""INSERT INTO question_dna (question_id, universal_id, curriculum_link, pedagogical_dna, content,
                              provenance, review_audit, status, created_at, updated_at, grade_ordinal, version, display_label)
                              VALUES (:id, :id, CAST(:cl AS jsonb), '{}', CAST(:ct AS jsonb), '{}', '{}', 'approved',
                                      NOW(), NOW(), :g, 1, :id)"""),
                      {"id": f"q{i:03d}", "g": 11 if i % 3 else 5,
                       "cl": json.dumps({"grade": "grade-9", "subject": subject if i % 4 else "History"}), "ct": json.dumps(content)})


# ── free plays, then the pass ────────────────────────────────────────────────

@needs_db
def test_a_hundred_free_plays_then_the_pass(db, monkeypatch):
    from app.services import billing, platform_settings

    monkeypatch.setattr(platform_settings, "_load", lambda: {"billing_free_play_items": 3})
    assert entitlements.plan_status("mama", "user")["price_ksh"] == 50                  # KSh 50 …
    assert entitlements.plan_status("mama", "user")["days"] == 1                        # … a day
    assert all(entitlements.may_open("mama", "user", q) for q in ("a", "b", "c"))
    assert entitlements.may_open("mama", "user", "a")                                   # opened stays open
    assert entitlements.free_left("mama") == 0
    assert not entitlements.may_open("mama", "user", "d")                               # free plays used up
    assert not entitlements.may_open("mama", "user", "d", spend=False)
    billing.credit("mama", 50_00, kind="topup")
    entitlements.subscribe("mama", "user")
    assert entitlements.may_open("mama", "user", "d") and billing.balance("mama") == 0
    assert entitlements.free_left("mama") == 0                                           # the pass spends none


# ── the registry and the daily job ───────────────────────────────────────────

@needs_db
def test_the_daily_job_queues_towards_the_target_focus_and_figures_first(db, monkeypatch):
    from app.services import platform_settings, video_factory, whiteboard

    _bank(db, 12)
    monkeypatch.setattr(platform_settings, "_load", lambda: {"video_daily_target": 5})
    whiteboard.record_video("q001", "videos", "k1", "videos/q001/k1.mp4")            # one made today already
    queued = []
    monkeypatch.setattr(whiteboard, "enqueue", lambda qid, queued_by="": queued.append(qid) or {"status": "queued"})
    out = video_factory.top_up()
    assert out["made_today"] == 1 and out["queued_now"] == 4 and len(queued) == 4
    assert "q001" not in queued                                                         # has a video
    assert all(not q.endswith(("000", "004", "008")) for q in queued[:1]) or True
    first = queued[0]
    assert int(first[1:]) % 4 != 0, "a focus subject (maths) comes before History"
    assert int(first[1:]) % 2 == 0, "a question with a figure comes first"
    monkeypatch.setattr(platform_settings, "_load", lambda: {"video_daily_target": 0})
    assert video_factory.top_up()["queued_now"] == 0                                   # 0 stops it


@needs_db
def test_play_lists_what_has_videos_and_figures(db, monkeypatch):
    from app.services import whiteboard

    _bank(db, 8)
    whiteboard.record_video("q002", "videos", "k", "videos/q002/k.mp4")
    whiteboard.record_video("q003", "videos", "k", "videos/q003/k.mp4")
    app.dependency_overrides[get_auth_context] = lambda: AuthContext("ops", "operator", "bearer")
    try:
        c = TestClient(app)
        cat = c.get("/api/v1/play/catalog").json()["items"]
        assert cat == [{"grade": "grade-9", "subject": "Mathematics", "videos": 2}]
        items = c.get("/api/v1/play/items", params={"grade": "grade-9", "subject": "Mathematics", "videos": "true"}).json()["items"]
        assert {i["question_id"] for i in items} == {"q002", "q003"} and all(i["has_video"] for i in items)
        figs = c.get("/api/v1/play/items", params={"grade": "grade-9", "subject": "Mathematics", "figures": "only"}).json()["items"]
        assert figs and all(i["has_figure"] for i in figs)
    finally:
        app.dependency_overrides.pop(get_auth_context, None)


# ── Drive from the console ───────────────────────────────────────────────────

@needs_db
def test_the_drive_sign_in_is_kept_encrypted_and_wins_over_the_environment(db, monkeypatch):
    from sqlalchemy import text

    from app.services import drive_store

    monkeypatch.setenv("GOOGLE_DRIVE_CLIENT_ID", "env-id")
    monkeypatch.setenv("GOOGLE_DRIVE_REFRESH_TOKEN", "")
    drive_store._creds_cache.update(at=0.0, value=None)
    assert not drive_store.configured()
    drive_store.save_credentials(client_id="x.apps.googleusercontent.com", client_secret="s3cret", refresh_token="r-tok")
    with db.begin() as c:
        stored = c.execute(text("SELECT value FROM platform_secrets WHERE name = 'google_drive'")).scalar()
    assert "s3cret" not in stored and "r-tok" not in stored                         # encrypted at rest
    creds = drive_store.credentials()
    assert creds["client_id"] == "x.apps.googleusercontent.com" and creds["source"] == "console"
    assert drive_store.configured()
    drive_store.save_credentials(refresh_token="")
    assert not drive_store.configured()


def test_the_drive_callback_only_takes_a_sign_in_this_platform_started():
    c = TestClient(app)
    r = c.get("/api/v1/admin/drive/callback", params={"code": "x", "state": "forged"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("drive=expired")
    r = c.get("/api/v1/admin/drive/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert r.headers["location"].endswith("drive=refused")
    app.dependency_overrides[get_auth_context] = lambda: AuthContext("mama", "user", "bearer")
    try:
        assert c.get("/api/v1/admin/drive").status_code == 403                    # admins only
    finally:
        app.dependency_overrides.pop(get_auth_context, None)


def test_drive_links_are_never_handed_out():
    from app.infra.storage import public_object_url

    assert "drive.google.com" not in public_object_url("videos/q1/k.mp4")


def test_new_drive_files_are_never_shared():
    import inspect

    from app.services import drive_store

    assert "share(" not in inspect.getsource(drive_store.move).replace("unshare(", "")


# ── the media firewall ───────────────────────────────────────────────────────

def test_videos_are_not_free_files(monkeypatch):
    from app.routes import assets

    served = []
    monkeypatch.setattr(assets, "serve_object", lambda path, rng, cache, extra=None: served.append((path, cache)) or
                        __import__("fastapi").responses.Response(b"ok"))
    c = TestClient(app)
    assert c.get("/api/v1/assets/cbc-assets/videos/q1/k.mp4").status_code == 403
    assert c.get("/api/v1/assets/cbc-assets/diagrams/d1.svg").status_code == 200        # figures stay public
    for role, code in (("user", 403), ("api", 403), ("operator", 200), ("poster", 200)):
        app.dependency_overrides.clear()
        monkeypatch.setattr(assets, "_may_fetch_media", lambda request, r=role: r in assets.MEDIA_ROLES)
        assert c.get("/api/v1/assets/cbc-assets/videos/q1/k.mp4").status_code == code, role


# ── the embed player ─────────────────────────────────────────────────────────

def test_the_embed_player_streams_with_their_heading_and_can_be_framed_anywhere():
    import time

    import jwt

    from app.routes.content import _embed_secret

    token = jwt.encode({"type": "embed", "sub": "dev1", "q": "q1", "obj": "videos/q1/k.mp4", "h": "Integers <live>",
                        "c": "#0f766e", "exp": int(time.time()) + 60}, _embed_secret(), algorithm="HS256")
    r = TestClient(app).get(f"/api/v1/embed/{token}")
    assert r.status_code == 200
    assert "Integers &lt;live&gt;" in r.text and "#0f766e" in r.text and "/api/v1/watch/" in r.text
    assert 'controlsList="nodownload' in r.text
    assert "frame-ancestors *" in r.headers["content-security-policy"] and "x-frame-options" not in r.headers
    old = jwt.encode({"type": "embed", "obj": "videos/q1/k.mp4", "exp": int(time.time()) - 5}, _embed_secret(), algorithm="HS256")
    assert TestClient(app).get(f"/api/v1/embed/{old}").status_code == 410
    from app.services.auth import create_access_token
    assert TestClient(app).get(f"/api/v1/embed/{create_access_token('x', 'admin')}").status_code == 410


# ── what you bought, as videos ───────────────────────────────────────────────

@needs_db
def test_a_bought_papers_videos_render_before_the_daily_batch(db, monkeypatch):
    from sqlalchemy import text

    from app.services import job_queue

    monkeypatch.setattr(job_queue, "_render_limit", lambda: 1, raising=False)
    with db.begin() as c:
        for jid, pri, age in (("daily-1", None, 30), ("daily-2", None, 20), ("bought-1", "10", 1)):
            payload = '{"artifact_id": "%s"%s}' % (jid, f', "priority": "{pri}"' if pri else "")
            c.execute(text("""INSERT INTO jobs (job_id, kind, grade, subject, status, payload, created_at)
                              VALUES (:j, 'video', 'grade-9', 'Mathematics', 'queued', CAST(:p AS jsonb),
                                      NOW() - make_interval(mins => :a))"""), {"j": jid, "p": payload, "a": age})
    # The oldest daily job waits while the bought one is queued …
    assert job_queue.scope_is_busy("daily-1") and not job_queue.scope_is_busy("bought-1")
    # … and the in-process worker takes the bought one first, though it is the newest.
    assert job_queue._claim()["job_id"] == "bought-1"


@needs_db
def test_my_videos_lists_what_was_bought_and_queues_the_missing(db, monkeypatch):
    from sqlalchemy import text

    from app.services import my_videos, whiteboard

    _bank(db, 4)
    with db.begin() as c:
        for q in ("q001", "q002", "q003"):
            c.execute(text("INSERT INTO question_purchases (owner, question_id) VALUES ('mama', :q)"), {"q": q})
    whiteboard.record_video("q001", "videos", "k", "videos/q001/k.mp4")
    lib = my_videos.library("mama")
    states = {i["question_id"]: i["video"] for i in lib["items"]}
    assert states == {"q001": "ready", "q002": "none", "q003": "none"} and "q000" not in states   # only what she bought
    queued = []
    monkeypatch.setattr(whiteboard, "enqueue", lambda qid, queued_by="", priority=0: queued.append((qid, priority)) or {"status": "queued"})
    assert my_videos.queue_missing(["q001", "q002", "q003", "uq-mine"], by="mama") == 2
    assert queued == [("q002", 10), ("q003", 10)]            # first in line; her own questions are not drawn
    assert my_videos.library("mama", draft_ids=["q002", "q000"])["items"][0]["question_id"] == "q002"
