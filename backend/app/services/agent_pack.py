"""The context pack: everything an outside agent needs, in one download.

An agent sitting in a project folder with this pack in it can be asked
"give me a Grade 7 Mathematics mid-term 1 assessment" and know what that
means here: which MCP tool to call, what the platform will hand back,
what the design covers, what every prompt asks for, and where the
finished PDF is. AGENTS.md is written to be read by Claude Code, Codex
and Antigravity alike (Claude Code also reads it as CLAUDE.md).

The prompts are included so a person can read what the platform asks a
model to do — and so an agent that prefers to prepare its own context
before a task can. They are the seeded defaults; a prompt edited in
Langfuse is what the platform actually sends, and the task's own step
carries that.
"""
from __future__ import annotations

import io
import json
import zipfile
from typing import Any


def _playbook(base_url: str, grade: str, subject: str) -> str:
    scope = f" for {grade} {subject}" if grade and subject else ""
    return f"""# CBC content platform — agent playbook{scope}

You are driving a content platform that turns KICD curriculum designs into
teacher's guides, figures, question banks and printed assessment papers.
The platform assembles every prompt and runs every check; **you answer the
prompts on your own model**. Nothing you produce is filed until it has been
through the platform's normaliser, maths engine, checks and rewrites.

## Setup (once)

MCP server: `cbc/cbc_mcp.py` in a kit (or `backend/app/agent_clients/cbc_mcp.py`
in the platform repo) over stdio, with `CBC_API_URL={base_url}` and
`CBC_API_KEY=<an operator API key>`. A kit's `install.sh` writes that config for
its agent. Or call the REST API directly — see `manifest.json` in this pack.

## The one-line products

| Ask | Do |
|---|---|
| "Grade 7 Mathematics mid-term 1 assessment" | `cbc_start_task {{station: "order", grade: "grade-7", subject: "Mathematics", kind: "term", term: 1, count: 30}}` |
| "End of Term 2 exam, Grade 9 Integrated Science" | same with `term: 2`, `count: 40` |
| "Topical test on Integers, Grade 9" | `kind: "topical", strand: "Numbers", sub_strand: "Integers", count: 30` |
| "End of strand assessment, Numbers, Grade 9" | `kind: "strand", strand: "Numbers", count: 40` |
| "Teacher's guide for Integers" | `station: "notes"` with the strand and sub-strand |
| "50 questions on Integers" | `station: "questions"`, `count: 50` |

An **order** works out the sub-strands the scope covers, runs notes → figures →
questions for each that is missing, composes the paper in the national
format (KPSEA at Grades 4–6, KJSEA at 7–9), freezes it with a QR code to its
marking scheme, and returns `result.render_urls` — the paper, the booklet
(paper + scheme), the marking scheme, and PDFs. Give the user those links.

## The loop

1. `cbc_start_task` returns a task. While `status` is `awaiting`, `step.messages`
   is a prompt for you: answer it **exactly as it asks** (JSON when
   `step.expect` is `json`; the schema is in the prompt), then
   `cbc_complete_task {{task_id, content, model}}`.
2. The reply is the next step or the finished task. Keep going until
   `status` is `done`. An order for one term is typically 15–40 prompts; a
   50-item batch is 2 chunks plus a rewrite or two; a guide is one per lesson.
3. If a step's prompt says items FAILED a check and names why, fix exactly
   what is named — the engine's value is right; do not argue with it.
4. When `status` is `failed`, read `error`. "No sub-strands found" means the
   design is not ingested: run `cbc_start_task {{station: "ingest", grade, subject}}`
   (the design document must be in the console's Datasets screen), then start
   the order again. Notes missing for a sub-strand: the order writes them.

## Rules for answering prompts

- Return only what the prompt asks for. No preamble, no fences around JSON.
- LaTeX inside JSON strings uses a single backslash escaped for JSON: `\\\\times`.
- Figures a question needs go in `figure` as data (see `formats.json`); the
  platform draws them. Maps go in `map`. Never describe a figure in words.
- Do not repeat the guide's worked examples as questions; the checks catch it.
- Sentence answers to sentence questions; values to value questions.

## Reading what was made

- A frozen paper: `cbc_fetch /api/v1/exams/{{exam_id}}/paper.html` (add
  `?answers=true` for the scheme, `?with_scheme=true` for both) — or the PDF
  at `/paper.pdf`. The scheme's public link (QR) needs no sign-in.
- A guide: `cbc_fetch /api/v1/artifacts/{{artifact_id}}/render`.
- The bank: `cbc_fetch /api/v1/questions?grade=&subject=&sub_strand=`.

## Engines you can call directly

`cbc_solve` (maths), `cbc_draw_figure`, `cbc_draw_map`, `cbc_check_questions`,
`cbc_compose_paper`, `cbc_freeze_paper`. Use them when the user asks for a
figure, a map, a check or a paper on its own.

## What is in this pack

- `manifest.json` — the REST protocol and engines.
- `formats.json` — the national paper formats, the figure contract, the map contract.
- `design/` — the design's strands, sub-strands, outcomes, hours and the term split{scope}.
- `prompts/` — every prompt the platform sends, as seeded. The task's step
  carries the live version.
"""


def build(*, base_url: str = "", grade: str = "", subject: str = "") -> bytes:
    """The pack as a zip."""
    from . import assessment_format, figure_sketch
    from .prompt_sync import _all_prompts

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        playbook = _playbook(base_url or "https://your-platform", grade, subject)
        zf.writestr("AGENTS.md", playbook)
        zf.writestr("CLAUDE.md", playbook)
        zf.writestr("manifest.json", json.dumps(_manifest(base_url), ensure_ascii=False, indent=1))
        formats = {
            "assessment_formats": {f.key: f.to_dict() for f in
                                   (assessment_format.LOWER_PRIMARY, assessment_format.KPSEA,
                                    assessment_format.KJSEA, assessment_format.SENIOR)},
            "assessment_names": assessment_format.ASSESSMENT_NAMES,
            "figure_contract": figure_sketch.prompt_block(),
        }
        try:
            from . import map_sketch

            formats["map_contract"] = getattr(map_sketch, "PROMPT_BLOCK", "") or getattr(map_sketch, "prompt_block", lambda: "")()
        except Exception:  # noqa: BLE001
            pass
        zf.writestr("formats.json", json.dumps(formats, ensure_ascii=False, indent=1))
        seen: set[str] = set()
        for name, text in sorted(_all_prompts().items()):
            if "/" in name or text in seen:
                continue
            seen.add(text)
            zf.writestr(f"prompts/{name}.md", f"# {name}\n\n{text}")
        if grade and subject:
            zf.writestr(f"design/{grade}-{subject.lower().replace(' ', '-')}.json",
                        json.dumps(_design(grade, subject), ensure_ascii=False, indent=1))
    return buf.getvalue()


def _manifest(base_url: str) -> dict[str, Any]:
    try:
        from ..routes.agent import manifest as _m

        out = _m(_=None)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        out = {}
    out["base_url"] = base_url
    out["auth"] = "header X-API-Key: <api key with the operator role>"
    return out


def _design(grade: str, subject: str) -> dict[str, Any]:
    from ..infra.db import fetch_all
    from .grade_sql import clause as grade_clause
    from . import product_orders

    try:
        rows = fetch_all(
            f"""
            SELECT strand_name, sub_strand_name, allocated_hours, slos, key_inquiry_questions,
                   learning_experiences, required_diagrams, experiments
            FROM curriculum_substrands
            WHERE {grade_clause("grade", "grade")} AND LOWER(subject) = LOWER(:subject)
            ORDER BY id
            """,
            {"grade": grade, "subject": subject})
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not read the design: {exc}"}
    terms = {}
    try:
        terms = {n: [r["sub_strand"] for r in product_orders.term_scope(grade, subject, n)] for n in (1, 2, 3)}
    except Exception:  # noqa: BLE001
        pass
    return {"grade": grade, "subject": subject, "terms": terms,
            "sub_strands": [dict(r) for r in rows]}


# ── the per-agent kit ────────────────────────────────────────────────────────
#
# The pack above is the context. The KIT is the pack plus what the chosen
# agent needs to open it and start: its own MCP config with the key and the
# server path already in it, the server itself (no repo to clone), a
# one-line installer, and an AGENTS.md whose first section is written for
# that agent. Choose the agent the way you choose an OS to download for.

AGENTS = ("antigravity", "claude", "codex", "ollama")

_AGENT_TITLE = {"antigravity": "Antigravity", "claude": "Claude Code", "codex": "Codex CLI", "ollama": "Ollama"}


def _mcp_json(server_path: str, base_url: str, key: str) -> str:
    return json.dumps({"mcpServers": {"cbc": {"command": "python3", "args": [server_path],
                                              "env": {"CBC_API_URL": base_url, "CBC_API_KEY": key}}}},
                      indent=2)


def _codex_toml(server_path: str, base_url: str, key: str) -> str:
    return (f'[mcp_servers.cbc]\ncommand = "python3"\nargs = ["{server_path}"]\n'
            f'[mcp_servers.cbc.env]\nCBC_API_URL = "{base_url}"\nCBC_API_KEY = "{key}"\n')


def _installer(agent: str) -> str:
    return f"""#!/bin/sh
# Installs the CBC MCP server for {_AGENT_TITLE[agent]}. Run from this folder:  sh install.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
# The server lives OUTSIDE the workspace. A coding agent that finds a
# Python file in its project folder "fixes" it instead of using the tools
# it provides; a folder holding only the playbook leaves it nothing to edit.
HOME_KIT="$HOME/.cbc/{agent}"
mkdir -p "$HOME_KIT"
cp "$HERE/cbc/cbc_mcp.py" "$HERE/cbc/cbc_agent.py" "$HERE/cbc/.env" "$HOME_KIT/"
SERVER="$HOME_KIT/cbc_mcp.py"
BASE="$(sed -n 's/^CBC_API_URL=//p' "$HOME_KIT/.env")"
KEY="$(sed -n 's/^CBC_API_KEY=//p' "$HOME_KIT/.env")"
rm -rf "$HERE/cbc"
echo "server installed at $HOME_KIT (removed from this folder so the agent has nothing to edit)"
write_json() {{ # $1 = target file
  mkdir -p "$(dirname "$1")"
  if [ -s "$1" ] && grep -q '"mcpServers"' "$1" && ! grep -q '"cbc"' "$1"; then
    python3 - "$1" "$SERVER" "$BASE" "$KEY" "$HERE" <<'PY'
import json, sys
path, server, base, key, here = sys.argv[1:6]
cfg = json.load(open(path))
cfg.setdefault("mcpServers", {{}})["cbc"] = {{"command": "python3", "args": [server],
    "env": {{"CBC_API_URL": base, "CBC_API_KEY": key, "CBC_DOWNLOAD_DIR": here + "/papers"}}}}
json.dump(cfg, open(path, "w"), indent=2)
PY
  else
    python3 - "$1" "$SERVER" "$BASE" "$KEY" "$HERE" <<'PY'
import json, sys
path, server, base, key, here = sys.argv[1:6]
json.dump({{"mcpServers": {{"cbc": {{"command": "python3", "args": [server],
    "env": {{"CBC_API_URL": base, "CBC_API_KEY": key, "CBC_DOWNLOAD_DIR": here + "/papers"}}}}}}}}, open(path, "w"), indent=2)
PY
  fi
  echo "wrote $1"
}}
case "{agent}" in
  antigravity) write_json "$HOME/.gemini/antigravity/mcp_config.json"
               echo "Now: open THIS folder in Antigravity, then Agent panel -> MCP Servers -> Refresh. You should see 'cbc' with 14 tools." ;;
  claude)      write_json "$HERE/.mcp.json"
               echo "Now: cd \"$HERE\" && claude   (Claude Code reads .mcp.json and CLAUDE.md here; approve the cbc server when asked)" ;;
  codex)       mkdir -p "$HOME/.codex"
               if grep -q 'mcp_servers.cbc' "$HOME/.codex/config.toml" 2>/dev/null; then echo "cbc already in ~/.codex/config.toml"; else
                 printf '\n[mcp_servers.cbc]\ncommand = "python3"\nargs = ["%s"]\n[mcp_servers.cbc.env]\nCBC_API_URL = "%s"\nCBC_API_KEY = "%s"\nCBC_DOWNLOAD_DIR = "%s/papers"\n' "$SERVER" "$BASE" "$KEY" "$HERE" >> "$HOME/.codex/config.toml"
                 echo "wrote ~/.codex/config.toml"; fi
               echo "Now: cd \"$HERE\" && codex   (Codex reads AGENTS.md here)" ;;
  ollama)      echo "Run:  sh run.sh order grade-7 Mathematics \"\" \"\" 30 qwen2.5:32b" ;;
esac
"""


def _ollama_runner() -> str:
    return """#!/bin/sh
# sh run.sh <station|order> <grade> <subject> [strand] [sub_strand] [count] [model] [llm_url]
#   sh run.sh order grade-7 Mathematics "" "" 30 qwen2.5:32b
#   sh run.sh questions grade-9 Mathematics Numbers Integers 50 qwen2.5:32b http://localhost:11434/v1
KIT="$HOME/.cbc/ollama"; [ -f "$KIT/.env" ] || KIT="$(cd "$(dirname "$0")" && pwd)/cbc"
set -a; . "$KIT/.env"; set +a
STATION="${1:-order}"; GRADE="$2"; SUBJECT="$3"; STRAND="${4:-}"; SUB="${5:-}"; COUNT="${6:-30}"
MODEL="${7:-qwen2.5:32b}"; URL="${8:-http://localhost:11434/v1}"
exec python3 "$KIT/cbc_agent.py" run --station "$STATION" --grade "$GRADE" --subject "$SUBJECT" \
  --strand "$STRAND" --sub-strand "$SUB" --count "$COUNT" --model "$MODEL" --llm-url "$URL"
"""


def _agent_preface(agent: str, base_url: str) -> str:
    title = _AGENT_TITLE[agent]
    steps = {
        "antigravity": ("Run `sh install.sh` once (it writes `~/.gemini/antigravity/mcp_config.json`), open this "
                        "folder in Antigravity, and refresh MCP Servers in the agent panel. Then type your "
                        "request in the agent chat."),
        "claude": ("Run `sh install.sh` once (it writes `.mcp.json` here), then `claude` in this folder. Claude "
                   "Code reads `CLAUDE.md` and the `cbc` server. Then type your request."),
        "codex": ("Run `sh install.sh` once (it adds `[mcp_servers.cbc]` to `~/.codex/config.toml`), then "
                  "`codex` in this folder. Codex reads `AGENTS.md`. Then type your request."),
        "ollama": ("No agent: `sh run.sh order grade-7 Mathematics \"\" \"\" 30 qwen2.5:32b` runs a whole "
                   "order on your local model and prints the print links. 32B+ models hold up; 7B ones "
                   "are sent back by the checks often."),
    }[agent]
    return f"""# Start here — {title}

**You are an OPERATOR of a platform, not a developer of one.** Talk to the
platform only through the `cbc` MCP tools (`cbc_manifest`, `cbc_produce`,
`cbc_start_task`, `cbc_complete_task`, …). Never write or run Python, curl or
urllib against the API, never edit or "fix" any file in this folder or in
`~/.cbc/`, and never try to reach `localhost` — there is no server on this
machine. If a tool is missing, stop and tell the user to refresh MCP servers.

**A task outlives the connection.** Every tool call answers within about a
minute; a task runs for hours on the platform behind them. If a call comes
back with `ok: false` and a `task_id`, or the MCP server is reloaded, do not
start over: call `cbc_get_task` with that `task_id` (or `cbc_list_tasks` to
find it) and carry on answering its steps. A finished task keeps its result
and print links. Only start a new `cbc_produce` for a new paper.

This folder is ready for {title}. The platform at {base_url} assembles every
prompt and runs every check; {title} answers the prompts on its own model.
Your API key is in `cbc/.env` and already inside the config the installer
writes — keep this folder private. `cbc/.env` also carries `CBC_API_URL`; if
it says `localhost`, the platform's public address was not set when this kit
was made — edit it to the address you open the console at, and run
`sh install.sh` again.

**Setup (once):** {steps}

**Then say what you want, in words:**

- "Give me a Grade 7 Mathematics mid-term 1 assessment, 30 questions."
- "Topical test on Integers for Grade 9, 30 questions, and the marking scheme."
- "Write the teacher's guide for Grade 8 Integrated Science, Living things, Cells."

The agent calls `cbc_produce` (or `cbc_start_task`), answers each step the
platform hands it, and then **downloads the files** with `cbc_download_paper`
(exam_id from the result, `token` from `result.render_urls`; what = paper,
scheme, booklet or answer_sheet) into `papers/` in this folder, and opens
them for you. The links in `result.render_urls` open in any browser too.

**Improving what came back.** Every result carries the platform's own review:
`result.self_check` (what the engine and the checks found, what was rewritten,
what is still outstanding) and `result.quality_gate` (the score and the next
actions). Ask the agent to read them and act — "read the self_check on that
task and fix the outstanding items", or "run it again with these instructions:
harder Section B, more Kenyan situations" — and it re-runs the station with
`custom_instructions`. Nothing is filed as approved until you approve it in
the console; the DRAFT stamp comes off when every item on the paper is.

---

"""


def build_kit(*, agent: str, base_url: str, api_key: str, grade: str = "", subject: str = "") -> bytes:
    """The pack for one agent, ready to open: config, server, key, playbook."""
    import pathlib

    if agent not in AGENTS:
        raise ValueError(f"unknown agent {agent!r}; one of {', '.join(AGENTS)}")
    here = pathlib.Path(__file__).resolve().parents[1] / "agent_clients"
    mcp_src = (here / "cbc_mcp.py").read_text(encoding="utf-8")
    loop_src = (here / "cbc_agent.py").read_text(encoding="utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        playbook = _agent_preface(agent, base_url) + _playbook(base_url, grade, subject)
        zf.writestr("AGENTS.md", playbook)
        zf.writestr("CLAUDE.md", playbook)
        zf.writestr("README.md", playbook)
        zf.writestr("cbc/cbc_mcp.py", mcp_src)
        zf.writestr("cbc/cbc_agent.py", loop_src)
        zf.writestr("cbc/.env", f"CBC_API_URL={base_url}\nCBC_API_KEY={api_key}\n")
        zf.writestr("install.sh", _installer(agent))
        if agent == "ollama":
            zf.writestr("run.sh", _ollama_runner())
        if agent == "claude":
            zf.writestr(".mcp.json", _mcp_json("./cbc/cbc_mcp.py", base_url, api_key))
        if agent == "antigravity":
            zf.writestr("mcp_config.example.json", _mcp_json("/ABSOLUTE/PATH/TO/THIS/FOLDER/cbc/cbc_mcp.py", base_url, api_key))
        if agent == "codex":
            zf.writestr("codex-config.example.toml", _codex_toml("/ABSOLUTE/PATH/TO/THIS/FOLDER/cbc/cbc_mcp.py", base_url, api_key))
        zf.writestr("manifest.json", json.dumps(_manifest(base_url), ensure_ascii=False, indent=1))
        from . import assessment_format, figure_sketch

        formats = {"assessment_formats": {f.key: f.to_dict() for f in
                                          (assessment_format.LOWER_PRIMARY, assessment_format.KPSEA,
                                           assessment_format.KJSEA, assessment_format.SENIOR)},
                   "assessment_names": assessment_format.ASSESSMENT_NAMES,
                   "figure_contract": figure_sketch.prompt_block()}
        zf.writestr("formats.json", json.dumps(formats, ensure_ascii=False, indent=1))
        from .prompt_sync import _all_prompts

        seen: set[str] = set()
        for name, text in sorted(_all_prompts().items()):
            if "/" in name or text in seen:
                continue
            seen.add(text)
            zf.writestr(f"prompts/{name}.md", f"# {name}\n\n{text}")
        if grade and subject:
            zf.writestr(f"design/{grade}-{subject.lower().replace(' ', '-')}.json",
                        json.dumps(_design(grade, subject), ensure_ascii=False, indent=1))
    return buf.getvalue()
