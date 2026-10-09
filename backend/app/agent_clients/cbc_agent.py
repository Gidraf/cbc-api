#!/usr/bin/env python3
"""Run a station with a model of your own — Ollama, or any OpenAI-compatible endpoint.

    python3 backend/app/agent_clients/cbc_agent.py run --station questions --grade grade-9 --subject Mathematics \\
        --strand Numbers --sub-strand Integers --count 50 \\
        --model llama3.1:70b --llm-url http://localhost:11434/v1

One paper, saved as PDFs:

    python3 cbc_agent.py run --station order --grade grade-9 --subject Mathematics --kind term --term 1 \\
        --count 30 --model qwen2.5:32b --download ./papers

Every grade from 6 to 12, every ingested subject, every term, unattended —
PDFs in ./papers and a ledger there so a stopped sweep resumes:

    python3 cbc_agent.py sweep --from grade-6 --to grade-12 --model qwen2.5:32b --download ./papers

Middle-out — Grade 9 first, then 10, 8, 11, 7, 12, 6 — each grade finished
before the next, and every subject's Term 3 paper before any Term 1:

    python3 cbc_agent.py sweep --from grade-6 --to grade-12 --order middle-out --terms 3 1 2 \\
        --model qwen3:14b --download ./papers

Serve the queue — every task waiting on the platform, whoever started it
(the console, an order, the exam studio), answered on your model, and keep
watching for new ones until stopped:

    python3 cbc_agent.py serve --model qwen3:14b --download ./papers

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

def _load_env_file() -> None:
    """The kit's own .env (CBC_API_URL, CBC_API_KEY …), next to this file.
    Run by hand, `python3 cbc_agent.py night` stopped at "set CBC_API_KEY"
    because only the launcher scripts read it. A value already in the
    environment wins."""
    for path in (os.getenv("CBC_ENV_FILE", ""), os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")):
        if not path or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip().removeprefix("export ").strip() if hasattr(str, "removeprefix") \
                    else key.strip().replace("export ", "", 1).strip()
                os.environ.setdefault(key, value.strip().strip('"').strip("'"))
        return


_load_env_file()
API = os.getenv("CBC_API_URL", "http://localhost:8000").rstrip("/")
KEY = os.getenv("CBC_API_KEY", "")


class PlatformError(SystemExit):
    """The platform answered with an error. A SystemExit, so a one-off `run`
    still stops on it; `serve` reads `status` and decides whether to retry."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


def _platform(method: str, path: str, body: Any = None) -> dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"X-API-Key": KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise PlatformError(f"{method} {path} → {exc.code}: {detail[:400]}", exc.code)


def _patient(method: str, path: str, body: Any = None, *, what: str = "") -> dict[str, Any]:
    """`_platform`, retried through what a long unattended run meets: the
    platform redeploying (502/503/504), the network dropping, a timeout.
    A 4xx is the platform saying no, and is raised at once."""
    delay = 5.0
    while True:
        try:
            return _platform(method, path, body)
        except PlatformError as exc:
            if exc.status < 500:
                raise
            reason = f"{exc.status}"
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            reason = str(getattr(exc, "reason", exc))[:120]
        print(f"  platform unreachable{f' ({what})' if what else ''}: {reason}; retrying in {delay:.0f}s",
              flush=True)
        if _WINDOW and not _in_window(_WINDOW):
            raise _WindowClosed()
        time.sleep(delay)
        delay = min(delay * 2, 300.0)


# The platform's largest prompt plus a chunk's answer: about 12k tokens in
# and 6k out. 24k leaves room; a Mac with 24 GB runs a 14B at this.
NUM_CTX = int(os.getenv("LLM_NUM_CTX", "24576"))
# Room for the longest answer. A 15-item chunk from qwen3:14b ran past 8,192
# tokens and was cut off mid-item; 12,288 lets it finish.
NUM_PREDICT = int(os.getenv("LLM_NUM_PREDICT", "12288"))
# The window grows past NUM_CTX for a prompt that needs it, up to this. A
# 2-question batch arrived at 71,000 characters — the guide is in it — which
# left a 24k window 4k tokens to answer in. 32k keeps a 14B on an 18 GB Mac.
MAX_CTX = int(os.getenv("LLM_MAX_CTX", "32768"))


def _context_for(messages: list[dict[str, str]]) -> int:
    """The window this prompt needs: its tokens (about 3.2 characters each
    for this mix of prose, LaTeX and JSON) plus room for the answer, rounded
    up to 2k so a slightly longer prompt does not reload the model."""
    chars = sum(len(str(m.get("content") or "")) for m in messages)
    needed = int(chars / 3.2) + NUM_PREDICT
    size = max(NUM_CTX, -(-needed // 2048) * 2048)
    if size > MAX_CTX:
        print(f"\n  note: this prompt wants a {size:,}-token window; capped at {MAX_CTX:,} "
              f"(LLM_MAX_CTX) — the start of it may be cut", flush=True)
    return min(size, MAX_CTX)
# Unloading between tasks costs a reload every time (11 s for a 14B).
KEEP_ALIVE = os.getenv("LLM_KEEP_ALIVE", "60m")
# qwen3 and deepseek-r1 reason before they answer. Better answers, several
# times slower; off unless asked for (--think or LLM_THINK=1).
THINK = os.getenv("LLM_THINK", "").lower() in ("1", "true", "yes", "on")
# The serving window, while `serve --window` runs; retries respect it too.
_WINDOW = ""
_ollama_native: dict[str, bool] = {}


def _is_ollama(llm_url: str) -> bool:
    """Whether the endpoint is an Ollama server (its native API answers).
    Cached per URL; one probe, not one per prompt."""
    base = llm_url.rstrip("/")
    base = base[:-3] if base.endswith("/v1") else base
    if base in _ollama_native:
        return _ollama_native[base]
    try:
        with urllib.request.urlopen(urllib.request.Request(base + "/api/tags"), timeout=10) as resp:
            _ollama_native[base] = resp.status == 200
    except Exception:  # noqa: BLE001
        _ollama_native[base] = False
    return _ollama_native[base]


def _model(llm_url: str, model: str, messages: list[dict[str, str]], *, expect: str,
           temperature: float) -> str:
    """`_model_once`, retried through a model server that drops a request:
    Ollama restarting (its launch agent swapped, it ran out of memory and
    came back), or still loading the model. Three tries, then the error."""
    import http.client

    waits = (15, 45, 90)
    for attempt, wait in enumerate((*waits, None), start=1):
        try:
            return _model_once(llm_url, model, messages, expect=expect, temperature=temperature)
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or wait is None:
                raise
            reason = f"HTTP {exc.code}"
        except (http.client.RemoteDisconnected, urllib.error.URLError, ConnectionError) as exc:
            if wait is None:
                raise
            reason = str(getattr(exc, "reason", exc))[:100]
        print(f" model server dropped the request ({reason}); retry {attempt} in {wait}s …",
              end="", flush=True)
        time.sleep(wait)
    raise RuntimeError("unreachable")


def _model_once(llm_url: str, model: str, messages: list[dict[str, str]], *, expect: str,
                temperature: float) -> str:
    """One chat completion. Ollama gets its native API, so the context window
    is set per request (LLM_NUM_CTX, default 16k) — over /v1 it cannot be,
    and Ollama's default of 4,096 truncates the platform's prompts silently.
    Anything else gets the OpenAI-compatible call."""
    if _is_ollama(llm_url):
        base = llm_url.rstrip("/")
        base = base[:-3] if base.endswith("/v1") else base
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": False,
                                "keep_alive": KEEP_ALIVE, "think": THINK,
                                "options": {"temperature": temperature, "num_ctx": _context_for(messages),
                                            "num_predict": NUM_PREDICT}}
        if expect == "json":
            body["format"] = "json"
        req = urllib.request.Request(base + "/api/chat", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1800) as resp:
            out = json.loads(resp.read().decode())
        content = str((out.get("message") or {}).get("content") or "")
        if "<think>" in content:
            import re

            content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
        return content
    body = {"model": model, "messages": messages, "temperature": temperature, "stream": False}
    if expect == "json":
        body["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if os.getenv("LLM_API_KEY"):
        headers["Authorization"] = f"Bearer {os.getenv('LLM_API_KEY')}"
    req = urllib.request.Request(llm_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=1800) as resp:
        out = json.loads(resp.read().decode())
    content = str(((out.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    # Thinking models (qwen3, deepseek-r1) may put their reasoning in the
    # content; the platform wants the answer.
    if "<think>" in content:
        import re

        content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    return content


def _fetch(url: str, path: str) -> int:
    """A print link (tokenised; no key needed) to a local file. Bytes written."""
    req = urllib.request.Request(url, headers={"Accept": "application/pdf, text/html"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = resp.read()
        kind = resp.headers.get("Content-Type", "")
    if "json" in kind:
        raise RuntimeError(body.decode("utf-8", "replace")[:200])
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(body)
    return len(body)


def download_paper(result: dict[str, Any], folder: str, label: str) -> list[str]:
    """The booklet (paper + scheme) and the answer sheet, as PDFs, into
    `folder`. The PDF service may be down; the HTML prints the same page."""
    urls = (result.get("render_urls") or {}) if isinstance(result, dict) else {}
    paper = (result.get("paper") or {}) if isinstance(result, dict) else {}
    exam_id = str(paper.get("exam_id") or "paper")
    saved: list[str] = []
    wanted = [("booklet_pdf", "booklet", ".pdf"), ("booklet", "booklet", ".html"),
              ("answer_sheet", "answer-sheet", ".html"), ("paper_pdf", "paper", ".pdf")]
    got_booklet = False
    for key, what, ext in wanted:
        url = urls.get(key)
        if not url or (what == "booklet" and got_booklet):
            continue
        path = os.path.join(folder, f"{label}-{exam_id}-{what}{ext}")
        try:
            size = _fetch(url, path)
        except Exception as exc:  # noqa: BLE001
            print(f"  could not save {what}{ext}: {str(exc)[:120]}")
            continue
        saved.append(path)
        print(f"  saved {path} ({size:,} bytes)")
        if what == "booklet":
            got_booklet = True
    return saved


_context_warned = False


def _warn_if_prompt_exceeds_context(chars: int, llm_url: str) -> None:
    """Ollama's window is 4,096 tokens unless told otherwise, and a prompt
    longer than it is cut short WITHOUT an error: the model answers a
    prompt it never saw the end of, and every check downstream fails it.
    The platform's prompts run to 6–12k tokens."""
    global _context_warned
    if _context_warned or "11434" not in llm_url or _is_ollama(llm_url):
        return
    tokens = chars // 4
    limit = int(os.getenv("OLLAMA_CONTEXT_LENGTH") or 0)
    if tokens > 3500 and (not limit or tokens > limit - 500):
        _context_warned = True
        print(f"\n  WARNING: this prompt is about {tokens:,} tokens. Ollama's default window is 4,096 and "
              f"it truncates silently. Start Ollama with a bigger window before trusting any output:\n"
              f"    OLLAMA_CONTEXT_LENGTH=16384 OLLAMA_KEEP_ALIVE=-1 ollama serve\n"
              f"  (set the same variable in this shell so this check can see it)")


def _recover(task: dict[str, Any], exc: "PlatformError", body: dict[str, Any], resumed: int) -> dict[str, Any]:
    """After a refused answer: carry on from where the task is, or — if the
    platform lost it in a restart — start it again with the same body."""
    try:
        return _patient("GET", f"/api/v1/agent/tasks/{task['task_id']}", what=task["task_id"])
    except PlatformError as lost:
        if lost.status != 404 or resumed >= RESUBMITS:
            raise exc from lost
    fresh = _patient("POST", "/api/v1/agent/tasks", body, what="restarting a lost task")
    print(f"  the platform lost {task['task_id']} (restarted?); resumed as {fresh['task_id']} — "
          f"answered prompts replay from its journal", flush=True)
    return fresh


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    body: dict[str, Any] = {
        "station": args.station, "grade": args.grade, "subject": args.subject,
        "strand": args.strand, "sub_strand": args.sub_strand, "count": args.count,
        "custom_instructions": args.instructions, "wait_seconds": 30,
    }
    if getattr(args, "kind", ""):
        body["kind"] = args.kind
    if getattr(args, "term", None):
        body["term"] = args.term
    if getattr(args, "extra", None):
        body["extra"] = dict(args.extra)
    task = _patient("POST", "/api/v1/agent/tasks", body, what="starting the task")
    print(f"task {task['task_id']} — {args.station} for {args.grade} {args.subject} "
          f"{args.sub_strand or args.strand or (f'term {args.term}' if getattr(args, 'term', None) else '')}"
          + (" (joined a task already running)" if task.get("joined_existing") else ""))
    resumed = 0
    while True:
        status = task.get("status")
        if status == "awaiting" and task.get("step"):
            if _WINDOW and not _in_window(_WINDOW):
                print(f"  window {_WINDOW} closed; {task['task_id']} carries over to the next night", flush=True)
                raise _WindowClosed()
            step = task["step"]
            chars = sum(len(m["content"]) for m in step["messages"])
            _warn_if_prompt_exceeds_context(chars, args.llm_url)
            print(f"  step {step['number']} ({step['stage']}, {chars:,} chars) → {args.model} …", end="", flush=True)
            t0 = time.time()
            answer = _model(args.llm_url, args.model, step["messages"], expect=step["expect"],
                            temperature=float(step.get("temperature") or 0.3))
            print(f" {len(answer):,} chars in {time.time() - t0:.0f}s")
            try:
                task = _patient("POST", f"/api/v1/agent/tasks/{task['task_id']}/complete",
                                {"content": answer, "model": f"{args.model}", "wait_seconds": 60,
                                 "step": step["number"]}, what=task["task_id"])
            except PlatformError as exc:
                task = _recover(task, exc, body, resumed)
                resumed += 1
        elif status == "running":
            try:
                task = _patient("GET", f"/api/v1/agent/tasks/{task['task_id']}/wait?seconds=60",
                                what=task["task_id"])
            except PlatformError as exc:
                task = _recover(task, exc, body, resumed)
                resumed += 1
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
    for line in (result.get("progress") or [])[-6:] if isinstance(result, dict) else []:
        print(f"  {line.get('what')}: {line.get('detail')}")
    if isinstance(result, dict) and result.get("render_urls"):
        for key in ("booklet_pdf", "booklet", "answer_sheet"):
            if result["render_urls"].get(key):
                print(f"  {key}: {result['render_urls'][key]}")
        if getattr(args, "download", ""):
            label = f"{args.grade}-{args.subject.lower().replace(' ', '-')}" + (f"-term{args.term}" if getattr(args, "term", None) else "")
            download_paper(result, args.download, label)
    return task


# ── Every grade, every subject, every term, unattended ───────────────────────

_GRADES = ["grade-pp1", "grade-pp2"] + [f"grade-{n}" for n in range(1, 13)]


def _grades_between(first: str, last: str) -> list[str]:
    lo, hi = _GRADES.index(first), _GRADES.index(last)
    return _GRADES[lo:hi + 1]


def middle_out(grades: list[str]) -> list[str]:
    """Grade 9, 10, 8, 11, 7, 12, 6: start where the market is and widen a
    step each way, so there is something to sell after the first day
    rather than after the last."""
    if len(grades) < 3:
        return list(grades)
    mid = len(grades) // 2
    out = [grades[mid]]
    step = 1
    while len(out) < len(grades):
        if mid + step < len(grades):
            out.append(grades[mid + step])
        if mid - step >= 0:
            out.append(grades[mid - step])
        step += 1
    return out


def _ingested_subjects(grade: str) -> list[str]:
    """Subjects an order can run on: ingested AND with sub-strands. A
    platform that does not yet say `ready` is read on `ingested`."""
    out = _platform("GET", f"/api/v1/admin/langfuse/datasets/{grade}/subjects")
    rows = out.get("subjects") or []
    if any("ready" in s for s in rows):
        skipped = [str(s["name"]) for s in rows if s.get("ingested") and not s.get("ready")]
        if skipped:
            print(f"{grade}: {len(skipped)} ingested subject(s) have no sub-strands yet and are left "
                  f"for the next run: {', '.join(skipped)}")
        return [str(s["name"]) for s in rows if s.get("ready")]
    return [str(s["name"]) for s in rows if s.get("ingested")]


# Failures before the sweep stops retrying a paper (it says so; --redo resets).
SWEEP_MAX_ATTEMPTS = int(os.getenv("CBC_SWEEP_MAX_ATTEMPTS", "3"))


def sweep(args: argparse.Namespace) -> None:
    """Every ingested subject of every grade in the range, one paper per
    term, one after another, each saved as PDFs — and a ledger in the
    download folder so a sweep stopped overnight picks up where it was.

    A subject with no sub-strands yet is skipped and named; a paper that
    fails is recorded and the sweep moves on. Nothing here needs a person
    at the keyboard: the platform assembles the prompts, the model you
    name answers them, and the PDFs land in the folder.
    """
    grades = _grades_between(args.from_grade, args.to_grade) if args.from_grade else list(args.grades or [])
    if not grades:
        raise SystemExit("name the grades: --from grade-6 --to grade-12, or --grades grade-7 grade-8")
    if getattr(args, "order", "") == "middle-out":
        grades = middle_out(grades)
    print("grade order: " + " → ".join(grades))
    os.makedirs(args.download, exist_ok=True)
    ledger_path = os.path.join(args.download, "sweep-ledger.json")
    ledger: dict[str, Any] = {}
    if os.path.exists(ledger_path):
        with open(ledger_path, encoding="utf-8") as fh:
            ledger = json.load(fh)

    def remember(key: str, entry: dict[str, Any]) -> None:
        tries = int((ledger.get(key) or {}).get("attempts") or 0)
        if entry.get("status") not in ("done", "carried"):
            tries += 1
        ledger[key] = {**entry, "attempts": tries, "at": time.strftime("%Y-%m-%d %H:%M")}
        with open(ledger_path, "w", encoding="utf-8") as fh:
            json.dump(ledger, fh, indent=1)

    # A grade is finished before the next begins, and within a grade every
    # subject's paper for the first term named comes before any second-term
    # paper — a complete set for one term is what a school buys.
    plan: list[tuple[str, str, int]] = []
    for grade in grades:
        try:
            subjects = args.subjects or _ingested_subjects(grade)
        except SystemExit as exc:
            print(f"{grade}: could not list subjects — {exc}")
            continue
        for term in args.terms:
            for subject in subjects:
                plan.append((grade, subject, term))
    print(f"{len(plan)} paper(s) planned across {len(grades)} grade(s); ledger at {ledger_path}")

    done = failed = skipped = 0
    for grade, subject, term in plan:
        key = f"{grade}|{subject}|term{term}"
        if key in ledger and ledger[key].get("status") == "done" and not args.redo:
            skipped += 1
            continue
        tries = int((ledger.get(key) or {}).get("attempts") or 0)
        if tries >= SWEEP_MAX_ATTEMPTS and ledger[key].get("status") != "carried" and not args.redo:
            # Runs restart whenever the Mac goes idle; a paper that fails for
            # a reason no rerun fixes (a design that was never parsed) would
            # otherwise take hours every time.
            skipped += 1
            continue
        print(f"\n=== {grade} · {subject} · Term {term} ===")
        run_args = argparse.Namespace(
            station="order", grade=grade, subject=subject, strand="", sub_strand="",
            count=args.count, instructions=args.instructions, model=args.model, llm_url=args.llm_url,
            kind="term", term=term, download="" if getattr(args, "no_pdf", False) else args.download,
        )
        if _WINDOW and not _in_window(_WINDOW):
            print(f"\nwindow {_WINDOW} closed; the rest of the plan waits for the next night", flush=True)
            break
        try:
            task = run(run_args)
        except _WindowClosed:
            remember(key, {"status": "carried", "error": "window closed mid-paper; answers are journalled"})
            print("  carried over: the next night resumes it where it stopped", flush=True)
            break
        except SystemExit as exc:
            # The platform refused the start (no sub-strands, bad key…).
            failed += 1
            remember(key, {"status": "refused", "error": str(exc)[:300]})
            print(f"  refused: {str(exc)[:200]}")
            continue
        except Exception as exc:  # noqa: BLE001
            failed += 1
            remember(key, {"status": "error", "error": str(exc)[:300]})
            print(f"  error: {str(exc)[:200]}")
            continue
        result = task.get("result") or {}
        if task.get("status") == "done" and isinstance(result, dict) and (result.get("paper") or {}).get("exam_id"):
            done += 1
            remember(key, {"status": "done", "exam_id": result["paper"]["exam_id"],
                           "questions": result["paper"].get("question_count"),
                           "links": result.get("render_urls") or {}})
        else:
            failed += 1
            remember(key, {"status": task.get("status") or "failed", "error": str(task.get("error") or "")[:300],
                           "task_id": task.get("task_id")})
    print(f"\nsweep finished: {done} paper(s) saved, {failed} failed, {skipped} already done. "
          f"Run the same command again to retry the failures.")


# ── Serve the queue, without stopping ───────────────────────────────────────

_START_FIELDS = ("grade", "subject", "strand", "sub_strand", "kind", "term", "sub_strands", "count",
                 "custom_instructions", "review_cycles")
RESUBMITS = 10


def _resubmit(task: dict[str, Any]) -> dict[str, Any]:
    """Start a task the platform lost again, with exactly its parameters.

    A redeploy drops every live task (they live in the API's memory). The
    answers already given are journalled under the task's parameters, so the
    same start replays them and only the prompts not yet answered come back.
    """
    params = dict(task.get("params") or {})
    body: dict[str, Any] = {"station": task.get("station"), "wait_seconds": 30}
    for key in _START_FIELDS:
        if params.get(key) not in (None, "", []):
            body[key] = params.pop(key)
        else:
            params.pop(key, None)
    if params:
        body["extra"] = params
    fresh = _patient("POST", "/api/v1/agent/tasks", body, what="restarting a lost task")
    print(f"  the platform lost {task.get('task_id')} (restarted?); resumed as {fresh.get('task_id')} — "
          f"answered prompts replay from its journal", flush=True)
    return fresh


def _in_window(window: str, now: "time.struct_time | None" = None) -> bool:
    """Whether the clock is inside HH:MM-HH:MM. A window that crosses
    midnight (22:00-06:00) wraps; an empty window is always open."""
    if not window:
        return True
    start, end = (int(a) * 60 + int(b) for a, b in (part.split(":") for part in window.split("-")))
    t = now or time.localtime()
    minute = t.tm_hour * 60 + t.tm_min
    return start <= minute < end if start < end else (minute >= start or minute < end)


def _unload(llm_url: str, model: str) -> None:
    """Free the model's memory now rather than when keep_alive runs out."""
    if not _is_ollama(llm_url):
        return
    base = llm_url.rstrip("/")
    base = base[:-3] if base.endswith("/v1") else base
    try:
        req = urllib.request.Request(base + "/api/generate", method="POST",
                                     data=json.dumps({"model": model, "keep_alive": 0}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
        print(f"unloaded {model} from memory", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"could not unload {model}: {exc}", flush=True)


class _WindowClosed(Exception):
    """The serving window ended; stop before the next prompt."""


def _work(task_id: str, args: argparse.Namespace) -> str:
    """Answer one task's prompts until it finishes. Returns its final status."""
    failures = resubmits = 0
    task = _patient("GET", f"/api/v1/agent/tasks/{task_id}", what=task_id)
    last = task
    p = task.get("params") or {}
    where = p.get("sub_strand") or p.get("strand") or (f"term {p['term']}" if p.get("term") else "")
    print(f"\n▶ {task_id} · {task.get('station')} · {p.get('grade')} {p.get('subject')} {where}", flush=True)
    while True:
        if task.get("params"):
            last = task
        status = task.get("status")
        if status == "awaiting" and task.get("step"):
            if not _in_window(args.window):
                # The step in hand is left for the next window; the platform
                # holds it, and the next run picks it up.
                raise _WindowClosed()
            step = task["step"]
            chars = sum(len(m["content"]) for m in step["messages"])
            print(f"  step {step['number']} ({step['stage']}, {chars:,} chars) → {args.model} …", end="", flush=True)
            t0 = time.time()
            try:
                answer = _model(args.llm_url, args.model, step["messages"], expect=step["expect"],
                                temperature=float(step.get("temperature") or 0.3))
            except Exception as exc:  # noqa: BLE001 — Ollama down, out of memory, timed out
                failures += 1
                print(f" model failed ({str(exc)[:120]}); attempt {failures}", flush=True)
                if failures >= args.max_attempts:
                    print(f"  leaving {task_id} for now after {failures} failed attempts", flush=True)
                    return "skipped"
                time.sleep(min(30 * failures, 300))
                task = _patient("GET", f"/api/v1/agent/tasks/{task_id}", what=task_id)
                continue
            failures = 0
            print(f" {len(answer):,} chars in {time.time() - t0:.0f}s", flush=True)
            try:
                task = _patient("POST", f"/api/v1/agent/tasks/{task_id}/complete",
                                {"content": answer, "model": args.model, "wait_seconds": 60,
                                 "step": step["number"]}, what=task_id)
            except PlatformError as exc:
                # Someone else answered this step, or the task ended or was
                # lost meanwhile: read where it is now and carry on from there.
                print(f"  {str(exc)[:160]}", flush=True)
                try:
                    task = _patient("GET", f"/api/v1/agent/tasks/{task_id}", what=task_id)
                except PlatformError as lost:
                    if lost.status != 404 or resubmits >= RESUBMITS:
                        return "gone"
                    resubmits += 1
                    task = _resubmit(last)
                    task_id = task["task_id"]
        elif status == "running":
            try:
                task = _patient("GET", f"/api/v1/agent/tasks/{task_id}/wait?seconds=60", what=task_id)
            except PlatformError as lost:
                if lost.status != 404 or resubmits >= RESUBMITS:
                    return "gone"
                resubmits += 1
                task = _resubmit(last)
                task_id = task["task_id"]
        else:
            result = task.get("result") or {}
            print(f"■ {task_id} {status} after {task.get('steps_completed')} step(s)"
                  + (f" — {task.get('error')}" if task.get("error") else ""), flush=True)
            if isinstance(result, dict) and result.get("render_urls") and args.download:
                p = task.get("params") or {}
                label = f"{p.get('grade')}-{str(p.get('subject') or '').lower().replace(' ', '-')}" + \
                        (f"-term{p['term']}" if p.get("term") else "")
                try:
                    download_paper(result, args.download, label)
                except Exception as exc:  # noqa: BLE001
                    print(f"  could not download the paper: {exc}", flush=True)
            return str(status)


def serve(args: argparse.Namespace) -> None:
    """Every task the platform is waiting on, answered on your model, one
    after another — then keep watching for new ones. Tasks started from the
    console, an order, the exam studio or another agent all land here.

    Runs until stopped (Ctrl-C), or with --until-empty until the queue is
    clear. A task whose model calls keep failing is set aside and retried
    on a later pass, never allowed to block the rest.
    """
    print(f"serving {API} on {args.model} at {args.llm_url}"
          f"{' (thinking on)' if THINK else ''}; context {NUM_CTX:,} tokens", flush=True)
    global _WINDOW
    _WINDOW = args.window or ""
    if args.window and not _in_window(args.window):
        print(f"outside the serving window {args.window}; nothing to do now", flush=True)
        return
    if args.window:
        print(f"serving until the window {args.window} closes", flush=True)
    try:
        _serve_loop(args)
    except _WindowClosed:
        print(f"window {args.window} closed; stopping", flush=True)
    finally:
        if args.window:
            _unload(args.llm_url, args.model)


def _serve_loop(args: argparse.Namespace) -> None:
    set_aside: dict[str, float] = {}
    idle_since: float | None = None
    worked = 0
    while True:
        if not _in_window(args.window):
            raise _WindowClosed()
        live = _patient("GET", "/api/v1/agent/tasks", what="listing tasks").get("live") or []
        waiting = [t for t in live if t.get("status") in ("awaiting", "running")
                   and set_aside.get(t["task_id"], 0) <= time.time()]
        # Oldest first: the task someone has waited on longest.
        waiting.sort(key=lambda t: float(t.get("created_at") or 0))
        if not waiting:
            if args.until_empty:
                print(f"queue empty — {worked} task(s) worked; stopping (--until-empty)", flush=True)
                return
            if idle_since is None:
                idle_since = time.time()
                print(f"queue empty; watching every {args.poll}s for new tasks …", flush=True)
            time.sleep(args.poll)
            continue
        idle_since = None
        for t in waiting:
            try:
                outcome = _work(t["task_id"], args)
            except _WindowClosed:
                raise
            except PlatformError as exc:
                outcome = "gone"
                print(f"  {t['task_id']}: {str(exc)[:160]}", flush=True)
            if outcome == "skipped":
                set_aside[t["task_id"]] = time.time() + 900
            else:
                set_aside.pop(t["task_id"], None)
                worked += 1


# ── The night planner: campaigns, carry-over, a report each morning ────────
#
# Each night it plans from facts, not guesses: the campaign's phase (create
# or review), the bank's coverage per sub-strand, the jobs carried from
# earlier nights, and how long each kind of job has actually taken. Planning
# takes seconds; the model's hours go to writing.

PLANNER_DIR = os.path.expanduser(os.getenv("CBC_PLANNER_DIR", "~/cbc-claude/planner"))
GRADE_ORDER = ["grade-9", "grade-10", "grade-8", "grade-11", "grade-7", "grade-12", "grade-6"]
# First guesses, in minutes, until a few nights have measured the real ones.
DEFAULT_MINUTES = {"notes": 60.0, "questions": 40.0, "review": 30.0}


def _default_campaign(today: str) -> dict[str, Any]:
    return {
        "start": today,
        "grades": GRADE_ORDER,
        "subjects": [],
        "phases": [{"name": "create", "weeks": 10, "target_questions": 20000},
                   {"name": "review", "weeks": 20}],
        "repeat": [{"name": "create", "weeks": 15, "target_questions": 40000},
                   {"name": "review", "weeks": 15}],
        "batch": 20,
        "carry_limit_nights": 2,
        "max_attempts": 3,
    }


def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, default=str)
    os.replace(tmp, path)


def phase_for(campaign: dict[str, Any], day: str) -> dict[str, Any]:
    """The phase a date falls in: the listed phases, then the repeat cycle
    for ever. Returns the phase with its own start and end dates."""
    import datetime as dt

    start = dt.date.fromisoformat(str(campaign["start"]))
    when = dt.date.fromisoformat(day)
    cursor = start
    phases = list(campaign.get("phases") or [])
    repeat = list(campaign.get("repeat") or []) or phases[-1:] or [{"name": "create", "weeks": 1}]
    cycle = 0
    queue = [(p, 0) for p in phases]
    while True:
        if not queue:
            cycle += 1
            queue = [(p, cycle) for p in repeat]
        phase, n = queue.pop(0)
        end = cursor + dt.timedelta(weeks=float(phase.get("weeks") or 1))
        if when < end or when < start:
            return {**phase, "cycle": n, "phase_start": cursor.isoformat(), "phase_end": end.isoformat(),
                    "key": f"{phase.get('name')}-{cursor.isoformat()}"}
        cursor = end


def _night_of(now: "time.struct_time | None" = None) -> str:
    """The night a moment belongs to: 22:00 on the 8th and 03:00 on the 9th
    are both the night of the 8th."""
    import datetime as dt

    t = dt.datetime.fromtimestamp(time.mktime(now)) if now else dt.datetime.now()
    return (t.date() - dt.timedelta(days=1) if t.hour < 12 else t.date()).isoformat()


def _minutes_left(window: str) -> float:
    if not window:
        return 9 * 60.0
    end_h, end_m = (int(x) for x in window.split("-")[1].split(":"))
    t = time.localtime()
    now = t.tm_hour * 60 + t.tm_min
    end = end_h * 60 + end_m
    return float((end - now) % (24 * 60))


def _window_minutes(window: str) -> float:
    if not window:
        return 9 * 60.0
    (sh, sm), (eh, em) = ((int(a), int(b)) for a, b in (p.split(":") for p in window.split("-")))
    return float(((eh * 60 + em) - (sh * 60 + sm)) % (24 * 60)) or 24 * 60.0


def _estimate(state: dict[str, Any], kind: str) -> float:
    seen = sorted(state.get("measured", {}).get(kind, [])[-10:])
    return float(seen[len(seen) // 2]) if seen else DEFAULT_MINUTES.get(kind, 45.0)


def _subjects(grade: str, campaign: dict[str, Any], cache: dict[str, list[str]]) -> list[str]:
    if campaign.get("subjects"):
        return list(campaign["subjects"])
    if grade not in cache:
        try:
            cache[grade] = _ingested_subjects(grade)
        except SystemExit as exc:
            print(f"  {grade}: could not list subjects — {str(exc)[:120]}", flush=True)
            cache[grade] = []
    return cache[grade]


def _coverage(grade: str, subject: str, cache: dict[str, Any], *, notes: bool = True) -> list[dict[str, Any]]:
    key = f"{grade}|{subject}|{notes}"
    if key not in cache:
        from urllib.parse import quote

        try:
            out = _patient("GET", f"/api/v1/agent/coverage?grade={quote(grade)}&subject={quote(subject)}"
                                  f"&notes={'true' if notes else 'false'}", what=f"coverage {grade} {subject}")
            cache[key] = out.get("sub_strands") or []
        except PlatformError as exc:
            print(f"  coverage {grade} {subject}: {str(exc)[:120]}", flush=True)
            cache[key] = []
    return cache[key]


def _size_phase(phase: dict[str, Any], campaign: dict[str, Any], state: dict[str, Any],
                subjects: dict[str, list[str]], cov: dict[str, Any]) -> dict[str, Any]:
    """Once per phase: how many sub-strands the campaign covers and how many
    questions the bank held at the start, so the target can be shared out and
    the projection measured against it."""
    sized = state.setdefault("phases", {}).get(phase["key"])
    if sized:
        return sized
    print(f"sizing the {phase['name']} phase: counting sub-strands across the campaign …", flush=True)
    count = questions = 0
    for grade in campaign.get("grades") or GRADE_ORDER:
        for subject in _subjects(grade, campaign, subjects):
            rows = _coverage(grade, subject, cov, notes=False)
            count += len(rows)
            questions += sum(int(r.get("questions") or 0) for r in rows)
    target = int(phase.get("target_questions") or 0)
    sized = {"sub_strands": count, "bank_at_start": questions,
             "per_sub_strand": -(-target // count) if (target and count) else 0}
    state["phases"][phase["key"]] = sized
    print(f"  {count} sub-strands, {questions} usable questions now; "
          f"target {target} → {sized['per_sub_strand']} per sub-strand", flush=True)
    return sized


def _open_jobs(state: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted((j for j in state.get("jobs", {}).values() if j.get("status") in ("planned", "carried")),
                  key=lambda j: (j.get("created") or "", j["id"]))


def _new_job(state: dict[str, Any], kind: str, row: dict[str, Any], grade: str, subject: str,
             night: str, **more: Any) -> dict[str, Any]:
    n = state.setdefault("seq", 0) + 1
    state["seq"] = n
    job = {"id": f"{night}-{n:04d}-{kind}", "kind": kind, "grade": grade, "subject": subject,
           "strand": row.get("strand") or "", "sub_strand": row.get("sub_strand") or "",
           "status": "planned", "attempts": 0, "created": night, "nights": [], **more}
    state.setdefault("jobs", {})[job["id"]] = job
    return job


def _fits(cost: float, budget: float, plan: dict[str, Any], carried: list[Any]) -> bool:
    """A job goes in if it fits what is left of the night — or if the night
    would otherwise be empty, since the window closing carries it over."""
    if cost <= budget:
        return True
    return not plan["new"] and not carried and budget > 15


def plan_night(campaign: dict[str, Any], state: dict[str, Any], *, night: str, window: str,
               minutes_left: float | None = None) -> dict[str, Any]:
    """The night's plan: carried jobs first; then new work to fill the
    night — unless the carry-over is so large the night goes to it alone."""
    phase = phase_for(campaign, night)
    left = _minutes_left(window) if minutes_left is None else minutes_left
    carried = _open_jobs(state)
    carried_minutes = sum(_estimate(state, j["kind"]) for j in carried)
    limit = float(campaign.get("carry_limit_nights") or 2) * _window_minutes(window)
    plan = {"night": night, "phase": phase, "catch_up": carried_minutes > limit,
            "carried": [j["id"] for j in carried], "new": [], "budget": left}
    if plan["catch_up"]:
        return plan
    budget = left - carried_minutes
    busy = {(j["kind"], j["grade"], j["subject"], j["sub_strand"].lower()) for j in carried}
    subjects: dict[str, list[str]] = state.setdefault("_subject_cache", {})
    cov: dict[str, Any] = {}
    batch = int(campaign.get("batch") or 20)

    if phase.get("name") == "create":
        per = _size_phase(phase, campaign, state, subjects, cov)["per_sub_strand"] or batch * 2
        for grade in campaign.get("grades") or GRADE_ORDER:
            if budget <= 0:
                break
            rows: list[tuple[float, str, dict[str, Any]]] = []
            for subject in _subjects(grade, campaign, subjects):
                for row in _coverage(grade, subject, cov):
                    have = int(row.get("questions") or 0)
                    if have < per and ("questions", grade, subject, row["sub_strand"].lower()) not in busy:
                        rows.append((have / per, subject, row))
            # Questions first: a sub-strand that already has its guide goes
            # straight to questions, ahead of one that needs a guide written.
            rows.sort(key=lambda r: (r[2].get("has_notes") is False, r[0], r[1], r[2]["sub_strand"]))
            for _ratio, subject, row in rows:
                needs_notes = row.get("has_notes") is False
                cost = _estimate(state, "questions") + (_estimate(state, "notes") if needs_notes else 0)
                if not _fits(cost, budget, plan, carried):
                    budget = 0
                    break
                after = None
                if needs_notes:
                    notes = _new_job(state, "notes", row, grade, subject, night)
                    plan["new"].append(notes["id"])
                    after = notes["id"]
                count = max(1, min(batch, per - int(row.get("questions") or 0)))
                job = _new_job(state, "questions", row, grade, subject, night, count=count, after=after)
                plan["new"].append(job["id"])
                budget -= cost
    else:
        since = phase["phase_start"]
        for grade in campaign.get("grades") or GRADE_ORDER:
            if budget <= 0:
                break
            rows = []
            for subject in _subjects(grade, campaign, subjects):
                for row in _coverage(grade, subject, cov, notes=False):
                    reviewed = str(row.get("last_reviewed") or "")
                    if int(row.get("questions") or 0) and reviewed[:10] < since \
                            and ("review", grade, subject, row["sub_strand"].lower()) not in busy:
                        rows.append((reviewed, subject, row))
            rows.sort(key=lambda r: (r[0], r[1], r[2]["sub_strand"]))      # never reviewed first
            for _when, subject, row in rows:
                cost = _estimate(state, "review")
                if not _fits(cost, budget, plan, carried):
                    budget = 0
                    break
                job = _new_job(state, "review", row, grade, subject, night)
                plan["new"].append(job["id"])
                budget -= cost
    return plan


def _job_args(job: dict[str, Any], args: argparse.Namespace) -> argparse.Namespace:
    station = job["kind"]
    return argparse.Namespace(
        station=station, grade=job["grade"], subject=job["subject"], strand=job.get("strand") or "",
        sub_strand=job.get("sub_strand") or "", count=job.get("count") if station == "questions" else None,
        instructions="", model=args.model, llm_url=args.llm_url, kind="", term=None, download="",
        extra={"fix": True, "approve_clean": False} if station == "review" else None)


def work_night(plan: dict[str, Any], state: dict[str, Any], campaign: dict[str, Any],
               args: argparse.Namespace) -> dict[str, Any]:
    """Run the plan in order until it is done or the window closes."""
    jobs = state["jobs"]
    order = plan["carried"] + plan["new"]
    tally = {"done": [], "failed": [], "given_up": [], "carried": [], "saved": 0}
    max_attempts = int(campaign.get("max_attempts") or 3)
    for i, job_id in enumerate(order):
        job = jobs[job_id]
        if args.window and not _in_window(args.window):
            for rest in order[i:]:
                jobs[rest]["status"] = "carried"
                tally["carried"].append(rest)
            print(f"\nwindow {args.window} closed; {len(order) - i} job(s) carry over", flush=True)
            break
        after = job.get("after")
        if after and jobs.get(after, {}).get("status") != "done":
            job["status"] = "carried"
            tally["carried"].append(job_id)
            print(f"\n· {job_id} waits for {after} (its teacher's guide)", flush=True)
            continue
        print(f"\n=== {job_id}: {job['kind']} · {job['grade']} {job['subject']} · {job['sub_strand']}"
              + (f" · {job.get('count')} items" if job.get("count") else ""), flush=True)
        job["nights"] = sorted(set(job.get("nights", []) + [plan["night"]]))
        started = time.time()
        try:
            task = run(_job_args(job, args))
        except _WindowClosed:
            job["status"] = "carried"
            tally["carried"].append(job_id)
            for rest in order[i + 1:]:
                jobs[rest]["status"] = "carried"
                tally["carried"].append(rest)
            print(f"window closed mid-job; {job_id} resumes next night from its journal", flush=True)
            break
        except (SystemExit, Exception) as exc:  # noqa: BLE001
            task = {"status": "failed", "error": str(exc)[:300]}
        minutes = (time.time() - started) / 60.0
        if task.get("status") == "done":
            job["status"] = "done"
            result = task.get("result") if isinstance(task.get("result"), dict) else {}
            saved = result.get("saved")
            job["saved"] = len(saved) if isinstance(saved, list) else int(saved or 0)
            tally["saved"] += job["saved"] if job["kind"] == "questions" else 0
            state.setdefault("measured", {}).setdefault(job["kind"], []).append(round(minutes, 1))
            tally["done"].append(job_id)
        else:
            job["attempts"] = int(job.get("attempts") or 0) + 1
            job["error"] = str(task.get("error") or task.get("status"))[:300]
            job["status"] = "given_up" if job["attempts"] >= max_attempts else "carried"
            tally["given_up" if job["status"] == "given_up" else "failed"].append(job_id)
            print(f"  {job_id} {job['status']} (attempt {job['attempts']}): {job['error'][:160]}", flush=True)
        _save_json(os.path.join(PLANNER_DIR, "state.json"), state)
    return tally


def _report(plan: dict[str, Any], tally: dict[str, Any], state: dict[str, Any],
            campaign: dict[str, Any]) -> str:
    import datetime as dt

    phase = plan["phase"]
    night = plan["night"]
    nights = state.setdefault("nights", [])
    nights.append({"night": night, "phase": phase["key"], "saved": tally["saved"],
                   "done": len(tally["done"]), "carried": len(tally["carried"]),
                   "failed": len(tally["failed"]), "catch_up": plan["catch_up"]})
    lines = [f"# Night of {night} — {phase['name']} phase "
             f"({phase['phase_start']} to {phase['phase_end']})", ""]
    if plan["catch_up"]:
        lines += ["**Catch-up night**: the carry-over was larger than "
                  f"{campaign.get('carry_limit_nights', 2)} nights' work, so no new jobs were planned.", ""]
    lines += [f"- Planned: {len(plan['carried'])} carried + {len(plan['new'])} new",
              f"- Done: {len(tally['done'])}   Carried to next night: {len(tally['carried'])}   "
              f"Failed (will retry): {len(tally['failed'])}   Given up: {len(tally['given_up'])}",
              f"- Questions saved tonight: {tally['saved']}", ""]
    if phase.get("name") == "create" and phase.get("target_questions"):
        sized = state.get("phases", {}).get(phase["key"], {})
        in_phase = [n for n in nights if n["phase"] == phase["key"]]
        added = sum(n["saved"] for n in in_phase)
        recent = [n["saved"] for n in in_phase[-7:]]
        rate = sum(recent) / len(recent) if recent else 0.0
        end = dt.date.fromisoformat(phase["phase_end"])
        nights_left = max(0, (end - dt.date.fromisoformat(night)).days)
        have = int(sized.get("bank_at_start") or 0) + added
        projected = have + rate * nights_left
        target = int(phase["target_questions"])
        verdict = "on track" if projected >= target else \
            f"short by about {int(target - projected):,} — the rate needs to be {((target - have) / max(1, nights_left)):.0f} a night"
        lines += [f"## Toward {target:,} questions",
                  f"- In the bank now: about {have:,} ({added:,} added this phase)",
                  f"- Rate: {rate:.0f} a night over the last {len(recent)} night(s); {nights_left} nights left",
                  f"- Projection at the end of the phase: about {int(projected):,} — {verdict}", ""]
    for title, key in (("Done", "done"), ("Carried over", "carried"), ("Failed", "failed"), ("Given up", "given_up")):
        if tally[key]:
            lines.append(f"## {title}")
            for jid in tally[key]:
                j = state["jobs"][jid]
                extra = f" — {j.get('saved')} saved" if key == "done" and j["kind"] == "questions" else \
                        (f" — {j.get('error', '')[:120]}" if key in ("failed", "given_up") else "")
                lines.append(f"- {j['kind']} · {j['grade']} {j['subject']} · {j['sub_strand']}{extra}")
            lines.append("")
    text = "\n".join(lines)
    path = os.path.join(PLANNER_DIR, "reports", f"{night}.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def night(args: argparse.Namespace) -> None:
    """One night: plan from the campaign and the bank, work the plan inside
    the window, carry what is left, write the morning report."""
    global _WINDOW
    _WINDOW = args.window or ""
    if args.window and not _in_window(args.window) and not args.plan_only:
        print(f"outside the window {args.window}; nothing to do now")
        return
    campaign_path = os.path.join(PLANNER_DIR, "campaign.json")
    state_path = os.path.join(PLANNER_DIR, "state.json")
    tonight = _night_of()
    if not os.path.exists(campaign_path):
        _save_json(campaign_path, _default_campaign(tonight))
        print(f"wrote a starting campaign to {campaign_path} — edit it to change phases and targets")
    campaign = _load_json(campaign_path, _default_campaign(tonight))
    state = _load_json(state_path, {})
    try:
        _platform("GET", "/api/v1/agent/coverage?grade=grade-9&subject=Mathematics&notes=false")
    except PlatformError as exc:
        if exc.status == 404 and "No live task" not in str(exc):
            raise SystemExit(f"{API} has no coverage report yet (/api/v1/agent/coverage → 404). "
                             f"Deploy the branch with the planner, then run this again.")
        raise
    plan = plan_night(campaign, state, night=tonight, window=args.window)
    phase = plan["phase"]
    print(f"night of {tonight}: {phase['name']} phase ({phase['phase_start']} → {phase['phase_end']}); "
          f"{len(plan['carried'])} carried + {len(plan['new'])} new job(s)"
          + (" — CATCH-UP NIGHT" if plan["catch_up"] else ""), flush=True)
    for jid in plan["carried"] + plan["new"]:
        j = state["jobs"][jid]
        print(f"  {'↻' if jid in plan['carried'] else '+'} {j['kind']:9} {j['grade']:9} {j['subject'][:28]:28} "
              f"{j['sub_strand'][:40]}" + (f" ({j['count']})" if j.get("count") else ""), flush=True)
    if args.plan_only:
        for jid in plan["new"]:
            state["jobs"].pop(jid, None)
        return
    _save_json(state_path, state)
    try:
        tally = work_night(plan, state, campaign, args)
    finally:
        _save_json(state_path, state)
    report = _report(plan, tally, state, campaign)
    _save_json(state_path, state)
    print(f"\nmorning report: {report}", flush=True)


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
    p.add_argument("--kind", default="", help="order: term | topical | strand")
    p.add_argument("--term", type=int, default=None, help="order: 1, 2 or 3")
    p.add_argument("--download", default="", help="folder to save the paper's PDFs into when the order is done")
    p.add_argument("--extra", type=json.loads, default=None,
                   help='station options as JSON, e.g. review: \'{"fix": true, "approve_clean": false}\'')
    p.add_argument("--model", required=True, help="e.g. llama3.1:70b, qwen2.5:32b, gpt-4.1")
    p.add_argument("--llm-url", dest="llm_url", default=os.getenv("LLM_URL", "http://localhost:11434/v1"),
                   help="OpenAI-compatible base URL; Ollama serves /v1")
    w = sub.add_parser("sweep", help="every ingested subject of every grade in a range, one paper per term, unattended")
    w.add_argument("--from", dest="from_grade", default="", help="first grade, e.g. grade-6")
    w.add_argument("--to", dest="to_grade", default="grade-12", help="last grade, e.g. grade-12")
    w.add_argument("--grades", nargs="*", help="or an explicit list: grade-7 grade-8")
    w.add_argument("--subjects", nargs="*", help="only these subjects (default: every ingested one)")
    w.add_argument("--terms", nargs="*", type=int, default=[1, 2, 3],
                   help="in priority order: --terms 3 1 2 does every subject's Term 3 paper first")
    w.add_argument("--order", choices=["given", "middle-out"], default="given",
                   help="middle-out: start in the middle of the range and widen a step each way (9, 10, 8, 11, 7, 12, 6)")
    w.add_argument("--count", type=int, default=30)
    w.add_argument("--instructions", default="")
    w.add_argument("--download", default=os.getenv("CBC_DOWNLOAD_DIR", os.path.join(os.getcwd(), "papers")))
    w.add_argument("--redo", action="store_true", help="re-run papers the ledger already marks done")
    w.add_argument("--no-pdf", dest="no_pdf", action="store_true",
                   help="leave the papers on the platform; do not download their PDFs")
    w.add_argument("--model", required=True)
    w.add_argument("--llm-url", dest="llm_url", default=os.getenv("LLM_URL", "http://localhost:11434/v1"))
    w.add_argument("--window", default=os.getenv("CBC_SERVE_WINDOW", ""),
                   help="only work between these times, e.g. 22:00-07:00; an unfinished paper carries over")
    v = sub.add_parser("serve", help="answer every task the platform is waiting on, and keep watching for more")
    v.add_argument("--model", required=True)
    v.add_argument("--llm-url", dest="llm_url", default=os.getenv("LLM_URL", "http://localhost:11434/v1"))
    v.add_argument("--poll", type=int, default=30, help="seconds between looks at an empty queue")
    v.add_argument("--until-empty", dest="until_empty", action="store_true",
                   help="stop once nothing is waiting, instead of watching for new tasks")
    v.add_argument("--max-attempts", dest="max_attempts", type=int, default=3,
                   help="failed model calls on one step before the task is set aside for 15 minutes")
    v.add_argument("--think", action="store_true", help="let qwen3 / deepseek-r1 reason first (slower)")
    v.add_argument("--download", default=os.getenv("CBC_DOWNLOAD_DIR", ""),
                   help="save finished papers' PDFs here")
    v.add_argument("--window", default=os.getenv("CBC_SERVE_WINDOW", ""),
                   help="only serve between these times, e.g. 00:00-07:00; outside it, stop and unload the model")
    n = sub.add_parser("night", help="plan tonight from the campaign and the bank, work it, report in the morning")
    n.add_argument("--model", required=True)
    n.add_argument("--llm-url", dest="llm_url", default=os.getenv("LLM_URL", "http://localhost:11434/v1"))
    n.add_argument("--window", default=os.getenv("CBC_SERVE_WINDOW", ""))
    n.add_argument("--plan-only", dest="plan_only", action="store_true", help="print tonight's plan and stop")
    args = parser.parse_args()
    if getattr(args, "think", False):
        global THINK
        THINK = True
    if not KEY:
        sys.exit("set CBC_API_KEY (an API key from the console's Providers page)")
    if args.command == "sweep":
        global _WINDOW
        _WINDOW = getattr(args, "window", "") or ""
        if _WINDOW and not _in_window(_WINDOW):
            print(f"outside the window {_WINDOW}; nothing to do now")
            return
        sweep(args)
    elif args.command == "night":
        night(args)
    elif args.command == "serve":
        try:
            serve(args)
        except KeyboardInterrupt:
            print("\nstopped.")
    else:
        run(args)


if __name__ == "__main__":
    main()
