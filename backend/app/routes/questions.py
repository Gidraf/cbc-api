from __future__ import annotations

import json as json_lib
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from ..errors import raise_api_error
from ..services import (demand_profile, notation, prompt_fragments,
                        prompt_store)
from ..services.auth import AuthContext, require_roles
from ..services.level_register import language_block, register_block, teacher_block
from ..services.faith_scope import prompt_block as faith_prompt_block
from ..services.grade_scope import notes_for as grade_scope_notes
from ..services.grade_order import grade_label, grade_level, grade_ordinal, normalize_grade
from ..services.langfuse_seed import SEED_PROMPT_BLOCKS
from ..services.question_dna import question_dna_service
from ..services import diagram_svg

logger = logging.getLogger("cbc-questions-factory")

router = APIRouter(prefix="/api/v1/questions", tags=["Question Bank & DNA"])


class QuestionActionRequest(BaseModel):
    action: Literal["re-create", "regenerate", "re-review"]


class QuestionBatchGenerateRequest(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    slo_id: str | None = None
    batch_count: int = 5
    question_types: list[str] = [
        "multiple_choice",
        "diagram_based",
        "experiment_based",
        "structured_scenario",
        "quantitative_calculation",
    ]
    bloom_levels: list[str] = ["Application", "Analysis", "Critical Thinking", "Recall"]
    difficulty: float = 0.65
    parent_anchor_type: str = "holistic"  # "holistic" | "hour" | "diagram" | "experiment"
    target_hour: int | None = None  # 1..4
    target_diagram_id: str | None = None
    target_experiment_id: str | None = None
    custom_instructions: str = ""


class QuestionSingleGenerateRequest(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    slo_id: str | None = None
    question_type: str = "structured_scenario"
    bloom_level: str = "Application"
    difficulty: float = 0.65
    concept_target: str = ""
    custom_instructions: str = ""


class DiagramAuthoredRequest(BaseModel):
    """Author questions from a diagram by blanking part of it.

    ``part_ids`` pins exactly which parts to blank; leave it empty to let the
    planner choose deterministically in reading order.
    """

    diagram_id: str
    grade: str = ""
    subject: str = ""
    strand: str = ""
    sub_strand: str = ""
    mode: Literal["label_blanks", "hide_parts", "crop_region", "missing_parameters"] = "label_blanks"
    max_blanks: int = 3
    part_ids: list[str] = []
    region_id: str | None = None
    custom_instructions: str = ""


class QuestionBatchApproveRequest(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    questions: list[dict[str, Any]]
    status: str = "approved"
    # The gate result from the generation call, so the stored audit records what
    # was actually measured rather than a hardcoded pass.
    quality_gate: dict[str, Any] | None = None


class QuestionExportExamRequest(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    exam_title: str = "Kenya Competency-Based Assessment: Formative & Summative Examination"
    time_allowed: str = "1 Hour 30 Minutes"
    total_marks: int = 50
    questions: list[dict[str, Any]]


class QuestionUpdateRequest(BaseModel):
    content: dict[str, Any]
    review_audit: dict[str, Any] | None = None


class TargetRequest(BaseModel):
    """What a scope is meant to produce in a day."""

    grade: str
    subject: str
    strand: str = ""
    generate_per_day: int = 500
    review_per_day: int = 250
    approve_per_day: int = 50
    active: bool = True


# How many items to ask for in one call while streaming. Small on purpose: a
# single call for fifty degrades — the structure gate catches more faults per
# item the larger the batch — and nothing can be shown to a reviewer until the
# whole call returns. Eight is about fifteen seconds of waiting per instalment.
STREAM_CHUNK = 8


@router.get("/factory/generate-stream")
def factory_generate_questions_stream(
    grade: str = Query(...),
    subject: str = Query(...),
    strand: str = Query(...),
    sub_strand: str = Query(...),
    batch_count: int = Query(20, ge=1, le=500),
    difficulty: float = Query(0.65),
    slo_id: str = Query(""),
    custom_instructions: str = Query(""),
    auth: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
):
    """Generate a batch, sending each instalment as it lands.

    Not token streaming. A batch is one JSON object, so streaming its tokens
    would send a reviewer half-written braces — the useful unit is a finished,
    structure-checked question. So the run is broken into small calls and each
    one's items are emitted as they complete.

    Three things follow from that, and all of them are why it is worth doing:
    a reviewer can start reading after fifteen seconds rather than after ten
    minutes; a provider failure at item forty keeps the first thirty-nine; and
    the items are better, because a single call asked for fifty produces worse
    ones than six calls asked for eight.
    """
    import json as _json

    def instalments():
        produced = 0
        sent_ids: set[str] = set()
        yield _sse("start", {"target": batch_count, "sub_strand": sub_strand})

        while produced < batch_count:
            want = min(STREAM_CHUNK, batch_count - produced)
            try:
                result = factory_generate_questions_batch(
                    QuestionBatchGenerateRequest(
                        grade=grade, subject=subject, strand=strand,
                        sub_strand=sub_strand, batch_count=want,
                        difficulty=difficulty,
                        slo_id=slo_id or None,
                        custom_instructions=custom_instructions,
                    ),
                    auth,
                )
            except Exception as exc:  # noqa: BLE001
                # What has already been sent is already saved. The stream ends
                # with the reason rather than with silence.
                logger.warning("Stream stopped after %d item(s): %s", produced, exc)
                yield _sse("error", {"produced": produced, "reason": str(exc)[:300]})
                return

            items = result.get("questions") or []
            fresh = [q for q in items
                     if str(q.get("question_id") or "") not in sent_ids]
            for item in fresh:
                sent_ids.add(str(item.get("question_id") or ""))
                produced += 1
                yield _sse("question", {"n": produced, "question": item})

            yield _sse("progress", {
                "produced": produced, "target": batch_count,
                "rejected": result.get("rejected") or [],
                "repair": result.get("repair") or {},
                "gate": (result.get("quality_gate") or {}).get("overall_score"),
            })

            # A chunk that produced nothing new will not produce anything on
            # the next pass either, and looping on it spends money to stand
            # still.
            if not fresh:
                yield _sse("error", {
                    "produced": produced,
                    "reason": "The last instalment returned no new items. "
                              "Stopping rather than asking again for the same "
                              "thing.",
                })
                return

        yield _sse("done", {"produced": produced})

    return StreamingResponse(
        instalments(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Nginx buffers a response body by default, which holds every
            # instalment until the whole run finishes — exactly what this
            # exists to avoid.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    import json as _json

    return f"event: {event}\ndata: {_json.dumps(data, default=str)}\n\n"


@router.get("/throughput")
def question_throughput_board(
    grade: str = Query(...),
    subject: str = Query(...),
    strand: str = Query(""),
    on: str = Query("", description="A day, ISO. Defaults to today."),
    days: int = Query(14, ge=1, le=90),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Today against its target, and the fortnight behind it.

    A day's numbers on their own say nothing. Whether the queue between
    generating and reviewing is GROWING is the question this exists to answer,
    because the number that kills this operation is not "we generated 400
    today" — it is "3,000 items are waiting and nobody noticed".
    """
    from ..services import question_throughput

    from ..services import production_coverage

    today = question_throughput.progress(grade, subject, strand, on=on or None)
    # A day's throughput says nothing about how much of the CURRICULUM is done.
    # 500 questions written is a good day and still 3% of a grade, and an
    # operator watching only the funnel cannot tell those apart.
    try:
        produced = production_coverage.report(grade, subject).to_dict()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not measure production for %s/%s: %s",
                       grade, subject, exc)
        produced = {}
    return {
        **today.to_dict(),
        "history": question_throughput.history(grade, subject, strand, days=days),
        "coverage": produced,
    }


@router.post("/throughput/target")
def set_question_target(
    payload: TargetRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Set the day's plan for one scope.

    A target on a grade and subject covers every strand in it until a strand is
    given its own — otherwise adding a strand silently drops it out of the plan.
    """
    from ..services import question_throughput

    return question_throughput.set_target(
        payload.grade, payload.subject, payload.strand,
        generate_per_day=payload.generate_per_day,
        review_per_day=payload.review_per_day,
        approve_per_day=payload.approve_per_day,
        active=payload.active)


@router.post("/{question_id}/passed")
def record_question_step(
    question_id: str,
    event: str = Query(..., description="reviewed | approved | rejected"),
    grade: str = Query(""),
    subject: str = Query(""),
    strand: str = Query(""),
    sub_strand: str = Query(""),
    note: str = Query(""),
    auth: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Mark one item as read, signed for, or sent back.

    Counted as its own event rather than written over a status column: an item
    generated, reviewed, rejected and regenerated in one day shows as one
    generation on a status column, and the reviewer's day disappears.
    """
    from ..services import question_throughput

    allowed = (question_throughput.REVIEWED, question_throughput.APPROVED,
               question_throughput.REJECTED)
    if event not in allowed:
        raise_api_error("VALIDATION_FAILED",
                        f"'{event}' is not a step. Known: {', '.join(allowed)}.")

    written = question_throughput.record(
        event, question_id=question_id, grade=grade, subject=subject,
        strand=strand, sub_strand=sub_strand,
        actor=getattr(auth, "subject", ""), detail={"note": note} if note else {})
    return {"question_id": question_id, "event": event, "recorded": written}


@router.get("/structure")
def question_structure_report(
    grade: str = Query(...),
    subject: str = Query(...),
    sub_strand: str = Query(""),
    strand: str = Query(""),
    limit: int = Query(200, ge=1, le=500),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Every filed item against the shape its own type promises."""
    from ..services import question_structure

    items = question_dna_service.list_questions(
        grade=grade, subject=subject, strand=strand or None,
        sub_strand=sub_strand or None, limit=limit)
    return question_structure.check_all(
        items, grade=grade, subject=subject, strand=strand,
        sub_strand=sub_strand)


@router.get("/paper.html", response_class=HTMLResponse)
def questions_paper_html(
    grade: str = Query(...),
    subject: str = Query(...),
    sub_strand: str = Query(""),
    strand: str = Query(""),
    status: str = Query(""),
    answers: bool = Query(False, description="The marking scheme rather than the paper"),
    limit: int = Query(200, ge=1, le=500),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
):
    """A question set as a document — the paper, or the marking scheme.

    Questions lived in the console as JSON, so judging one meant reading a
    field at a time and nobody ever saw what a learner would be handed: where
    the LaTeX typesets or prints its own backslashes, where a diagram question
    has its figure beside it or does not.

    `answers=false` is the paper and carries no answer anywhere on it.
    """
    from ..services import question_paper

    items = question_dna_service.list_questions(
        grade=grade, subject=subject, strand=strand or None,
        sub_strand=sub_strand or None, status=status or None, limit=limit)

    return HTMLResponse(question_paper.render_html(
        items, grade=grade, subject=subject, strand=strand,
        sub_strand=sub_strand, answers=answers))


@router.get("/paper.pdf")
def questions_paper_pdf(
    grade: str = Query(...),
    subject: str = Query(...),
    sub_strand: str = Query(""),
    strand: str = Query(""),
    status: str = Query(""),
    answers: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> Any:
    """The same document as a file, for a classroom with no screen in it."""
    from fastapi import Response

    from ..services import pdf, question_paper

    items = question_dna_service.list_questions(
        grade=grade, subject=subject, strand=strand or None,
        sub_strand=sub_strand or None, status=status or None, limit=limit)
    document = question_paper.render_html(
        items, grade=grade, subject=subject, strand=strand,
        sub_strand=sub_strand, answers=answers)
    try:
        body = pdf.from_html(document)
    except pdf.PdfUnavailable as exc:
        raise_api_error("MODEL_ENDPOINT_UNAVAILABLE", str(exc))

    stem = "-".join(part.lower().replace(" ", "-") for part in
                    (grade, subject, sub_strand or strand,
                     "marking-scheme" if answers else "paper") if part)
    return Response(
        content=body, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{stem or "paper"}.pdf"'},
    )


@router.get("")
def list_questions(
    grade: str | None = Query(default=None),
    subject: str | None = Query(default=None),
    strand: str | None = Query(default=None),
    sub_strand: str | None = Query(default=None),
    slo_id: str | None = Query(default=None),
    question_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    order: Literal["curriculum", "recent"] = Query(
        default="curriculum",
        description="curriculum walks PP1 to Grade 12; recent is newest first, for review queues",
    ),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    items = question_dna_service.list_questions(
        grade=grade,
        subject=subject,
        strand=strand,
        sub_strand=sub_strand,
        slo_id=slo_id,
        question_type=question_type,
        status=status,
        order=order,
        limit=limit,
        offset=offset,
    )
    return {
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "next_offset": offset + limit if len(items) == limit else None,
        "order": order,
        "items": items,
    }


@router.get("/by-substrand")
def get_questions_by_substrand(
    grade: str = Query(...),
    subject: str = Query(...),
    strand: str = Query(...),
    sub_strand: str = Query(...),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Questions for one sub-strand, filtered in SQL rather than in Python.

    This used to load 500 rows and filter them in a loop, so a sub-strand's
    questions could be missed entirely once the bank grew past that page.
    """
    items = question_dna_service.list_questions(
        grade=grade,
        subject=subject,
        strand=strand,
        sub_strand=sub_strand,
        order="curriculum",
        limit=500,
    )
    return {"total": len(items), "questions": items}


@router.get("/{question_id}/dna")
def get_question_dna(
    question_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    return question_dna_service.get_question(question_id)


@router.put("/{question_id}")
def update_question_content(
    question_id: str,
    payload: QuestionUpdateRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    return question_dna_service.update_question(
        question_id=question_id,
        content=payload.content,
        review_audit=payload.review_audit,
    )


@router.delete("/{question_id}")
def delete_question(
    question_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    return question_dna_service.delete_question(question_id)


@router.post("/{question_id}/action")
def trigger_question_action(
    question_id: str,
    payload: QuestionActionRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    action = payload.action
    if action == "re-create":
        return question_dna_service.action_recreate(question_id)
    elif action == "regenerate":
        return question_dna_service.action_regenerate(question_id)
    elif action == "re-review":
        return question_dna_service.action_rereview(question_id)
    else:
        raise_api_error("SCHEMA_VALIDATION_FAILED", f"Unsupported question action: {action}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# QUESTIONS FACTORY: UNLIMITED MULTI-TYPOLOGY ASSESSMENT ENGINE
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/factory/generate-batch")
def factory_generate_questions_batch(
    payload: QuestionBatchGenerateRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Generates an unlimited batch of publication-grade assessment items across multiple typologies

    grounded in the saved 4-Hour Notes, SVG Diagrams, and Practical Experiments of the sub-strand.
    """
    from ..infra.db import fetch_one
    from ..services.content_type_classifier import classify_content_type
    from ..services.diagram_scene import describe_scene_for_prompt
    from ..services.diagram_binding import resolve_binding
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator
    from ..services.quality_gate import quality_gate_service
    from ..services.question_normalizer import question_normalizer
    from ..services.web_research import web_research_agent

    resolved = pipeline_orchestrator.router.resolve_for_stage("question_generation")
    ct_profile = classify_content_type(payload.subject, payload.grade, payload.sub_strand)

    # 1. Fetch saved sub-strand ground-truth bundle (Notes, Diagrams, Experiments).
    #
    # The grade filter is load-bearing: CBC is a spiral curriculum, so the same
    # sub-strand name recurs across grades with escalating complexity. Matching on
    # subject and sub-strand alone would build Grade 4 questions from Grade 9 notes.
    grade_slug = normalize_grade(payload.grade)

    # Read the ARTIFACTS the stations file, then the older published row.
    #
    # This looked only at `substrand_resources`, which nothing on the board
    # writes — it is filled by the explicit publish-bundle step and by the
    # older pipeline. So a sub-strand whose lesson plan had been written,
    # reviewed, scored and approved, with diagrams drawn and activities
    # authored, had no row at all and questions refused with "No generated
    # content found" about content that was plainly there.
    from ..services import substrand_bundle

    row = substrand_bundle.load(payload.grade, payload.subject, payload.sub_strand)

    if not row:
        from ..services.remedies import missing_upstream

        raise_api_error(
            "SUBSTRAND_BUNDLE_NOT_FOUND",
            f"No generated content found for {payload.subject} · {payload.sub_strand} in "
            f"{grade_label(grade_slug)}. Questions are written from the lesson "
            f"plan and what was made for it, so that content has to exist first.",
            remedy=missing_upstream(payload.grade, payload.subject, "questions",
                                    have={"ingest", "strands", "substrands"}),
        )

    notes_obj = row.get("notes") or {}
    diagrams_obj = row.get("diagrams") or []
    activities_obj = row.get("activities") or {}

    # Questions are the five-layer stage: strand, sub-strand, notes, assets and
    # the teaching skill. The bundle existing is not the same as the bundle
    # being complete — questions written without the diagrams they are supposed
    # to test end up describing visuals nobody produced.
    from ..services.content_lineage import QUESTION
    from ..services.stage_guard import require_context

    lineage = require_context(
        QUESTION,
        grade=payload.grade, subject=payload.subject,
        strand=payload.strand, sub_strand=payload.sub_strand,
        notes_content=notes_obj,
        assets=[d for d in diagrams_obj if isinstance(d, dict)],
        target_hour=payload.target_hour,
    )

    # Bound in the target_hour branch below; read unconditionally during
    # normalisation, so it must exist on every path.
    selected_mod: dict[str, Any] | None = None

    # The blueprint's own SLOs — what coverage is measured against.
    # Normalised on both sides rather than matched against two spellings: the
    # same grade reaches this in four different forms, which is what
    # `grade_sql.clause` exists for.
    from ..services.grade_sql import clause as grade_clause

    blueprint_row = fetch_one(
        f"""
        SELECT slos FROM curriculum_substrands
        WHERE {grade_clause("grade", "grade")}
          AND LOWER(subject) = LOWER(:subject)
          AND LOWER(sub_strand_name) LIKE :ss
        LIMIT 1
        """,
        {"grade": grade_slug, "subject": payload.subject.strip(),
         "ss": f"%{payload.sub_strand.lower().strip()}%"},
    )
    blueprint_slos = (blueprint_row or {}).get("slos") or []

    notes_text = ""
    if notes_obj and isinstance(notes_obj, dict):
        notes_text = f"Title: {notes_obj.get('title', '')}\nAllocated Hours: {notes_obj.get('allocated_hours', 4)}\nIntro: {notes_obj.get('intro', '')}\n\n"
        for idx, hm in enumerate(notes_obj.get("hour_modules") or notes_obj.get("key_concepts") or []):
            h_title = hm.get("hour_title") or hm.get("heading") or f"Hour {idx+1}"
            h_content = hm.get("full_lecture_notes") or hm.get("detailed_exposition") or hm.get("content") or ""
            notes_text += f"--- {h_title} ---\n{h_content}\n"
            for sub in hm.get("subsections") or hm.get("sub_sections") or []:
                notes_text += f"Sub-topic: {sub.get('title')}: {sub.get('content')}\n"
            if hm.get("pedagogical_notes"):
                notes_text += f"PCK Note: {hm.get('pedagogical_notes')}\n"
            if hm.get("common_misconceptions"):
                notes_text += f"Misconception: {hm.get('common_misconceptions')}\n"

    diagrams_text = ""
    if isinstance(diagrams_obj, list):
        for idx, d in enumerate(diagrams_obj):
            if isinstance(d, dict):
                diagrams_text += f"Diagram {idx+1}: {d.get('title') or d.get('diagram_title', '')}\nDescription: {d.get('description', '')}\nConcept: {d.get('concept', '')}\n"

    experiments_text = ""
    if isinstance(activities_obj, dict):
        acts = activities_obj.get("activities") or []
        exps = activities_obj.get("experiments") or []
        for idx, a in enumerate(acts if isinstance(acts, list) else [acts]):
            if isinstance(a, dict):
                experiments_text += f"Activity {idx+1}: {a.get('activity_name', '')}\nType: {a.get('activity_type', '')}\nProcedure: {a.get('procedure', '')}\nSafety: {a.get('safety_precautions', '')}\n"
        for idx, e in enumerate(exps if isinstance(exps, list) else [exps]):
            if isinstance(e, dict):
                experiments_text += f"Experiment {idx+1}: {e.get('experiment_title', '')}\nApparatus: {e.get('apparatus_required', '')}\nMethod: {e.get('methodology_steps', '')}\nObservations: {e.get('expected_observations', '')}\n"

    # 2. Web Research Dossier for Verifiable Research References
    dossier = web_research_agent.research_topic(
        subject=payload.subject,
        strand=payload.strand,
        sub_strand=payload.sub_strand,
        grade=payload.grade,
        topic_type="questions",
    )

    # 2.5 Extract Specific Parent Anchor Context (Hour, Diagram, or Experiment)
    parent_anchor_directive = ""
    target_diag_obj = None
    target_exp_obj = None

    if payload.target_diagram_id:
        for d in (diagrams_obj if isinstance(diagrams_obj, list) else []):
            if isinstance(d, dict) and (d.get("asset_id") == payload.target_diagram_id or d.get("diagram_id") == payload.target_diagram_id):
                target_diag_obj = d
                break
        if target_diag_obj:
            parent_anchor_directive = (
                prompt_store.render(
                    "anchor-diagram", SEED_PROMPT_BLOCKS["anchor-diagram"],
                    describe_scene_for_prompt_target_diag_obj_ge=describe_scene_for_prompt(target_diag_obj.get('scene_document') or {}),
                    target_diag_obj_get_asset_id=target_diag_obj.get('asset_id'),
                    target_diag_obj_get_hour_title_all=target_diag_obj.get('hour_title', 'All'),
                    target_diag_obj_get_micro_concept=target_diag_obj.get('micro_concept'),
                    target_diag_obj_get_title=target_diag_obj.get('title'),
                    target_diag_obj_get_vivid_prompt_or_target_d=target_diag_obj.get('vivid_prompt') or target_diag_obj.get('description'))
            )

    elif payload.target_experiment_id:
        for a in ((activities_obj.get("activities") or []) if isinstance(activities_obj, dict) else []):
            if isinstance(a, dict) and (a.get("activity_id") == payload.target_experiment_id):
                target_exp_obj = a
                break
        if target_exp_obj:
            parent_anchor_directive = (
                prompt_store.render(
                    "anchor-experiment", SEED_PROMPT_BLOCKS["anchor-experiment"],
                    target_exp_obj_get_activity_id=target_exp_obj.get('activity_id'),
                    target_exp_obj_get_activity_name=target_exp_obj.get('activity_name'),
                    target_exp_obj_get_hour_title_all=target_exp_obj.get('hour_title', 'All'),
                    target_exp_obj_get_materials=target_exp_obj.get('materials'),
                    target_exp_obj_get_objective=target_exp_obj.get('objective'),
                    target_exp_obj_get_procedure_steps=target_exp_obj.get('procedure_steps'),
                    target_exp_obj_get_safety_hazards_to_check=target_exp_obj.get('safety_hazards_to_check'))
            )

    elif payload.target_hour:
        hour_idx = int(payload.target_hour)
        h_mods = (notes_obj.get("hour_modules") or notes_obj.get("key_concepts") or []) if isinstance(notes_obj, dict) else []
        selected_mod = h_mods[hour_idx - 1] if (isinstance(h_mods, list) and 0 <= hour_idx - 1 < len(h_mods)) else None
        
        # Find all diagrams and experiments belonging specifically to this hour
        h_diags = [d for d in (diagrams_obj if isinstance(diagrams_obj, list) else []) if isinstance(d, dict) and (d.get("hour_index") == hour_idx or (not d.get("hour_index") and hour_idx == 1))]
        h_diags_str = ""
        for hd in h_diags:
            h_diags_str += f"- Asset [{hd.get('asset_id', 'vis')}]: {hd.get('title')} ({hd.get('micro_concept', '')})\n  Prompt/Description: {hd.get('vivid_prompt') or hd.get('description', '')}\n"

        acts_list = (activities_obj.get("activities") or []) if isinstance(activities_obj, dict) else (activities_obj if isinstance(activities_obj, list) else [])
        h_acts = [a for a in acts_list if isinstance(a, dict) and (a.get("hour_index") == hour_idx or (not a.get("hour_index") and hour_idx == 1))]
        h_acts_str = ""
        for ha in h_acts:
            h_acts_str += f"- Activity [{ha.get('activity_id', 'act')}]: {ha.get('activity_name')} (Objective: {ha.get('objective', '')})\n  Procedure: {ha.get('procedure_steps')}\n"

        if selected_mod:
            h_title = selected_mod.get("hour_title") or selected_mod.get("heading") or f"Hour {hour_idx}"
            h_body = selected_mod.get("full_lecture_notes") or selected_mod.get("detailed_exposition") or selected_mod.get("content") or ""
            parent_anchor_directive = (
                prompt_store.render(
                    "anchor-hour-module", SEED_PROMPT_BLOCKS["anchor-hour-module"],
                    h_acts_str_or_none=h_acts_str or 'None',
                    h_body_2500=h_body[:2500],
                    h_diags_str_or_none=h_diags_str or 'None',
                    h_title=h_title,
                    hour_idx=hour_idx)
            )

    # 3. Assemble Langfuse Context
    context = langfuse_context_service.assemble_agent_context(
        agent_name="question-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars={
            "level": getattr(payload, "level", None) or grade_level(payload.grade),
            "notes_title": getattr(payload, "notes_title", "") or payload.sub_strand,
            "subject_code": payload.subject[:4].upper(),
            "strand": payload.strand,
            "sub_strand": payload.sub_strand,
            "slo_id": payload.slo_id or f"{payload.grade}-{payload.subject[:4].upper()}-01",
            # The OUTCOMES, not only their identifier. The prompt had the ID
            # and never the text, so every question was written against a
            # string — which is what the gate means by "no SLO text on the
            # curriculum link", and why slo congruence never scored.
            "slos": blueprint_slos,
            "notes_summary": str((notes_obj or {}).get("summary")
                                 or (notes_obj or {}).get("intro") or "")[:2_000],
            "diagram_concept": ", ".join(
                str(d.get("diagram_title") or d.get("title") or "")
                for d in (diagrams_obj if isinstance(diagrams_obj, list) else [])[:6]
                if isinstance(d, dict)),
            "experiments_generated": [
                str(e.get("title") or e.get("activity_name") or "")
                for e in ((activities_obj or {}).get("experiments") or [])
                if isinstance(e, dict)],
            "difficulty": payload.difficulty,
            "level_register": register_block(
                    payload.grade,
                    notes=grade_scope_notes(payload.grade, payload.subject),
                ),
        "teacher_band": teacher_block(payload.grade),
        "language_register": language_block(payload.grade),
            # A question whose answer is "3/4" and a marking scheme expecting
            # "$\\frac{3}{4}$" are the same answer written two ways, and one of
            # them is marked wrong. The notation has to be the same in the
            # question as it was in the lesson.
            "notation": notation.for_prompt(payload.subject, grade=payload.grade),
            # What this subject needs that no other does — a balanced equation
            # for Chemistry, a scaled map for Geography, sol-fa for Music.
            "domain_directives": prompt_fragments.compose(
                payload.subject, "questions", payload.grade),
            # What THIS sub-strand's design says a task has to be — the command
            # word it is assessed at, the spread across the ladder, and one
            # worked task at the top of the range.
            "demand_profile": demand_profile.for_prompt(
                payload.grade, payload.subject, payload.strand,
                payload.sub_strand, count=payload.batch_count,
                lesson_hours=str((notes_obj or {}).get("allocated_hours") or "")),
            "faith_scope": faith_prompt_block(payload.subject),
            "content_type_directives": ct_profile.format_for_prompt(),
            "notes_content": notes_text[:3000] or payload.sub_strand,
            "diagram_id": target_diag_obj.get("asset_id", "diag_01") if target_diag_obj else "diag_01",
            "diagram_info": diagrams_text[:1500] or "Visual models available.",
            "activity_info": experiments_text[:1500] or "Practical experiments available.",
        },
    )

    types_str = ", ".join(payload.question_types)
    blooms_str = ", ".join(payload.bloom_levels)

    context.messages.append({
        "role": "user",
        "content": (
            prompt_store.render(
                "questions-factory-directive", SEED_PROMPT_BLOCKS["questions-factory-directive"],
                batch_count=payload.batch_count,
                blooms_str=blooms_str,
                ct_profile_content_type_upper=ct_profile.content_type.upper(),
                ct_profile_example_citation=ct_profile.example_citation(),
                ct_profile_format_for_prompt=ct_profile.format_for_prompt(),
                ct_profile_scenario_seed=ct_profile.scenario_seed(),
                custom_instructions=payload.custom_instructions,
                diagrams_text_2000=diagrams_text[:2000],
                difficulty=payload.difficulty,
                dossier_formatted_context=dossier.formatted_context,
                experiments_text_2000=experiments_text[:2000],
                grade=payload.grade,
                grade_3_upper=payload.grade[:3].upper(),
                notes_text_4000=notes_text[:4000],
                parent_anchor_directive=parent_anchor_directive,
                strand=payload.strand,
                sub_strand=payload.sub_strand,
                subject=payload.subject,
                subject_4_upper=payload.subject[:4].upper(),
                types_str=types_str)
        ),
    })

    resp = llm_client.generate(resolved, context.messages, temperature=0.25)
    raw_questions = resp.content.get("questions", []) if isinstance(resp.content, dict) else (resp.content if isinstance(resp.content, list) else [])

    # Questions written from the figures themselves. A diagram question written
    # from a *description* can only say "study the diagram"; these blank named
    # parts and take the marking scheme from the diagram, so the paper and its
    # answers cannot disagree.
    from ..services.occlusion_questions import author_for_substrand

    def _author(prompt: str) -> dict[str, Any]:
        return llm_client.generate(
            resolved, [{"role": "user", "content": prompt}], temperature=0.2
        ).content or {}

    occlusion = author_for_substrand(
        diagrams_obj,
        generate=_author,
        context={
            "grade": payload.grade, "subject": payload.subject,
            "strand": payload.strand, "sub_strand": payload.sub_strand,
        },
    )
    if occlusion["questions"]:
        raw_questions = list(raw_questions) + occlusion["questions"]
        logger.info("Added %d occlusion question(s): %s", len(occlusion["questions"]), occlusion["summary"])
    audit_report = web_research_agent.perform_quality_audit(resp.content, "questions", dossier)

    # 4. Normalize into the shared QuestionItem contract.
    #
    # Items that cannot satisfy the contract are rejected with a stated reason
    # rather than repaired. A multiple-choice item with no answer key used to
    # silently become "option A"; it now comes back to the operator as a rejection.
    diagrams_list = [
        d for d in (diagrams_obj if isinstance(diagrams_obj, list) else [diagrams_obj])
        if isinstance(d, dict)
    ]

    # Every drawing the sub-strand actually has, not only the visuals on the
    # newest diagram version. The book numbers its figures across the whole
    # lesson, and 1.1 and 1.2 routinely live in different artifact versions —
    # so a question written about the second one had nothing to bind to and
    # came back as "Q5 — diagram_based item ... has no diagram binding".
    try:
        from ..services import lesson_assets

        known = {str(d.get("title") or d.get("diagram_title") or "").strip().lower()
                 for d in diagrams_list}
        for asset in lesson_assets.collect(payload.grade, payload.subject,
                                           payload.sub_strand):
            if asset.get("kind") != "diagram" or not asset.get("svg"):
                continue
            title = str(asset.get("title") or "").strip()
            if not title or title.lower() in known:
                continue
            known.add(title.lower())
            diagrams_list.append({
                "asset_id": asset.get("asset_id") or "",
                "diagram_title": title,
                "alt_text": asset.get("alt") or title,
                "svg_markup": asset.get("svg") or "",
                "storage_url": asset.get("url") or "",
            })
    except Exception as exc:  # noqa: BLE001
        # Questions from the bundle alone beat no questions at all.
        logger.warning("Could not add filed drawings for %s/%s: %s",
                       payload.grade, payload.sub_strand, exc)

    hour_title = ""
    if selected_mod:
        hour_title = str(selected_mod.get("hour_title") or selected_mod.get("heading") or "")
    elif target_diag_obj:
        hour_title = str(target_diag_obj.get("hour_title") or "")
    elif target_exp_obj:
        hour_title = str(target_exp_obj.get("hour_title") or "")

    batch = question_normalizer.normalize_batch(
        raw_questions if isinstance(raw_questions, list) else [],
        grade=payload.grade,
        subject=payload.subject,
        strand=payload.strand,
        sub_strand=payload.sub_strand,
        slo_id=payload.slo_id,
        default_difficulty=payload.difficulty,
        diagram_resolver=lambda raw_q, q_type: resolve_binding(
            raw_q, q_type, diagrams_list, anchored_diagram=target_diag_obj
        ),
        target_hour=payload.target_hour,
        target_hour_title=hour_title,
    )

    normalized_questions = [item.to_public_dict(include_answers=True) for item in batch.items]

    # 4b. The STRUCTURE gate. An item can be well written, correctly cited and
    #     curriculum-aligned and still be unusable — two options, a
    #     "structured" question with one part, four marks for a calculation
    #     with no scheme to award them against. A review queue of 250 items a
    #     day is only worth having if the malformed ones never reach a person,
    #     so they are held here with the reason and the fix.
    from ..services import question_structure, question_throughput

    structure = question_structure.check_all(
        normalized_questions, grade=payload.grade, subject=payload.subject,
        strand=payload.strand, sub_strand=payload.sub_strand)
    held = {v["question_id"] for v in structure["verdicts"] if v["blocked"]}

    # Repair before discarding. Each held item was generated and paid for, and
    # is usually wrong in exactly one nameable way — two options, a structured
    # item with one part, marks with no scheme to award them against. At 500 a
    # day the difference between repairing and regenerating is the difference
    # between recovering the work and buying it twice.
    repair: dict[str, Any] = {}
    if held:
        from ..services import content_repair

        try:
            mended = content_repair.repair_questions(
                normalized_questions, structure["verdicts"],
                grade=payload.grade, subject=payload.subject,
                design_extract=notes_text[:4_000], resolved=resolved)
            repair = mended.to_dict()
            if mended.repaired:
                by_id = {str(m.get("question_id") or ""): m for m in mended.repaired}
                normalized_questions = [by_id.get(str(q.get("question_id") or ""), q)
                                        for q in normalized_questions]
                # Re-measured, because the gate below reports what is FILED and
                # a repaired item is a different item.
                structure = question_structure.check_all(
                    normalized_questions, grade=payload.grade, subject=payload.subject,
        strand=payload.strand, sub_strand=payload.sub_strand)
                held = {v["question_id"] for v in structure["verdicts"] if v["blocked"]}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Repair pass failed for %s: %s", payload.sub_strand, exc)

    if held:
        for verdict in structure["verdicts"]:
            if verdict["blocked"]:
                batch.rejected.append({
                    "question_id": verdict["question_id"],
                    "reason": "; ".join(f["says"] for f in verdict["findings"]
                                        if f["severity"] == question_structure.BLOCKS),
                    "fix": "; ".join(f["fix"] for f in verdict["findings"]
                                     if f["severity"] == question_structure.BLOCKS),
                    "stage": "structure",
                })
        normalized_questions = [q for q in normalized_questions
                                if str(q.get("question_id") or "") not in held]

    # 4b-ii. The BATCH judgement: whether this set is pitched at the grade at
    #     all. No per-item rule can see it — every item can be well formed and
    #     the whole paper still be four years too easy, which is exactly what a
    #     reviewer found in Grade 9 integers ("this is Grade 3/4 Math").
    #
    #     It does not discard anything. Every item was generated and paid for,
    #     an easy opener is legitimate, and a set that is merely thin needs
    #     MORE items rather than fewer. It is filed against the batch with the
    #     shape the grade's own paper uses, and the items stay drafts — which
    #     is what `draft` is for: filed, countable, and not signed off.
    if structure.get("batch_blocked"):
        demand = structure.get("demand") or {}
        batch.rejected.append({
            "question_id": "",
            "reason": demand.get("says") or "",
            "fix": demand.get("fix") or "",
            "stage": "demand",
        })
        question_throughput.record_batch(
            question_throughput.BLOCKED, [{"question_id": "batch"}],
            grade=payload.grade, subject=payload.subject, strand=payload.strand,
            sub_strand=payload.sub_strand, detail={"gate": "demand"})

    # 4c. Counted per ITEM, not per run: the target is written in questions,
    #     and a run of 4 would otherwise look like a run of 400.
    question_throughput.record_batch(
        question_throughput.GENERATED, normalized_questions,
        grade=payload.grade, subject=payload.subject, strand=payload.strand,
        sub_strand=payload.sub_strand,
        detail={"model": resolved.model})
    if held:
        question_throughput.record_batch(
            question_throughput.BLOCKED,
            [{"question_id": qid} for qid in held],
            grade=payload.grade, subject=payload.subject, strand=payload.strand,
            sub_strand=payload.sub_strand, detail={"gate": "structure"})

    # 5. Quality gate over the validated items
    gate_result = quality_gate_service.run_layer_gate(
        layer_name="questions",
        content=normalized_questions,
        blueprint={"slos": blueprint_slos, "notes_body": notes_text},
        content_type_profile=ct_profile,
        custom_instructions=payload.custom_instructions,
    )

    # 5b. SAVED, with the gate's own verdict filed beside the items.
    #
    #     Generation returned its items in the response and wrote them
    #     nowhere: persistence lived only in `/factory/approve-batch`, a
    #     separate call nothing made automatically. So a run could produce four
    #     good items, report them on screen, and leave the question bank empty —
    #     which is why coverage read "questions 0 / 345" and the paper printed
    #     "this set has no questions in it" after a successful run.
    #
    #     Saved as `draft`: filed, countable and readable, but not approved.
    #     Approval is a person's signature and this is not it.
    saved: list[dict[str, Any]] = []
    if normalized_questions:
        try:
            saved = question_dna_service.save_batch_questions(
                grade=payload.grade, subject=payload.subject,
                strand=payload.strand, sub_strand=payload.sub_strand,
                questions=normalized_questions, status="draft",
                gate_result=gate_result.to_dict() if hasattr(gate_result, "to_dict") else None,
            )
        except Exception as exc:  # noqa: BLE001
            # The items are in the response either way; losing the file is bad
            # and losing the run as well is worse.
            logger.warning("Generated %d item(s) for %s but could not save them: %s",
                           len(normalized_questions), payload.sub_strand, exc)

    return {
        "saved": len(saved),
        "repair": repair,
        "sub_strand": payload.sub_strand,
        "grade": grade_slug,
        "requested_count": payload.batch_count,
        "batch_count": len(batch.items),
        "questions": normalized_questions,
        "rejected": batch.rejected,
        "rejected_count": len(batch.rejected),
        "typology_mix": batch.mix(),
        "usage": resp.usage,
        "model": resp.model,
        "content_type": ct_profile.to_dict(),
        "research_dossier": dossier.to_dict(),
        "quality_audit": audit_report.to_dict(),
        "quality_gate": gate_result.to_dict(),
    }


@router.post("/factory/generate-single")
def factory_generate_single_question(
    payload: QuestionSingleGenerateRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Generates or refines a single targeted question of any specific typology."""
    batch_req = QuestionBatchGenerateRequest(
        grade=payload.grade,
        subject=payload.subject,
        strand=payload.strand,
        sub_strand=payload.sub_strand,
        slo_id=payload.slo_id,
        batch_count=1,
        question_types=[payload.question_type],
        bloom_levels=[payload.bloom_level],
        difficulty=payload.difficulty,
        custom_instructions=f"Target Concept: {payload.concept_target}. {payload.custom_instructions}",
    )
    return factory_generate_questions_batch(batch_req)


@router.post("/factory/author-from-diagram")
def factory_author_questions_from_diagram(
    payload: DiagramAuthoredRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Write questions *from* a diagram rather than matching one to a question.

    Blanks part of the figure, then asks only about the gaps. The marking scheme
    is taken from the diagram, so a model that mislabels a part cannot put a
    wrong answer into the answer key — it is corrected and the correction is
    reported.
    """
    from ..infra.db import fetch_one
    from ..services.diagram_question_agent import (
        OcclusionNotPossible,
        author_questions_from_diagram,
    )
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator

    row = fetch_one(
        """
        SELECT diagram_id, title, svg_markup, scene_document, storage_url, grade, subject
        FROM diagram_registry WHERE diagram_id = :did
        """,
        {"did": payload.diagram_id},
    )
    if not row:
        raise_api_error("NOT_FOUND", f"No diagram with id {payload.diagram_id}")

    diagram = {
        "asset_id": row["diagram_id"],
        "diagram_id": row["diagram_id"],
        "title": row.get("title", ""),
        "svg_markup": diagram_svg.svg_for(row),
        "scene_document": row.get("scene_document") or {},
        "storage_url": row.get("storage_url", ""),
    }

    resolved = pipeline_orchestrator.router.resolve_for_stage("question_generation")

    def _generate(prompt: str) -> dict[str, Any]:
        messages = [{"role": "user", "content": prompt + (
            f"\n\nADDITIONAL INSTRUCTIONS: {payload.custom_instructions}"
            if payload.custom_instructions else ""
        )}]
        resp = llm_client.generate(resolved, messages, temperature=0.2)
        return resp.content if isinstance(resp.content, dict) else {}

    try:
        result = author_questions_from_diagram(
            diagram,
            generate=_generate,
            mode=payload.mode,
            max_blanks=payload.max_blanks,
            part_ids=payload.part_ids or None,
            region_id=payload.region_id,
            context={
                "grade": payload.grade or row.get("grade", ""),
                "subject": payload.subject or row.get("subject", ""),
                "strand": payload.strand,
                "sub_strand": payload.sub_strand,
            },
        )
    except OcclusionNotPossible as exc:
        # A diagram with nothing safe to blank is a content problem, not a
        # server fault — say which diagram and why.
        raise_api_error("UNPROCESSABLE_DIAGRAM", str(exc))

    corrections = [
        note
        for question in result["questions"]
        for note in question.get("answer_corrections", [])
    ]

    return {
        "diagram_id": payload.diagram_id,
        "diagram_title": diagram["title"],
        "mode": result["occlusion"]["mode"],
        "questions": result["questions"],
        "rejected": result["rejected"],
        "occlusion": result["occlusion"],
        "removed_facts": result["removed_facts"],
        "paper_svg": result["paper_svg"],
        "answer_svg": result["answer_svg"],
        "answer_corrections": corrections,
        "counts": {
            "accepted": len(result["questions"]),
            "rejected": len(result["rejected"]),
            "answers_corrected": len(corrections),
        },
    }


@router.post("/factory/approve-batch")
def factory_approve_question_batch(
    payload: QuestionBatchApproveRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Save and approve a reviewed batch, minting unique IDs and DNA lineage."""
    saved_records = question_dna_service.save_batch_questions(
        grade=payload.grade,
        subject=payload.subject,
        strand=payload.strand,
        sub_strand=payload.sub_strand,
        questions=payload.questions,
        status=payload.status,
        gate_result=payload.quality_gate,
    )

    scored = [r["mean_score"] for r in saved_records if r.get("mean_score") is not None]
    return {
        "status": payload.status,
        "total_approved": len(saved_records),
        "mean_quality_score": round(sum(scored) / len(scored), 4) if scored else None,
        "saved_records": saved_records,
    }


@router.post("/factory/export-exam")
def factory_export_exam_paper(
    payload: QuestionExportExamRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Render a draft paper and marking scheme from in-memory questions.

    Diagrams are resolved from the registry and inlined. Previously this built
    markdown that never referenced the diagram fields, so a diagram question
    printed with no diagram.

    For a paper that must be reproducible later, compose it through
    ``POST /api/v1/exams`` instead — that freezes the question versions.
    """
    from ..infra.db import fetch_all
    from ..services.exam_renderer import render_html, render_markdown

    grade_slug = normalize_grade(payload.grade)

    diagram_ids = {
        str((q.get("diagram") or {}).get("diagram_id"))
        for q in payload.questions
        if isinstance(q.get("diagram"), dict) and (q.get("diagram") or {}).get("diagram_id")
    }
    diagrams: dict[str, dict[str, Any]] = {}
    if diagram_ids:
        rows = fetch_all(
            """
            SELECT diagram_id, title, svg_markup, storage_url, scene_document
            FROM diagram_registry WHERE diagram_id = ANY(:ids)
            """,
            {"ids": list(diagram_ids)},
        )
        # The markup lives in MinIO; the row carries the link to it.
        diagrams = {r["diagram_id"]: diagram_svg.with_svg(r) for r in rows}

    missing_visuals = [
        q.get("display_label") or q.get("question_id")
        for q in payload.questions
        if isinstance(q.get("diagram"), dict)
        and str((q.get("diagram") or {}).get("diagram_id")) not in diagrams
    ]

    exam = {
        "title": payload.exam_title,
        "grade": grade_slug,
        "subject": payload.subject,
        "strand": payload.strand,
        "sub_strand": payload.sub_strand,
        "time_allowed": payload.time_allowed,
        "total_marks": payload.total_marks,
        "instructions": [],
    }

    markdown = render_markdown(exam, payload.questions, diagrams)

    return {
        "exam_title": payload.exam_title,
        "grade": grade_slug,
        "grade_label": grade_label(grade_slug),
        "total_questions": len(payload.questions),
        "diagrams_embedded": len(diagrams),
        "questions_missing_visuals": missing_visuals,
        "question_paper_markdown": markdown["question_paper"],
        "marking_scheme_markdown": markdown["marking_scheme"],
        "printable_html": render_html(exam, payload.questions, diagrams, include_answers=True),
    }
