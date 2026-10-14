from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import bcrypt
import jwt
from fastapi import Depends, Header

from ..errors import raise_api_error
from ..infra.db import execute, fetch_one
from ..settings import settings

ROLES = {"admin", "operator", "reviewer", "developer", "user", "api", "poster"}


@dataclass(slots=True)
class AuthContext:
    subject: str
    role: str
    auth_type: str


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


# Spent on a login for a name that does not exist, so a wrong name and a
# wrong password take the same time and the answer does not say which.
_DUMMY_HASH = bcrypt.hashpw(b"not-a-password", bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """bcrypt only. Plain-text passwords are hashed at startup
    (state.harden_users) and never compared as text."""
    if not password_hash or not password_hash.startswith(("$2b$", "$2a$", "$2y$")):
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return False


def create_access_token(subject: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.jwt_exp_minutes)
    payload = {
        "sub": subject,
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_refresh_token(subject: str) -> str:
    token_raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token_raw.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_exp_days)

    execute(
        """
        INSERT INTO refresh_tokens (token_hash, user_id, expires_at, created_at)
        VALUES (:token_hash, :user_id, :expires_at, NOW())
        ON CONFLICT (token_hash) DO NOTHING
        """,
        {
            "token_hash": token_hash,
            "user_id": subject,
            "expires_at": expires_at,
        },
    )
    return token_raw


def verify_and_consume_refresh_token(token_raw: str) -> str:
    token_hash = hashlib.sha256(token_raw.encode("utf-8")).hexdigest()
    row = fetch_one(
        "SELECT user_id, expires_at FROM refresh_tokens WHERE token_hash = :hash",
        {"hash": token_hash},
    )
    if not row:
        raise_api_error("UNAUTHORIZED_ACCESS", "Invalid or expired refresh token")

    # Delete used refresh token (one-time use rotation)
    execute("DELETE FROM refresh_tokens WHERE token_hash = :hash", {"hash": token_hash})
    expires = row.get("expires_at")
    if expires is None or expires <= datetime.now(expires.tzinfo or timezone.utc):
        raise_api_error("UNAUTHORIZED_ACCESS", "Invalid or expired refresh token")
    return row["user_id"]


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise_api_error("UNAUTHORIZED_ACCESS", "Invalid or expired access token")


def authenticate_login(username: str, password: str) -> AuthContext:
    """The database is the only source of accounts, and bcrypt the only check.
    A wrong name, a wrong password and a switched-off account all get the
    same answer, so the reply never confirms that an account exists."""
    user_row = fetch_one(
        "SELECT username, password_hash, role, is_active FROM app_users WHERE username = :uname",
        {"uname": username},
    )
    if not user_row:
        verify_password(password, _DUMMY_HASH)
        raise_api_error("UNAUTHORIZED_ACCESS", "Invalid username or password")
    ok = verify_password(password, str(user_row.get("password_hash") or ""))
    if not ok or not user_row.get("is_active", True) or user_row.get("role") not in ROLES:
        raise_api_error("UNAUTHORIZED_ACCESS", "Invalid username or password")
    return AuthContext(subject=username, role=user_row["role"], auth_type="bearer")


_ACCOUNT_CACHE: dict[str, tuple[float, dict | None]] = {}
_ACCOUNT_TTL = 30.0


def current_account(username: str) -> dict | None:
    """The account as the database has it now (role, switched on), kept for
    30 seconds: switching an account off or changing its role takes effect
    within that, not when its token runs out."""
    import time

    hit = _ACCOUNT_CACHE.get(username)
    if hit and time.monotonic() - hit[0] < _ACCOUNT_TTL:
        return hit[1]
    row = fetch_one("SELECT username, role, is_active FROM app_users WHERE username = :u", {"u": username})
    if len(_ACCOUNT_CACHE) > 5000:
        _ACCOUNT_CACHE.clear()
    _ACCOUNT_CACHE[username] = (time.monotonic(), row)
    return row


def get_auth_context(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> AuthContext:
    if x_api_key:
        fixed = settings.developer_api_key or ""
        # The fixed key from .env only when it is a real secret: never an
        # example value copied from .env.example.
        if (len(fixed) >= 32 and "example" not in fixed.lower()
                and secrets.compare_digest(x_api_key.encode(), fixed.encode())):
            return AuthContext(subject="developer_api_key", role="developer", auth_type="api_key")

        # Check in api_keys database table
        key_hash = hashlib.sha256(x_api_key.encode("utf-8")).hexdigest()
        key_row = fetch_one(
            "SELECT user_id, role, is_active FROM api_keys WHERE key_hash = :khash AND is_active = TRUE",
            {"khash": key_hash},
        )
        if key_row and key_row.get("role") in ROLES:
            # A key dies with its account: switched off, the keys stop too.
            owner = current_account(str(key_row["user_id"]))
            if owner is not None and not owner.get("is_active", True):
                raise_api_error("UNAUTHORIZED_ACCESS", "This key's account is switched off.")
            execute("UPDATE api_keys SET last_used_at = NOW() WHERE key_hash = :khash", {"khash": key_hash})
            return AuthContext(subject=key_row["user_id"], role=key_row["role"], auth_type="api_key")
        # A key that matches nothing is refused here, not passed on to the
        # bearer check (which would only say the header is missing).
        raise_api_error("UNAUTHORIZED_ACCESS", "Invalid or revoked API key")

    if not authorization:
        raise_api_error("UNAUTHORIZED_ACCESS", "Missing Authorization header")

    if not authorization.lower().startswith("bearer "):
        raise_api_error("UNAUTHORIZED_ACCESS", "Authorization header must use Bearer token")

    token = authorization.split(" ", 1)[1].strip()
    payload = _decode_token(token)
    role = str(payload.get("role", ""))
    subject = str(payload.get("sub", ""))

    if role not in ROLES or not subject or payload.get("type") not in (None, "access"):
        raise_api_error("UNAUTHORIZED_ACCESS", "Invalid token payload")
    account = current_account(subject)
    if account is None or not account.get("is_active", True) or account.get("role") not in ROLES:
        # Deleted, switched off, or given a role that no longer exists: the
        # token stops working now, not when it runs out.
        raise_api_error("UNAUTHORIZED_ACCESS", "This account is not active. Sign in again.")
    # The role the account has now: a change by an admin applies at once.
    role = str(account["role"])

    return AuthContext(subject=subject, role=role, auth_type="bearer")


def require_roles(*allowed_roles: str) -> Callable[[AuthContext], AuthContext]:
    allowed = set(allowed_roles)

    def dependency(context: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if context.role not in allowed:
            raise_api_error("FORBIDDEN", "Role is not authorized for this action")
        return context

    return dependency
