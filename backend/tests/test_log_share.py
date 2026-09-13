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


def test_the_share_link_is_off_unless_a_token_is_set(monkeypatch) -> None:
    monkeypatch.delenv("LOG_SHARE_TOKEN", raising=False)
    client = _client(monkeypatch, [])
    assert client.get("/api/v1/admin/logs/share?token=anything").status_code == 404


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
    monkeypatch.setenv("LOG_SHARE_TOKEN", "short")
    client = _client(monkeypatch, [])
    assert client.get("/api/v1/admin/logs/share?token=short").status_code == 404


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
