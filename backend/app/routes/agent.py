"""The agent API: run a station, answer its prompts on your own model.

    POST /api/v1/agent/tasks                 start a station as a task
    GET  /api/v1/agent/tasks/{id}            its state and the pending prompt
    POST /api/v1/agent/tasks/{id}/complete   answer the pending prompt
    GET  /api/v1/agent/tasks/{id}/wait       long-poll for the next prompt
    GET  /api/v1/agent/manifest              the protocol, for an agent to read

and the engines on their own, for an agent that wants to draw a figure,
solve an expression, check a batch or compose a paper without running a
station:

    POST /api/v1/agent/engines/solve
    POST /api/v1/agent/engines/figure
    POST /api/v1/agent/engines/map
    POST /api/v1/agent/engines/check-questions

Authenticated with an API key like everything else. The station code is
the queue's own: a task runs `_run_queued` / `_run_queued_questions`, so
what the agent produces goes through exactly the checks, repairs, figure
drawing and filing the queue applies — the only difference is who
answered the prompts.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..errors import raise_api_error
from ..services import byom
from ..services.auth import AuthContext, require_roles

logger = logging.getLogger("cbc-agent-api")
router = APIRouter(prefix="/api/v1/agent", tags=["Agent (bring your own model)"])

STATIONS = ("notes", "diagram", "activity", "material", "media", "simulation", "questions",
            "strands", "substrands")


class StartTaskRequest(BaseModel):
    station: str
    grade: str
    subject: str
    strand: str = ""
    sub_strand: str = ""
    count: int | None = None
    custom_instructions: str = ""
    review_cycles: int | None = None
    # Whatever else the station's payload takes (strand_id, plan_only, …).
    extra: dict[str, Any] = Field(default_factory=dict)
    # How long to wait for the first prompt before returning.
    wait_seconds: float = Field(default=20, ge=0, le=120)


class CompleteRequest(BaseModel):
    content: Any = Field(..., description="The model's answer: a JSON object, or the raw text")
    model: str = Field(default="", description="What answered, for the ledger: e.g. ollama/llama3.1")
    wait_seconds: float = Field(default=25, ge=0, le=120)


def _runner(station: str, params: dict[str, Any]) -> Any:
    from ..routes import curriculum

    job = {"kind": station, "grade": params.get("grade") or "", "subject": params.get("subject") or "",
           "strand": params.get("strand") or "", "sub_strand": params.get("sub_strand") or "",
           "payload": {k: v for k, v in params.items()
                       if k not in ("grade", "subject", "strand", "sub_strand")}}
    handler = curriculum._PIPELINE_HANDLERS.get(station)
    if handler is None:
        raise ValueError(f"'{station}' is not a station")
    return handler(job)


def _view(task: byom.Task) -> dict[str, Any]:
    out = task.to_dict()
    out["how"] = ("answer the `step.messages` on your model, then POST the answer to "
                  f"/api/v1/agent/tasks/{task.task_id}/complete as {{\"content\": …}}"
                  if task.status == byom.AWAITING else
                  "the station is working; poll /wait" if task.status == byom.RUNNING else
                  f"finished: {task.status}")
    return out


@router.get("/manifest")
def manifest(_: AuthContext = Depends(require_roles("admin", "operator", "developer"))) -> dict[str, Any]:
    """What an agent needs to know, in one read."""
    from ..services import figure_sketch

    return {
        "protocol": [
            "POST /api/v1/agent/tasks with {station, grade, subject, strand, sub_strand, count}.",
            "The response carries `step.messages` — a system/user message list — when the station "
            "needs a model. Run them on any model. `step.expect` is 'json' or 'text'; for json, "
            "return the JSON object the prompt asks for.",
            "POST /api/v1/agent/tasks/{task_id}/complete with {content, model}. The response is the "
            "next step, or the finished task with its result (artifact ids, saved counts, gate).",
            "A station may ask several prompts in a row (a guide is six lessons; a batch of fifty "
            "questions is two chunks plus rewrites). Keep answering until status is 'done'.",
            "GET /api/v1/agent/tasks/{task_id}/wait?seconds=30 long-polls for the next prompt.",
            "Prompts are the platform's own, assembled from the design, the demand profile and what "
            "was written before. Answer them faithfully — the checks downstream are the platform's "
            "and a wrong answer is caught, rewritten (another prompt to you) or held.",
        ],
        "stations": {
            "notes": "the teacher's guide for a sub-strand (per-lesson prompts, then checks and rewrites)",
            "diagram": "plan the sub-strand's figures, then draw each (maps are drawn by the platform)",
            "activity": "activities and experiments",
            "material": "the learner's material, one prompt per piece",
            "questions": "a batch of items for a sub-strand; needs notes first. `count` items.",
            "media": "media prompts", "simulation": "simulation briefs",
            "strands": "read the design's strands", "substrands": "one strand's sub-strands (draft)",
        },
        "order": ["ingest (console)", "strands", "substrands", "notes", "diagram", "questions",
                  "then compose and freeze a paper: GET /api/v1/questions/paper/exam.json, "
                  "POST /api/v1/questions/paper/freeze"],
        "engines": {
            "POST /api/v1/agent/engines/solve": {"expression": "$(-12)+4\\\\times(-3)$"},
            "POST /api/v1/agent/engines/figure": {"figure": "see figure_kinds"},
            "POST /api/v1/agent/engines/map": {"map": {"extent": "Kenya", "features": ["..."]}},
            "POST /api/v1/agent/engines/check-questions": {"grade": "grade-9", "subject": "Mathematics",
                                                           "sub_strand": "Integers", "questions": ["…"]},
        },
        "figure_kinds": figure_sketch.prompt_block(),
        "papers": {
            "compose": "GET /api/v1/questions/paper/exam.json?grade=&subject=&kind=topical&sub_strand=&count=30",
            "print": "GET /api/v1/questions/paper/exam.html (…&answers=true for the scheme, &with_scheme=true for both)",
            "freeze": "POST /api/v1/questions/paper/freeze — frozen paper with a QR code to its scheme; "
                      "then GET /api/v1/exams/{exam_id}/paper.html|paper.pdf",
        },
        "guide": "GET /api/v1/artifacts/{artifact_id}/render for a guide; the task result names the artifact.",
    }


@router.post("/tasks")
def start_task(payload: StartTaskRequest,
               auth: AuthContext = Depends(require_roles("admin", "operator", "developer"))) -> dict[str, Any]:
    if payload.station not in STATIONS:
        raise_api_error("SCHEMA_VALIDATION_FAILED",
                        f"'{payload.station}' is not a station. One of: {', '.join(STATIONS)}.")
    params: dict[str, Any] = {"grade": payload.grade, "subject": payload.subject,
                              "strand": payload.strand, "sub_strand": payload.sub_strand,
                              "custom_instructions": payload.custom_instructions, **payload.extra}
    if payload.count:
        params["count"] = payload.count
    if payload.review_cycles is not None:
        params["review_cycles"] = payload.review_cycles
    task = byom.start(payload.station, params, created_by=auth.subject, runner=_runner)
    logger.info("BYOM task %s started by %s: %s for %s/%s/%s", task.task_id, auth.subject,
                payload.station, payload.grade, payload.subject, payload.sub_strand or payload.strand)
    byom.wait(task, payload.wait_seconds, since_steps=0)
    return _view(task)


@router.get("/tasks")
def list_tasks(_: AuthContext = Depends(require_roles("admin", "operator", "developer"))) -> dict[str, Any]:
    live = [t.to_dict(with_result=False) for t in byom.all_tasks()]
    for item in live:
        item.pop("step", None)
    ledger: list[dict[str, Any]] = []
    try:
        from ..infra.db import fetch_all

        ledger = fetch_all("SELECT task_id, station, params, status, created_by, steps, model_used, error, "
                           "created_at, finished_at FROM agent_tasks ORDER BY created_at DESC LIMIT 100")
    except Exception as exc:  # noqa: BLE001
        logger.debug("No agent_tasks ledger: %s", exc)
    return {"live": live, "ledger": ledger}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, _: AuthContext = Depends(require_roles("admin", "operator", "developer"))) -> dict[str, Any]:
    task = byom.get(task_id)
    if task is None:
        raise_api_error("NOT_FOUND", f"No live task {task_id}. If the API restarted, start it again.")
    return _view(task)


@router.get("/tasks/{task_id}/wait")
def wait_task(task_id: str, seconds: float = Query(30, ge=0, le=120),
              _: AuthContext = Depends(require_roles("admin", "operator", "developer"))) -> dict[str, Any]:
    task = byom.get(task_id)
    if task is None:
        raise_api_error("NOT_FOUND", f"No live task {task_id}.")
    byom.wait(task, seconds, since_steps=len(task.steps))
    return _view(task)


@router.post("/tasks/{task_id}/complete")
def complete_task(task_id: str, payload: CompleteRequest,
                  _: AuthContext = Depends(require_roles("admin", "operator", "developer"))) -> dict[str, Any]:
    task = byom.get(task_id)
    if task is None:
        raise_api_error("NOT_FOUND", f"No live task {task_id}.")
    done_before = len(task.steps)
    try:
        byom.complete(task_id, payload.content, payload.model)
    except ValueError as exc:
        raise_api_error("SCHEMA_VALIDATION_FAILED", str(exc))
    # Wait for the station to consume the answer and either ask again or finish.
    byom.wait(task, payload.wait_seconds, since_steps=done_before + 1)
    return _view(task)


@router.delete("/tasks/{task_id}")
def cancel_task(task_id: str, _: AuthContext = Depends(require_roles("admin", "operator", "developer"))) -> dict[str, Any]:
    task = byom.cancel(task_id)
    if task is None:
        raise_api_error("NOT_FOUND", f"No live task {task_id}.")
    return _view(task)


# ── the engines, on their own ────────────────────────────────────────────────

class SolveRequest(BaseModel):
    expression: str
    claimed_answer: str = ""


@router.post("/engines/solve")
def engine_solve(payload: SolveRequest,
                 _: AuthContext = Depends(require_roles("admin", "operator", "developer"))) -> dict[str, Any]:
    """The maths engine: the value, the working, and a verdict on a claimed answer."""
    from ..services import worked_solutions

    solution = worked_solutions.solve(payload.expression)
    out = {"solved": solution.solved, "answer": solution.answer, "verified": solution.verified,
           "why_not": solution.why_not,
           "steps": [{"working": ln.latex, "because": ln.because} for ln in solution.lines]}
    if payload.claimed_answer:
        out["claim"] = worked_solutions.check(payload.expression, payload.claimed_answer)
    return out


class FigureRequest(BaseModel):
    figure: dict[str, Any]
    register: bool = Field(default=False, description="File it in the diagram registry and return its id")
    grade: str = ""
    subject: str = ""
    sub_strand: str = ""


@router.post("/engines/figure")
def engine_figure(payload: FigureRequest,
                  _: AuthContext = Depends(require_roles("admin", "operator", "developer"))) -> dict[str, Any]:
    """A question figure from data: number line, chart, table, clock, shape, …"""
    from ..services import figure_sketch

    drawn = figure_sketch.render(payload.figure)
    if drawn is None:
        raise_api_error("SCHEMA_VALIDATION_FAILED",
                        "That figure could not be drawn. " + figure_sketch.prompt_block()[:600])
    out = {"svg": drawn["svg"], "title": drawn["title"], "kind": drawn["kind"]}
    if payload.register:
        from ..services.diagram_dedup import diagram_deduplicator

        dedup = diagram_deduplicator.deduplicate_and_store(
            svg_str=drawn["svg"], diagram_title=drawn["title"], alt_text=drawn["alt_text"],
            scene_document=drawn["scene"],
            metadata={"grade": payload.grade, "subject": payload.subject,
                      "sub_strand": payload.sub_strand, "question_figure": True, "kind": drawn["kind"]})
        out["diagram_id"] = dedup.diagram_id
        out["storage_url"] = dedup.storage_url
    return out


class MapRequest(BaseModel):
    map: dict[str, Any]
    title: str = ""
    register: bool = False
    grade: str = ""
    subject: str = ""
    sub_strand: str = ""


@router.post("/engines/map")
def engine_map(payload: MapRequest,
               _: AuthContext = Depends(require_roles("admin", "operator", "developer"))) -> dict[str, Any]:
    """A sketch map from the map contract (extent, features, key)."""
    from ..services import map_sketch

    spec = map_sketch.from_model({"map": payload.map, "diagram_title": payload.title})
    if spec is None:
        raise_api_error("SCHEMA_VALIDATION_FAILED", "That is not a map the renderer can draw.")
    drawn = map_sketch.render(spec)
    out = {"svg": drawn["svg"], "title": drawn["title"], "unplaced": drawn.get("unplaced") or [],
           "parts": len((drawn.get("scene") or {}).get("parts") or [])}
    if payload.register:
        from ..services.diagram_dedup import diagram_deduplicator

        dedup = diagram_deduplicator.deduplicate_and_store(
            svg_str=drawn["svg"], diagram_title=drawn["title"],
            alt_text=drawn["alt_text"], scene_document=drawn["scene"],
            metadata={"grade": payload.grade, "subject": payload.subject,
                      "sub_strand": payload.sub_strand, "map": True})
        out["diagram_id"] = dedup.diagram_id
        out["storage_url"] = dedup.storage_url
    return out


class CheckQuestionsRequest(BaseModel):
    grade: str
    subject: str
    strand: str = ""
    sub_strand: str = ""
    questions: list[dict[str, Any]]


@router.post("/engines/check-questions")
def engine_check_questions(payload: CheckQuestionsRequest,
                           _: AuthContext = Depends(require_roles("admin", "operator", "developer"))) -> dict[str, Any]:
    """The question checks, on items in the API shape — keys against the
    engine, repeats, demand, coverage — without filing anything."""
    from ..services import question_check

    report = question_check.check(payload.questions, grade=payload.grade, subject=payload.subject,
                                  strand=payload.strand, sub_strand=payload.sub_strand)
    return report.to_dict()
