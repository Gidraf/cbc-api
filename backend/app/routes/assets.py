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


@router.get("/{bucket}/{object_path:path}")
def asset(bucket: str, object_path: str, request: Request) -> Response:
    from ..infra.storage import object_storage

    if bucket != settings.minio_bucket or ".." in object_path:
        return Response(status_code=404)
    client = object_storage._get_client()
    try:
        stat = client.stat_object(bucket, object_path)
    except Exception:  # noqa: BLE001
        return Response(status_code=404)
    size = int(stat.size)
    media = stat.content_type or mimetypes.guess_type(object_path)[0] or "application/octet-stream"
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=86400"}
    start, end, status = 0, size - 1, 200
    match = _RANGE.match(request.headers.get("range", ""))
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
