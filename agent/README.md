# Bring your own model

The platform assembles every prompt — the design extract, the demand profile,
the lessons already written, the shape of the national paper — and a station
normally sends it to a provider you pay per token. In this mode the station
**hands the prompt out through the API instead**, you answer it on whatever you
already have — Claude Code, Codex, Antigravity, a local Ollama — and post the
answer back. Everything downstream is the platform's: the normaliser, the maths
engine, the checks and rewrites, the figure and map renderers, the paper, the
QR-coded marking scheme, the PDF.

Your side pulls prompts and pushes answers. The platform never needs to reach
your machine, and it never sees a model credential.

## 0. The one-line product

> Give me a Grade 7 Mathematics mid-term 1 assessment.

Console: Content factory → choose the grade and subject → **Produce a paper**
→ Term 1, 30 questions → Produce. The order works out the sub-strands Term 1
covers, writes the guides, figures and items that don't exist yet, composes
the paper in the national format, freezes it, and shows the print links on
the same panel. (Provider mode: your bound models pay. Agent mode, below: your
subscription pays.)

Agent: `cbc_produce {grade: "grade-7", subject: "Mathematics", kind: "term", term: 1, count: 30}`
and keep answering the steps it hands you until it is `done`; the result
carries `render_urls`.

**The context pack.** `GET /api/v1/agent/pack?grade=grade-7&subject=Mathematics`
(console: Providers → API keys → *Download agent pack*, or `cbc_fetch`) is a
zip with `AGENTS.md`/`CLAUDE.md` (the playbook: what each one-line request
maps to, how the loop works, the rules for answering), `manifest.json`,
`formats.json` (paper formats, figure and map contracts), every prompt the
platform sends, and the design with its term split. Unzip it into the folder
your agent works in and the agent knows the job.

## 1. An API key

Console → Providers → *API keys* → create one with the `operator` role. Put it in
`CBC_API_KEY`; put the platform address in `CBC_API_URL`.

## 2a. Claude Code / Codex / Antigravity — the MCP server

`agent/cbc_mcp.py` is a stdio MCP server with no dependencies. Register it:

```json
{
  "mcpServers": {
    "cbc": {
      "command": "python3",
      "args": ["/path/to/cbc-api/agent/cbc_mcp.py"],
      "env": { "CBC_API_URL": "https://your-platform", "CBC_API_KEY": "cbc_live_..." }
    }
  }
}
```

(Claude Code: `.mcp.json` in the project or `claude mcp add`; Codex and
Antigravity take the same shape in their MCP settings.)

Then ask the agent, in words:

> Read `cbc_manifest`. Run the **questions** station for grade-9 Mathematics,
> strand Numbers, sub-strand Integers, 50 items. Answer every step it hands you
> exactly as the prompt asks and complete the task until it is done. Then
> compose a 30-question topical paper and freeze it, and give me the print links.

The agent's own model answers the prompts; its subscription pays. A 50-item
batch is two chunks plus one or two rewrite prompts (the checks send back only
the items that failed) and a second-reader prompt; a guide is one prompt per
lesson plus rewrites; the learner's material is one per piece.

Tools: `cbc_manifest`, `cbc_start_task`, `cbc_get_task`, `cbc_complete_task`,
`cbc_list_tasks`, `cbc_cancel_task`, `cbc_solve`, `cbc_draw_figure`,
`cbc_draw_map`, `cbc_check_questions`, `cbc_compose_paper`, `cbc_freeze_paper`,
`cbc_fetch`.

## 2b. Ollama or any OpenAI-compatible endpoint — the loop

No agent needed:

```bash
export CBC_API_URL=https://your-platform CBC_API_KEY=cbc_live_...
python3 agent/cbc_agent.py run --station notes --grade grade-9 --subject Mathematics \
    --strand Numbers --sub-strand Integers --model qwen2.5:32b --llm-url http://localhost:11434/v1
python3 agent/cbc_agent.py run --station questions --grade grade-9 --subject Mathematics \
    --strand Numbers --sub-strand Integers --count 50 --model qwen2.5:32b
```

It starts the task, answers each prompt on the model, posts it, and prints the
result (artifact ids, saved counts, gate). `--llm-url` takes any
OpenAI-compatible base URL, with `LLM_API_KEY` if it needs one.

A word on local models: the prompts ask for long, strict JSON with LaTeX in it.
A 7B model will fail the checks often and be sent back often; 32B and up hold
up. The platform's checks are the same whichever model answers, so a weak
model costs time, not correctness.

## 3. The protocol, if you write your own client

```
POST /api/v1/agent/tasks            {station, grade, subject, strand, sub_strand, count}
  → {task_id, status: "awaiting", step: {number, stage, expect, messages: [...]}}
POST /api/v1/agent/tasks/{id}/complete   {content: <json or text>, model: "…"}
  → the next step, or {status: "done", result: {...}}
GET  /api/v1/agent/tasks/{id}/wait?seconds=30      long-poll
GET  /api/v1/agent/tasks/{id}                       state
DELETE /api/v1/agent/tasks/{id}                     cancel
GET  /api/v1/agent/manifest                         everything above, plus the engines
```

Stations: `strands`, `substrands`, `notes`, `diagram`, `activity`, `material`,
`questions`, `media`, `simulation`. Order for one sub-strand: notes → diagram →
questions → compose/freeze a paper.

## 4. The engines, on their own

```
POST /api/v1/agent/engines/solve            {expression, claimed_answer?}
POST /api/v1/agent/engines/figure           {figure: {kind: "bar_chart", ...}, save?}
POST /api/v1/agent/engines/map              {map: {extent, features, key}, save?}
POST /api/v1/agent/engines/check-questions  {grade, subject, sub_strand, questions: [...]}
GET  /api/v1/questions/paper/exam.json      compose;  POST /api/v1/questions/paper/freeze  freeze
GET  /api/v1/exams/{exam_id}/paper.html|paper.pdf    print
```

## What lives where

A task's live state (the thread, the pending prompt) is in the API process; if
the API restarts mid-task the task is lost and `GET` says so — start it again.
Finished tasks are in the `agent_tasks` ledger (station, model used, steps,
result summary). Each prompt waits up to `BYOM_STEP_TIMEOUT_SECONDS` (default 45
minutes) for an answer.
