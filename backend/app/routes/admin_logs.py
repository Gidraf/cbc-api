"""The service's recent log lines, as text, for an operator or a tool.

Two doors. `GET /api/v1/admin/logs` is for a signed-in admin. `GET
/api/v1/admin/logs/share?token=…` is for a link the operator hands to
someone — or something — diagnosing a run without an account: it opens only
when LOG_SHARE_TOKEN is set, only to that token, only to logs, and the token
is a line in .env that can be changed the moment the link has served its
purpose. Credentials that reach the log are redacted before they are stored.
"""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from ..errors import raise_api_error
from ..services import log_store
from ..services.auth import AuthContext, require_roles

router = APIRouter(prefix="/api/v1/admin/logs", tags=["Admin Logs"])


def _serve(lines: int, grep: str, level: str, since_minutes: int, process: str) -> PlainTextResponse:
    rows = log_store.recent(lines=lines, grep=grep, level=level,
                            since_minutes=since_minutes, process=process)
    body = log_store.as_text(rows) or "(no matching log lines)\n"
    return PlainTextResponse(body)


@router.get("", response_class=PlainTextResponse)
def read_logs(
    lines: int = Query(500, ge=1, le=log_store.KEEP),
    grep: str = Query(""),
    level: str = Query(""),
    since_minutes: int = Query(0, ge=0),
    process: str = Query(""),
    _: AuthContext = Depends(require_roles("admin")),
) -> PlainTextResponse:
    return _serve(lines, grep, level, since_minutes, process)


@router.get("/share", response_class=PlainTextResponse)
def share_logs(
    token: str = Query(""),
    lines: int = Query(500, ge=1, le=log_store.KEEP),
    grep: str = Query(""),
    level: str = Query(""),
    since_minutes: int = Query(0, ge=0),
    process: str = Query(""),
) -> PlainTextResponse:
    expected = os.getenv("LOG_SHARE_TOKEN", "").strip()
    if not expected or len(expected) < 16:
        raise_api_error("NOT_FOUND", "Log sharing is not enabled on this deployment.")
    if not hmac.compare_digest(token.strip(), expected):
        raise_api_error("UNAUTHORIZED_ACCESS", "That link is not valid.")
    return _serve(lines, grep, level, since_minutes, process)
