from __future__ import annotations

import json as json_lib
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..errors import raise_api_error
from ..services.auth import AuthContext, require_roles
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


class QuestionBatchApproveRequest(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    questions: list[dict[str, Any]]
    status: str = "approved"


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
    question_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    items = question_dna_service.list_questions(
        grade=grade,
        subject=subject,
        strand=strand,
        question_type=question_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"total": len(items), "items": items}


@router.get("/by-substrand")
def get_questions_by_substrand(
    grade: str = Query(...),
    subject: str = Query(...),
    strand: str = Query(...),
    sub_strand: str = Query(...),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    clean_grade = grade.lower().replace("grade-", "").strip()
    clean_subj = subject.lower().strip()
    clean_ss = sub_strand.lower().strip()

    items = question_dna_service.list_questions(limit=500)
    filtered = []
    for q in items:
        cl = q.get("curriculum_link") or {}
        q_grade = str(cl.get("grade", "")).lower().replace("grade-", "").strip()
        q_subj = str(cl.get("subject", "")).lower().strip()
        q_ss = str(cl.get("sub_strand", "")).lower().strip()
        if (
            (q_grade == clean_grade or not clean_grade)
            and (q_subj == clean_subj or clean_subj in q_subj)
            and (q_ss == clean_ss or clean_ss in q_ss)
        ):
            filtered.append(q)

    return {"total": len(filtered), "questions": filtered}


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
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator
    from ..services.quality_gate import quality_gate_service
    from ..services.web_research import web_research_agent

    resolved = pipeline_orchestrator.router.resolve_for_stage("question_generation")
    ct_profile = classify_content_type(payload.subject, payload.grade, payload.sub_strand)

    # 1. Fetch saved sub-strand ground-truth bundle (Notes, Diagrams, Experiments)
    clean_grade = payload.grade.lower().replace("grade-", "").strip()
    clean_subj = payload.subject.lower().strip()
    clean_ss = payload.sub_strand.lower().strip()

    row = fetch_one(
        """
        SELECT * FROM substrand_resources
        WHERE LOWER(curriculum->>'subject') = :subject
          AND LOWER(curriculum->>'sub_strand') LIKE :ss
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        {"subject": clean_subj, "ss": f"%{clean_ss}%"},
    )

    notes_obj = row.get("notes") if row else {}
    diagrams_obj = row.get("diagrams") if row else []
    activities_obj = row.get("activities") if row else {}

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
            "content_type_directives": ct_profile.format_for_prompt(),
            "notes_content": notes_text[:3000] or payload.sub_strand,
            "diagram_id": "diag_01",
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
            f"=== 📖 GROUND TRUTH KNOWLEDGE BASE (FROM SAVED FOUNDATION LAYERS) ===\n"
            f"LAYER 1 MASTER LESSON NOTES & CITATIONS:\n{notes_text[:4000]}\n\n"
            f"LAYER 2 DIAGRAMS & VISUAL REPOSITORIES:\n{diagrams_text[:2000]}\n\n"
            f"LAYER 3 EXPERIMENTS, LAB PRACTICUMS & SAFETY:\n{experiments_text[:2000]}\n\n"
            f"CRITICAL ASSESSMENT DESIGN RULES (ZERO HALLUCINATION & FULL DNA):\n"
            f"1. YOU MUST GENERATE EXACTLY {payload.batch_count} INDEPENDENT, COMPLETE QUESTIONS.\n"
            f"2. Cover a balanced mix of requested typologies:\n"
            f"   - 'multiple_choice': 4 plausible distractors, correct flag, distractor diagnostic rationale for every option.\n"
            f"   - 'diagram_based': Questions directly referencing apparatus, anatomical/physical parts, or flowcharts from Layer 2.\n"
            f"   - 'experiment_based': Questions testing laboratory methodology, controlled variables, expected data readings, and safety PPE from Layer 3.\n"
            f"   - 'structured_scenario': Scenario-based problems set in authentic Kenyan counties (e.g. Uasin Gishu, Nakuru, Naivasha, Kericho) with sub-parts (a), (b), (c) and marks per part.\n"
            f"   - 'quantitative_calculation': Mathematical / statistical calculations (e.g. GDP contribution percentage, agricultural lime buffer tonnage, soil loss equation) with full formula steps.\n"
            f"   - 'extended_essay': Synthesis, environmental critique, or ASTGS 2019-2029 policy evaluation.\n"
            f"   - 'assertion_reason': Statement (A) and Reason (R) causality diagnostics.\n"
            f"3. IN-TEXT RESEARCH CITATIONS: Every question's 'provenance_citation' MUST cite verifiable sources (e.g. [KNBS Economic Survey 2024], [KALRO Technical Bulletin 2023], [KICD DTE Design 2024]).\n"
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
            f'      "max_marks": 2,\n'
            f'      "estimated_time_mins": 3,\n'
            f'      "micro_concept": "<specific sub-topic or competency tested>",\n'
            f'      "target_slo": "<specific learning outcome>",\n'
            f'      "stimulus_context": "<authentic Kenyan agricultural/scientific scenario background>",\n'
            f'      "question_text": "<clear, rigorous question prompt>",\n'
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
            f'        {{"part_id": "(b)", "sub_question": "...", "marks": 3, "model_answer": "..."}}\n'
            f'      ],\n'
            f'      "model_answer": "<comprehensive model response with scientific explanation>",\n'
            f'      "marking_scheme": "<step-by-step scoring keys: M1 for method, A1 for accuracy, B1 for explanation>",\n'
            f'      "kicd_rubric": {{\n'
            f'        "exceeding": "Demonstrates exhaustive mastery and links concept to macro-environmental systems.",\n'
            f'        "meeting": "Accurately demonstrates expected competence with correct technical explanations.",\n'
            f'        "approaching": "Partially demonstrates concept with minor inaccuracies or incomplete rationale.",\n'
            f'        "below": "Fails to demonstrate concept and requires structured instructional remediation."\n'
            f'      }},\n'
            f'      "provenance_citation": "[KNBS Economic Survey 2024] / [KALRO Technical Bulletin 2023] — Linked to Layer 1 Lesson Notes"\n'
            f'    }}\n'
            f'  ]\n'
            f"}}\n\n"
            f"ADDITIONAL DIRECTIVES: {payload.custom_instructions}"
        ),
    })

    resp = llm_client.generate(resolved, context.messages, temperature=0.25)
    raw_questions = resp.content.get("questions", []) if isinstance(resp.content, dict) else (resp.content if isinstance(resp.content, list) else [])
    audit_report = web_research_agent.perform_quality_audit(resp.content, "questions", dossier)

    # 4. Normalize All Generated Question Typologies
    normalized_questions = []
    if isinstance(raw_questions, list):
        for idx, q in enumerate(raw_questions):
            if not isinstance(q, dict):
                continue
            q_id = q.get("question_id") or f"Q_{idx+1}"
            u_id = q.get("universal_id") or f"{payload.grade[:3].upper()}-{payload.subject[:4].upper()}-{q.get('target_slo', 'SLO-01')}-{idx+1}"
            q_type = q.get("question_type") or "multiple_choice"

            # Normalize Options
            opts = q.get("options")
            correct = str(q.get("correct_answer") or "").strip()
            distractors = q.get("distractor_explanations") or {}

            norm_opts = []
            if isinstance(opts, dict):
                for k, v in opts.items():
                    opt_text = v.get("text", str(v)) if isinstance(v, dict) else str(v)
                    is_corr = (k.upper() == correct.upper()) or (isinstance(v, dict) and v.get("is_correct", False))
                    rationale = distractors.get(k) or (v.get("distractor_rationale") if isinstance(v, dict) else "")
                    norm_opts.append({
                        "id": k,
                        "text": opt_text,
                        "is_correct": is_corr,
                        "distractor_rationale": rationale,
                    })
            elif isinstance(opts, list):
                for o_idx, item in enumerate(opts):
                    if isinstance(item, dict):
                        opt_id = item.get("id") or chr(65 + o_idx)
                        is_corr = item.get("is_correct", False) or (opt_id.upper() == correct.upper())
                        norm_opts.append({
                            "id": opt_id,
                            "text": item.get("text", str(item)),
                            "is_correct": is_corr,
                            "distractor_rationale": item.get("distractor_rationale") or distractors.get(opt_id, ""),
                        })
                    else:
                        opt_id = chr(65 + o_idx)
                        norm_opts.append({
                            "id": opt_id,
                            "text": str(item),
                            "is_correct": opt_id.upper() == correct.upper(),
                            "distractor_rationale": "",
                        })

            # Normalize Rubric
            rubric = q.get("kicd_rubric") or q.get("marking_guide") or {}
            if not rubric and q.get("marking_scheme"):
                rubric = {
                    "exceeding": "Exceeds expected outcome with thorough analytical synthesis.",
                    "meeting": str(q.get("marking_scheme")),
                    "approaching": "Partially demonstrates concept with guidance required.",
                    "below": "Requires clinical remediation.",
                }

            normalized_questions.append({
                "question_id": q_id,
                "universal_id": u_id,
                "question_type": q_type,
                "bloom_level": q.get("bloom_level", "Application"),
                "difficulty_index": q.get("difficulty_index", payload.difficulty),
                "max_marks": q.get("max_marks", 2),
                "estimated_time_mins": q.get("estimated_time_mins", 3),
                "micro_concept": q.get("micro_concept", payload.sub_strand),
                "target_slo": q.get("target_slo", payload.slo_id or "SLO-01"),
                "stimulus_context": q.get("stimulus_context", ""),
                "question_text": q.get("question_text", ""),
                "diagram_ref": q.get("diagram_ref", ""),
                "options": norm_opts if norm_opts else None,
                "correct_answer": correct or (norm_opts[0]["id"] if norm_opts else None),
                "structured_parts": q.get("structured_parts"),
                "model_answer": q.get("model_answer") or q.get("explanation", ""),
                "marking_scheme": q.get("marking_scheme", ""),
                "marking_guide": rubric,
                "provenance_citation": q.get("provenance_citation") or "[KNBS Economic Survey 2024 / KALRO Bulletin 2023] — Linked to Layer 1 Lesson Notes",
                "approved": False,
            })

    # 5. Quality Gate
    gate_result = quality_gate_service.run_layer_gate(
        layer_name="questions",
        content=normalized_questions,
        blueprint={},
        content_type_profile=ct_profile,
        custom_instructions=payload.custom_instructions,
    )

    return {
        "sub_strand": payload.sub_strand,
        "batch_count": len(normalized_questions),
        "questions": normalized_questions,
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


@router.post("/factory/approve-batch")
def factory_approve_question_batch(
    payload: QuestionBatchApproveRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Saves and approves a batch of reviewed questions into question_dna with full DNA lineage."""
    saved_records = question_dna_service.save_batch_questions(
        grade=payload.grade,
        subject=payload.subject,
        strand=payload.strand,
        sub_strand=payload.sub_strand,
        questions=payload.questions,
        status=payload.status,
    )
    return {
        "status": "approved",
        "total_approved": len(saved_records),
        "saved_records": saved_records,
    }


@router.post("/factory/export-exam")
def factory_export_exam_paper(
    payload: QuestionExportExamRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Formats the questions into a publication-ready Kenya National Examination Paper and Marking Scheme."""
    paper_md = f"# {payload.exam_title}\n"
    paper_md += f"**Subject:** {payload.subject} | **Grade/Level:** {payload.grade.upper()} | **Time Allowed:** {payload.time_allowed}\n"
    paper_md += f"**Strand:** {payload.strand} ➔ **Sub-strand:** {payload.sub_strand}\n"
    paper_md += f"**Total Marks:** {payload.total_marks} Marks\n\n"
    paper_md += "---\n\n### INSTRUCTIONS TO CANDIDATES:\n"
    paper_md += "1. Answer ALL questions in the spaces provided.\n"
    paper_md += "2. Candidates should check the question paper to ensure all questions are printed.\n"
    paper_md += "3. Candidates should answer the questions in English.\n\n---\n\n## SECTION A: ASSESSMENT QUESTIONS\n\n"

    scheme_md = f"# MARKING SCHEME & 4-TIER EVALUATION GUIDE\n"
    scheme_md += f"**Examination:** {payload.exam_title}\n"
    scheme_md += f"**Subject:** {payload.subject} ({payload.grade.upper()}) — {payload.sub_strand}\n\n---\n\n"

    for idx, q in enumerate(payload.questions):
        q_num = idx + 1
        q_type = q.get("question_type", "Question").replace("_", " ").upper()
        marks = q.get("max_marks", 2)
        stimulus = q.get("stimulus_context")
        q_text = q.get("question_text", "")

        paper_md += f"#### Question {q_num} [{q_type}] ({marks} Marks)\n"
        if stimulus:
            paper_md += f"> *{stimulus}*\n\n"
        paper_md += f"{q_text}\n\n"

        if q.get("options"):
            for opt in q["options"]:
                paper_md += f"- **{opt.get('id', '')}.** {opt.get('text', '')}\n"
            paper_md += "\n"

        if q.get("structured_parts"):
            for part in q["structured_parts"]:
                paper_md += f"**{part.get('part_id', '')}** {part.get('sub_question', '')} *({part.get('marks', 1)} Marks)*\n\n"

        paper_md += "---\n\n"

        # Scheme entry
        scheme_md += f"### Question {q_num} Scoring Key ({marks} Marks)\n"
        if q.get("correct_answer"):
            scheme_md += f"**Correct Answer:** `{q.get('correct_answer')}`\n\n"
        scheme_md += f"**Model Answer / Solution:**\n{q.get('model_answer', '')}\n\n"
        scheme_md += f"**Step-by-Step Marks Breakdown:**\n{q.get('marking_scheme', '')}\n\n"
        scheme_md += f"**Provenance Citation:** *{q.get('provenance_citation', '')}*\n\n"

        rubric = q.get("marking_guide") or q.get("kicd_rubric") or {}
        if rubric:
            scheme_md += "| Level | Performance Indicator |\n|---|---|\n"
            scheme_md += f"| **Exceeding** | {rubric.get('exceeding', '')} |\n"
            scheme_md += f"| **Meeting** | {rubric.get('meeting', '')} |\n"
            scheme_md += f"| **Approaching** | {rubric.get('approaching', '')} |\n"
            scheme_md += f"| **Below** | {rubric.get('below', '')} |\n\n"

        scheme_md += "---\n\n"

    return {
        "exam_title": payload.exam_title,
        "question_paper_markdown": paper_md,
        "marking_scheme_markdown": scheme_md,
        "total_questions": len(payload.questions),
    }

