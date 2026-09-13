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

from fastapi import APIRouter, Depends, Query, Request
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


@router.get("/share-link")
def share_link(
    request: Request,
    _: AuthContext = Depends(require_roles("admin")),
) -> dict:
    """The share link itself, for an admin to copy from the console.

    Built from the address this request arrived on, so it is right for
    whatever host and scheme the deployment is actually reached at. Only an
    admin sees it; it is the token, and the token opens the logs.
    """
    expected = os.getenv("LOG_SHARE_TOKEN", "").strip()
    enabled = bool(expected) and len(expected) >= 16
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    forwarded_host = request.headers.get("x-forwarded-host", "")
    scheme = forwarded_proto.split(",")[0].strip() or request.url.scheme
    host = forwarded_host.split(",")[0].strip() or request.headers.get("host", "") or request.url.netloc
    base = f"{scheme}://{host}"
    return {
        "enabled": enabled,
        "url": f"{base}/api/v1/admin/logs/share?token={expected}&since_minutes=60" if enabled else "",
        "how_to_enable": ("" if enabled else
                          "Set LOG_SHARE_TOKEN in .env to a random string of at least 16 "
                          "characters and restart the API."),
    }
