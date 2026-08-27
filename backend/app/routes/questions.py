from __future__ import annotations

import json as json_lib
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..errors import raise_api_error
from ..services.auth import AuthContext, require_roles
from ..services.level_register import register_block
from ..services.faith_scope import prompt_block as faith_prompt_block
from ..services.grade_scope import notes_for as grade_scope_notes
from ..services.grade_order import grade_label, grade_ordinal, normalize_grade
from ..services.question_dna import question_dna_service

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
    alt_grade = grade_slug.replace("grade-", "")
    clean_subj = payload.subject.lower().strip()
    clean_ss = payload.sub_strand.lower().strip()

    row = fetch_one(
        """
        SELECT * FROM substrand_resources
        WHERE LOWER(curriculum->>'subject') = :subject
          AND LOWER(curriculum->>'sub_strand') LIKE :ss
          AND LOWER(curriculum->>'grade') IN (:grade, :alt_grade)
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        {"subject": clean_subj, "ss": f"%{clean_ss}%", "grade": grade_slug, "alt_grade": alt_grade},
    )

    if not row:
        raise_api_error(
            "SUBSTRAND_BUNDLE_NOT_FOUND",
            f"No generated content found for {payload.subject} · {payload.sub_strand} in "
            f"{grade_label(grade_slug)}. Generate the notes, diagrams and activities first — "
            f"questions must be grounded in this grade's own content.",
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
    blueprint_row = fetch_one(
        """
        SELECT slos FROM curriculum_substrands
        WHERE grade IN (:grade, :alt_grade)
          AND LOWER(subject) = LOWER(:subject)
          AND LOWER(sub_strand_name) LIKE :ss
        LIMIT 1
        """,
        {"grade": grade_slug, "alt_grade": alt_grade, "subject": payload.subject.strip(), "ss": f"%{clean_ss}%"},
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
                f"\n=== 🎯 TARGET PARENT ANCHOR: SPECIFIC VECTOR DIAGRAM (MANDATORY FOCUS) ===\n"
                f"Asset ID: {target_diag_obj.get('asset_id')}\n"
                f"Title: {target_diag_obj.get('title')}\n"
                f"Hour Module: {target_diag_obj.get('hour_title', 'All')}\n"
                f"Micro-Concept: {target_diag_obj.get('micro_concept')}\n"
                f"Visual Specification: {target_diag_obj.get('vivid_prompt') or target_diag_obj.get('description')}\n"
                # A truncated slice of raw SVG cannot tell a model which part_id
                # to name. The parts catalogue can, and is far shorter.
                f"{describe_scene_for_prompt(target_diag_obj.get('scene_document') or {})}\n"
                f"CRITICAL RULE: ALL GENERATED QUESTIONS MUST DIRECTLY TEST THIS ATTACHED DIAGRAM ({target_diag_obj.get('title')}). "
                f"Set 'diagram_ref': '{target_diag_obj.get('asset_id')}'. Include sub-questions asking to label specific parts, explain flow arrows, or deduce conclusions from this exact graphic.\n"
                f"To ask about specific parts, set 'diagram_part_ids' to part_id values from the catalogue above — "
                f"never invent one. To ask about a section only, set 'diagram_region_id' to a region_id listed above.\n"
            )

    elif payload.target_experiment_id:
        for a in ((activities_obj.get("activities") or []) if isinstance(activities_obj, dict) else []):
            if isinstance(a, dict) and (a.get("activity_id") == payload.target_experiment_id):
                target_exp_obj = a
                break
        if target_exp_obj:
            parent_anchor_directive = (
                f"\n=== 🧪 TARGET PARENT ANCHOR: SPECIFIC PRACTICAL EXPERIMENT / CSL PROTOCOL ===\n"
                f"Activity ID: {target_exp_obj.get('activity_id')}\n"
                f"Title: {target_exp_obj.get('activity_name')}\n"
                f"Hour Module: {target_exp_obj.get('hour_title', 'All')}\n"
                f"Objective: {target_exp_obj.get('objective')}\n"
                f"Apparatus & Materials: {target_exp_obj.get('materials')}\n"
                f"Procedure Steps: {target_exp_obj.get('procedure_steps')}\n"
                f"Safety Protocols: {target_exp_obj.get('safety_hazards_to_check')}\n"
                f"CRITICAL RULE: ALL GENERATED QUESTIONS MUST DIRECTLY TEST THIS PRACTICAL INVESTIGATION. "
                f"Provide empirical observed data tables and multi-part questions (a)-(d) evaluating data analysis, scientific mechanisms, and farmer remediation recommendations.\n"
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
                f"\n=== ⏰ TARGET PARENT ANCHOR: LESSON HOUR MODULE {hour_idx} ({h_title}) ===\n"
                f"Hour Title: {h_title}\n"
                f"Hour Lesson Notes Content:\n{h_body[:2500]}\n\n"
                f"Hour {hour_idx} Visual Assets / Diagrams Available:\n{h_diags_str or 'None'}\n\n"
                f"Hour {hour_idx} Practical Activities / Lab Experiments Available:\n{h_acts_str or 'None'}\n\n"
                f"CRITICAL RULE: ALL GENERATED QUESTIONS MUST DIRECTLY TEST THE CONCEPTS, DIAGRAMS, AND EXPERIMENTS TAUGHT IN THIS SPECIFIC HOUR {hour_idx}.\n"
                f"If testing a diagram or experiment from this hour, set 'diagram_ref' to that asset's ID and evaluate its specific mechanisms and data.\n"
            )

    # 3. Assemble Langfuse Context
    context = langfuse_context_service.assemble_agent_context(
        agent_name="question-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars={
            "subject_code": payload.subject[:4].upper(),
            "strand": payload.strand,
            "sub_strand": payload.sub_strand,
            "slo_id": payload.slo_id or f"{payload.grade}-{payload.subject[:4].upper()}-01",
            "difficulty": payload.difficulty,
            "level_register": register_block(
                    payload.grade,
                    notes=grade_scope_notes(payload.grade, payload.subject),
                ),
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
            f"{ct_profile.format_for_prompt()}\n\n"
            f"{dossier.formatted_context}\n\n"
            f"=== 🎯 HIGH-THROUGHPUT QUESTIONS FACTORY ASSESSMENT DIRECTIVE ===\n"
            f"Subject: {payload.subject} ({payload.grade}) [Content Type: {ct_profile.content_type.upper()}]\n"
            f"Strand: {payload.strand} ➔ Sub-strand: {payload.sub_strand}\n"
            f"Target Batch Count: EXACTLY {payload.batch_count} DIVERSE ASSESSMENT ITEMS\n"
            f"Mandated Question Typologies: {types_str}\n"
            f"Cognitive Bloom Progression: {blooms_str}\n"
            f"Difficulty Index: {payload.difficulty} (0.10 to 0.99)\n\n"
            f"{parent_anchor_directive}\n\n"
            f"=== 📖 GROUND TRUTH KNOWLEDGE BASE (FROM SAVED FOUNDATION LAYERS) ===\n"
            f"LAYER 1 MASTER LESSON NOTES & CITATIONS:\n{notes_text[:4000]}\n\n"
            f"LAYER 2 DIAGRAMS & VISUAL REPOSITORIES:\n{diagrams_text[:2000]}\n\n"
            f"LAYER 3 EXPERIMENTS, LAB PRACTICUMS & SAFETY:\n{experiments_text[:2000]}\n\n"
            f"CRITICAL ASSESSMENT DESIGN RULES (ZERO HALLUCINATION & FULL DNA):\n"
            f"1. YOU MUST GENERATE EXACTLY {payload.batch_count} INDEPENDENT, COMPLETE QUESTIONS.\n"
            f"2. Cover a balanced mix of requested typologies with maximum academic rigor:\n"
            f"   - 'multiple_choice': 4 plausible distractors, correct flag, and deep distractor diagnostic rationale for every option.\n"
            f"   - 'diagram_based': Questions directly referencing apparatus, anatomical/physical parts, or flowcharts from Layer 2. Set 'diagram_ref' to the matching diagram asset ID or title. Provide structured questions that test labeling, interpretation of flow arrows, functional roles of components, and troubleshooting abnormal readings.\n"
            f"   - 'experiment_based': MUST NOT be generic or superficial (e.g., NEVER just say 'evaluate your experiment').\n"
            f"     MUST formulate an AUTHENTIC, RIGOROUS LABORATORY PRACTICUM / FIELDWORK INVESTIGATION:\n"
            f"     * Explicit Experimental Context & Setup: Describe the full investigation as Kenyan learners would actually conduct it, situated in {ct_profile.scenario_seed()}. Draw the apparatus, materials and procedure from this subject's own practice as described in the content-type directives above.\n"
            f"     * Practical Protocol & Empirical Data Table: Provide step-by-step apparatus setup (e.g., 10g dried soil, 50ml distilled water, Universal Indicator / calibrated pH meter, 0.1M HCl titrant) and an observed readings table (initial pH, drops of acid added, final pH, buffer capacity, precipitation).\n"
            f"     * Structured Multi-Part Inquiries ('structured_parts'):\n"
            f"       - Part (a): Data Analysis & Interpretation (evaluate differences and calculate values from observed data).\n"
            f"       - Part (b): Scientific Mechanisms & Principles (explain chemical buffering, ion exchange, or biological reactions).\n"
            f"       - Part (c): Application & Community Relevance (concrete recommendations an informed practitioner in this subject would make for a Kenyan community, using the verified subject data supplied above).\n"
            f"       - Part (d): Experimental Controls & Safety Protocols (controlled variables, safety PPE precautions for handling reagents, and sources of experimental error).\n"
            f"     * Exhaustive Model Answer & Scoring Keys: Provide a multi-paragraph model answer covering all scenarios thoroughly, and a detailed point-by-point marking scheme with M1, A1, B1 marks.\n"
            f"   - 'structured_scenario': Real-world scenario-based problems set in authentic Kenyan counties with sub-parts (a), (b), (c) and marks per part.\n"
            f"   - 'quantitative_calculation': Mathematical / statistical calculations (e.g. GDP contribution percentage, agricultural lime buffer tonnage, soil loss equation) with full formula steps.\n"
            f"   - 'extended_essay': Synthesis, environmental critique, or ASTGS 2019-2029 policy evaluation.\n"
            f"   - 'assertion_reason': Statement (A) and Reason (R) causality diagnostics.\n"
            f"3. IN-TEXT RESEARCH CITATIONS: Every question's 'provenance_citation' MUST cite a source from the Permitted Citation Sources list in the directives above. Do not cite sources belonging to other subjects.\n"
            f"4. Include comprehensive Step-by-Step 'marking_scheme' and 4-Level 'kicd_rubric' (Exceeding, Meeting, Approaching, Below Expectation) for every item.\n\n"
            f"RETURN JSON FORMAT MATCHING:\n"
            f"{{\n"
            f'  "sub_strand": "{payload.sub_strand}",\n'
            f'  "batch_count": {payload.batch_count},\n'
            f'  "questions": [\n'
            f'    {{\n'
            f'      "question_id": "Q1",\n'
            f'      "universal_id": "{payload.grade[:3].upper()}-{payload.subject[:4].upper()}-01",\n'
            f'      "question_type": "multiple_choice | diagram_based | experiment_based | structured_scenario | quantitative_calculation | extended_essay | assertion_reason",\n'
            f'      "bloom_level": "Recall | Understanding | Application | Analysis | Evaluation | Creation",\n'
            f'      "difficulty_index": {payload.difficulty},\n'
            f'      "max_marks": 5,\n'
            f'      "estimated_time_mins": 5,\n'
            f'      "micro_concept": "<specific sub-topic or competency tested>",\n'
            f'      "target_slo": "<specific learning outcome>",\n'
            f'      "stimulus_context": "<authentic Kenyan scenario appropriate to THIS subject, with any data table the question needs>",\n'
            f'      "question_text": "<clear, rigorous question prompt detailing instructions and inquiry>",\n'
            f'      "diagram_ref": "diag_01",\n'
            f'      "options": [\n'
            f'        {{"id": "A", "text": "...", "is_correct": false, "distractor_rationale": "Why plausible but incorrect..."}},\n'
            f'        {{"id": "B", "text": "...", "is_correct": true, "distractor_rationale": "Correct answer mechanism..."}},\n'
            f'        {{"id": "C", "text": "...", "is_correct": false, "distractor_rationale": "..."}},\n'
            f'        {{"id": "D", "text": "...", "is_correct": false, "distractor_rationale": "..."}}\n'
            f'      ],\n'
            f'      "correct_answer": "B",\n'
            f'      "structured_parts": [\n'
            f'        {{"part_id": "(a)", "sub_question": "...", "marks": 2, "model_answer": "..."}},\n'
            f'        {{"part_id": "(b)", "sub_question": "...", "marks": 3, "model_answer": "..."}},\n'
            f'        {{"part_id": "(c)", "sub_question": "...", "marks": 2, "model_answer": "..."}}\n'
            f'      ],\n'
            f'      "model_answer": "<exhaustive multi-paragraph model response with scientific explanation covering all scenarios>",\n'
            f'      "marking_scheme": "<step-by-step scoring keys: M1 for method, A1 for accuracy, B1 for explanation>",\n'
            f'      "kicd_rubric": {{\n'
            f'        "exceeding": "Demonstrates exhaustive mastery and links concept to macro-environmental systems.",\n'
            f'        "meeting": "Accurately demonstrates expected competence with correct technical explanations.",\n'
            f'        "approaching": "Partially demonstrates concept with minor inaccuracies or incomplete rationale.",\n'
            f'        "below": "Fails to demonstrate concept and requires structured instructional remediation."\n'
            f'      }},\n'
            f'      "provenance_citation": "{ct_profile.example_citation()} — Linked to Layer 1 Lesson Notes"\n'
            f'    }}\n'
            f'  ]\n'
            f"}}\n\n"
            f"ADDITIONAL DIRECTIVES: {payload.custom_instructions}"
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

    # 5. Quality gate over the validated items
    gate_result = quality_gate_service.run_layer_gate(
        layer_name="questions",
        content=normalized_questions,
        blueprint={"slos": blueprint_slos, "notes_body": notes_text},
        content_type_profile=ct_profile,
        custom_instructions=payload.custom_instructions,
    )

    return {
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
        "svg_markup": row.get("svg_markup", ""),
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
            SELECT diagram_id, title, svg_markup, scene_document
            FROM diagram_registry WHERE diagram_id = ANY(:ids)
            """,
            {"ids": list(diagram_ids)},
        )
        diagrams = {r["diagram_id"]: r for r in rows}

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
