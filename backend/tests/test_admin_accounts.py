"""Admin: who signed up, when, and who pays."""
from __future__ import annotations

import os

import pytest

DB = os.getenv("CBC_TEST_PHASE2_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB, reason="set CBC_TEST_PHASE2_DATABASE_URL to an empty Postgres database")


def test_the_api_containers_are_given_the_mpesa_settings() -> None:
    from pathlib import Path

    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()
    for name in ("MPESA_CONSUMER_KEY", "MPESA_CONSUMER_SECRET", "MPESA_SHORTCODE", "MPESA_PASSKEY", "MPESA_TYPE",
                 "MPESA_TILL_NUMBER", "MPESA_CALLBACK_TOKEN", "MPESA_ENV"):
        assert f"{name}: ${{{name}" in compose, name


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
    yield engine
    engine.dispose()


@needs_db
def test_accounts_show_when_they_joined_and_what_they_paid(db) -> None:
    from app.infra.db import execute
    from app.routes.billing import admin_accounts
    from app.services.auth import AuthContext

    for name, role in (("amina", "user"), ("dev1", "api"), ("admin2", "admin")):
        execute("INSERT INTO app_users (username, password_plain, password_hash, role, is_active, updated_at) "
                "VALUES (:u, '', 'x', :r, TRUE, NOW())", {"u": name, "r": role})
    execute("""INSERT INTO mpesa_payments (checkout_request_id, owner, phone, amount, status, updated_at)
               VALUES ('c1', 'amina', '2547***678', 200, 'paid', NOW()), ('c2', 'amina', 'x', 50, 'failed', NOW()),
                      ('c3', 'dev1', 'x', 100, 'pending', NOW())""")
    out = admin_accounts(days=30, auth=AuthContext(subject="admin", role="admin", auth_type="bearer"))
    names = {a["username"]: a for a in out["accounts"]}
    assert set(names) == {"amina", "dev1"}, "staff are not customers"
    assert names["amina"]["paid_ksh"] == 200 and names["amina"]["payments"] == 1, "only what was paid"
    assert names["dev1"]["payments"] == 0 and names["amina"]["created_at"]
    assert out["totals"]["today"] == {"signups": 2, "revenue_ksh": 200, "payers": 1}
    assert out["all"] == {"accounts": 2, "paying": 1, "revenue_ksh": 200}
    assert out["mpesa_ready"] is False and "MPESA_CONSUMER_KEY" in out["mpesa_note"]
