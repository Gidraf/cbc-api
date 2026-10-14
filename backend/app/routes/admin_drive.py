"""Google Drive, connected from the console by an admin — no terminal.

1. In Google Cloud, make an OAuth client of type "Web application" with this
   redirect URI: <public address>/api/v1/admin/drive/callback (the console
   shows the exact one), and paste its ID and secret in Settings.
2. Press "Connect Google Drive": Google asks the admin to allow access to
   the files the platform makes (scope drive.file, nothing else), and sends
   the platform back a refresh token, kept encrypted in the database.

From then on the half-hourly job moves finished videos there, privately: no
file is shared, and every video reaches a viewer through the platform.
"""
from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode

import jwt
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from ..errors import raise_api_error
from ..services.auth import AuthContext, require_roles

router = APIRouter(prefix="/api/v1/admin/drive", tags=["Google Drive"])
ADMIN = require_roles("admin")
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def _redirect_uri(request: Request) -> str:
    from ..services import platform_settings

    return f"{platform_settings.public_base_url(request)}/api/v1/admin/drive/callback"


def _state_secret() -> str:
    from ..settings import settings

    return "drive-oauth:" + settings.jwt_secret


@router.get("")
def drive_status(request: Request, auth: AuthContext = Depends(ADMIN)) -> dict[str, Any]:
    """Connected or not, from where, and what has moved — never a secret."""
    from ..infra.db import fetch_one
    from ..services import drive_store

    c = drive_store.credentials()
    counts = {}
    try:
        counts = fetch_one("""SELECT COUNT(*) AS files, COALESCE(SUM(bytes), 0) AS bytes,
                                     COUNT(*) FILTER (WHERE private_at IS NULL) AS public_left
                              FROM drive_objects""") or {}
    except Exception:  # noqa: BLE001
        counts = {}
    return {"connected": drive_store.configured(), "source": c.get("source") or "",
            "has_client": bool(c["client_id"] and c["client_secret"]),
            "client_id_hint": (c["client_id"][:12] + "…") if c["client_id"] else "",
            "connected_at": c.get("connected_at") or "", "folder_id": c.get("folder_id") or "",
            "redirect_uri": _redirect_uri(request),
            "moved_files": int(counts.get("files") or 0), "moved_gb": round(int(counts.get("bytes") or 0) / 1e9, 2),
            "still_shared": int(counts.get("public_left") or 0)}


class Client(BaseModel):
    client_id: str = Field(min_length=10, max_length=300)
    client_secret: str = Field(min_length=6, max_length=300)
    folder_id: str = Field(default="", max_length=200)


@router.put("/client")
def set_client(payload: Client, auth: AuthContext = Depends(ADMIN)) -> dict[str, Any]:
    """The Google OAuth client (Web application) the platform signs in with."""
    from ..services import drive_store

    if not payload.client_id.strip().endswith(".apps.googleusercontent.com"):
        raise_api_error("VALIDATION_FAILED", "That is not a Google OAuth client ID (it ends in .apps.googleusercontent.com).")
    drive_store.save_credentials(client_id=payload.client_id.strip(), client_secret=payload.client_secret.strip(),
                                 folder_id=payload.folder_id.strip())
    return {"ok": True}


@router.get("/connect")
def connect(request: Request, auth: AuthContext = Depends(ADMIN)) -> dict[str, Any]:
    """Where to send the admin's browser: Google's consent page."""
    from ..services import drive_store

    c = drive_store.credentials()
    if not (c["client_id"] and c["client_secret"]):
        raise_api_error("VALIDATION_FAILED", "Save the Google OAuth client ID and secret first.")
    state = jwt.encode({"sub": auth.subject, "type": "drive_oauth", "exp": int(time.time()) + 900},
                       _state_secret(), algorithm="HS256")
    params = {"client_id": c["client_id"], "redirect_uri": _redirect_uri(request), "response_type": "code",
              "scope": drive_store.SCOPE, "access_type": "offline", "prompt": "consent",
              "include_granted_scopes": "true", "state": state}
    return {"auth_url": f"{AUTH_URL}?{urlencode(params)}"}


@router.get("/callback", include_in_schema=False)
def callback(request: Request, code: str = Query(""), state: str = Query(""), error: str = Query("")) -> RedirectResponse:
    """Google sends the admin back here. The state proves it is the sign-in
    this platform started, for an admin, minutes ago."""
    import httpx

    from ..services import drive_store

    def back(result: str) -> RedirectResponse:
        return RedirectResponse(f"/settings?drive={result}", status_code=302)

    if error:
        return back("refused")
    try:
        claims = jwt.decode(state, _state_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return back("expired")
    if claims.get("type") != "drive_oauth" or not code:
        return back("failed")
    c = drive_store.credentials()
    try:
        r = httpx.post(drive_store.TOKEN_URL, timeout=30, data={
            "code": code, "client_id": c["client_id"], "client_secret": c["client_secret"],
            "redirect_uri": _redirect_uri(request), "grant_type": "authorization_code"})
        body = r.json() if r.content else {}
    except (httpx.HTTPError, ValueError):
        return back("failed")
    if r.status_code != 200 or not body.get("refresh_token"):
        return back("failed")
    from datetime import datetime, timezone

    drive_store.save_credentials(refresh_token=str(body["refresh_token"]),
                                 connected_at=datetime.now(timezone.utc).isoformat())
    return back("connected")


@router.post("/disconnect")
def disconnect(auth: AuthContext = Depends(ADMIN)) -> dict[str, Any]:
    """Forget the refresh token (the files stay in Drive; the platform stops moving more)."""
    from ..services import drive_store

    drive_store.save_credentials(refresh_token="", connected_at="")
    return {"ok": True}


@router.post("/privatize")
def make_private(auth: AuthContext = Depends(ADMIN)) -> dict[str, Any]:
    """Take "anyone with the link" off files moved before moves stopped sharing them."""
    from ..services import drive_store

    if not drive_store.configured():
        raise_api_error("VALIDATION_FAILED", "Connect Google Drive first.")
    return {"made_private": drive_store.privatize(limit=500)}


@router.post("/move-now")
def move_now(auth: AuthContext = Depends(ADMIN)) -> dict[str, Any]:
    from ..services import drive_store

    return drive_store.enqueue(queued_by=auth.subject) or {"status": "not connected"}
