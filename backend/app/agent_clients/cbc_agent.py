#!/usr/bin/env python3
"""Run a station with a model of your own — Ollama, or any OpenAI-compatible endpoint.

    python3 backend/app/agent_clients/cbc_agent.py run --station questions --grade grade-9 --subject Mathematics \\
        --strand Numbers --sub-strand Integers --count 50 \\
        --model llama3.1:70b --llm-url http://localhost:11434/v1

The platform assembles each prompt; this answers it on the model you name
and posts the answer back; the platform checks, repairs, draws and files.
Your machine only needs to reach the platform and the model — the platform
never needs to reach you.

Environment: CBC_API_URL, CBC_API_KEY, and optionally LLM_API_KEY for the
model endpoint (Ollama needs none).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

API = os.getenv("CBC_API_URL", "http://localhost:8000").rstrip("/")
KEY = os.getenv("CBC_API_KEY", "")


def _platform(method: str, path: str, body: Any = None) -> dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"X-API-Key": KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"{method} {path} → {exc.code}: {detail[:400]}")


def _model(llm_url: str, model: str, messages: list[dict[str, str]], *, expect: str,
           temperature: float) -> str:
    """One OpenAI-compatible chat completion. Ollama serves this at /v1."""
    body: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature, "stream": False}
    if expect == "json":
        body["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if os.getenv("LLM_API_KEY"):
        headers["Authorization"] = f"Bearer {os.getenv('LLM_API_KEY')}"
    req = urllib.request.Request(llm_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=1800) as resp:
        out = json.loads(resp.read().decode())
    return str(((out.get("choices") or [{}])[0].get("message") or {}).get("content") or "")


def run(args: argparse.Namespace) -> None:
    started = time.time()
    task = _platform("POST", "/api/v1/agent/tasks", {
        "station": args.station, "grade": args.grade, "subject": args.subject,
        "strand": args.strand, "sub_strand": args.sub_strand, "count": args.count,
        "custom_instructions": args.instructions, "wait_seconds": 30,
    })
    print(f"task {task['task_id']} — {args.station} for {args.grade} {args.subject} {args.sub_strand or args.strand}")
    while True:
        status = task.get("status")
        if status == "awaiting" and task.get("step"):
            step = task["step"]
            chars = sum(len(m["content"]) for m in step["messages"])
            print(f"  step {step['number']} ({step['stage']}, {chars:,} chars) → {args.model} …", end="", flush=True)
            t0 = time.time()
            answer = _model(args.llm_url, args.model, step["messages"], expect=step["expect"],
                            temperature=float(step.get("temperature") or 0.3))
            print(f" {len(answer):,} chars in {time.time() - t0:.0f}s")
            task = _platform("POST", f"/api/v1/agent/tasks/{task['task_id']}/complete",
                             {"content": answer, "model": f"{args.model}", "wait_seconds": 60})
        elif status == "running":
            task = _platform("GET", f"/api/v1/agent/tasks/{task['task_id']}/wait?seconds=60")
        else:
            break
    print(f"{task.get('status')} after {task.get('steps_completed')} step(s), {time.time() - started:.0f}s")
    if task.get("error"):
        print("error:", task["error"])
    result = task.get("result") or {}
    for key in ("saved", "batch_count", "artifact", "quality_gate", "self_check", "drawings"):
        if key in result:
            value = result[key]
            if isinstance(value, dict):
                value = {k: value[k] for k in ("artifact_id", "version", "passed", "overall_score", "score",
                                               "clean", "drawn", "of") if k in value}
            print(f"  {key}: {value}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run", help="run one station end to end on your model")
    p.add_argument("--station", required=True)
    p.add_argument("--grade", required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--strand", default="")
    p.add_argument("--sub-strand", dest="sub_strand", default="")
    p.add_argument("--count", type=int, default=None)
    p.add_argument("--instructions", default="")
    p.add_argument("--model", required=True, help="e.g. llama3.1:70b, qwen2.5:32b, gpt-4.1")
    p.add_argument("--llm-url", dest="llm_url", default=os.getenv("LLM_URL", "http://localhost:11434/v1"),
                   help="OpenAI-compatible base URL; Ollama serves /v1")
    args = parser.parse_args()
    if not KEY:
        sys.exit("set CBC_API_KEY (an API key from the console's Providers page)")
    run(args)


if __name__ == "__main__":
    main()
