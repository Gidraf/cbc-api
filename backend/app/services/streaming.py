"""Videos that are watched, not downloaded.

A parent or teacher on the video plan gets a short-lived link for one video
(`watch_link`): a signed token naming the stored object and the account, good
for a few hours. The stream itself (`stream`) is served inline with no
caching, from the server's storage or — for a video moved to Google Drive —
passed through from Drive byte range by byte range, so the Drive link is
never handed out. Nothing stops a determined person recording their screen;
this stops the easy copies: no file link, no download button, no cache.
"""
from __future__ import annotations

import time
from typing import Any

import jwt

TTL_SECONDS = 3 * 3600
STREAM_HEADERS = {"Cache-Control": "no-store, private", "Content-Disposition": "inline",
                  "X-Content-Type-Options": "nosniff", "Cross-Origin-Resource-Policy": "same-origin"}


def _secret() -> str:
    from ..settings import settings

    return "watch:" + settings.jwt_secret


def watch_link(owner: str, object_name: str, ttl: int = TTL_SECONDS) -> dict[str, Any]:
    now = int(time.time())
    token = jwt.encode({"type": "watch", "sub": owner, "obj": object_name, "iat": now, "exp": now + ttl},
                       _secret(), algorithm="HS256")
    return {"stream_url": f"/api/v1/watch/{token}", "expires_in": ttl}


def read(token: str) -> dict[str, Any] | None:
    try:
        claims = jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if claims.get("type") != "watch" or not claims.get("obj") or ".." in str(claims["obj"]):
        return None
    return claims


def stream(object_name: str, range_header: str) -> Any:
    """The video's bytes (the asked range of them), or None if it is nowhere."""
    from fastapi.responses import StreamingResponse

    from ..routes.assets import serve_object
    from . import drive_store

    served = serve_object(object_name, range_header, cache="no-store, private", extra=STREAM_HEADERS)
    if served is not None:
        return served
    moved = drive_store.record(object_name)
    if not moved or not moved.get("file_id"):
        return None
    drive = drive_store.Drive()
    headers = {**drive._auth()}
    if range_header:
        headers["Range"] = range_header
    request = drive.http.build_request("GET", f"{drive_store.API}/files/{moved['file_id']}",
                                       params={"alt": "media"}, headers=headers)
    upstream = drive.http.send(request, stream=True)
    if upstream.status_code not in (200, 206):
        upstream.close()
        return None
    out_headers = dict(STREAM_HEADERS)
    for name in ("Content-Length", "Content-Range", "Accept-Ranges"):
        if upstream.headers.get(name):
            out_headers[name] = upstream.headers[name]
    out_headers.setdefault("Accept-Ranges", "bytes")

    def body():
        try:
            yield from upstream.iter_bytes(64 * 1024)
        finally:
            upstream.close()

    return StreamingResponse(body(), status_code=upstream.status_code,
                             media_type=upstream.headers.get("Content-Type", "video/mp4"), headers=out_headers)
