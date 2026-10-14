"""Secrets that must never be the ones in the repository.

At startup (`ensure`):

* JWT_SECRET missing, short, or the old default: a strong secret is made
  once, kept in the database (platform_secrets) and used, so a token can
  never be signed with a value anyone can read in the code. Everyone signs
  in again once. Setting a strong JWT_SECRET in .env takes precedence.
* CBC_MASTER_KEY missing, or the value that used to sit in
  docker-compose.yml: a loud error. It encrypts the saved provider keys, so
  it cannot be swapped silently — app/admin_tools.py (rotate-master-key) moves them to
  a new key (deploy/harden.sh does it in order).

`report()` says what is weak without saying any value.
"""
from __future__ import annotations

import logging
import os
import secrets

logger = logging.getLogger("cbc-security")

WEAK_JWT = {"change-me-jwt-secret", "change-this-jwt-secret", "changeme", "secret", "jwt-secret", ""}
MIN_JWT = 32
# The key that docker-compose.yml used to fall back to. It is public: anything
# encrypted with it is as good as plain text to whoever has the repository.
PUBLISHED_MASTER_KEY = "u8iP_EgFrh50kABm2MvxAfv5mN53uV8SQEgrMwJwztw="


def jwt_weak(value: str) -> bool:
    return value in WEAK_JWT or len(value) < MIN_JWT


def master_key_weak(value: str | None) -> bool:
    return not value or value.strip() == PUBLISHED_MASTER_KEY


def ensure() -> dict[str, str]:
    from ..infra.db import execute, fetch_one
    from ..settings import settings

    out: dict[str, str] = {}
    if jwt_weak(settings.jwt_secret):
        execute("""CREATE TABLE IF NOT EXISTS platform_secrets (
                       name TEXT PRIMARY KEY, value TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        execute("INSERT INTO platform_secrets (name, value) VALUES ('jwt_secret', :v) ON CONFLICT (name) DO NOTHING",
                {"v": secrets.token_urlsafe(48)})
        row = fetch_one("SELECT value FROM platform_secrets WHERE name = 'jwt_secret'") or {}
        if row.get("value"):
            settings.jwt_secret = str(row["value"])
            out["jwt_secret"] = "generated (set a strong JWT_SECRET in .env to manage it yourself)"
            logger.warning("JWT_SECRET is missing or weak: using a strong secret kept in the database.")
    if master_key_weak(os.getenv("CBC_MASTER_KEY")):
        out["cbc_master_key"] = "weak"
        logger.error("CBC_MASTER_KEY is missing or is the value published in the repository: saved provider keys "
                     "are not protected. Run deploy/harden.sh on the server.")
    return out


def report() -> dict[str, bool]:
    """Which secrets are weak right now (true = weak). Names only."""
    from ..settings import settings

    return {"jwt_secret": jwt_weak(settings.jwt_secret), "cbc_master_key": master_key_weak(os.getenv("CBC_MASTER_KEY"))}
