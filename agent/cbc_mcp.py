#!/usr/bin/env python3
"""An MCP server that lets Claude Code, Codex or Antigravity drive the platform.

The platform assembles every prompt; the agent's own model answers it. Run
this over stdio from the agent's MCP config:

    {"mcpServers": {"cbc": {"command": "python3", "args": ["agent/cbc_mcp.py"],
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
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API = os.getenv("CBC_API_URL", "http://localhost:8000").rstrip("/")
KEY = os.getenv("CBC_API_KEY", "")


def _call(method: str, path: str, body: Any = None, query: dict[str, Any] | None = None) -> Any:
    url = API + path
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v not in (None, "")})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"X-API-Key": KEY, "Content-Type": "application/json",
                                          "Accept": "application/json, text/html"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read()
            kind = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raw, kind = exc.read(), "application/json"
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
     "description": "Draw a question figure from data (number_line, bar_chart, pie_chart, line_graph, table, clock, thermometer, shape, fraction, angle). Returns SVG; register=true files it and returns a diagram_id.",
     "inputSchema": {"type": "object", "required": ["figure"],
                     "properties": {"figure": {"type": "object"}, "register": {"type": "boolean"},
                                    "grade": {"type": "string"}, "subject": {"type": "string"}, "sub_strand": {"type": "string"}}}},
    {"name": "cbc_draw_map",
     "description": "Draw a sketch map of Kenya (or a schematic area) from the map contract: extent, features (name/kind, lat/lon or x/y), key. Returns SVG; register=true files it.",
     "inputSchema": {"type": "object", "required": ["map"],
                     "properties": {"map": {"type": "object"}, "title": {"type": "string"}, "register": {"type": "boolean"},
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
]


def _tool(name: str, args: dict[str, Any]) -> Any:
    if name == "cbc_manifest":
        return _call("GET", "/api/v1/agent/manifest")
    if name == "cbc_start_task":
        return _trim_task(_call("POST", "/api/v1/agent/tasks", args))
    if name == "cbc_get_task":
        wait = args.get("wait_seconds")
        if wait:
            return _trim_task(_call("GET", f"/api/v1/agent/tasks/{args['task_id']}/wait", query={"seconds": wait}))
        return _trim_task(_call("GET", f"/api/v1/agent/tasks/{args['task_id']}"))
    if name == "cbc_complete_task":
        return _trim_task(_call("POST", f"/api/v1/agent/tasks/{args['task_id']}/complete",
                                {"content": args.get("content"), "model": args.get("model") or "agent"}))
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
    raise ValueError(f"unknown tool {name}")


def _reply(request_id: Any, result: Any = None, error: str = "") -> None:
    message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error:
        message["error"] = {"code": -32000, "message": error}
    else:
        message["result"] = result
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> None:
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
                                "serverInfo": {"name": "cbc", "version": "1.0"}})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            _reply(request_id, {"tools": TOOLS})
        elif method == "tools/call":
            try:
                result = _tool(params.get("name", ""), params.get("arguments") or {})
                _reply(request_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})
            except Exception as exc:  # noqa: BLE001
                _reply(request_id, {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True})
        elif method == "ping":
            _reply(request_id, {})
        elif request_id is not None:
            _reply(request_id, error=f"method not supported: {method}")


if __name__ == "__main__":
    main()
