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
from ..state import runtime_state

ROLES = {"admin", "operator", "reviewer", "developer"}


@dataclass(slots=True)
class AuthContext:
    subject: str
    role: str
    auth_type: str


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_or_plain: str) -> bool:
    if not hashed_or_plain:
        return False
    if hashed_or_plain.startswith("$2b$") or hashed_or_plain.startswith("$2a$"):
        try:
            return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_or_plain.encode("utf-8"))
        except Exception:  # noqa: BLE001
            return False
    # Backward compatibility with initial plain passwords
    return secrets.compare_digest(plain_password, hashed_or_plain)


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
    return row["user_id"]


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise_api_error("UNAUTHORIZED_ACCESS", "Invalid or expired access token")


def authenticate_login(username: str, password: str) -> AuthContext:
    user_row = fetch_one(
        "SELECT username, password_plain, password_hash, role, is_active FROM app_users WHERE username = :uname",
        {"uname": username},
    )

    if user_row:
        if not user_row.get("is_active", True):
            raise_api_error("UNAUTHORIZED_ACCESS", "Account is deactivated")

        pwd_check = user_row.get("password_hash") or user_row.get("password_plain", "")
        if not verify_password(password, pwd_check):
            raise_api_error("UNAUTHORIZED_ACCESS", "Invalid username or password")

        role = user_row["role"]
        return AuthContext(subject=username, role=role, auth_type="bearer")

    # Fallback to runtime_state in-memory users
    accounts = runtime_state.user_accounts
    account = accounts.get(username)
    if not account or not verify_password(password, account.get("password", "")):
        raise_api_error("UNAUTHORIZED_ACCESS", "Invalid username or password")

    role = account["role"]
    return AuthContext(subject=username, role=role, auth_type="bearer")


def get_auth_context(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> AuthContext:
    if x_api_key:
        if settings.developer_api_key and x_api_key == settings.developer_api_key:
            return AuthContext(subject="developer_api_key", role="developer", auth_type="api_key")

        # Check in api_keys database table
        key_hash = hashlib.sha256(x_api_key.encode("utf-8")).hexdigest()
        key_row = fetch_one(
            "SELECT user_id, role, is_active FROM api_keys WHERE key_hash = :khash AND is_active = TRUE",
            {"khash": key_hash},
        )
        if key_row:
            execute("UPDATE api_keys SET last_used_at = NOW() WHERE key_hash = :khash", {"khash": key_hash})
            return AuthContext(subject=key_row["user_id"], role=key_row["role"], auth_type="api_key")

    if not authorization:
        raise_api_error("UNAUTHORIZED_ACCESS", "Missing Authorization header")

    if not authorization.lower().startswith("bearer "):
        raise_api_error("UNAUTHORIZED_ACCESS", "Authorization header must use Bearer token")

    token = authorization.split(" ", 1)[1].strip()
    payload = _decode_token(token)
    role = str(payload.get("role", ""))
    subject = str(payload.get("sub", ""))

    if role not in ROLES or not subject:
        raise_api_error("UNAUTHORIZED_ACCESS", "Invalid token payload")

    return AuthContext(subject=subject, role=role, auth_type="bearer")


def require_roles(*allowed_roles: str) -> Callable[[AuthContext], AuthContext]:
    allowed = set(allowed_roles)

    def dependency(context: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if context.role not in allowed:
            raise_api_error("FORBIDDEN", "Role is not authorized for this action")
        return context

    return dependency
