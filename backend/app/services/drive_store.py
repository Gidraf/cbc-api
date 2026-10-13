"""Rendered videos moved to the owner's Google Drive, and their links with them.

The videos filled the server's disk (75 GB, most of it MP4). This moves each
finished video — and its thumbnail — to a folder in the owner's Drive,
checks the copy against the original (Drive's MD5), makes it viewable by
anyone with the link, and records the move. From then on the storage layer
answers for the moved object from Drive: its public link is the Drive link,
it still "exists" (so it is never rendered again), and reading it fetches
it from Drive. The server's copy is removed only after a safety window.

Signing in: Google gives a service account no storage in a personal Drive,
so this signs in as the owner — an OAuth client and a refresh token made
once with `backend/scripts/drive_auth.py`. The scope is `drive.file`: the
platform can see and manage only the files it created, nothing else in the
Drive.

Settings (environment):
    GOOGLE_DRIVE_CLIENT_ID, GOOGLE_DRIVE_CLIENT_SECRET, GOOGLE_DRIVE_REFRESH_TOKEN
    GOOGLE_DRIVE_FOLDER_ID      optional; else a folder "CBC videos" is made
    DRIVE_KEEP_LOCAL_DAYS       days the server keeps its copy after a move (7)
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger("cbc-drive")

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
FOLDER_NAME = os.getenv("GOOGLE_DRIVE_FOLDER_NAME", "CBC videos")
# What moves: the rendered videos and their thumbnails. The posts' text and
# everything else (drawings, notes) stays where it is.
PREFIXES = ("videos/", "social/")
SUFFIXES = (".mp4", ".jpg")
CHUNK = 8 * 1024 * 1024
JOB_KIND = "drive_transfer"
PER_JOB = int(os.getenv("DRIVE_FILES_PER_JOB", "40"))


def keep_local_days() -> float:
    try:
        return max(0.0, float(os.getenv("DRIVE_KEEP_LOCAL_DAYS", "7")))
    except ValueError:
        return 7.0


def configured() -> bool:
    return all(os.getenv(k) for k in ("GOOGLE_DRIVE_CLIENT_ID", "GOOGLE_DRIVE_CLIENT_SECRET",
                                      "GOOGLE_DRIVE_REFRESH_TOKEN"))


def movable(object_name: str) -> bool:
    return bool(object_name) and object_name.startswith(PREFIXES) and object_name.endswith(SUFFIXES)


def view_url(file_id: str) -> str:
    """A link that plays and downloads for anyone who has it."""
    return f"https://drive.google.com/uc?export=download&id={file_id}"


# ── the record of what moved ────────────────────────────────────────────────

_cache: dict[str, tuple[dict[str, Any] | None, float]] = {}
_cache_lock = threading.Lock()
# A "not moved yet" answer goes stale: the worker moves files while the API
# serves links. A move, once recorded, does not.
UNMOVED_SECONDS = 60.0


def record(object_name: str) -> dict[str, Any] | None:
    """The move recorded for one object, or None. Cached per process: a page
    full of video links asks this once per link."""
    if not movable(object_name):
        return None
    with _cache_lock:
        hit = _cache.get(object_name)
        if hit and (hit[0] is not None or time.time() - hit[1] < UNMOVED_SECONDS):
            return hit[0]
    row = None
    try:
        from ..infra.db import fetch_one

        row = fetch_one("SELECT * FROM drive_objects WHERE object_name = :n", {"n": object_name})
    except Exception as exc:  # noqa: BLE001
        logger.debug("Drive record unreadable for %s: %s", object_name, exc)
        return None              # unknown, not "not moved": do not cache
    value = dict(row) if row else None
    with _cache_lock:
        _cache[object_name] = (value, time.time())
    return value


def record_by_file(file_id: str) -> dict[str, Any] | None:
    try:
        from ..infra.db import fetch_one

        row = fetch_one("SELECT * FROM drive_objects WHERE file_id = :f", {"f": file_id})
        return dict(row) if row else None
    except Exception:  # noqa: BLE001
        return None


def object_name_of(url: str) -> str:
    """The stored object a Drive link stands for, or "" for any other link."""
    import re

    m = re.search(r"drive\.google\.com/.*?(?:[?&]id=|/d/)([\w-]+)", url or "")
    if not m:
        return ""
    row = record_by_file(m.group(1))
    return str(row["object_name"]) if row else ""


def _forget(object_name: str) -> None:
    with _cache_lock:
        _cache.pop(object_name, None)


# ── Drive itself ────────────────────────────────────────────────────────────

class Drive:
    """The few Drive calls this needs, over plain HTTP."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.http = client or httpx.Client(timeout=120.0, follow_redirects=True)
        self._token = ""
        self._expires = 0.0
        self._folder = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")

    def token(self) -> str:
        if self._token and time.time() < self._expires - 60:
            return self._token
        r = self.http.post(TOKEN_URL, data={
            "client_id": os.getenv("GOOGLE_DRIVE_CLIENT_ID", ""),
            "client_secret": os.getenv("GOOGLE_DRIVE_CLIENT_SECRET", ""),
            "refresh_token": os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN", ""),
            "grant_type": "refresh_token"})
        if r.status_code != 200:
            raise RuntimeError(f"Google refused the Drive sign-in ({r.status_code}): {r.text[:200]} — "
                               f"make a new refresh token with backend/scripts/drive_auth.py")
        body = r.json()
        self._token, self._expires = body["access_token"], time.time() + float(body.get("expires_in") or 3600)
        return self._token

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token()}"}

    def folder(self) -> str:
        """The folder the videos go in: the one named in settings, else the
        platform's own "CBC videos" folder, made the first time."""
        if self._folder:
            return self._folder
        q = (f"name = '{FOLDER_NAME}' and mimeType = 'application/vnd.google-apps.folder' "
             f"and trashed = false")
        r = self.http.get(f"{API}/files", params={"q": q, "fields": "files(id)"}, headers=self._auth())
        r.raise_for_status()
        found = r.json().get("files") or []
        if found:
            self._folder = found[0]["id"]
        else:
            r = self.http.post(f"{API}/files", params={"fields": "id"}, headers=self._auth(),
                               json={"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"})
            r.raise_for_status()
            self._folder = r.json()["id"]
        return self._folder

    def upload(self, name: str, payload: bytes, mime: str) -> dict[str, Any]:
        """A resumable upload, in chunks. Returns {id, md5Checksum, size}."""
        r = self.http.post(UPLOAD, params={"uploadType": "resumable", "fields": "id,md5Checksum,size"},
                           headers={**self._auth(), "X-Upload-Content-Type": mime,
                                    "X-Upload-Content-Length": str(len(payload))},
                           json={"name": name, "parents": [self.folder()]})
        r.raise_for_status()
        session = r.headers["Location"]
        total, start = len(payload), 0
        while True:
            end = min(start + CHUNK, total) - 1
            chunk = payload[start:end + 1]
            r = self.http.put(session, content=chunk, headers={
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {start}-{end}/{total}" if total else "bytes */0"})
            if r.status_code in (200, 201):
                return r.json()
            if r.status_code != 308:
                raise RuntimeError(f"Drive upload of {name} stopped ({r.status_code}): {r.text[:200]}")
            got = r.headers.get("Range", "")
            start = int(got.split("-")[-1]) + 1 if got else end + 1

    def share(self, file_id: str) -> None:
        """Viewable by anyone with the link — what a posted video needs."""
        r = self.http.post(f"{API}/files/{file_id}/permissions", headers=self._auth(),
                           json={"role": "reader", "type": "anyone"})
        r.raise_for_status()

    def download(self, file_id: str) -> bytes:
        r = self.http.get(f"{API}/files/{file_id}", params={"alt": "media"}, headers=self._auth())
        r.raise_for_status()
        return r.content


# ── the move ────────────────────────────────────────────────────────────────

def pending(limit: int = PER_JOB) -> list[str]:
    """Finished videos and thumbnails on the server and not yet on Drive."""
    from ..infra.db import fetch_all
    from ..infra.storage import object_storage
    from ..settings import settings

    client = object_storage._get_client()
    moved = {str(r["object_name"]) for r in (fetch_all("SELECT object_name FROM drive_objects") or [])}
    cutoff = time.time() - 120          # not one still being written
    out: list[str] = []
    for prefix in PREFIXES:
        for obj in client.list_objects(settings.minio_bucket, prefix=prefix, recursive=True):
            name = str(obj.object_name)
            modified = getattr(obj, "last_modified", None)
            if (movable(name) and name not in moved
                    and (modified is None or modified.timestamp() < cutoff)):
                out.append(name)
                if len(out) >= limit:
                    return out
    return out


def move(object_name: str, drive: Drive) -> dict[str, Any]:
    """One object to Drive: upload, check the copy, share it, record it."""
    from ..infra.db import execute
    from ..infra.storage import object_storage

    payload = object_storage.read_bytes(object_name)
    if not payload:
        raise RuntimeError(f"{object_name} is empty or gone on the server")
    md5 = hashlib.md5(payload).hexdigest()
    mime = "video/mp4" if object_name.endswith(".mp4") else "image/jpeg"
    made = drive.upload(object_name.replace("/", "__"), payload, mime)
    if made.get("md5Checksum") and made["md5Checksum"] != md5:
        raise RuntimeError(f"The Drive copy of {object_name} does not match the original; not recorded")
    drive.share(made["id"])
    execute(
        """INSERT INTO drive_objects (object_name, file_id, url, md5, bytes)
           VALUES (:n, :f, :u, :m, :b)
           ON CONFLICT (object_name) DO UPDATE SET file_id = EXCLUDED.file_id, url = EXCLUDED.url,
                md5 = EXCLUDED.md5, bytes = EXCLUDED.bytes, moved_at = NOW(), local_removed_at = NULL""",
        {"n": object_name, "f": made["id"], "u": view_url(made["id"]), "m": md5, "b": len(payload)})
    _forget(object_name)
    return {"object_name": object_name, "file_id": made["id"], "bytes": len(payload)}


def remove_local_copies(days: float | None = None) -> int:
    """The server's copies of objects moved more than `days` ago, deleted —
    the disk space the move was for. Only objects whose Drive copy was
    checked; never one still needed locally."""
    from ..infra.db import execute, fetch_all
    from ..infra.storage import object_storage

    days = keep_local_days() if days is None else days
    rows = fetch_all("""SELECT object_name FROM drive_objects WHERE local_removed_at IS NULL
                        AND moved_at < NOW() - (:d * INTERVAL '1 day')""", {"d": days}) or []
    removed = 0
    for row in rows:
        name = str(row["object_name"])
        if object_storage.remove_object(name):
            execute("UPDATE drive_objects SET local_removed_at = NOW() WHERE object_name = :n", {"n": name})
            removed += 1
    return removed


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    """The queued move: a batch of objects, then the server copies whose
    safety window has passed. Another job is queued if more are waiting."""
    from . import job_queue, run_log

    if not configured():
        return {"status": "skipped", "reason": "Google Drive is not set up (GOOGLE_DRIVE_* settings)"}
    drive = Drive()
    todo = pending()
    live = job_queue.Live(str(job.get("job_id") or ""), stages=(("upload", 100),))
    run_log.step("Moving", f"{len(todo)} file(s) to Google Drive")
    moved, failed, sent = 0, [], 0
    for n, name in enumerate(todo, start=1):
        try:
            out = move(name, drive)
            moved += 1
            sent += out["bytes"]
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{name}: {str(exc)[:160]}")
            logger.warning("Drive move of %s failed: %s", name, exc)
        live("upload", n, len(todo))
    removed = remove_local_copies()
    run_log.step("Moved", f"{moved} file(s), {sent / 1e6:.1f} MB; {removed} server copies removed")
    if len(todo) >= PER_JOB and moved:
        enqueue(queued_by="drive (more waiting)")
    if failed and not moved:
        raise RuntimeError("Nothing moved: " + "; ".join(failed[:3]))
    return {"status": "done", "moved": moved, "megabytes": round(sent / 1e6, 1), "failed": failed,
            "server_copies_removed": removed}


def enqueue(queued_by: str = "drive") -> dict[str, Any] | None:
    """Queue a move, unless one is already waiting or running."""
    from ..infra.db import fetch_one
    from . import job_queue

    if not configured():
        return None
    busy = fetch_one("SELECT job_id FROM jobs WHERE kind = :k AND status IN ('queued', 'running') LIMIT 1",
                     {"k": JOB_KIND})
    if busy:
        return {"job_id": busy["job_id"], "status": "already queued"}
    job = job_queue.enqueue(JOB_KIND, "", "", {}, queued_by=queued_by)
    job_queue.dispatch(job.job_id)
    return {"job_id": job.job_id, "status": "queued"}


def summary() -> dict[str, Any]:
    """For the console: whether Drive is set up, what has moved, what waits."""
    from ..infra.db import fetch_one

    out: dict[str, Any] = {"configured": configured(), "keep_local_days": keep_local_days()}
    try:
        row = fetch_one("""SELECT COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS b,
                                  COUNT(*) FILTER (WHERE local_removed_at IS NOT NULL) AS freed,
                                  COALESCE(SUM(bytes) FILTER (WHERE local_removed_at IS NOT NULL), 0) AS freed_b
                           FROM drive_objects""") or {}
        busy = fetch_one("""SELECT job_id, status, live FROM jobs WHERE kind = :k AND status IN ('queued', 'running')
                            ORDER BY created_at DESC LIMIT 1""", {"k": JOB_KIND})
        out.update(moved=int(row.get("n") or 0), moved_mb=round(int(row.get("b") or 0) / 1e6, 1),
                   freed=int(row.get("freed") or 0), freed_mb=round(int(row.get("freed_b") or 0) / 1e6, 1),
                   job=dict(busy) if busy else None)
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)[:200]
    return out
