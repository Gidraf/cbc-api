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

MCP server: `agent/cbc_mcp.py` (in the platform repo) over stdio, with
`CBC_API_URL={base_url}` and `CBC_API_KEY=<an operator API key>`. Or call the
REST API directly — see `manifest.json` in this pack.

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
4. When `status` is `failed`, read `error`, fix the cause (usually: the design
   is not ingested, or notes are missing for a sub-strand), and start again.

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
