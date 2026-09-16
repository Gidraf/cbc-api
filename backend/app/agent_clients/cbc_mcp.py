#!/usr/bin/env python3
"""An MCP server that lets Claude Code, Codex or Antigravity drive the platform.

The platform assembles every prompt; the agent's own model answers it. Run
this over stdio from the agent's MCP config:

    {"mcpServers": {"cbc": {"command": "python3", "args": ["backend/app/agent_clients/cbc_mcp.py"],
                            "env": {"CBC_API_URL": "https://your-server",
                                    "CBC_API_KEY": "cbc_live_..."}}}}

Then, in the agent: "Use cbc_start_task to run the questions station for
Grade 9 Mathematics Integers with 50 items; answer every step it hands you
and complete it; then compose and freeze a 30-question paper."

No third-party packages: MCP over stdio is JSON-RPC 2.0 with three methods
this server needs — initialize, tools/list and tools/call.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API = os.getenv("CBC_API_URL", "http://localhost:8000").rstrip("/")
KEY = os.getenv("CBC_API_KEY", "")

# Every tool call answers within about a minute, whatever the platform is
# doing. An agent's MCP client gives a call a fixed time and then declares
# the server dead — Antigravity said "the cbc MCP server process timed out
# and needs to be reloaded" — and an order is hours of work behind short
# calls, so no single call may be long. The platform's own long-polls are
# asked for at most LONG_POLL seconds; a step that takes longer is picked
# up by the next cbc_get_task. The task itself lives on the platform and
# survives any number of these.
CALL_TIMEOUT = int(os.getenv("CBC_CALL_TIMEOUT", "50"))
LONG_POLL = int(os.getenv("CBC_LONG_POLL", "20"))
DOWNLOAD_TIMEOUT = int(os.getenv("CBC_DOWNLOAD_TIMEOUT", "50"))


def _timed_out(what: str, task_id: str = "") -> dict[str, Any]:
    out = {"ok": False, "error": f"{what} took longer than {CALL_TIMEOUT}s; the platform is still working on it.",
           "what_to_do": "Wait a moment, then call cbc_get_task with the task_id — the task is still alive."}
    if task_id:
        out["task_id"] = task_id
    return out


def _call(method: str, path: str, body: Any = None, query: dict[str, Any] | None = None) -> Any:
    url = API + path
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v not in (None, "")})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"X-API-Key": KEY, "Content-Type": "application/json",
                                          "Accept": "application/json, text/html"})
    try:
        with urllib.request.urlopen(req, timeout=CALL_TIMEOUT) as resp:
            raw = resp.read()
            kind = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raw, kind = exc.read(), "application/json"
    except (socket.timeout, TimeoutError):
        return _timed_out(f"{method} {path.split('?')[0]}")
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), (socket.timeout, TimeoutError)):
            return _timed_out(f"{method} {path.split('?')[0]}")
        return {"ok": False, "error": f"could not reach {API}: {exc.reason}",
                "what_to_do": "Check CBC_API_URL and that the platform is up; then retry the same call."}
    text = raw.decode("utf-8", "replace")
    if "json" in kind:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}
    return {"html": text}


def _trim_task(task: dict[str, Any]) -> dict[str, Any]:
    """The step's messages are what the agent must read; the rest is short."""
    return task


TOOLS: list[dict[str, Any]] = [
    {"name": "cbc_manifest", "description": "How the platform works: stations, the task protocol, engines, papers. Read first.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "cbc_start_task",
     "description": ("Run a station (notes, diagram, activity, material, questions, media, simulation, strands, substrands) "
                     "for a grade/subject/sub-strand. Returns the task and, when the station needs a model, "
                     "`step.messages` for YOU to answer. Answer them exactly as asked and call cbc_complete_task."),
     "inputSchema": {"type": "object", "required": ["station", "grade", "subject"],
                     "properties": {"station": {"type": "string"}, "grade": {"type": "string"},
                                    "subject": {"type": "string"}, "strand": {"type": "string"},
                                    "sub_strand": {"type": "string"}, "count": {"type": "integer"},
                                    "custom_instructions": {"type": "string"},
                                    "review_cycles": {"type": "integer"},
                                    "extra": {"type": "object"}}}},
    {"name": "cbc_produce",
     "description": ("ONE REQUEST, ONE PRODUCT. Start an order: works out the sub-strands (a term, a strand, or one sub-strand), "
                     "runs the guides/figures/questions still missing, composes the paper in the national format, freezes it "
                     "with a QR code to its marking scheme, and returns print links in result.render_urls. Then keep "
                     "answering steps with cbc_complete_task until status is 'done'."),
     "inputSchema": {"type": "object", "required": ["grade", "subject"],
                     "properties": {"grade": {"type": "string"}, "subject": {"type": "string"},
                                    "kind": {"type": "string", "enum": ["term", "topical", "strand"]},
                                    "term": {"type": "integer"}, "strand": {"type": "string"},
                                    "sub_strand": {"type": "string"}, "sub_strands": {"type": "array"},
                                    "count": {"type": "integer"}, "format": {"type": "string"},
                                    "title": {"type": "string"}}}},
    {"name": "cbc_get_task", "description": "The task's state and its pending step (messages to answer).",
     "inputSchema": {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "string"},
                                                                              "wait_seconds": {"type": "number"}}}},
    {"name": "cbc_complete_task",
     "description": ("Answer the pending step. `content` is the JSON object the prompt asked for (or the raw text when "
                     "step.expect is 'text'). Returns the NEXT step, or the finished task with its result. "
                     "Keep completing until status is 'done'."),
     "inputSchema": {"type": "object", "required": ["task_id", "content"],
                     "properties": {"task_id": {"type": "string"}, "content": {},
                                    "model": {"type": "string", "description": "what answered, e.g. claude-opus-5"}}}},
    {"name": "cbc_list_tasks", "description": "Live and recent tasks.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "cbc_cancel_task", "description": "Cancel a task.",
     "inputSchema": {"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "string"}}}},
    {"name": "cbc_solve", "description": "The maths engine: value, working, and a verdict on a claimed answer.",
     "inputSchema": {"type": "object", "required": ["expression"],
                     "properties": {"expression": {"type": "string"}, "claimed_answer": {"type": "string"}}}},
    {"name": "cbc_draw_figure",
     "description": "Draw a question figure from data (number_line, bar_chart, pie_chart, line_graph, table, clock, thermometer, shape, fraction, angle). Returns SVG; save=true files it and returns a diagram_id.",
     "inputSchema": {"type": "object", "required": ["figure"],
                     "properties": {"figure": {"type": "object"}, "save": {"type": "boolean"},
                                    "grade": {"type": "string"}, "subject": {"type": "string"}, "sub_strand": {"type": "string"}}}},
    {"name": "cbc_draw_map",
     "description": "Draw a sketch map of Kenya (or a schematic area) from the map contract: extent, features (name/kind, lat/lon or x/y), key. Returns SVG; save=true files it.",
     "inputSchema": {"type": "object", "required": ["map"],
                     "properties": {"map": {"type": "object"}, "title": {"type": "string"}, "save": {"type": "boolean"},
                                    "grade": {"type": "string"}, "subject": {"type": "string"}, "sub_strand": {"type": "string"}}}},
    {"name": "cbc_check_questions", "description": "Run the question checks (engine, repeats, demand, coverage) on items in the API shape without filing them.",
     "inputSchema": {"type": "object", "required": ["grade", "subject", "questions"],
                     "properties": {"grade": {"type": "string"}, "subject": {"type": "string"}, "strand": {"type": "string"},
                                    "sub_strand": {"type": "string"}, "questions": {"type": "array"}}}},
    {"name": "cbc_compose_paper", "description": "Compose a paper from the bank (topical/strand/term) in the national format; returns sections, ids and render URLs.",
     "inputSchema": {"type": "object", "required": ["grade", "subject"],
                     "properties": {"grade": {"type": "string"}, "subject": {"type": "string"},
                                    "kind": {"type": "string", "enum": ["topical", "strand", "term"]},
                                    "strand": {"type": "string"}, "sub_strand": {"type": "string"},
                                    "count": {"type": "integer"}, "format": {"type": "string"}, "seed": {"type": "string"},
                                    "drafts": {"type": "boolean"}, "term": {"type": "integer"}}}},
    {"name": "cbc_freeze_paper", "description": "Freeze a composed paper: exact items, share token, QR code to the scheme; returns exam_id and print URLs.",
     "inputSchema": {"type": "object", "required": ["grade", "subject"],
                     "properties": {"grade": {"type": "string"}, "subject": {"type": "string"},
                                    "kind": {"type": "string"}, "strand": {"type": "string"}, "sub_strand": {"type": "string"},
                                    "count": {"type": "integer"}, "format": {"type": "string"}, "seed": {"type": "string"},
                                    "drafts": {"type": "boolean"}, "title": {"type": "string"}, "term": {"type": "integer"}}}},
    {"name": "cbc_fetch", "description": "GET any platform path (a rendered guide, a paper's HTML, a JSON endpoint) with the API key.",
     "inputSchema": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}},
    {"name": "cbc_download",
     "description": ("Download a file the platform produced — a paper's PDF or HTML from result.render_urls, a guide — "
                     "into the local folder CBC_DOWNLOAD_DIR (default ./papers) and return its path, so it can be opened "
                     "or shown to the user. Accepts a full URL or a platform path. The HTML of a paper prints as A4."),
     "inputSchema": {"type": "object", "required": ["url"],
                     "properties": {"url": {"type": "string"}, "filename": {"type": "string", "description": "optional name"}}}},
    {"name": "cbc_download_paper",
     "description": ("Download a frozen paper by exam_id as PDF (or HTML) into CBC_DOWNLOAD_DIR: what = paper | scheme | "
                     "booklet | answer_sheet. Uses the paper's share token from render_urls if you pass it, else your key."),
     "inputSchema": {"type": "object", "required": ["exam_id"],
                     "properties": {"exam_id": {"type": "string"},
                                    "what": {"type": "string", "enum": ["paper", "scheme", "booklet", "answer_sheet"]},
                                    "format": {"type": "string", "enum": ["pdf", "html"]},
                                    "token": {"type": "string"}}}},
]

DOWNLOAD_DIR = os.getenv("CBC_DOWNLOAD_DIR", os.path.join(os.getcwd(), "papers"))


def _download(url: str, filename: str = "") -> dict[str, Any]:
    """Fetch bytes to a local file; a platform path gets the key, a share
    link needs none. A JSON error body is reported, not saved as a file."""
    full = url if url.startswith(("http://", "https://")) else API + "/" + url.lstrip("/")
    headers = {"Accept": "application/pdf, text/html, application/json"}
    if full.startswith(API):
        headers["X-API-Key"] = KEY
    req = urllib.request.Request(full, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
            body = resp.read()
            kind = resp.headers.get("Content-Type", "")
            disposition = resp.headers.get("Content-Disposition", "")
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": exc.read().decode("utf-8", "replace")[:400]}
    except (socket.timeout, TimeoutError, urllib.error.URLError) as exc:
        return {"ok": False, "status": 0, "error": f"download did not finish in {DOWNLOAD_TIMEOUT}s: {exc}",
                "what_to_do": "Retry once; if it is a PDF, ask for format 'html' and print that to PDF."}
    if "json" in kind:
        return {"ok": False, "status": 200, "error": body.decode("utf-8", "replace")[:400]}
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    name = filename
    if not name:
        import re

        match = re.search(r'filename="?([^";]+)"?', disposition)
        name = match.group(1) if match else (urllib.parse.urlparse(full).path.rsplit("/", 1)[-1] or "download")
        if "pdf" in kind and not name.endswith(".pdf"):
            name += ".pdf"
        elif "html" in kind and not name.endswith(".html"):
            name += ".html"
    path = os.path.join(DOWNLOAD_DIR, os.path.basename(name))
    with open(path, "wb") as fh:
        fh.write(body)
    return {"ok": True, "path": path, "bytes": len(body), "content_type": kind,
            "how_to_show": ("Open it for the user (it is a PDF) — or, for HTML, open it in a browser and print "
                            "to PDF; the page is laid out for A4.")}


def _download_paper(args: dict[str, Any]) -> dict[str, Any]:
    exam_id = args["exam_id"]
    what = args.get("what") or "paper"
    fmt = args.get("format") or "pdf"
    token = args.get("token") or ""
    query = {"paper": "", "scheme": "answers=true", "booklet": "with_scheme=true",
             "answer_sheet": "answer_sheet=true"}[what]
    if token:
        path = f"/api/v1/exams/{exam_id}/print{'.pdf' if fmt == 'pdf' else ''}?token={token}"
        path += ("&" + query) if query else ""
    else:
        path = f"/api/v1/exams/{exam_id}/paper.{fmt}" + ("?" + query if query else "")
    out = _download(path, filename=f"{exam_id}-{what}.{fmt}")
    if not out.get("ok") and fmt == "pdf":
        # The PDF service may be down; the HTML prints the same page.
        fallback = _download_paper({**args, "format": "html"})
        fallback["note"] = f"PDF failed ({out.get('error', '')[:120]}); saved the HTML instead — print it to PDF."
        return fallback
    return out


def _with_task_id(out: Any, task_id: str) -> Any:
    """A timed-out poll still names the task, so the agent's next call is
    cbc_get_task and not a fresh cbc_produce that would start it over."""
    if isinstance(out, dict) and out.get("ok") is False and "task_id" not in out:
        out["task_id"] = task_id
    return out


def _tool(name: str, args: dict[str, Any]) -> Any:
    if name == "cbc_manifest":
        return _call("GET", "/api/v1/agent/manifest")
    if name == "cbc_start_task":
        return _trim_task(_call("POST", "/api/v1/agent/tasks", {**args, "wait_seconds": LONG_POLL}))
    if name == "cbc_produce":
        body = {"station": "order", **args, "wait_seconds": LONG_POLL}
        body.setdefault("kind", "term")
        return _trim_task(_call("POST", "/api/v1/agent/tasks", body))
    if name == "cbc_get_task":
        wait = min(float(args.get("wait_seconds") or 0), LONG_POLL)
        if wait:
            out = _call("GET", f"/api/v1/agent/tasks/{args['task_id']}/wait", query={"seconds": wait})
        else:
            out = _call("GET", f"/api/v1/agent/tasks/{args['task_id']}")
        return _with_task_id(_trim_task(out), args["task_id"])
    if name == "cbc_complete_task":
        out = _call("POST", f"/api/v1/agent/tasks/{args['task_id']}/complete",
                    {"content": args.get("content"), "model": args.get("model") or "agent",
                     "wait_seconds": LONG_POLL})
        return _with_task_id(_trim_task(out), args["task_id"])
    if name == "cbc_list_tasks":
        return _call("GET", "/api/v1/agent/tasks")
    if name == "cbc_cancel_task":
        return _call("DELETE", f"/api/v1/agent/tasks/{args['task_id']}")
    if name == "cbc_solve":
        return _call("POST", "/api/v1/agent/engines/solve", args)
    if name == "cbc_draw_figure":
        return _call("POST", "/api/v1/agent/engines/figure", args)
    if name == "cbc_draw_map":
        return _call("POST", "/api/v1/agent/engines/map", args)
    if name == "cbc_check_questions":
        return _call("POST", "/api/v1/agent/engines/check-questions", args)
    if name == "cbc_compose_paper":
        return _call("GET", "/api/v1/questions/paper/exam.json", query=args)
    if name == "cbc_freeze_paper":
        return _call("POST", "/api/v1/questions/paper/freeze", args)
    if name == "cbc_fetch":
        return _call("GET", args["path"])
    if name == "cbc_download":
        return _download(args["url"], args.get("filename") or "")
    if name == "cbc_download_paper":
        return _download_paper(args)
    raise ValueError(f"unknown tool {name}")


_stdout_lock = threading.Lock()


def _reply(request_id: Any, result: Any = None, error: str = "") -> None:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error:
        message["error"] = {"code": -32000, "message": error}
    else:
        message["result"] = result
    with _stdout_lock:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()


def _run_call(request_id: Any, params: dict[str, Any]) -> None:
    try:
        result = _tool(params.get("name", ""), params.get("arguments") or {})
        _reply(request_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})
    except Exception as exc:  # noqa: BLE001
        _reply(request_id, {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True})


def main() -> None:
    # Tool calls run on their own threads so a ping, a tools/list or a
    # second call is answered while one waits on the platform. Serving them
    # in turn meant a long call left every ping unanswered, and the agent
    # took the silence for a dead server and reloaded it.
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, request_id, params = request.get("method"), request.get("id"), request.get("params") or {}
        if method == "initialize":
            _reply(request_id, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                                "serverInfo": {"name": "cbc", "version": "1.1"}})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _reply(request_id, {"tools": TOOLS})
        elif method == "tools/call":
            threading.Thread(target=_run_call, args=(request_id, params), daemon=True).start()
        elif method == "ping":
            _reply(request_id, {})
        elif method == "notifications/cancelled":
            continue
        elif request_id is not None:
            _reply(request_id, error=f"method not supported: {method}")


if __name__ == "__main__":
    main()
