from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import jwt
from fastapi import Depends, Header

from ..errors import raise_api_error
from ..settings import settings
from ..state import runtime_state


ROLES = {"admin", "operator", "reviewer", "developer"}


@dataclass(slots=True)
class AuthContext:
    subject: str
    role: str
    auth_type: str


def create_access_token(subject: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.jwt_exp_minutes)
    payload = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise_api_error("UNAUTHORIZED_ACCESS", "Invalid or expired access token")


def authenticate_login(username: str, password: str) -> AuthContext:
    accounts = runtime_state.user_accounts
    account = accounts.get(username)
    if not account or account["password"] != password:
        raise_api_error("UNAUTHORIZED_ACCESS", "Invalid username or password")

    role = account["role"]
    if role not in ROLES:
        raise_api_error("UNAUTHORIZED_ACCESS", "Invalid account role configuration")

    return AuthContext(subject=username, role=role, auth_type="bearer")


def get_auth_context(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> AuthContext:
    if x_api_key and settings.developer_api_key and x_api_key == settings.developer_api_key:
        return AuthContext(subject="developer_api_key", role="developer", auth_type="api_key")

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
            raise_api_error("UNAUTHORIZED_ACCESS", "Role is not authorized for this action")
        return context

    return dependency
