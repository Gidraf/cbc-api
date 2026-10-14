"""Links sent by email: reset a forgotten password, confirm an address.

A link carries a random token; only its SHA-256 is stored, so a copy of the
database opens no account. A reset link works once, for an hour, and using
it signs every device out. A confirm link names the address it was sent to:
change the address and the old link confirms nothing.

Links are written with the configured public address only — never one read
from the request, which anyone can set, so a forged Host cannot make the
platform email someone a link to another site.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
from typing import Any

from ..infra.db import execute, fetch_all, fetch_one

logger = logging.getLogger("cbc-email-links")

RESET_MINUTES = 60
CONFIRM_DAYS = 3
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")


def valid_email(address: str) -> bool:
    return bool(EMAIL.match(address or "")) and len(address) <= 254


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def base_url() -> str:
    from . import platform_settings

    return str(platform_settings.get("public_base_url") or "").rstrip("/")


def _new(username: str, purpose: str, email: str, seconds: int) -> str:
    token = secrets.token_urlsafe(32)
    execute("""INSERT INTO auth_links (token_hash, username, purpose, email, expires_at)
               VALUES (:h, :u, :p, :e, NOW() + make_interval(secs => :s))""",
            {"h": _hash(token), "u": username, "p": purpose, "e": email, "s": seconds})
    execute("DELETE FROM auth_links WHERE expires_at < NOW() - INTERVAL '7 days'")
    return token


def _take(token: str, purpose: str) -> dict[str, Any] | None:
    """Spend a link: the row, once, if it is this kind, unused and in date."""
    if not token or len(token) > 200:
        return None
    return fetch_one("""UPDATE auth_links SET used_at = NOW()
                        WHERE token_hash = :h AND purpose = :p AND used_at IS NULL AND expires_at > NOW()
                        RETURNING username, email""", {"h": _hash(token), "p": purpose})


# ── forgotten passwords ──────────────────────────────────────────────────────

def accounts_for(who: str) -> list[dict[str, Any]]:
    """The active accounts a username or an email address names (with an email to send to)."""
    who = (who or "").strip().lower()
    if not who or len(who) > 254:
        return []
    return fetch_all("""SELECT username, email FROM app_users
                        WHERE is_active AND COALESCE(email, '') <> ''
                          AND (LOWER(username) = :w OR LOWER(email) = :w)
                        ORDER BY username LIMIT 3""", {"w": who})


def send_reset(who: str) -> int:
    """Email a reset link to each account `who` names. How many were sent —
    for the log, never for the person asking."""
    base = base_url()
    sent = 0
    for row in accounts_for(who):
        if not base:
            logger.error("Reset link not sent: set the Public address in Settings first.")
            return 0
        execute("UPDATE auth_links SET used_at = NOW() WHERE username = :u AND purpose = 'reset' AND used_at IS NULL",
                {"u": row["username"]})
        token = _new(row["username"], "reset", row["email"], RESET_MINUTES * 60)
        from . import mailer

        if mailer.send_reset(row["email"], row["username"], f"{base}/reset?token={token}", RESET_MINUTES):
            sent += 1
    return sent


def reset(token: str, new_password: str) -> str | None:
    """Set the password a reset link is for. The username, or None."""
    from .auth import hash_password

    row = _take(token, "reset")
    if not row:
        return None
    user = row["username"]
    execute("UPDATE app_users SET password_hash = :h, password_plain = '', updated_at = NOW() WHERE username = :u",
            {"h": hash_password(new_password), "u": user})
    execute("DELETE FROM refresh_tokens WHERE user_id = :u", {"u": user})
    execute("UPDATE auth_links SET used_at = NOW() WHERE username = :u AND purpose = 'reset' AND used_at IS NULL",
            {"u": user})
    # The link reached their inbox: that confirms the address too.
    execute("""UPDATE app_users SET email_verified_at = COALESCE(email_verified_at, NOW())
               WHERE username = :u AND LOWER(COALESCE(email, '')) = LOWER(:e)""", {"u": user, "e": row["email"]})
    return user


def peek_reset(token: str) -> bool:
    """Whether a reset link still works (the page asks before showing the form)."""
    if not token or len(token) > 200:
        return False
    return bool(fetch_one("""SELECT 1 AS ok FROM auth_links WHERE token_hash = :h AND purpose = 'reset'
                             AND used_at IS NULL AND expires_at > NOW()""", {"h": _hash(token)}))


# ── confirming an address ────────────────────────────────────────────────────

def send_confirm(username: str) -> str:
    """Email a confirm link. "sent", "verified", "no email", "not set up" or "failed"."""
    from . import mailer

    row = fetch_one("SELECT email, email_verified_at FROM app_users WHERE username = :u", {"u": username})
    if not row or not row.get("email"):
        return "no email"
    if row.get("email_verified_at"):
        return "verified"
    base = base_url()
    if not base or not mailer.configured():
        logger.error("Confirm link not sent: %s.", "no Public address in Settings" if not base else "SMTP is not set up")
        return "not set up"
    execute("UPDATE auth_links SET used_at = NOW() WHERE username = :u AND purpose = 'confirm' AND used_at IS NULL",
            {"u": username})
    token = _new(username, "confirm", row["email"], CONFIRM_DAYS * 86400)
    ok = mailer.send_confirm(row["email"], username, f"{base}/verify?token={token}", CONFIRM_DAYS)
    return "sent" if ok else "failed"


def confirm(token: str) -> str | None:
    """Confirm the address a link was sent to — if it is still the account's."""
    row = _take(token, "confirm")
    if not row:
        return None
    done = fetch_one("""UPDATE app_users SET email_verified_at = NOW(), updated_at = NOW()
                        WHERE username = :u AND LOWER(COALESCE(email, '')) = LOWER(:e)
                        RETURNING username""", {"u": row["username"], "e": row["email"]})
    return done["username"] if done else None


def set_email(username: str, email: str) -> None:
    """A new address starts unconfirmed (and old confirm links stop working)."""
    execute("""UPDATE app_users SET email = :e, email_verified_at = NULL, updated_at = NOW()
               WHERE username = :u AND LOWER(COALESCE(email, '')) <> LOWER(:e)""", {"u": username, "e": email})
    execute("UPDATE auth_links SET used_at = NOW() WHERE username = :u AND purpose = 'confirm' AND used_at IS NULL",
            {"u": username})


def status(username: str) -> dict[str, Any]:
    row = fetch_one("SELECT email, email_verified_at FROM app_users WHERE username = :u", {"u": username}) or {}
    return {"email": row.get("email") or "", "email_verified": bool(row.get("email_verified_at"))}


def in_background(fn, *args) -> None:
    """Run a send after the answer has gone: a failure is logged, never raised."""
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001
        logger.error("Email link not sent: %s", type(exc).__name__ + ": " + str(exc)[:200])
