#!/usr/bin/env python3
"""Is this Ollama, and these models, up to the platform's prompts?

Pure standard library. Points at an Ollama server, lists what it has, and
puts each model through what the platform will ask of it: a plain answer
(speed), a JSON object in a given schema (discipline), a long prompt with a
fact buried early (the context window actually in force), and a CBC-shaped
batch of three questions with a figure (the real thing, in miniature).

    python3 ollama_probe.py --url https://ollama.gidraf.dev
    python3 ollama_probe.py --url https://ollama.gidraf.dev --models qwen3:14b --num-ctx 16384
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def call(url: str, path: str, body: dict | None = None, timeout: int = 900) -> dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url.rstrip("/") + path, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def chat(url: str, model: str, messages: list[dict[str, str]], *, num_ctx: int, json_mode: bool = False,
         temperature: float = 0.3) -> tuple[str, dict[str, Any]]:
    body: dict[str, Any] = {"model": model, "messages": messages, "stream": False,
                            "options": {"temperature": temperature, "num_ctx": num_ctx}}
    if json_mode:
        body["format"] = "json"
    t0 = time.time()
    out = call(url, "/api/chat", body)
    content = str((out.get("message") or {}).get("content") or "")
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    stats = {
        "seconds": round(time.time() - t0, 1),
        "prompt_tokens": out.get("prompt_eval_count"),
        "output_tokens": out.get("eval_count"),
        "tok_per_s": round(out["eval_count"] / (out["eval_duration"] / 1e9), 1)
        if out.get("eval_count") and out.get("eval_duration") else None,
    }
    return content, stats


CBC_PROMPT = """You write assessment items for Kenya's CBC. Grade 9 Mathematics, strand Numbers, sub-strand Integers.
Return ONLY a JSON object: {"questions": [ ...exactly 3 items... ]}. Each item:
{"question_type": "multiple_choice", "question_text": "<a Kenyan situation, then the ask; LaTeX inside $...$>",
 "expression": "<the arithmetic that models the situation, e.g. -250 + 600 - 180 + 120/4>",
 "options": [{"id":"A","text":"...","is_correct":true,"distractor_rationale":"..."}, {"id":"B",...}, {"id":"C",...}, {"id":"D",...}],
 "marking_scheme": "A1 for ...", "model_answer": "<one sentence>", "bloom_level": "Application", "max_marks": 1}
One of the three MUST carry a figure: "figure": {"kind": "number_line", "min": -10, "max": 10, "step": 2, "marks": [{"value": -4, "label": "P"}]}
and its stem must say "Study the figure below". Exactly one option correct per item. No text outside the JSON."""


def probe(url: str, model: str, num_ctx: int) -> dict[str, Any]:
    report: dict[str, Any] = {"model": model}

    # 1. Speed and sanity.
    text, stats = chat(url, model, [{"role": "user", "content": "In one sentence, what is an integer?"}], num_ctx=num_ctx)
    report["plain"] = {"ok": "integer" in text.lower() or "whole" in text.lower(), "answer": text[:120], **stats}

    # 2. JSON discipline.
    text, stats = chat(url, model, [{"role": "user", "content":
        'Return ONLY a JSON object {"sum": <number>, "working": "<one line>"} for 17 + (-25).'}],
        num_ctx=num_ctx, json_mode=True)
    try:
        obj = json.loads(text)
        report["json"] = {"ok": isinstance(obj, dict) and float(obj.get("sum", 0)) == -8, "got": obj, **stats}
    except Exception as exc:  # noqa: BLE001
        report["json"] = {"ok": False, "error": str(exc)[:80], "raw": text[:120], **stats}

    # 3. The context window in force: a fact early in a long prompt.
    filler = " ".join(f"Line {i}: the river Tana flows through Garissa county." for i in range(700))  # ≈ 9-10k tokens
    long_prompt = f"Remember this code: ZEBRA-4471. Now some reading:\n{filler}\nWhat was the code I asked you to remember? Reply with the code only."
    text, stats = chat(url, model, [{"role": "user", "content": long_prompt}], num_ctx=num_ctx, temperature=0.0)
    report["context"] = {"ok": "4471" in text, "prompt_tokens": stats["prompt_tokens"], "answer": text[:60],
                         "seconds": stats["seconds"],
                         "note": "" if "4471" in text else "the start of the prompt was cut: raise num_ctx / OLLAMA_CONTEXT_LENGTH"}

    # 4. A CBC-shaped batch.
    text, stats = chat(url, model, [{"role": "user", "content": CBC_PROMPT}], num_ctx=num_ctx, json_mode=True)
    try:
        obj = json.loads(text)
        items = obj.get("questions") if isinstance(obj, dict) else None
        items = items if isinstance(items, list) else []
        keyed = [q for q in items if isinstance(q, dict)
                 and sum(1 for o in (q.get("options") or []) if isinstance(o, dict) and o.get("is_correct")) == 1]
        with_fig = [q for q in items if isinstance(q, dict) and isinstance(q.get("figure"), dict)]
        with_expr = [q for q in items if isinstance(q, dict) and str(q.get("expression") or "").strip()]
        report["cbc"] = {"ok": len(items) == 3 and len(keyed) == 3 and len(with_fig) >= 1,
                         "items": len(items), "one_key_each": len(keyed), "with_figure": len(with_fig),
                         "with_expression": len(with_expr),
                         "sample": str((items[0] if items else {}).get("question_text") or "")[:140], **stats}
    except Exception as exc:  # noqa: BLE001
        report["cbc"] = {"ok": False, "error": str(exc)[:80], "raw": text[:160], **stats}
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:11434")
    ap.add_argument("--models", nargs="*", help="default: every model the server lists")
    ap.add_argument("--num-ctx", type=int, default=16384)
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = ap.parse_args()

    try:
        tags = call(args.url, "/api/tags")
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"cannot reach {args.url}/api/tags: {exc}")
    have = [m["name"] for m in tags.get("models", [])]
    print(f"{args.url}: {len(have)} model(s): {', '.join(have) or '(none)'}")
    models = args.models or have
    reports = []
    for model in models:
        if model not in have:
            print(f"\n{model}: not on this server (ollama pull {model})")
            continue
        print(f"\n=== {model}  (num_ctx {args.num_ctx}) ===")
        try:
            r = probe(args.url, model, args.num_ctx)
        except urllib.error.HTTPError as exc:
            print(f"  HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:200]}")
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"  failed: {exc}")
            continue
        reports.append(r)
        for key in ("plain", "json", "context", "cbc"):
            x = r[key]
            mark = "PASS" if x.get("ok") else "FAIL"
            speed = f"{x['tok_per_s']} tok/s" if x.get("tok_per_s") else ""
            extra = {k: v for k, v in x.items() if k not in ("ok", "tok_per_s", "seconds", "got", "raw", "answer", "sample", "note", "error")}
            print(f"  {key:8s} {mark}  {x.get('seconds', '')}s {speed}  {extra}")
            for k in ("answer", "sample", "note", "error", "raw"):
                if x.get(k):
                    print(f"           {k}: {x[k]}")
        verdict = ("usable for the platform" if all(r[k]["ok"] for k in ("json", "context", "cbc"))
                   else "not yet: fix what FAILed above before pointing the platform at it")
        print(f"  → {verdict}")
    if args.json:
        print(json.dumps(reports, indent=1))


if __name__ == "__main__":
    main()
