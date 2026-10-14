from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..errors import raise_api_error
from ..infra.db import execute, fetch_all, fetch_one
from ..services.auth import (
    AuthContext,
    authenticate_login,
    create_access_token,
    create_refresh_token,
    get_auth_context,
    hash_password,
    require_roles,
    verify_and_consume_refresh_token,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication & Keys"])


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str | None = None
    role: str = "user"          # "developer" signs up for the content API


class RefreshRequest(BaseModel):
    refresh_token: str


class CreateApiKeyRequest(BaseModel):
    label: str = "Default API Key"
    # The role the key carries. Never above the maker's own: an admin may
    # mint a developer key for a script, a developer may not mint an admin.
    role: str = ""


@router.post("/login")
def login(payload: LoginRequest, request: Request) -> dict[str, Any]:
    from ..services import rate_limit

    who = payload.username.strip().lower()[:64]
    rate_limit.hit("login_ip", rate_limit.client_ip(request))
    rate_limit.hit("login_user", who)
    context = authenticate_login(payload.username, payload.password)
    rate_limit.clear("login_user", who)
    access_token = create_access_token(context.subject, context.role)
    refresh_token = create_refresh_token(context.subject)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "role": context.role,
        "subject": context.subject,
        "user": {
            "username": payload.username,
            "role": context.role,
            "subject_scope": context.subject,
        },
    }


USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
MIN_PASSWORD = 10
# Names a stranger must never take: the built-in accounts, the people the
# platform trusts by name (video makers), and anything that reads as staff.
RESERVED = {"admin", "administrator", "operator", "reviewer", "developer", "root", "system", "support", "staff",
            "cbc", "api", "poster", "developer_api_key", "link", "security", "billing", "mpesa"}


def _reserved(name: str) -> bool:
    from ..services import platform_settings

    raw = platform_settings.get("video_makers", ["gidraf"]) or []
    makers = raw if isinstance(raw, list) else str(raw).replace(";", ",").split(",")
    return name in RESERVED or name in {str(m).strip().lower() for m in makers}


@router.post("/register")
def register(payload: RegisterRequest, request: Request) -> dict[str, Any]:
    from ..services import rate_limit
    from ..state import KNOWN_WEAK

    rate_limit.hit("register_all", "*")
    rate_limit.hit("register_ip", rate_limit.client_ip(request))

    name = payload.username.strip().lower()
    if not USERNAME.match(name):
        raise_api_error("VALIDATION_FAILED", "A username is 3–32 letters, numbers, dots, dashes or underscores.")
    if len(payload.password) < MIN_PASSWORD or payload.password.lower() in KNOWN_WEAK or payload.password.lower() == name:
        raise_api_error("VALIDATION_FAILED", f"Choose a password of {MIN_PASSWORD} characters or more that is not your username.")
    if len(payload.password) > 128:
        raise_api_error("VALIDATION_FAILED", "Passwords are 128 characters at most.")
    existing = fetch_one("SELECT username FROM app_users WHERE LOWER(username) = :uname", {"uname": name})
    if existing or _reserved(name):
        raise_api_error("VALIDATION_FAILED", "That username is taken. Choose another.")
    payload.username = name

    pwd_hash = hash_password(payload.password)
    execute(
        """
        INSERT INTO app_users (username, password_plain, password_hash, role, email, is_active, updated_at)
        VALUES (:uname, '', :phash, :role, :email, TRUE, NOW())
        """,
        {
            "uname": payload.username,
            "phash": pwd_hash,
            # A signup is a USER (a parent or a teacher: the builder, their
            # own drafts and papers) or an API developer (the content API and
            # their own keys). Neither reaches the factory: "developer",
            # "reviewer" and the other staff roles are given by an admin only.
            "role": "api" if payload.role in {"developer", "api"} else "user",
            "email": payload.email,
        },
    )

    return {"status": "registered", "username": payload.username}


class ChangePassword(BaseModel):
    current_password: str
    new_password: str


@router.post("/password")
def change_password(payload: ChangePassword, request: Request,
                    context: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
    """Set your own password: the current one (a random one an admin gave
    you counts), then the new one. Every other signed-in session of yours
    is signed out."""
    from ..services import rate_limit
    from ..services.auth import authenticate_login, hash_password
    from ..state import KNOWN_WEAK

    if context.auth_type != "bearer":
        raise_api_error("FORBIDDEN", "Sign in to change your password (an API key cannot).")
    rate_limit.hit("login_user", context.subject.lower())
    authenticate_login(context.subject, payload.current_password)     # the current one, or refused
    new = payload.new_password
    if len(new) < MIN_PASSWORD or new.lower() in KNOWN_WEAK or new.lower() == context.subject.lower():
        raise_api_error("VALIDATION_FAILED", f"Choose a password of {MIN_PASSWORD} characters or more that is not your username.")
    if len(new) > 128 or new == payload.current_password:
        raise_api_error("VALIDATION_FAILED", "Choose a new password, 128 characters at most.")
    execute("UPDATE app_users SET password_hash = :h, password_plain = '', updated_at = NOW() WHERE username = :u",
            {"h": hash_password(new), "u": context.subject})
    execute("DELETE FROM refresh_tokens WHERE user_id = :u", {"u": context.subject})
    rate_limit.clear("login_user", context.subject.lower())
    return {"ok": True}


@router.post("/refresh")
def refresh_token_endpoint(payload: RefreshRequest) -> dict[str, Any]:
    username = verify_and_consume_refresh_token(payload.refresh_token)
    user_row = fetch_one("SELECT username, role, is_active FROM app_users WHERE username = :uname", {"uname": username})
    if not user_row or not user_row.get("is_active", True):
        raise_api_error("UNAUTHORIZED_ACCESS", "This account is not active. Sign in again.")
    role = user_row["role"]

    new_access_token = create_access_token(username, role)
    new_refresh_token = create_refresh_token(username)

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "role": role,
        "subject": username,
    }


@router.get("/me")
def get_current_session(context: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
    return {
        "subject": context.subject,
        "role": context.role,
        "auth_type": context.auth_type,
    }


@router.post("/api-keys")
def create_developer_api_key(
    payload: CreateApiKeyRequest,
    context: AuthContext = Depends(require_roles("admin", "developer", "api")),
) -> dict[str, Any]:
    # An API developer's keys carry "api" — the content API, nothing more.
    ranks = {"api": 1, "reviewer": 2, "developer": 3, "operator": 4, "admin": 5}
    wanted = (payload.role or context.role).strip().lower()
    if wanted not in ranks or ranks[wanted] > ranks.get(context.role, 0):
        raise_api_error("FORBIDDEN", f"A {context.role} cannot make a {wanted} key.")
    raw_key = f"cbc_live_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    key_id = f"key_{secrets.token_hex(6)}"

    execute(
        """
        INSERT INTO api_keys (key_id, key_hash, user_id, role, label, is_active, created_at)
        VALUES (:kid, :khash, :uid, :role, :label, TRUE, NOW())
        """,
        {
            "kid": key_id,
            "khash": key_hash,
            "uid": context.subject,
            "role": wanted,
            "label": payload.label,
        },
    )

    return {
        "key_id": key_id,
        "api_key": raw_key,
        "role": wanted,
        "label": payload.label,
        "note": "Copy this API key now. It will not be shown again in plain text.",
    }


@router.get("/api-keys")
def list_api_keys(context: AuthContext = Depends(require_roles("admin", "developer", "api"))) -> dict[str, Any]:
    # An admin sees every key on the deployment; anyone else sees their own.
    if context.role == "admin":
        keys = fetch_all(
            "SELECT key_id, user_id, role, label, is_active, last_used_at, created_at "
            "FROM api_keys ORDER BY created_at DESC")
    else:
        keys = fetch_all(
            "SELECT key_id, user_id, role, label, is_active, last_used_at, created_at "
            "FROM api_keys WHERE user_id = :uid ORDER BY created_at DESC",
            {"uid": context.subject},
        )
    return {"api_keys": keys}


@router.delete("/api-keys/{key_id}")
def revoke_api_key(
    key_id: str,
    context: AuthContext = Depends(require_roles("admin", "developer", "api")),
) -> dict[str, Any]:
    if context.role == "admin":
        execute("DELETE FROM api_keys WHERE key_id = :kid", {"kid": key_id})
    else:
        execute(
            "DELETE FROM api_keys WHERE key_id = :kid AND user_id = :uid",
            {"kid": key_id, "uid": context.subject},
        )
    return {"status": "revoked", "key_id": key_id}
