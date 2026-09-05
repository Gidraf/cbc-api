from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..errors import raise_api_error
from ..settings import settings
from ..services.auth import AuthContext, require_roles
from ..services.math_engine import (
    CurriculumContext,
    build_simulation_track,
    generate_math_question,
    get_formulas_for_context,
    load_context_from_db,
    narration_agent,
    render_educational_document_html,
    render_geometry_svg,
    render_graph_svg,
    solve_math_problem,
    verify_solution,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/math", tags=["Mathematics Engine & Simulation"])


class LoadContextRequest(BaseModel):
    grade: str
    subject: str
    sub_strand: str
    hour_number: int = 1


class SolveProblemRequest(BaseModel):
    problem: str
    problem_type: str = "auto"


class VerifyAnswerRequest(BaseModel):
    problem: str
    candidate_answer: str


class ExtractEquationsRequest(BaseModel):
    notes_text: str
    grade: str = "grade-7"
    subject: str = "Mathematics"


class NarrateStepRequest(BaseModel):
    operation: str
    latex: str
    expression_before: str = ""
    expression_after: str = ""
    grade: str = "grade-7"


class SimulateRequest(BaseModel):
    problem: str
    grade: str = "grade-7"
    subject: str = "Mathematics"
    sub_strand: str = ""
    strand: str = ""
    title: str = ""
    # Off by default: the player reads each step with the device's own voice,
    # which costs nothing and syncs to the words. Set it to ask for a
    # synthesised recording as well.
    enable_tts: bool | None = None


class GenerateQuestionRequest(BaseModel):
    grade: str
    subject: str
    sub_strand: str
    template_id: str = "auto"
    difficulty: str = "standard"
    enable_simulation: bool = True


class RenderPrintRequest(BaseModel):
    document: dict[str, Any]
    audience: str = "student"


class RenderGraphRequest(BaseModel):
    spec: dict[str, Any]


@router.post("/context")
def get_math_context(
    payload: LoadContextRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Load the KICD curriculum context for a given grade, subject, and sub-strand."""
    ctx = load_context_from_db(
        grade=payload.grade,
        subject=payload.subject,
        sub_strand=payload.sub_strand,
        hour_number=payload.hour_number,
    )
    return {"context": ctx.to_dict(), "raw_notes_preview": ctx.notes_summary[:1000]}


@router.post("/solve")
def solve_problem(
    payload: SolveProblemRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Deterministically solve a mathematical problem with step-by-step LaTeX trace."""
    trace = solve_math_problem(payload.problem, payload.problem_type)
    if trace.unsolved:
        raise_api_error("UNSOLVED_PROBLEM", trace.unsolved_reason,
                        detail={"problem": payload.problem})
    return trace.to_dict()


@router.post("/verify")
def verify_math_answer(
    payload: VerifyAnswerRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Verify if a candidate answer satisfies the problem."""
    return verify_solution(payload.problem, payload.candidate_answer)


@router.get("/formulas")
def list_formulas(
    grade: str = Query("", description="Grade filter"),
    topic: str = Query("", description="Topic filter"),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Return curriculum-aligned formula registry."""
    formulas = get_formulas_for_context(grade=grade, topic=topic)
    return {"count": len(formulas), "formulas": formulas}


@router.post("/extract-equations")
def extract_equations(
    payload: ExtractEquationsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Extract equations and mathematical formulas from notes text."""
    eqs = narration_agent.extract_equations_from_notes(
        payload.notes_text, grade=payload.grade, subject=payload.subject
    )
    return {"count": len(eqs), "equations": eqs}


@router.post("/narrate-step")
def narrate_step(
    payload: NarrateStepRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Convert a mathematical step into clear spoken words."""
    narration = narration_agent.narrate_solution_step(
        operation=payload.operation,
        latex=payload.latex,
        expression_before=payload.expression_before,
        expression_after=payload.expression_after,
        grade=payload.grade,
    )
    return {"narration": narration}


@router.post("/simulate")
def create_simulation(
    payload: SimulateRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Solve, narrate, and store a step-by-step walkthrough.

    Returns as soon as the walkthrough is built. Narration audio is queued and
    arrives later — poll `GET /api/v1/math/walkthrough/{id}` for `audio_status`.
    """
    trace = solve_math_problem(payload.problem)
    if trace.unsolved:
        raise_api_error("UNSOLVED_PROBLEM", trace.unsolved_reason,
                        detail={"problem": payload.problem})
    curr_link = {
        "grade": payload.grade,
        "subject": payload.subject,
        "strand": payload.strand,
        "sub_strand": payload.sub_strand,
    }
    track = build_simulation_track(
        problem=payload.problem,
        solution_trace=trace,
        curriculum_link=curr_link,
        title=payload.title or f"Solution: {payload.problem[:40]}",
        enable_tts=(settings.tts_synthesise if payload.enable_tts is None
                    else payload.enable_tts),
    )
    return track.to_dict()


@router.post("/generate-question")
def generate_question(
    payload: GenerateQuestionRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Generate a curriculum-linked question with solution and simulation."""
    ctx = load_context_from_db(
        grade=payload.grade,
        subject=payload.subject,
        sub_strand=payload.sub_strand,
    )
    q = generate_math_question(
        context=ctx,
        template_id=payload.template_id,
        difficulty=payload.difficulty,
        enable_simulation=payload.enable_simulation,
    )
    return q


@router.post("/render-print")
def render_print_html(
    payload: RenderPrintRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> HTMLResponse:
    """Render EducationalDocument JSON into print-ready A4 HTML with KaTeX."""
    html_out = render_educational_document_html(payload.document, audience=payload.audience)
    return HTMLResponse(content=html_out)


@router.post("/render-graph")
def render_graph(
    payload: RenderGraphRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Render standalone SVG graph or geometry figure."""
    spec = payload.spec
    if spec.get("kind") in ("triangle", "circle", "geometry"):
        svg = render_geometry_svg(spec)
    else:
        svg = render_graph_svg(spec)
    return {"svg": svg}


@router.post("/walkthrough/{simulation_id}/step/{step_index}/audio")
def upload_step_audio(
    simulation_id: str,
    step_index: int,
    file: UploadFile = File(..., description="The recording for this step"),
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """A person's own voice for one step of a walkthrough.

    No synthesiser is as good as a teacher, and for the lessons that matter
    most the answer is not a better engine — it is somebody reading the step
    aloud once. This stores the recording at exactly the key the synthesiser
    would use, and the synthesiser returns any file already at that key before
    it calls an engine. So a recorded step is never overwritten, never
    re-synthesised, and never costs anything again.
    """
    from ..infra.db import execute, fetch_one, to_json
    from ..infra.storage import object_storage

    allowed = ("audio/mpeg", "audio/mp3", "audio/mp4", "audio/ogg",
               "audio/wav", "audio/x-wav", "audio/webm")
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in allowed:
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{content_type or 'unknown'}' is not audio. This takes: "
            f"{', '.join(sorted(set(allowed)))}.",
        )

    payload = file.file.read()
    if not payload:
        raise_api_error("VALIDATION_FAILED", "The recording is empty.")
    if len(payload) > 15 * 1024 * 1024:
        raise_api_error("VALIDATION_FAILED",
                        "A single step's recording should not exceed 15MB.")

    row = fetch_one(
        "SELECT track FROM math_simulations WHERE simulation_id = :sid",
        {"sid": simulation_id},
    )
    if not row:
        raise_api_error("NOT_FOUND", f"No walkthrough {simulation_id}.")

    track = row.get("track") or {}
    steps = track.get("steps") or []
    target = next((s for s in steps if int(s.get("index", -1)) == step_index), None)
    if target is None:
        raise_api_error(
            "NOT_FOUND",
            f"Walkthrough {simulation_id} has no step {step_index}. It has "
            f"{len(steps)}.",
        )

    # The synthesiser's own key, so this file simply IS the step's audio.
    object_key = f"simulations/{simulation_id}/step_{step_index}.mp3"
    try:
        url = object_storage.save_bytes(object_key, payload, content_type)
    except Exception as exc:  # noqa: BLE001
        raise_api_error("STORAGE_UPLOAD_FAILED", f"Could not store it: {exc}")

    target["audio_url"] = url
    target["audio_source"] = "recorded"
    target["recorded_by"] = getattr(auth, "subject", "")
    track["steps"] = steps

    voiced = sum(1 for s in steps if s.get("audio_url"))
    execute(
        """
        UPDATE math_simulations
           SET track = CAST(:track AS jsonb), audio_status = :status, updated_at = NOW()
         WHERE simulation_id = :sid
        """,
        {"track": to_json(track), "sid": simulation_id,
         "status": "ready" if voiced == len(steps) else "partial"},
    )

    return {
        "simulation_id": simulation_id,
        "step": step_index,
        "audio_url": url,
        "audio_source": "recorded",
        "bytes": len(payload),
        "steps_voiced": voiced,
        "steps_total": len(steps),
    }


@router.get("/walkthrough/{simulation_id}")
def read_walkthrough(
    simulation_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """One stored walkthrough, including whatever narration has been synthesised.

    The player calls this while `audio_status` is `pending`: the walkthrough is
    watchable immediately on step timings, and the narration appears when the
    worker has finished with it.
    """
    from ..infra.db import fetch_one

    row = fetch_one(
        """
        SELECT simulation_id, title, curriculum_link, track, audio_status, updated_at
          FROM math_simulations WHERE simulation_id = :sid
        """,
        {"sid": simulation_id},
    )
    if not row:
        raise_api_error("NOT_FOUND", f"No walkthrough {simulation_id}.")
    track = row.get("track") or {}
    return {
        "simulation_id": row.get("simulation_id"),
        "title": row.get("title"),
        "curriculum_link": row.get("curriculum_link") or {},
        "audio_status": row.get("audio_status"),
        "updated_at": str(row.get("updated_at") or ""),
        **track,
    }
