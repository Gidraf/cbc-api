"""The developer studio: a project idea in, a working app built on the CBC
API out — with its videos, its book and a link to try it.

One job (kind "dev_project") runs the stages in order and records each, so a
retry carries on where it stopped:

  plan     a model (Claude, OpenAI/Codex, Gemini or a local Ollama — the
           project says which; or "agent": your own Claude Code, Codex,
           Antigravity or Ollama answers each prompt through Agent tasks)
           thinks the idea through: the pitch, the
           architecture and how data flows through it, a walkthrough, the
           files, the tests, a demo script and the episodes;
  code     each file written in turn, knowing the plan and the files before it;
  test     the app opened in a real browser on sample questions: its own
           tests (tests.js) run, and any page error counts — failures go back
           to the model to fix, twice at most;
  publish  the files stored, served at /p/<id>/ — the test link, sandboxed
           into an origin of its own (model-written code never shares the
           console's). The app asks ./cbc/... for questions; that route
           answers from the bank without a key, a few at a time;
  shots    the demo script played on the live app, a screen per step;
  videos   per episode a vertical short — the architecture drawn with data
           flowing through it, the code typed, the app working — and the
           whole series as one long landscape video; the project's intro
           comes last. No humanoid: the work speaks, in a voice picked for
           the project;
  book     a PDF in the notes' book design: the idea, the architecture, the
           walkthrough, every file, the screens of the finished app.

Apps are static web apps (HTML, CSS, JavaScript) — "Android" ideas are
installable PWAs — so they run anywhere a link opens.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("cbc-dev-studio")

JOB_KIND = "dev_project"
PREFIX = "devprojects"
STAGES = ("plan", "code", "test", "publish", "shots", "videos", "book")
CATEGORIES = ("productivity", "games", "visualisation", "animations", "android")
DEV_VOICES = ["en-US-AndrewNeural", "en-GB-RyanNeural", "en-US-AvaNeural", "en-GB-SoniaNeural", "en-KE-ChilembaNeural",
              "en-NG-AbeoNeural", "en-IN-PrabhatNeural", "en-US-BrianNeural", "en-AU-WilliamNeural", "en-KE-AsiliaNeural"]
MAX_FILES = 6
MAX_FILE_CHARS = 14_000

IDEAS: dict[str, list[str]] = {
    "productivity": ["A revision planner that turns a learner's weak sub-strands into a daily question schedule",
                     "A teacher's quick quiz builder that prints a one-page quiz from five CBC questions"],
    "games": ["A timed maths race: answer CBC questions to move your runner to the finish line",
              "Flashcard memory match: pair each question with its answer"],
    "visualisation": ["A curriculum explorer that draws grades, strands and sub-strands as a zoomable tree",
                      "A difficulty heatmap of a subject's questions by sub-strand"],
    "animations": ["An animated step-by-step solver that reveals a question's worked answer line by line",
                   "A spinning wheel that picks a random question for the class"],
    "android": ["An installable offline practice app (PWA) that caches ten questions for the bus ride home",
                "A daily question widget-style PWA with streaks"],
}

# The prompts are seeded (langfuse_seed: dev-project-planner, dev-file-writer,
# dev-file-fixer) so they can be read and improved in the console without a deploy.
# ── storage of a project ─────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row(project_id: str) -> dict[str, Any]:
    from ..infra.db import fetch_one

    row = fetch_one("SELECT * FROM dev_projects WHERE project_id = :id", {"id": project_id})
    if not row:
        raise ValueError("No such project.")
    return row


def _save(project_id: str, **fields: Any) -> None:
    from ..infra.db import execute, to_json

    sets, params = [], {"id": project_id, "t": _now()}
    for k, v in fields.items():
        if isinstance(v, (dict, list)):
            sets.append(f"{k} = CAST(:{k} AS jsonb)")
            params[k] = to_json(v)
        else:
            sets.append(f"{k} = :{k}")
            params[k] = v
    execute(f"UPDATE dev_projects SET {', '.join(sets)}, updated_at = :t WHERE project_id = :id", params)


def create(idea: str, *, category: str = "productivity", provider: str = "", model: str = "", by: str = "") -> dict[str, Any]:
    """A new project, queued."""
    from ..infra.db import execute
    from . import job_queue

    idea = " ".join((idea or "").split())[:600]
    if category not in CATEGORIES:
        category = "productivity"
    if not idea:
        idea = IDEAS[category][int(_now().timestamp()) % len(IDEAS[category])]
    pid = "dp-" + hashlib.sha256(f"{idea}|{_now().isoformat()}".encode()).hexdigest()[:10]
    execute("""INSERT INTO dev_projects (project_id, idea, category, provider, model, created_by)
               VALUES (:id, :idea, :c, :p, :m, :by)""",
            {"id": pid, "idea": idea, "c": category, "p": provider[:40], "m": model[:80], "by": by[:80]})
    job = job_queue.enqueue(JOB_KIND, "", "", {"artifact_id": pid, "project_id": pid}, queued_by=by or "dev-studio")
    job_queue.dispatch(job.job_id)
    return {"project_id": pid, "idea": idea, "job_id": job.job_id}


def listing(limit: int = 50) -> list[dict[str, Any]]:
    from ..infra.db import fetch_all

    rows = fetch_all("""SELECT project_id, idea, category, provider, model, stage, status, error, title, urls, created_at, updated_at
                        FROM dev_projects ORDER BY created_at DESC LIMIT :n""", {"n": limit}) or []
    return [_plain(r) for r in rows]


def one(project_id: str) -> dict[str, Any]:
    r = _plain(_row(project_id))
    r["files"] = [{"path": p, "chars": len(c)} for p, c in (r.get("files") or {}).items()]
    return r


def _plain(r: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()}


# ── the model ────────────────────────────────────────────────────────────────

def _ask(row: dict[str, Any], prompt: str, system: str = "") -> dict[str, Any]:
    from .llm_client import llm_client
    from .pipeline import pipeline_orchestrator

    provider = row.get("provider") if row.get("provider") not in ("", "agent") else None
    resolved = pipeline_orchestrator.router.resolve_for_stage("question_generation", provider, row.get("model") or None)
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    out = llm_client.generate(resolved, messages, temperature=0.3, expect="json")
    payload = out.content
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload if isinstance(payload, dict) else {}


SYSTEM = ""   # the role is in each seeded prompt


def _fill(template: str, variables: dict[str, Any]) -> str:
    from .langfuse_context import langfuse_context_service

    return langfuse_context_service._render_template(template, variables)


def plan(row: dict[str, Any]) -> dict[str, Any]:
    from .langfuse_context import langfuse_context_service

    prompt = _fill(langfuse_context_service.get_agent_prompt("dev-project-planner"),
                   {"category": row["category"], "idea": row["idea"]})
    p = _ask(row, prompt, SYSTEM)
    p["files"] = _tidy_files(p.get("files") or [])
    return p


def _tidy_files(planned: list[Any]) -> list[dict[str, str]]:
    """The plan's files: safe paths only, each once — the page first, its tests last."""
    seen: set[str] = set()
    middle = []
    for f in planned:
        path = str((f or {}).get("path") or "") if isinstance(f, dict) else ""
        if not re.fullmatch(r"[\w-]+(/[\w-]+)*\.[a-z]{1,5}", path) or path in seen or path in ("index.html", "tests.js"):
            continue                                   # no "..", no absolute paths, each once
        seen.add(path)
        middle.append({"path": path, "purpose": str(f.get("purpose") or "")})
    # The page first and its tests last, always — the rest in between.
    return [{"path": "index.html", "purpose": "the page"}, *middle[:MAX_FILES - 2], {"path": "tests.js", "purpose": "the tests"}]


def write_file(row: dict[str, Any], p: dict[str, Any], path: str, done: dict[str, str]) -> str:
    others = "\n\n".join(f"--- {k} ---\n{v[:4000]}" for k, v in done.items())
    from .langfuse_context import langfuse_context_service

    prompt = _fill(langfuse_context_service.get_agent_prompt("dev-file-writer"),
                   {"title": p.get("title") or "", "pitch": p.get("pitch") or "",
                    "architecture": json.dumps(p.get("architecture")), "files": json.dumps(p.get("files")),
                    "tests": json.dumps(p.get("tests")), "demo": json.dumps(p.get("demo")),
                    "written": others or "(none)", "path": path})
    content = str(_ask(row, prompt, SYSTEM).get("content") or "")
    return content[:MAX_FILE_CHARS]


def fix(row: dict[str, Any], p: dict[str, Any], files: dict[str, str], report: dict[str, Any]) -> dict[str, str]:
    listing_ = "\n\n".join(f"--- {k} ---\n{v}" for k, v in files.items())
    from .langfuse_context import langfuse_context_service

    prompt = _fill(langfuse_context_service.get_agent_prompt("dev-file-fixer"),
                   {"report": json.dumps(report)[:4000], "listing": listing_[:40000]})
    out = _ask(row, prompt, SYSTEM)
    fixed = dict(files)
    for f in out.get("files") or []:
        if isinstance(f, dict) and f.get("path") in files and f.get("content"):
            fixed[f["path"]] = str(f["content"])[:MAX_FILE_CHARS]
    return fixed


# ── the browser: tests, the demo ─────────────────────────────────────────────

SAMPLE_QUESTIONS = [
    {"id": f"sample-{k}", "grade": "Grade 6", "subject": "Mathematics", "strand": "Numbers", "sub_strand": s,
     "type": "multiple_choice", "context": "", "question": q, "options": [{"id": l, "text": t} for l, t in zip("ABCD", opts)],
     "correct_option": "B", "answer": opts[1], "worked_answer": w, "marking_scheme": "", "marks": 1, "difficulty": 0.5,
     "has_figure": False, "figure": None}
    for k, (s, q, opts, w) in enumerate([
        ("Fractions", "Which fraction is equal to $\\frac{3}{4}$?", ["4/3", "6/8", "3/8", "9/16"], "Multiply top and bottom by 2: 6/8."),
        ("Money", "3 books cost KSh 45 each. What do they cost?", ["KSh 48", "KSh 135", "KSh 90", "KSh 150"], "45 × 3 = 135."),
        ("Length", "A garden is 12 m by 8 m. Find its perimeter.", ["20 m", "40 m", "96 m", "48 m"], "2 × (12 + 8) = 40."),
        ("Whole numbers", "Round 7 864 to the nearest hundred.", ["7 800", "7 900", "8 000", "7 860"], "64 is more than 50: 7 900."),
        ("Decimals", "What is 0.5 as a fraction?", ["1/5", "1/2", "5/1", "2/5"], "5 tenths is one half."),
    ])
]
CURRICULUM = [{"grade": "Grade 6", "subject": "Mathematics", "strand": "Numbers", "sub_strand": s, "questions": 40}
              for s in ("Fractions", "Money", "Length", "Whole numbers", "Decimals")]

_HARNESS = """<script>
window.__tests = []; window.__errors = [];
window.test = (name, fn) => window.__tests.push({name, fn});
window.assert = (c, m) => { if (!c) throw new Error(m || "assertion failed"); };
window.addEventListener("error", (e) => window.__errors.push(String(e.message || e)));
window.addEventListener("unhandledrejection", (e) => window.__errors.push(String(e.reason && e.reason.message || e.reason)));
window.__runTests = async () => { const out = []; for (const t of window.__tests) { try { await t.fn(); out.push({name: t.name, ok: true}); }
  catch (e) { out.push({name: t.name, ok: false, error: String(e && e.message || e)}); } } return out; };
</script>"""


def _sample_api(path: str, query: str) -> dict[str, Any] | None:
    if path.endswith("/cbc/curriculum"):
        return {"items": CURRICULUM}
    if path.endswith("/cbc/questions"):
        return {"items": SAMPLE_QUESTIONS, "total": len(SAMPLE_QUESTIONS)}
    m = re.search(r"/cbc/questions/([^/]+)$", path)
    if m:
        return next((q for q in SAMPLE_QUESTIONS if q["id"] == m.group(1)), SAMPLE_QUESTIONS[0])
    return None


def _browser(files: dict[str, str], *, run_tests: bool = True, demo: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Open the app in Chromium on sample data: the test report, and — given a
    demo — a screen (and where the action was) after each step."""
    import mimetypes

    from playwright.sync_api import sync_playwright

    from .browser import LAUNCH_ARGS

    host = "http://app.localhost"
    shots: list[dict[str, Any]] = []

    def handle(route):
        url = route.request.url[len(host):]
        path, _, query = url.partition("?")
        api = _sample_api(path, query)
        if api is not None:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(api))
        name = path.lstrip("/") or "index.html"
        if name not in files:
            if route.request.url.startswith(host):
                return route.fulfill(status=404, body="")
            return route.continue_()
        body = files[name]
        if name == "index.html" and run_tests:
            body = body.replace("<head>", "<head>" + _HARNESS, 1) if "<head>" in body else _HARNESS + body
        route.fulfill(status=200, body=body, content_type=mimetypes.guess_type(name)[0] or "text/plain")

    report: dict[str, Any] = {"tests": [], "errors": [], "console": []}
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True, args=LAUNCH_ARGS)
        try:
            ctx = br.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5)
            ctx.route("**/*", handle)
            page = ctx.new_page()
            page.on("console", lambda m: report["console"].append(m.text[:200]) if m.type == "error" else None)
            page.on("pageerror", lambda e: report["errors"].append(str(e)[:300]))
            page.goto(host + "/index.html", wait_until="load", timeout=30_000)
            page.wait_for_timeout(1500)
            if run_tests:
                if "tests.js" in files:
                    page.add_script_tag(content=files["tests.js"])
                report["tests"] = page.evaluate("() => window.__runTests ? window.__runTests() : []")
                report["errors"] += page.evaluate("() => window.__errors || []")
            for step in demo or []:
                box = [0, 0, 0, 0]
                sel = str(step.get("selector") or "")
                try:
                    if sel and step.get("action") in ("click", "type"):
                        loc = page.locator(sel).first
                        loc.scroll_into_view_if_needed(timeout=3000)
                        b = loc.bounding_box()
                        box = [round(b["x"]), round(b["y"]), round(b["width"]), round(b["height"])] if b else box
                        if step["action"] == "type":
                            loc.fill(str(step.get("value") or ""), timeout=3000)
                        page.wait_for_timeout(300)
                        before = page.screenshot(type="jpeg", quality=82)
                        if step["action"] == "click":
                            loc.click(timeout=3000)
                    else:
                        before = page.screenshot(type="jpeg", quality=82)
                    page.wait_for_timeout(900)
                    after = page.screenshot(type="jpeg", quality=82)
                except Exception as exc:  # noqa: BLE001
                    report["errors"].append(f"demo step {sel}: {exc}"[:200])
                    before = after = page.screenshot(type="jpeg", quality=82)
                shots.append({"before": base64.b64encode(before).decode(), "after": base64.b64encode(after).decode(),
                              "box": box, "say": str(step.get("say") or "")})
        finally:
            br.close()
    report["passed"] = bool(report["tests"]) and all(t.get("ok") for t in report["tests"]) and not report["errors"]
    report["shots"] = shots
    return report


# ── the video ────────────────────────────────────────────────────────────────

def voice_for(project_id: str) -> str:
    n = int(hashlib.sha256(project_id.encode()).hexdigest(), 16)
    return DEV_VOICES[n % len(DEV_VOICES)]


def _code_window(files: dict[str, str], path: str, lines: str) -> tuple[str, list[int]]:
    text = files.get(path) or next(iter(files.values()), "")
    rows = text.splitlines()
    m = re.match(r"(\d+)\s*-\s*(\d+)", str(lines or ""))
    a, b = (int(m.group(1)), int(m.group(2))) if m else (1, 14)
    a = max(1, min(a, len(rows) or 1))
    b = max(a, min(b, a + 15, len(rows)))
    return "\n".join(r[:90] for r in rows[a - 1:b]), []


def episode_scenes(row: dict[str, Any], k: int) -> list[dict[str, Any]]:
    """One episode: what it is about, the architecture (the first) or its code, the app working."""
    p, files, shots = row.get("plan") or {}, row.get("files") or {}, row.get("shots") or []
    ep = (p.get("episodes") or [])[k]
    scenes: list[dict[str, Any]] = [{"scene": "title", "text": ep.get("title") or p.get("title") or "",
                                     "say": ep.get("say_intro") or ep.get("title") or "", "caption": ep.get("say_intro") or ""}]
    if k == 0:
        arch = p.get("architecture") or {}
        flow = " ".join(p.get("data_flow") or [])[:500] or p.get("pitch") or ""
        scenes.append({"scene": "arch", "title": "How data flows", "nodes": arch.get("nodes") or [],
                       "edges": arch.get("edges") or [], "say": flow, "caption": flow})
    code, light = _code_window(files, str(ep.get("file") or ""), str(ep.get("lines") or ""))
    scenes.append({"scene": "code", "file": ep.get("file") or "", "code": code, "highlight": light,
                   "say": ep.get("explain") or "", "caption": ep.get("explain") or ""})
    for s in shots[k:k + 2] if shots else []:
        scenes.append({"scene": "screen", "img": "data:image/jpeg;base64," + s["before"], "box": s["box"],
                       "say": s["say"] or "Here it is, working.", "caption": s["say"]})
    return scenes


def _intro(row: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """The project's intro — last, as the series' signature."""
    p, urls = row.get("plan") or {}, row.get("urls") or {}
    site = (urls.get("app") or b.get("website") or "").replace("https://", "")
    return {"scene": "outro", "name": p.get("title") or "", "handle": "Built on the CBC API", "website": site,
            "cta": p.get("pitch") or "", "say": f"{p.get('title')}. {p.get('pitch')} Try it at the link, and build your own on the CBC API.",
            "caption": f"Try it: {site}"}


def render_videos(row: dict[str, Any]) -> dict[str, Any]:
    from . import drive_store, social, whiteboard

    pid = row["project_id"]
    b = {**social.brand(), "teacher": "off", "cover": True}
    voice = voice_for(pid)
    p = row.get("plan") or {}
    out: dict[str, Any] = {"shorts": [], "voice": voice}
    all_scenes: list[dict[str, Any]] = []
    for k in range(len(p.get("episodes") or [])):
        scenes = episode_scenes(row, k)
        all_scenes += scenes
        data = {"question_id": f"{pid}-e{k + 1}", "kind": "dev", "no_hand": True, "scenes": scenes + [_intro(row, b)]}
        q = {"question_id": data["question_id"], "question_text": p.get("pitch") or "", "curriculum": {}}
        framing = social.frame_payload(q, b)
        framing["hook"] = p.get("hook") or p.get("title") or "Built on the CBC API"
        framing["tag"] = "DEVELOPERS · CBC API"
        if framing.get("cover"):
            framing["cover"].update({"hook": framing["hook"], "question": f"Episode {k + 1}: {scenes[0]['text']}",
                                     "choices": [], "tag": "BUILD WITH THE CBC API", "figure": ""})
        key = hashlib.sha256(json.dumps([data, voice], sort_keys=True, default=str).encode()).hexdigest()[:20]
        made = whiteboard.render(data, title=str(scenes[0]["text"])[:80], voice=voice, social=framing, prefix=PREFIX, key=key)
        out["shorts"].append({"episode": k + 1, "title": scenes[0]["text"], "url": made.get("url"),
                              "thumbnail_url": made.get("thumbnail_url"), "seconds": made.get("seconds")})
        _copy_to_drive(drive_store, f"{PREFIX}/{data['question_id']}/{key}")
    data = {"question_id": f"{pid}-long", "kind": "dev", "no_hand": True, "scenes": all_scenes + [_intro(row, b)]}
    key = hashlib.sha256(json.dumps([data, voice], sort_keys=True, default=str).encode()).hexdigest()[:20]
    made = whiteboard.render(data, title=str(p.get("title") or "")[:80], voice=voice, prefix=PREFIX, key=key)
    out["long"] = {"url": made.get("url"), "seconds": made.get("seconds")}
    _copy_to_drive(drive_store, f"{PREFIX}/{data['question_id']}/{key}", thumb=False)
    return out


def _copy_to_drive(drive_store: Any, base: str, thumb: bool = True) -> None:
    try:
        drive_store.copy_now(f"{base}.mp4", f"{base}.jpg" if thumb else "")
    except Exception as exc:  # noqa: BLE001
        logger.info("Drive copy skipped for %s: %s", base, exc)


# ── the book ─────────────────────────────────────────────────────────────────

def _arch_svg(arch: dict[str, Any]) -> str:
    nodes = (arch.get("nodes") or [])[:9]
    edges = arch.get("edges") or []
    col = {n.get("id"): 0 for n in nodes}
    for _ in nodes:
        for e in edges:
            if e.get("from") in col and e.get("to") in col and col[e["to"]] < col[e["from"]] + 1 < len(nodes):
                col[e["to"]] = col[e["from"]] + 1
    cols = (max(col.values()) + 1) if col else 1
    by: dict[int, list[dict[str, Any]]] = {}
    for n in nodes:
        by.setdefault(col[n.get("id")], []).append(n)
    w, h, bw, bh = 640, 300, 120, 46
    pos = {}
    parts = []
    for c, lst in by.items():
        x = 20 + (c + 0.5) * ((w - 40) / cols) - bw / 2
        for r, n in enumerate(lst):
            y = 20 + (r + 0.5) * ((h - 40) / len(lst)) - bh / 2
            pos[n.get("id")] = (x, y)
            parts.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{bw}" height="{bh}" rx="8" fill="#eef4ff" stroke="#1d4ed8"/>'
                         f'<text x="{x + bw / 2:.0f}" y="{y + 28:.0f}" text-anchor="middle" font-size="12">{html.escape(str(n.get("label") or "")[:20])}</text>')
    for e in edges:
        if e.get("from") in pos and e.get("to") in pos:
            (x1, y1), (x2, y2) = pos[e["from"]], pos[e["to"]]
            parts.insert(0, f'<line x1="{x1 + bw:.0f}" y1="{y1 + bh / 2:.0f}" x2="{x2:.0f}" y2="{y2 + bh / 2:.0f}" stroke="#94a3b8" stroke-width="2" marker-end="url(#a)"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="100%"><defs><marker id="a" viewBox="0 0 10 10" '
            f'refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L10,5L0,10z" fill="#94a3b8"/></marker></defs>'
            + "".join(parts) + "</svg>")


BOOK_CSS = """@page{size:A5;margin:16mm 14mm}body{font-family:Georgia,'Times New Roman',serif;color:#1b1f2a;font-size:10.5pt;line-height:1.55}
h1{font-family:'Helvetica Neue',Arial,sans-serif;font-size:24pt;margin:0 0 6pt;color:#0f3d63}
h2{font-family:'Helvetica Neue',Arial,sans-serif;font-size:14pt;color:#0f3d63;border-bottom:2px solid #f2b705;padding-bottom:3pt;margin-top:18pt;page-break-after:avoid}
.cover{height:170mm;display:flex;flex-direction:column;justify-content:center;page-break-after:always}
.cover .tag{font-family:Arial,sans-serif;font-size:9pt;letter-spacing:.12em;color:#b45309;text-transform:uppercase}
.cover .pitch{font-size:13pt;color:#334155}.link{font-family:Menlo,monospace;font-size:9pt;color:#1d4ed8}
.box{background:#fff8e1;border-left:4px solid #f2b705;padding:6pt 9pt;margin:8pt 0}
pre{background:#0f172a;color:#e2e8f0;font-family:Menlo,Consolas,monospace;font-size:7.4pt;line-height:1.4;padding:8pt;border-radius:5pt;
white-space:pre-wrap;word-break:break-word}img{width:100%;border:1px solid #cbd5e1;border-radius:4pt;margin:6pt 0}
.cap{font-size:8.5pt;color:#64748b;text-align:center;margin-top:-3pt}ol li{margin-bottom:3pt}"""


def book_html(row: dict[str, Any]) -> str:
    p, files, urls, shots = row.get("plan") or {}, row.get("files") or {}, row.get("urls") or {}, row.get("shots") or []
    e = html.escape
    parts = [f"""<div class="cover"><div class="tag">Build with the CBC API · {e(row.get('category') or '')}</div>
<h1>{e(p.get('title') or row['idea'])}</h1><p class="pitch">{e(p.get('pitch') or '')}</p>
<p>Try it: <span class="link">{e(urls.get('app') or '')}</span></p></div>""",
             f"<h2>What it does</h2><p>{e(p.get('walkthrough') or '')}</p>",
             f"<h2>The architecture</h2>{_arch_svg(p.get('architecture') or {})}<p class='cap'>How the parts fit together</p>",
             "<h2>How data flows</h2><ol>" + "".join(f"<li>{e(s)}</li>" for s in p.get("data_flow") or []) + "</ol>"]
    if p.get("sample"):
        parts.append(f"<h2>The key idea in code</h2><pre>{e(p['sample'])}</pre>")
    if shots:
        parts.append("<h2>The finished app</h2>")
        for s in shots:
            parts.append(f'<img src="data:image/jpeg;base64,{s["after"]}"><p class="cap">{e(s.get("say") or "")}</p>')
    parts.append("<h2>Tested</h2><div class='box'>" + "<br>".join(
        f"{'✔' if t.get('ok') else '✘'} {e(t.get('name') or '')}" for t in (row.get("tests") or {}).get("tests") or []) + "</div>")
    parts.append("<h2>Every file</h2>")
    for path, code in files.items():
        parts.append(f"<p><b>{e(path)}</b></p><pre>{e(code)}</pre>")
    parts.append("<h2>Your turn</h2><p>Get a free key at the CBC API's developer page — 100 calls a day — and change "
                 "<code>./cbc/</code> to the API's address with your key in the X-API-Key header, from your own server.</p>")
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{BOOK_CSS}</style></head><body>{''.join(parts)}</body></html>"


def render_book(row: dict[str, Any]) -> str:
    from playwright.sync_api import sync_playwright

    from ..infra.storage import object_storage, public_object_url
    from .browser import LAUNCH_ARGS

    with sync_playwright() as p:
        br = p.chromium.launch(headless=True, args=LAUNCH_ARGS)
        try:
            page = br.new_page()
            page.set_content(book_html(row), wait_until="load")
            pdf = page.pdf(format="A5", print_background=True)
        finally:
            br.close()
    name = f"{PREFIX}/{row['project_id']}/book.pdf"
    object_storage.save_bytes(name, pdf, "application/pdf")
    return public_object_url(name)


# ── the job ──────────────────────────────────────────────────────────────────

def app_url(project_id: str) -> str:
    from . import platform_settings

    try:
        base = platform_settings.public_base_url(None)
    except Exception:  # noqa: BLE001
        base = ""
    return f"{(base or '').rstrip('/')}/p/{project_id}/"


def _write(pid: str) -> dict[str, Any]:
    """The stages a model does: plan, code, and the fixes the test asks for."""
    row = _row(pid)
    if not row.get("plan"):
        _save(pid, stage="plan")
        p = plan(row)
        _save(pid, plan=p, title=str(p.get("title") or "")[:120])
        row = _row(pid)
    if not row.get("files"):
        _save(pid, stage="code")
        done: dict[str, str] = {}
        for f in row["plan"]["files"]:
            done[f["path"]] = write_file(row, row["plan"], f["path"], done)
            _save(pid, files=done)
        row = _row(pid)
    if not (row.get("tests") or {}).get("checked"):
        _save(pid, stage="test")
        files = dict(row["files"])
        report: dict[str, Any] = {}
        for attempt in range(3):
            report = _browser(files)
            report.pop("shots", None)
            report["attempt"] = attempt + 1
            if report["passed"] or attempt == 2:
                break
            files = fix(row, row["plan"], files, report)
        _save(pid, files=files, tests={**report, "checked": True})
        row = _row(pid)
    return row


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    pid = str((job.get("payload") or {}).get("project_id") or "")
    row = _row(pid)
    _save(pid, status="running", error="")
    try:
        if row.get("provider") == "agent" and not (row.get("tests") or {}).get("checked"):
            # Written by your own agent (Claude Code, Codex, Antigravity, Ollama)
            # through Agent tasks; this job comes back when it has finished.
            start_agent(pid, by=str(job.get("queued_by") or ""))
            _save(pid, stage="agent", status="waiting")
            return {"status": "waiting", "project_id": pid}
        row = _write(pid)
        if not (row.get("urls") or {}).get("app"):
            _save(pid, stage="publish")
            publish(pid, row["files"])
            _save(pid, urls={**(row.get("urls") or {}), "app": app_url(pid)})
            row = _row(pid)
        if not row.get("shots"):
            _save(pid, stage="shots")
            got = _browser(row["files"], run_tests=False, demo=(row["plan"].get("demo") or [])[:6])
            _save(pid, shots=got["shots"])
            row = _row(pid)
        if not (row.get("urls") or {}).get("long"):
            _save(pid, stage="videos")
            vids = render_videos(row)
            _save(pid, urls={**(row.get("urls") or {}), "shorts": vids["shorts"], "long": vids["long"], "voice": vids["voice"]})
            row = _row(pid)
        if not (row.get("urls") or {}).get("book"):
            _save(pid, stage="book")
            _save(pid, urls={**(row.get("urls") or {}), "book": render_book(row)})
        _save(pid, stage="done", status="done")
        return {"status": "done", "project_id": pid}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dev project %s failed: %s", pid, exc)
        _save(pid, status="failed", error=f"{type(exc).__name__}: {exc}"[:900])
        raise


def start_agent(pid: str, *, by: str = "") -> str:
    """The writing as an Agent task: each prompt waits for your agent's answer;
    when the code has passed its test the rest (publish, videos, book) is queued."""
    from . import byom, job_queue

    def runner(station: str, params: dict[str, Any]) -> Any:
        _write(params["project_id"])
        job = job_queue.enqueue(JOB_KIND, "", "", {"artifact_id": params["project_id"], "project_id": params["project_id"]},
                                queued_by="agent")
        job_queue.dispatch(job.job_id)
        return {"project_id": params["project_id"], "next_job": job.job_id}

    task = byom.start("dev_project", {"project_id": pid, "grade": "", "subject": ""}, created_by=by or "dev-studio",
                      runner=runner)
    return task.task_id


def publish(project_id: str, files: dict[str, str]) -> None:
    from ..infra.storage import object_storage

    for path, content in files.items():
        object_storage.save_text(f"{PREFIX}/{project_id}/app/{path}", content)


def served_file(project_id: str, path: str) -> tuple[bytes, str] | None:
    """A published file of a project, for /p/<id>/<path>."""
    import mimetypes

    from ..infra.storage import object_storage

    if not re.fullmatch(r"dp-[0-9a-f]{10}", project_id) or not re.fullmatch(r"[\w./-]{1,80}", path) or ".." in path:
        return None
    raw = object_storage.read_bytes(f"{PREFIX}/{project_id}/app/{path}")
    if raw is None:
        return None
    return raw, (mimetypes.guess_type(path)[0] or "text/plain")


# ── LinkedIn: what goes out, the poster takes it ─────────────────────────────

def queue_linkedin(project_id: str, *, kinds: tuple[str, ...] = ("document", "short", "long")) -> int:
    """The project's book (a document post), its first short and the long video, queued for LinkedIn."""
    from ..infra.db import execute

    row = _row(project_id)
    p, urls = row.get("plan") or {}, row.get("urls") or {}
    tags = "#CBC #Kenya #EdTech #WebDev #JavaScript #BuildInPublic"
    base = f"{p.get('title')}: {p.get('pitch')}\n\nTry it: {urls.get('app') or ''}\nBuilt on the CBC API — questions, answers and marking schemes for Kenya's curriculum.\n\n{tags}"
    items = []
    if "document" in kinds and urls.get("book"):
        items.append(("document", urls["book"], f"📘 The full build, step by step — {base}"))
    if "short" in kinds and urls.get("shorts"):
        items.append(("video", urls["shorts"][0]["url"], f"🎬 {urls['shorts'][0]['title']} — {base}"))
    if "long" in kinds and (urls.get("long") or {}).get("url"):
        items.append(("video", urls["long"]["url"], f"▶️ The whole build in one video — {base}"))
    n = 0
    for kind, url, text in items:
        execute("""INSERT INTO linkedin_posts (post_id, project_id, kind, media_url, title, body)
                   VALUES (:id, :p, :k, :u, :t, :b) ON CONFLICT (post_id) DO NOTHING""",
                {"id": hashlib.sha256(f"{project_id}|{url}".encode()).hexdigest()[:16], "p": project_id, "k": kind,
                 "u": url, "t": str(p.get("title") or "")[:200], "b": text[:2900]})
        n += 1
    return n


def linkedin_next() -> dict[str, Any] | None:
    from ..infra.db import fetch_one

    # Claimed as it is handed out: asked twice, it is never posted twice. A
    # claim with no answer in an hour goes back to the queue.
    row = fetch_one("""UPDATE linkedin_posts SET status = 'posting', claimed_at = NOW()
                       WHERE post_id = (SELECT post_id FROM linkedin_posts
                                        WHERE attempts < 3 AND (status = 'queued' OR
                                              (status = 'posting' AND claimed_at < NOW() - INTERVAL '1 hour'))
                                        ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
                       RETURNING post_id, kind, media_url, title, body""")
    return dict(row) if row else None


def linkedin_done(post_id: str, ok: bool, *, url: str = "", error: str = "") -> None:
    from ..infra.db import execute

    execute("""UPDATE linkedin_posts SET status = CASE WHEN :ok THEN 'posted' WHEN attempts + 1 >= 3 THEN 'failed' ELSE 'queued' END,
                      attempts = attempts + 1, url = :u, error = :e, posted_at = CASE WHEN :ok THEN NOW() ELSE NULL END
               WHERE post_id = :id""", {"ok": ok, "u": url[:500], "e": error[:500], "id": post_id})
