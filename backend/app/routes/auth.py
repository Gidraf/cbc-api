from __future__ import annotations

import hashlib
import secrets
from typing import Any

from fastapi import APIRouter, Depends
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
    role: str = "developer"


class RefreshRequest(BaseModel):
    refresh_token: str


class CreateApiKeyRequest(BaseModel):
    label: str = "Default API Key"


@router.post("/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    context = authenticate_login(payload.username, payload.password)
    access_token = create_access_token(context.subject, context.role)
    refresh_token = create_refresh_token(context.subject)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "role": context.role,
        "subject": context.subject,
    }


@router.post("/register")
def register(payload: RegisterRequest) -> dict[str, Any]:
    existing = fetch_one("SELECT username FROM app_users WHERE username = :uname", {"uname": payload.username})
    if existing:
        raise_api_error("UNAUTHORIZED_ACCESS", "Username is already registered")

    pwd_hash = hash_password(payload.password)
    execute(
        """
        INSERT INTO app_users (username, password_plain, password_hash, role, email, is_active, updated_at)
        VALUES (:uname, '', :phash, :role, :email, TRUE, NOW())
        """,
        {
            "uname": payload.username,
            "phash": pwd_hash,
            "role": payload.role if payload.role in {"developer", "operator", "reviewer"} else "developer",
            "email": payload.email,
        },
    )

    return {"status": "registered", "username": payload.username}


@router.post("/refresh")
def refresh_token_endpoint(payload: RefreshRequest) -> dict[str, Any]:
    username = verify_and_consume_refresh_token(payload.refresh_token)
    user_row = fetch_one("SELECT username, role FROM app_users WHERE username = :uname", {"uname": username})
    role = user_row["role"] if user_row else "developer"

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
    context: AuthContext = Depends(require_roles("admin", "developer")),
) -> dict[str, Any]:
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
            "role": context.role,
            "label": payload.label,
        },
    )

    return {
        "key_id": key_id,
        "api_key": raw_key,
        "label": payload.label,
        "note": "Copy this API key now. It will not be shown again in plain text.",
    }


@router.get("/api-keys")
def list_api_keys(context: AuthContext = Depends(require_roles("admin", "developer"))) -> dict[str, Any]:
    keys = fetch_all(
        "SELECT key_id, user_id, role, label, is_active, last_used_at, created_at FROM api_keys WHERE user_id = :uid",
        {"uid": context.subject},
    )
    return {"api_keys": keys}


@router.delete("/api-keys/{key_id}")
def revoke_api_key(
    key_id: str,
    context: AuthContext = Depends(require_roles("admin", "developer")),
) -> dict[str, Any]:
    execute(
        "DELETE FROM api_keys WHERE key_id = :kid AND user_id = :uid",
        {"kid": key_id, "uid": context.subject},
    )
    return {"status": "revoked", "key_id": key_id}
