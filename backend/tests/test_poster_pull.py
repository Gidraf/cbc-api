"""The poster on the owner's Mac: it checks in and asks for its commands,
because the server cannot reach it."""
import pytest

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routes import play
    from app.services import platform_settings, social_export
    from app.services.auth import AuthContext, get_auth_context

    calls = {"queued": [], "beats": [], "done": [], "saved": [], "proxied": []}
    fresh = {"value": None}
    results: dict[int, dict] = {}

    monkeypatch.setattr(platform_settings, "get", lambda key, default=None: ["gidraf"] if key == "video_makers" else default)
    monkeypatch.setattr(social_export, "pull_poster", lambda: fresh["value"])
    monkeypatch.setattr(social_export, "poster_overview", lambda: {"rules": {"daily_cap": 30}, "queue": []})

    def queue(action, platform="", post_id="", by="", options=None):
        calls["queued"].append((action, platform, post_id, by))
        calls.setdefault("options", []).append(options)
        results[len(calls["queued"])] = {"ok": True, "paused": action == "pause"}
        return len(calls["queued"])

    monkeypatch.setattr(social_export, "queue_command", queue)
    monkeypatch.setattr(social_export, "command_result", lambda cid: results.get(cid))
    monkeypatch.setattr(social_export, "heartbeat", lambda pid, status: calls["beats"].append((pid, status)))
    monkeypatch.setattr(social_export, "take_command", lambda: {"command_id": 7, "action": "check", "platform": "tiktok", "post_id": ""})
    monkeypatch.setattr(social_export, "finish_command", lambda cid, result: calls["done"].append((cid, result)))
    monkeypatch.setattr(play, "_poster_call", lambda method, path, body=None, timeout=8.0: calls["proxied"].append((method, path)) or {"online": True, "via": "server"})
    monkeypatch.setattr("time.sleep", lambda s: None)   # the route waits for the Mac's answer

    from app.infra.storage import object_storage

    monkeypatch.setattr(object_storage, "save_bytes", lambda key, data, ctype: calls["saved"].append((key, len(data), ctype)))

    who = {"subject": "gidraf", "role": "user"}
    app.dependency_overrides[get_auth_context] = lambda: AuthContext(subject=who["subject"], role=who["role"], auth_type="api_key")
    try:
        yield TestClient(app), calls, fresh, who
    finally:
        app.dependency_overrides.pop(get_auth_context, None)


def test_with_the_mac_checking_in_a_command_goes_to_its_queue_and_waits_for_the_answer(client):
    c, calls, fresh, _ = client
    fresh["value"] = {"online": True, "mode": "local", "poster_id": "Gidrafs-MacBook"}
    r = c.post("/api/v1/play/poster/command", json={"action": "pause"})
    assert r.status_code == 200 and r.json() == {"ok": True, "paused": True}
    assert calls["queued"] == [("pause", "", "", "gidraf")] and calls["proxied"] == []


def test_without_the_mac_a_command_goes_straight_to_the_server_poster(client):
    c, calls, fresh, _ = client
    r = c.post("/api/v1/play/poster/command", json={"action": "check", "platform": "tiktok"})
    assert r.json()["via"] == "server" and calls["queued"] == []
    assert calls["proxied"] == [("POST", "/check")]


def test_the_overview_shows_the_mac_and_no_shared_screen(client):
    c, _, fresh, _ = client
    fresh["value"] = {"online": True, "mode": "local", "poster_id": "Gidrafs-MacBook", "paused": False}
    body = c.get("/api/v1/play/poster/overview").json()
    assert body["live"]["mode"] == "local" and body["live"]["poster_id"] == "Gidrafs-MacBook"
    assert body["view_url"] == "" and body["rules"]["daily_cap"] == 30


def test_the_mac_checks_in_takes_a_command_and_reports_it(client):
    c, calls, _, _ = client
    assert c.post("/api/v1/play/poster/heartbeat", json={"poster_id": "mac", "status": {"paused": False}}).json() == {"ok": True}
    assert calls["beats"] == [("mac", {"paused": False, "mode": "local"})]
    cmd = c.post("/api/v1/play/poster/commands/next").json()["command"]
    assert cmd["action"] == "check" and cmd["platform"] == "tiktok"
    c.post(f"/api/v1/play/poster/commands/{cmd['command_id']}/done", json={"result": {"ok": True, "logins": {"tiktok": True}}})
    assert calls["done"] == [(7, {"ok": True, "logins": {"tiktok": True}})]


def test_only_pngs_are_kept_as_screenshots(client):
    c, calls, _, _ = client
    ok = c.post("/api/v1/play/poster/shots", files={"file": ("tiktok-dry-1.png", PNG, "image/png")})
    assert ok.json() == {"name": "tiktok-dry-1.png"}
    assert calls["saved"] == [("poster/shots/tiktok-dry-1.png", len(PNG), "image/png")]
    assert c.post("/api/v1/play/poster/shots", files={"file": ("x.png", b"<html>", "image/png")}).status_code == 400
    assert c.post("/api/v1/play/poster/shots", files={"file": ("../x.sh", PNG, "image/png")}).status_code == 400


def test_someone_who_is_not_a_video_maker_cannot_drive_the_poster(client):
    c, calls, _, who = client
    who["subject"] = "amina"
    for method, path, kw in [("post", "/api/v1/play/poster/heartbeat", {"json": {"poster_id": "x"}}),
                             ("post", "/api/v1/play/poster/commands/next", {}),
                             ("post", "/api/v1/play/poster/command", {"json": {"action": "pause"}})]:
        assert getattr(c, method)(path, **kw).status_code == 403
    assert calls["beats"] == [] and calls["queued"] == []


def test_old_commands_expire_before_one_is_taken(monkeypatch):
    from app.infra import db
    from app.services import social_export

    seen = []
    monkeypatch.setattr(db, "execute", lambda sql, params=None: seen.append(("execute", sql)))
    monkeypatch.setattr(db, "fetch_one", lambda sql, params=None: seen.append(("fetch", sql)) or None)
    assert social_export.take_command() is None
    assert "10 minutes" in seen[0][1] and "SKIP LOCKED" in seen[1][1]


def test_post_now_buttons_carry_feed_or_groups_and_five_groups_at_most(client):
    c, calls, fresh, _who = client
    fresh["value"] = True
    r = c.post("/api/v1/play/poster/command", json={"action": "run_now", "options": {"share": "feed"}})
    assert r.status_code == 200 and calls["options"][-1] == {"share": "feed", "groups": []}
    r = c.post("/api/v1/play/poster/command",
               json={"action": "run_now", "platform": "facebook", "options": {"share": "groups", "groups": ["A", "B"]}})
    assert r.status_code == 200 and calls["options"][-1] == {"share": "groups", "groups": ["A", "B"]}
    six = [f"G{i}" for i in range(6)]
    r = c.post("/api/v1/play/poster/command", json={"action": "run_now", "options": {"share": "groups", "groups": six}})
    assert r.status_code >= 400
    r = c.post("/api/v1/play/poster/command", json={"action": "run_now", "options": {"share": "everywhere"}})
    assert r.status_code >= 400
    r = c.post("/api/v1/play/poster/command", json={"action": "run_now"})          # the old button: no options
    assert r.status_code == 200 and calls["options"][-1] == {}
