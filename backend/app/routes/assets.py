"""Stored files, served under the platform's own address.

Every figure, voice clip and video used to be linked at MinIO's own address
(`http://<server-ip>:6500/cbc-assets/…`): an IP nobody should see, and plain
http that a browser on the https console refuses to load. Served from here,
a file is `https://<public address>/api/v1/assets/<bucket>/<object>` and
travels through the same proxy as the console. Ranges are honoured, so a
video can be scrubbed.
"""
from __future__ import annotations

import mimetypes
import re

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from ..settings import settings

router = APIRouter(prefix="/api/v1/assets", tags=["Assets"])
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


# Video and sound are never free files: the platform's own people (staff, the
# poster's key) fetch them; everyone else streams them through /api/v1/watch.
MEDIA = (".mp4", ".webm", ".mov", ".m4v", ".mp3", ".wav", ".m4a", ".ogg")
MEDIA_ROLES = {"admin", "operator", "reviewer", "developer", "poster"}


def _may_fetch_media(request: Request) -> bool:
    from ..errors import ApiError
    from ..services.auth import get_auth_context

    try:
        auth = get_auth_context(authorization=request.headers.get("authorization"),
                                x_api_key=request.headers.get("x-api-key"))
    except ApiError:
        return False
    return auth.role in MEDIA_ROLES


@router.get("/{bucket}/{object_path:path}")
def asset(bucket: str, object_path: str, request: Request) -> Response:
    if bucket != settings.minio_bucket or ".." in object_path:
        return Response(status_code=404)
    media = object_path.lower().endswith(MEDIA)
    if media and not _may_fetch_media(request):
        return Response(status_code=403, content="Videos are watched in the platform, not downloaded.")
    cache = "private, no-store" if media else "public, max-age=86400"
    out = serve_object(object_path, request.headers.get("range", ""), cache=cache)
    if out is not None:
        return out
    # Moved to Google Drive: passed through from there — the Drive file is
    # private, and its link is never handed out.
    from ..services import streaming

    streamed = streaming.stream(object_path, request.headers.get("range", ""))
    return streamed if streamed is not None else Response(status_code=404)


def serve_object(object_path: str, range_header: str, *, cache: str, extra: dict[str, str] | None = None) -> Response | None:
    """One stored object, with byte ranges (a video can be scrubbed), or
    None when the server does not have it (it may have moved to Drive)."""
    from ..infra.storage import object_storage

    bucket = settings.minio_bucket
    client = object_storage._get_client()
    try:
        stat = client.stat_object(bucket, object_path)
    except Exception:  # noqa: BLE001
        return None
    size = int(stat.size)
    media = stat.content_type or mimetypes.guess_type(object_path)[0] or "application/octet-stream"
    headers = {"Accept-Ranges": "bytes", "Cache-Control": cache, **(extra or {})}
    start, end, status = 0, size - 1, 200
    match = _RANGE.match(range_header or "")
    if match and size:
        a, b = match.groups()
        start = int(a) if a else max(0, size - int(b or 0))
        end = min(int(b), size - 1) if (a and b) else size - 1
        if start > end or start >= size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        status = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    length = end - start + 1 if size else 0
    headers["Content-Length"] = str(length)
    obj = client.get_object(bucket, object_path, offset=start, length=length) if size else None

    def body():
        if obj is None:
            return
        try:
            yield from obj.stream(64 * 1024)
        finally:
            obj.close()
            obj.release_conn()

    return StreamingResponse(body(), status_code=status, media_type=media, headers=headers)
