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


# The platform's largest prompt plus a chunk's answer: about 12k tokens in
# and 6k out. 24k leaves room; a Mac with 24 GB runs a 14B at this.
NUM_CTX = int(os.getenv("LLM_NUM_CTX", "24576"))
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
    """One chat completion. Ollama gets its native API, so the context window
    is set per request (LLM_NUM_CTX, default 16k) — over /v1 it cannot be,
    and Ollama's default of 4,096 truncates the platform's prompts silently.
    Anything else gets the OpenAI-compatible call."""
    if _is_ollama(llm_url):
        base = llm_url.rstrip("/")
        base = base[:-3] if base.endswith("/v1") else base
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": False,
                                "options": {"temperature": temperature, "num_ctx": NUM_CTX}}
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
    task = _platform("POST", "/api/v1/agent/tasks", body)
    print(f"task {task['task_id']} — {args.station} for {args.grade} {args.subject} "
          f"{args.sub_strand or args.strand or (f'term {args.term}' if getattr(args, 'term', None) else '')}"
          + (" (joined a task already running)" if task.get("joined_existing") else ""))
    while True:
        status = task.get("status")
        if status == "awaiting" and task.get("step"):
            step = task["step"]
            chars = sum(len(m["content"]) for m in step["messages"])
            _warn_if_prompt_exceeds_context(chars, args.llm_url)
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
        ledger[key] = {**entry, "at": time.strftime("%Y-%m-%d %H:%M")}
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
        print(f"\n=== {grade} · {subject} · Term {term} ===")
        run_args = argparse.Namespace(
            station="order", grade=grade, subject=subject, strand="", sub_strand="",
            count=args.count, instructions=args.instructions, model=args.model, llm_url=args.llm_url,
            kind="term", term=term, download=args.download,
        )
        try:
            task = run(run_args)
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
    w.add_argument("--model", required=True)
    w.add_argument("--llm-url", dest="llm_url", default=os.getenv("LLM_URL", "http://localhost:11434/v1"))
    args = parser.parse_args()
    if not KEY:
        sys.exit("set CBC_API_KEY (an API key from the console's Providers page)")
    if args.command == "sweep":
        sweep(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
