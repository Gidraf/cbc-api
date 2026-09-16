"""The MCP server must answer a ping while a tool call waits on the platform,
and no tool call may outlive an agent's patience."""
from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1] / "app" / "agent_clients" / "cbc_mcp.py"


class _SlowApi(http.server.BaseHTTPRequestHandler):
    """Answers /manifest at once and holds /tasks/{id}/wait for `hold` seconds."""
    hold = 3.0

    def log_message(self, *_):  # quiet
        pass

    def _json(self, body, status=200):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if "/wait" in self.path:
            time.sleep(self.hold)
            return self._json({"task_id": "t1", "status": "awaiting", "step": {"number": 2}})
        if self.path.endswith("/manifest"):
            return self._json({"name": "cbc"})
        return self._json({"task_id": "t1", "status": "running"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path.endswith("/complete"):
            return self._json({"task_id": "t1", "status": "running", "wait_seconds_seen": body.get("wait_seconds")})
        return self._json({"task_id": "t1", "status": "awaiting", "seen": body})


@pytest.fixture
def api():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SlowApi)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def mcp(api):
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        env={"CBC_API_URL": api, "CBC_API_KEY": "k", "CBC_CALL_TIMEOUT": "2", "CBC_LONG_POLL": "20",
             "PATH": "/usr/bin:/bin"},
    )
    replies: dict[int, dict] = {}
    got = threading.Condition()

    def reader():
        for line in proc.stdout:
            msg = json.loads(line)
            with got:
                replies[msg["id"]] = msg
                got.notify_all()
    threading.Thread(target=reader, daemon=True).start()

    def send(rid, method, params=None):
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}) + "\n")
        proc.stdin.flush()

    def wait_for(rid, timeout=10):
        deadline = time.time() + timeout
        with got:
            while rid not in replies:
                remaining = deadline - time.time()
                assert remaining > 0, f"no reply to {rid}"
                got.wait(remaining)
            return replies[rid]

    yield send, wait_for
    proc.kill()


def _text(reply):
    return json.loads(reply["result"]["content"][0]["text"])


def test_a_ping_is_answered_while_a_tool_call_waits_on_the_platform(mcp):
    send, wait_for = mcp
    _SlowApi.hold = 1.5
    send(1, "tools/call", {"name": "cbc_get_task", "arguments": {"task_id": "t1", "wait_seconds": 30}})
    time.sleep(0.2)
    t0 = time.time()
    send(2, "ping")
    wait_for(2)
    assert time.time() - t0 < 1.0, "the ping waited behind the tool call"
    assert _text(wait_for(1))["status"] == "awaiting"


def test_a_call_the_platform_holds_too_long_returns_a_resume_hint_not_a_dead_server(mcp):
    send, wait_for = mcp
    _SlowApi.hold = 4.0   # longer than CBC_CALL_TIMEOUT=2
    send(3, "tools/call", {"name": "cbc_get_task", "arguments": {"task_id": "t1", "wait_seconds": 30}})
    out = _text(wait_for(3, timeout=8))
    assert out["ok"] is False and out["task_id"] == "t1"
    assert "cbc_get_task" in out["what_to_do"]
    send(4, "tools/call", {"name": "cbc_manifest", "arguments": {}})
    assert _text(wait_for(4))["name"] == "cbc", "the server is still serving"


def test_long_polls_are_capped_and_complete_asks_for_a_short_wait(mcp):
    send, wait_for = mcp
    send(5, "tools/call", {"name": "cbc_complete_task", "arguments": {"task_id": "t1", "content": {"a": 1}}})
    assert _text(wait_for(5))["wait_seconds_seen"] == 20
    send(6, "tools/call", {"name": "cbc_produce", "arguments": {"grade": "grade-9", "subject": "Mathematics"}})
    seen = _text(wait_for(6))["seen"]
    assert seen["station"] == "order" and seen["kind"] == "term" and seen["wait_seconds"] == 20
