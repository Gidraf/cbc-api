"""Finished videos moved to the owner's Google Drive, links and all."""
from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from app.services import drive_store as D

VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"x" * 5000


@pytest.fixture
def env(monkeypatch):
    for k, v in {"GOOGLE_DRIVE_CLIENT_ID": "cid", "GOOGLE_DRIVE_CLIENT_SECRET": "sec",
                 "GOOGLE_DRIVE_REFRESH_TOKEN": "ref"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("GOOGLE_DRIVE_FOLDER_ID", raising=False)
    D._cache.clear()
    D._creds_cache.update(at=0.0, value=None)        # the sign-in is read afresh: the environment's here


class FakeGoogle:
    """Token, folder search/create, resumable upload (in two chunks), share,
    download — as Drive answers them."""

    def __init__(self, md5=None, folder_exists=False):
        self.calls, self.md5, self.folder_exists = [], md5, folder_exists
        self.received = b""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append((request.method, url.split("?")[0]))
        if url.startswith(D.TOKEN_URL):
            assert b"grant_type=refresh_token" in request.content and b"refresh_token=ref" in request.content
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers.get("Authorization", "").startswith("Bearer tok") or "upload-session" in url
        if request.method == "GET" and url.startswith(f"{D.API}/files?"):
            return httpx.Response(200, json={"files": [{"id": "fold1"}] if self.folder_exists else []})
        if request.method == "POST" and url.startswith(f"{D.API}/files?"):
            assert json.loads(request.content)["mimeType"] == "application/vnd.google-apps.folder"
            return httpx.Response(200, json={"id": "fold1"})
        if request.method == "POST" and url.startswith(D.UPLOAD):
            meta = json.loads(request.content)
            assert meta["parents"] == ["fold1"] and meta["name"] == "social__q1__k1.mp4"
            return httpx.Response(200, headers={"Location": "https://upload-session/1"})
        if request.method == "PUT":
            self.received += request.content
            total = int(request.headers["Content-Range"].split("/")[1])
            if len(self.received) < total:
                return httpx.Response(308, headers={"Range": f"bytes=0-{len(self.received) - 1}"})
            return httpx.Response(200, json={"id": "file1", "size": str(total),
                                             "md5Checksum": self.md5 or hashlib.md5(self.received).hexdigest()})
        if url.endswith("/permissions"):
            assert json.loads(request.content) == {"role": "reader", "type": "anyone"}
            return httpx.Response(200, json={"id": "anyone"})
        if request.method == "GET" and "/files/file1" in url:
            return httpx.Response(200, content=VIDEO)
        raise AssertionError(url)


@pytest.fixture
def world(monkeypatch, env):
    from app.infra import db, storage

    rows, sql = {}, []
    monkeypatch.setattr(storage.object_storage, "read_bytes", lambda name: VIDEO)
    monkeypatch.setattr(db, "execute", lambda q, p=None: sql.append((q, p)) or (
        rows.__setitem__(p["n"], {"object_name": p["n"], "file_id": p["f"], "url": p["u"]})
        if "INSERT INTO drive_objects" in q else None))
    monkeypatch.setattr(db, "fetch_one", lambda q, p=None: rows.get((p or {}).get("n")) if "object_name = :n" in q
                        else next((r for r in rows.values() if r["file_id"] == (p or {}).get("f")), None))
    monkeypatch.setattr(D, "CHUNK", 3000)        # two chunks, so the 308 path is exercised
    return rows, sql


def test_a_video_is_uploaded_in_chunks_checked_kept_private_and_recorded(world):
    rows, _ = world
    google = FakeGoogle()
    out = D.move("social/q1/k1.mp4", D.Drive(httpx.Client(transport=httpx.MockTransport(google))))
    assert google.received == VIDEO, "every byte, across the chunks"
    assert out == {"object_name": "social/q1/k1.mp4", "file_id": "file1", "bytes": len(VIDEO)}
    assert rows["social/q1/k1.mp4"]["url"] == "https://drive.google.com/uc?export=download&id=file1"
    assert not any("/permissions" in url for _, url in google.calls), "never shared: viewers stream it through us"
    assert ("POST", f"{D.API}/files") in google.calls, "the folder was made the first time"


def test_a_copy_that_does_not_match_is_not_recorded(world):
    rows, _ = world
    google = FakeGoogle(md5="0" * 32)
    with pytest.raises(RuntimeError, match="does not match"):
        D.move("social/q1/k1.mp4", D.Drive(httpx.Client(transport=httpx.MockTransport(google))))
    assert rows == {}, "the server keeps the only good copy"


def test_an_existing_folder_is_reused(world):
    google = FakeGoogle(folder_exists=True)
    D.move("social/q1/k1.mp4", D.Drive(httpx.Client(transport=httpx.MockTransport(google))))
    assert ("POST", f"{D.API}/files") not in google.calls


def test_only_finished_videos_and_thumbnails_move():
    assert D.movable("social/q1/abc.mp4") and D.movable("videos/q9/abc.jpg")
    assert not D.movable("social/q1/abc.txt") and not D.movable("diagrams/x.svg") and not D.movable("")


def test_the_storage_layer_answers_for_a_moved_video_from_drive(monkeypatch, env):
    from app.infra import storage

    moved = {"object_name": "social/q1/k1.mp4", "file_id": "file1",
             "url": "https://drive.google.com/uc?export=download&id=file1"}
    monkeypatch.setattr(D, "record", lambda name: moved if name == "social/q1/k1.mp4" else None)
    monkeypatch.setattr(D, "record_by_file", lambda f: moved if f == "file1" else None)

    assert "drive.google.com" not in storage.public_object_url("social/q1/k1.mp4"), "our address, never Drive's"
    assert storage.public_object_url("social/q1/k1.mp4").endswith("/social/q1/k1.mp4")
    assert storage.public_object_url("diagrams/a.svg").endswith("/diagrams/a.svg"), "nothing else changes"

    class Gone:
        def stat_object(self, *a):
            raise FileNotFoundError

        def get_object(self, *a):
            raise FileNotFoundError

    monkeypatch.setattr(storage.object_storage, "_get_client", lambda: Gone())
    monkeypatch.setattr(storage.object_storage, "ensure_bucket", lambda: True)
    assert storage.object_storage.object_exists("social/q1/k1.mp4"), "moved is still made: never re-rendered"
    assert not storage.object_storage.object_exists("social/q2/k2.mp4")
    monkeypatch.setattr(D.Drive, "download", lambda self, fid: VIDEO if fid == "file1" else b"")
    assert storage.object_storage.read_bytes("social/q1/k1.mp4") == VIDEO, "the export still gets the bytes"
    assert storage.object_storage.object_name_of(moved["url"]) == "social/q1/k1.mp4"


def test_server_copies_go_only_after_the_safety_window(monkeypatch, env):
    from app.infra import db, storage

    seen, removed = {}, []
    monkeypatch.setattr(db, "fetch_all", lambda q, p=None: seen.update(p or {}) or [{"object_name": "social/q1/k1.mp4"}])
    monkeypatch.setattr(db, "execute", lambda q, p=None: None)
    monkeypatch.setattr(storage.object_storage, "remove_object", lambda n: removed.append(n) or True)
    monkeypatch.setenv("DRIVE_KEEP_LOCAL_DAYS", "7")
    assert D.remove_local_copies() == 1 and seen["d"] == 7.0 and removed == ["social/q1/k1.mp4"]


def test_not_set_up_moves_nothing_and_a_move_is_queued_once(monkeypatch):
    from app.infra import db

    for k in ("GOOGLE_DRIVE_CLIENT_ID", "GOOGLE_DRIVE_CLIENT_SECRET", "GOOGLE_DRIVE_REFRESH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(db, "fetch_one", lambda q, p=None: None)          # nothing connected in the console either
    D._creds_cache.update(at=0.0, value=None)
    assert D.run_job({"job_id": "j"})["status"] == "skipped" and D.enqueue() is None

    monkeypatch.setenv("GOOGLE_DRIVE_CLIENT_ID", "c"); monkeypatch.setenv("GOOGLE_DRIVE_CLIENT_SECRET", "s")
    monkeypatch.setenv("GOOGLE_DRIVE_REFRESH_TOKEN", "r")
    D._creds_cache.update(at=0.0, value=None)
    monkeypatch.setattr(db, "fetch_one", lambda q, p=None: {"job_id": "busy"})
    assert D.enqueue() == {"job_id": "busy", "status": "already queued"}


def test_an_old_link_to_a_moved_video_is_streamed_through_us_to_those_allowed(monkeypatch):
    from fastapi.responses import Response
    from starlette.requests import Request

    from app.infra import storage
    from app.routes import assets
    from app.services import streaming
    from app.settings import settings

    class Gone:
        def stat_object(self, *a):
            raise FileNotFoundError

    monkeypatch.setattr(storage.object_storage, "_get_client", lambda: Gone())
    monkeypatch.setattr(D, "record", lambda name: {"file_id": "f9", "url": "https://drive.google.com/uc?export=download&id=f9"})
    monkeypatch.setattr(streaming, "stream", lambda name, rng: Response(b"video", status_code=206))
    request = Request({"type": "http", "headers": [], "method": "GET", "path": "/"})
    assert assets.asset(settings.minio_bucket, "social/q1/k1.mp4", request).status_code == 403, "signed out: no file"
    monkeypatch.setattr(assets, "_may_fetch_media", lambda request: True)
    response = assets.asset(settings.minio_bucket, "social/q1/k1.mp4", request)
    assert response.status_code == 206 and "location" not in response.headers, "passed through, never a Drive redirect"


def test_the_move_reports_its_progress_as_uploads():
    from app.services.job_queue import Live

    live = Live("j", stages=(("upload", 100),))
    assert live.percent("upload", 10, 40) == 25.0
