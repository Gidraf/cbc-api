"""Email links: a forgotten password reset by email, an address confirmed by one.

The flows run against a real Postgres (CBC_TEST_PHASE2_DATABASE_URL, an empty
database); the mail server is replaced by a list of what would have been sent.
"""
from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import email_links, mailer, rate_limit

DB = os.getenv("CBC_TEST_PHASE2_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not DB, reason="set CBC_TEST_PHASE2_DATABASE_URL to an empty Postgres database")
BASE = "https://cbc.example.org"


@pytest.fixture()
def outbox(monkeypatch):
    sent: list[dict] = []

    def fake_send(to, subject, text, html_body=""):
        sent.append({"to": to, "subject": subject, "text": text, "html": html_body})
        return True

    monkeypatch.setattr(mailer, "send", fake_send)
    monkeypatch.setattr(mailer, "configured", lambda: True)
    monkeypatch.setattr(email_links, "base_url", lambda: BASE)
    return sent


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


def _link(mail: dict, path: str) -> str:
    m = re.search(re.escape(BASE + path) + r"\?token=([A-Za-z0-9_-]+)", mail["text"])
    assert m, mail["text"]
    return m.group(1)


def _signup(client, name="amina", email="amina@example.org", password="a long pass 1234"):
    return client.post("/api/v1/auth/register", json={"username": name, "password": password, "email": email})


# ── no database needed ───────────────────────────────────────────────────────

def test_the_admin_tools_hint_is_gone_from_the_sign_in_page() -> None:
    here = os.path.dirname(__file__)
    page = open(os.path.join(here, "..", "..", "frontend-web", "src", "views", "SignIn.tsx")).read()
    assert "admin_tools" not in page and "Lost the admin password" not in page
    assert "Forgot password?" in page and "/api/v1/auth/forgot" in page


def test_cvpaps_mailbox_names_are_read(monkeypatch) -> None:
    from app.settings import settings

    for k in ("smtp_host", "smtp_user", "smtp_password"):
        monkeypatch.setattr(settings, k, "")
    for k in ("SMTP_FROM", "SMTP_PORT", "MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_PORT", "MAIL_USE_SSL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MAIL_SERVER", "mail.example.org")
    monkeypatch.setenv("ADMIN_EMAIL", "info@example.org")
    monkeypatch.setenv("ADMIN_EMAIL_PASSWORD", "not-a-real-one")
    c = mailer.config()
    assert (c["host"], c["user"], c["sender"]) == ("mail.example.org", "info@example.org", "info@example.org")
    assert mailer.configured()
    assert "not-a-real-one" not in repr(mailer.summary()), "an admin never sees the password"


def test_without_a_mail_server_nothing_is_sent_and_nothing_raises(monkeypatch) -> None:
    from app.settings import settings

    for k in ("smtp_host", "smtp_user", "smtp_password"):
        monkeypatch.setattr(settings, k, "")
    for k in ("MAIL_SERVER", "SMTP_SERVER", "ADMIN_EMAIL", "ADMIN_EMAIL_PASSWORD", "MAIL_USERNAME", "MAIL_PASSWORD", "DOMAIN"):
        monkeypatch.delenv(k, raising=False)
    assert mailer.send("a@example.org", "x", "y") is False


def test_links_use_the_configured_address_never_the_requests() -> None:
    import inspect

    source = inspect.getsource(email_links.base_url)
    assert 'get("public_base_url")' in source and "request" not in source


def test_email_addresses_are_checked() -> None:
    assert email_links.valid_email("a.b@school.co.ke")
    for bad in ("", "nope", "a@b", "a b@c.com", "x" * 250 + "@a.com"):
        assert not email_links.valid_email(bad)


# ── the flows ────────────────────────────────────────────────────────────────

@needs_db
def test_signing_up_needs_an_email_and_sends_a_confirm_link(db, outbox) -> None:
    client = TestClient(app)
    r = client.post("/api/v1/auth/register", json={"username": "noemail", "password": "a long pass 1234"})
    assert r.status_code == 400

    assert _signup(client).status_code == 200
    assert len(outbox) == 1 and outbox[0]["to"] == "amina@example.org"
    token = _link(outbox[0], "/verify")
    assert email_links.status("amina") == {"email": "amina@example.org", "email_verified": False}

    assert client.post("/api/v1/auth/verify", json={"token": token}).status_code == 200
    assert email_links.status("amina")["email_verified"] is True
    # Once only.
    assert client.post("/api/v1/auth/verify", json={"token": token}).status_code == 400


@needs_db
def test_a_confirm_link_for_an_old_address_confirms_nothing(db, outbox) -> None:
    client = TestClient(app)
    _signup(client)
    old = _link(outbox[0], "/verify")
    email_links.set_email("amina", "new@example.org")
    assert client.post("/api/v1/auth/verify", json={"token": old}).status_code == 400
    assert email_links.status("amina") == {"email": "new@example.org", "email_verified": False}


@needs_db
def test_forgot_password_answers_the_same_for_anyone(db, outbox) -> None:
    client = TestClient(app)
    _signup(client)
    outbox.clear()
    known = client.post("/api/v1/auth/forgot", json={"who": "amina"}).json()
    unknown = client.post("/api/v1/auth/forgot", json={"who": "nobody@example.org"}).json()
    assert known == unknown
    assert [m["to"] for m in outbox] == ["amina@example.org"]


@needs_db
def test_a_reset_link_sets_the_password_once_and_signs_everyone_out(db, outbox) -> None:
    from app.infra.db import fetch_one

    client = TestClient(app)
    _signup(client)
    client.post("/api/v1/auth/login", json={"username": "amina", "password": "a long pass 1234"})
    outbox.clear()
    client.post("/api/v1/auth/forgot", json={"who": "AMINA@example.org"})     # by email, any case
    token = _link(outbox[0], "/reset")
    assert client.get(f"/api/v1/auth/reset/{token}").json() == {"valid": True}

    r = client.post("/api/v1/auth/reset", json={"token": token, "new_password": "short"})
    assert r.status_code == 400
    r = client.post("/api/v1/auth/reset", json={"token": token, "new_password": "a brand new pass 99"})
    assert r.status_code == 200 and r.json()["username"] == "amina"
    assert fetch_one("SELECT COUNT(*) AS n FROM refresh_tokens WHERE user_id = 'amina'")["n"] == 0

    assert client.post("/api/v1/auth/login", json={"username": "amina", "password": "a brand new pass 99"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"username": "amina", "password": "a long pass 1234"}).status_code != 200
    # Spent.
    assert client.get(f"/api/v1/auth/reset/{token}").json() == {"valid": False}
    assert client.post("/api/v1/auth/reset", json={"token": token, "new_password": "another pass 1234"}).status_code == 400
    # The link reached the inbox, so the address is confirmed too.
    assert email_links.status("amina")["email_verified"] is True


@needs_db
def test_a_newer_reset_link_replaces_the_older_and_only_hashes_are_kept(db, outbox) -> None:
    from app.infra.db import fetch_all

    client = TestClient(app)
    _signup(client)
    outbox.clear()
    client.post("/api/v1/auth/forgot", json={"who": "amina"})
    client.post("/api/v1/auth/forgot", json={"who": "amina"})
    first, second = _link(outbox[0], "/reset"), _link(outbox[1], "/reset")
    assert client.get(f"/api/v1/auth/reset/{first}").json() == {"valid": False}
    assert client.get(f"/api/v1/auth/reset/{second}").json() == {"valid": True}
    stored = {r["token_hash"] for r in fetch_all("SELECT token_hash FROM auth_links")}
    assert first not in stored and second not in stored


@needs_db
def test_an_inbox_cannot_be_flooded(db, outbox) -> None:
    client = TestClient(app)
    _signup(client)
    codes = [client.post("/api/v1/auth/forgot", json={"who": "amina"}).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and 429 in codes


def test_every_email_carries_the_headers_a_mail_server_requires(monkeypatch) -> None:
    """amavis blocks a message with no Date as BAD-HEADER-0 and bounces it."""
    import smtplib

    from app.settings import settings

    sent = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def starttls(self, **k): pass
        def login(self, *a): pass
        def send_message(self, msg): sent["msg"] = msg
        def quit(self): pass

    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(settings, "smtp_host", "mail.example.org")
    monkeypatch.setattr(settings, "smtp_user", "info@example.org")
    monkeypatch.setattr(settings, "smtp_password", "x")
    assert mailer.send("a@example.org", "Hello", "Body", "<p>Body</p>")
    msg = sent["msg"]
    for header in ("Date", "Message-ID", "From", "To", "Subject", "MIME-Version"):
        assert msg[header], header
    assert "@example.org" in msg["From"] and msg["Message-ID"].endswith("@example.org>")
