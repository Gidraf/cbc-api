"""Recent log lines, readable from a link, with credentials redacted."""
from __future__ import annotations

import logging
import os

import pytest
from fastapi.testclient import TestClient

from app.services import log_store


def test_credentials_never_reach_the_stored_line() -> None:
    line = ("call with Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop "
            "key sk-proj-abcdefghijklmnopqrstuvwxyz0123456789 and pk-lf-abcdefgh12345678")
    out = log_store.redact(line)
    assert "sk-proj" not in out and "pk-lf-abcdefgh" not in out and "eyJ" not in out
    assert out.count("[redacted]") >= 3


def test_the_handler_buffers_and_never_stores_database_chatter() -> None:
    handler = log_store.DbLogHandler("test")
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        handler.emit(logging.LogRecord("cbc-llm", logging.INFO, "", 0, "metered x: in=10", None, None))
        handler.emit(logging.LogRecord("sqlalchemy.engine", logging.INFO, "", 0, "SELECT 1", None, None))
        rows = list(handler._rows)
        assert [r[2] for r in rows] == ["metered x: in=10"]
    finally:
        handler._stop.set()


def _client(monkeypatch, rows):
    from app.main import app

    monkeypatch.setattr(log_store, "recent", lambda **kw: rows)
    return TestClient(app)


def test_a_token_that_is_neither_the_env_token_nor_a_key_is_refused(monkeypatch) -> None:
    from app.routes import admin_logs

    monkeypatch.delenv("LOG_SHARE_TOKEN", raising=False)
    monkeypatch.setattr(admin_logs, "_opens", lambda token: False)
    client = _client(monkeypatch, [])
    assert client.get("/api/v1/admin/logs/share?token=anything-long-enough-here").status_code == 401


def test_an_admin_api_key_opens_the_link(monkeypatch) -> None:
    """The key the operator made in the console is the token: one credential,
    revocable from the screen it was made on."""
    import hashlib

    from app.routes import admin_logs

    monkeypatch.delenv("LOG_SHARE_TOKEN", raising=False)
    key = "cbc_live_" + "x" * 40
    digest = hashlib.sha256(key.encode()).hexdigest()

    def fetch_one(query, params=None):
        return {"role": "admin"} if (params or {}).get("h") == digest else None
    import app.infra.db as db
    monkeypatch.setattr(db, "fetch_one", fetch_one)
    monkeypatch.setattr(db, "execute", lambda *a, **k: None)

    assert admin_logs._opens(key) is True
    assert admin_logs._opens("cbc_live_" + "y" * 40) is False


def test_a_developer_key_does_not_open_the_logs(monkeypatch) -> None:
    import hashlib

    from app.routes import admin_logs
    import app.infra.db as db

    monkeypatch.delenv("LOG_SHARE_TOKEN", raising=False)
    key = "cbc_live_" + "d" * 40
    monkeypatch.setattr(db, "fetch_one", lambda q, p=None: {"role": "developer"})
    monkeypatch.setattr(db, "execute", lambda *a, **k: None)
    assert admin_logs._opens(key) is False


def test_the_share_link_opens_only_to_its_own_token(monkeypatch) -> None:
    monkeypatch.setenv("LOG_SHARE_TOKEN", "a-long-random-token-for-tests")
    client = _client(monkeypatch, [
        {"at": "2026-09-13 10:00:00", "process": "worker", "level": "INFO",
         "logger": "cbc-run-meter", "message": "metered openai/gpt-5.6-terra: in=12000 (cached 11000) out=1900 cost=$0.0251"}])

    wrong = client.get("/api/v1/admin/logs/share?token=wrong-token-of-similar-length")
    assert wrong.status_code == 401

    right = client.get("/api/v1/admin/logs/share?token=a-long-random-token-for-tests&grep=metered")
    assert right.status_code == 200
    assert right.headers["content-type"].startswith("text/plain")
    assert "cost=$0.0251" in right.text and "worker" in right.text


def test_a_short_token_does_not_open_the_link(monkeypatch) -> None:
    from app.routes import admin_logs

    monkeypatch.setenv("LOG_SHARE_TOKEN", "short")
    assert admin_logs._opens("short") is False


def test_the_prune_drops_by_age_and_by_count(monkeypatch) -> None:
    ran: list[tuple[str, dict]] = []
    counts = iter([1000, 300])
    import app.infra.db as db
    monkeypatch.setattr(db, "execute", lambda q, p=None: ran.append((q, p or {})))
    monkeypatch.setattr(db, "fetch_one", lambda q, p=None: {"n": next(counts)})

    removed = log_store.prune(keep=500, retention_days=3)

    assert removed == 700
    assert any("days" in q and p.get("days") == "3" for q, p in ran)
    assert any("- :keep" in q and p.get("keep") == 500 for q, p in ran)


def test_the_hourly_job_is_scheduled_and_the_worker_runs_beat() -> None:
    import pathlib

    from app.celery_app import celery_app

    assert "prune-service-logs" in celery_app.conf.beat_schedule
    compose = (pathlib.Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    assert "--beat" in compose.split("generation-worker")[1].split("environment")[0]


def test_an_admin_can_read_the_share_link_from_the_console(monkeypatch) -> None:
    from app.main import app
    from app.routes import admin_logs
    from app.services.auth import AuthContext, require_roles

    monkeypatch.setenv("LOG_SHARE_TOKEN", "a-long-random-token-for-tests")
    app.dependency_overrides.clear()
    # stand in for a signed-in admin
    for route in app.routes:
        if getattr(route, "path", "") == "/api/v1/admin/logs/share-link":
            for dep in route.dependant.dependencies:
                app.dependency_overrides[dep.call] = lambda: AuthContext(subject="u", role="admin", auth_type="jwt")
    try:
        client = TestClient(app)
        out = client.get("/api/v1/admin/logs/share-link",
                         headers={"host": "api.example.test", "x-forwarded-proto": "https"}).json()
        assert out["enabled"] is True
        assert out["url"].startswith("https://api.example.test/api/v1/admin/logs/share?token=a-long-random-token-for-tests")
    finally:
        app.dependency_overrides.clear()


def test_installing_the_store_lets_info_through(monkeypatch) -> None:
    """The API process never configured logging; the root logger sat at
    WARNING and every INFO diagnostic was dropped before the store saw it."""
    root = logging.getLogger()
    saved_level, saved_handlers = root.level, list(root.handlers)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setattr(log_store, "_installed", None)
    try:
        root.setLevel(logging.WARNING)
        log_store.install("test")
        assert root.level <= logging.INFO
        assert any(isinstance(h, log_store.DbLogHandler) for h in root.handlers)
    finally:
        for h in root.handlers:
            if isinstance(h, log_store.DbLogHandler):
                h._stop.set()
                root.removeHandler(h)
        root.setLevel(saved_level)
        monkeypatch.setattr(log_store, "_installed", None)
