from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..infra.db import fetch_all, fetch_one
from ..services.artifact_dna import artifact_dna_service
from ..services.auth import AuthContext, require_roles
from ..services.curriculum_extractor import curriculum_extractor

router = APIRouter(prefix="/api/v1/curriculum", tags=["Curriculum Intelligence & DNA"])


class IngestRawCurriculumRequest(BaseModel):
    raw_payload: dict[str, Any] | None = None
    raw_text: str | None = None
    title: str | None = None
    source: str | None = None


@router.post("/ingest-raw")
def ingest_raw_curriculum(
    payload: IngestRawCurriculumRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Ingests unclarified raw dataset items or extracted PDF text, parses structured curriculum design,
    saves it to PostgreSQL, syncs to Langfuse, and generates downstream agent prompt guidelines."""
    data: dict[str, Any] = {}
    if payload.raw_payload:
        data = payload.raw_payload
    elif payload.raw_text:
        data = {
            "output": payload.raw_text,
            "title": payload.title or "Curriculum Document",
            "source": payload.source or "manual_upload",
        }

    return curriculum_extractor.ingest_raw_curriculum(data)


@router.post("/sync-langfuse-datasets")
def sync_langfuse_datasets(
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Fetches all raw dataset items directly from Langfuse (e.g. cbc/datasets),
    runs the AI curriculum structuring & dynamic prompt generation on each,
    and returns all structured blueprints."""
    from ..services.langfuse_context import langfuse_context_service

    raw_items = langfuse_context_service.fetch_raw_datasets_from_langfuse()

    # If no datasets in Langfuse yet, seed the default cbc/datasets with sample Agriculture DTE design
    if not raw_items:
        sample_payload = {
            "title": "Diploma in Teacher Education Agriculture Curriculum Design",
            "source": "Mobile_JS_Browser_Injector",
            "file_id": "1uRWxOaKYWZ-ZPgD-VEvYOTXDh62oy6Zd",
            "captured_at": "2026-08-23T07:57:54.268Z",
            "output": (
                "DIPLOMA IN TEACHER EDUCATION\nPRE-PRIMARY AND PRIMARY\nAGRICULTURE\nCURRICULUM DESIGN 2024\n\n"
                "ESSENCE STATEMENT\nKenya is mainly dependent on an agro-based economy that requires competent manpower for sustainable development.\n\n"
                "GENERAL LEARNING OUTCOMES\n1. Develop Agricultural knowledge, skills, values and attitudes.\n"
                "2. Apply knowledge and pedagogical skills to rear domestic animals.\n\n"
                "STRAND 1.0 AGRICULTURE AND ENVIRONMENT\n"
                "1.1 Overview of Agriculture (4 hours)\n"
                "By the end of the sub strand, the teacher trainee should be able to:\n"
                "a) discuss the importance of Agriculture in Kenya,\n"
                "b) relate the key natural resources to Agricultural production in Kenya,\n"
                "Suggested Learning Experiences\n"
                "• Through discussion and literature review, develop the meaning and importance of Agriculture.\n"
                "• Research on key natural resources that influence Agricultural production.\n"
                "Suggested Key Inquiry Questions\n"
                "How does curriculum in primary education relate to Agriculture productivity in Kenya?\n"
                "Core competencies to be developed:\nCritical thinking and problem solving.\nValues:\nPatriotism as teacher trainees take initiative.\n\n"
                "1.4 Soil Composition (4 hours)\n"
                "By the end of the sub strand, the teacher trainee should be able to:\n"
                "a) investigate components of a garden soil sample,\n"
                "b) relate components of soil to its productivity in Agriculture,\n"
                "Suggested Learning Experiences\n"
                "• Carry out experiments to investigate presence of components (air, water, organic matter) of a garden soil sample.\n"
                "• Prepare compost manure using heap and pit methods.\n"
                "Suggested Key Inquiry Questions\nWhat makes a quality fertile soil?"
            ),
        }
        try:
            # Upload to Langfuse
            langfuse_context_service.upload_dataset_item("cbc/datasets", sample_payload)
        except Exception:
            pass
        raw_items = [sample_payload]

    results = []
    for item in raw_items:
        try:
            res = curriculum_extractor.ingest_raw_curriculum(item)
            results.append(res)
        except Exception as exc:
            results.append({"status": "error", "item_id": item.get("item_id"), "error": str(exc)})

    return {
        "fetched_from_langfuse_count": len(raw_items),
        "structured_blueprints": results,
    }


@router.get("/raw-datasets")
def list_raw_datasets(
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Fetches all raw dataset items from Langfuse (e.g. cbc/datasets) to display in the UI for processing."""
    from ..services.langfuse_context import langfuse_context_service

    raw_items = langfuse_context_service.fetch_raw_datasets_from_langfuse()

    sample_dte = {
        "dataset_name": "cbc/datasets",
        "item_id": "1uRWxOaKYWZ-ZPgD-VEvYOTXDh62oy6Zd",
        "url": "https://drive.google.com/file/d/1uRWxOaKYWZ-ZPgD-VEvYOTXDh62oy6Zd/view",
        "title": "Diploma in Teacher Education Agriculture Curriculum Design (2024)",
        "source": "Mobile_JS_Browser_Injector",
        "file_id": "1uRWxOaKYWZ-ZPgD-VEvYOTXDh62oy6Zd",
        "captured_at": "2026-08-23T07:57:54.268Z",
        "output": (
            "DIPLOMA IN TEACHER EDUCATION\nPRE-PRIMARY AND PRIMARY\nAGRICULTURE\nCURRICULUM DESIGN 2024\n\n"
            "ESSENCE STATEMENT\nKenya is mainly dependent on an agro-based economy that requires competent manpower for sustainable development.\n\n"
            "GENERAL LEARNING OUTCOMES\n1. Develop Agricultural knowledge, skills, values and attitudes.\n"
            "2. Apply knowledge and pedagogical skills to rear domestic animals.\n\n"
            "STRAND 1.0 AGRICULTURE AND ENVIRONMENT\n"
            "1.1 Overview of Agriculture (4 hours)\n"
            "By the end of the sub strand, the teacher trainee should be able to:\n"
            "a) discuss the importance of Agriculture in Kenya,\n"
            "b) relate the key natural resources to Agricultural production in Kenya,\n"
            "Suggested Learning Experiences\n"
            "• Through discussion and literature review, develop the meaning and importance of Agriculture.\n"
            "• Research on key natural resources that influence Agricultural production.\n"
            "Suggested Key Inquiry Questions\n"
            "How does curriculum in primary education relate to Agriculture productivity in Kenya?\n"
            "Core competencies to be developed:\nCritical thinking and problem solving.\nValues:\nPatriotism as teacher trainees take initiative.\n\n"
            "1.4 Soil Composition (4 hours)\n"
            "By the end of the sub strand, the teacher trainee should be able to:\n"
            "a) investigate components of a garden soil sample,\n"
            "b) relate components of soil to its productivity in Agriculture,\n"
            "Suggested Learning Experiences\n"
            "• Carry out experiments to investigate presence of components (air, water, organic matter) of a garden soil sample.\n"
            "• Prepare compost manure using heap and pit methods.\n"
            "Suggested Key Inquiry Questions\nWhat makes a quality fertile soil?"
        ),
    }

    if not raw_items:
        raw_items = [sample_dte]

    # Check which datasets are already processed in DB
    processed_designs = fetch_all("SELECT design_id, subject, grade, level, review_status, updated_at FROM curriculum_designs")
    processed_map = {d["design_id"]: d for d in processed_designs}

    enriched = []
    for item in raw_items:
        txt = item.get("output") or item.get("text") or ""
        item_id = item.get("item_id") or item.get("file_id") or "raw_ds"
        enriched.append({
            "item_id": item_id,
            "dataset_name": item.get("dataset_name", "cbc/datasets"),
            "title": item.get("title") or f"Curriculum Dataset {item_id[:8]}",
            "source": item.get("source", "Langfuse Dataset"),
            "url": item.get("url", ""),
            "captured_at": item.get("captured_at", ""),
            "text_length": len(txt),
            "output_preview": txt[:300] + ("..." if len(txt) > 300 else ""),
            "raw_payload": item,
        })

    return {"raw_datasets": enriched, "count": len(enriched)}


class BlueprintDecisionRequest(BaseModel):
    design_id: str
    decision: str  # "accept" | "reject"
    notes: str = ""


@router.post("/blueprint-decision")
def set_blueprint_decision(
    payload: BlueprintDecisionRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Human reviewer accepts or rejects the AI-generated curriculum blueprint."""
    return curriculum_extractor.set_blueprint_decision(
        design_id=payload.design_id,
        decision=payload.decision,
        notes=payload.notes,
    )


@router.get("/designs")
def list_curriculum_designs(
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    designs = fetch_all(
        """
        SELECT cd.design_id, cd.subject, cd.subject_code, cd.grade, cd.level,
               cd.essence_statement, cd.general_learning_outcomes, cd.metadata,
               cd.review_status, cd.human_review_notes, cd.created_at, cd.updated_at,
               COUNT(cs.id) as substrand_count
        FROM curriculum_designs cd
        LEFT JOIN curriculum_substrands cs ON cd.design_id = cs.design_id
        GROUP BY cd.design_id, cd.review_status, cd.human_review_notes
        ORDER BY cd.updated_at DESC
        """
    )
    return {"designs": designs}


@router.get("/substrands")
def list_curriculum_substrands(
    grade: str | None = None,
    subject: str | None = None,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    conditions = ["1=1"]
    params: dict[str, Any] = {}

    if grade:
        conditions.append("grade = :grade")
        params["grade"] = grade
    if subject:
        conditions.append("LOWER(subject) = LOWER(:subject)")
        params["subject"] = subject

    query = f"""
        SELECT id, design_id, grade, subject, strand_id, strand_name,
               sub_strand_id, sub_strand_name, allocated_hours, slos,
               learning_experiences, key_inquiry_questions, core_competencies,
               values, assessment_rubrics, required_diagrams, experiments,
               pedagogical_guidance, prompt_context, created_at
        FROM curriculum_substrands
        WHERE {' AND '.join(conditions)}
        ORDER BY strand_id ASC, sub_strand_id ASC
    """
    rows = fetch_all(query, params)
    return {"substrands": rows, "count": len(rows)}


@router.get("/dna/{artifact_id}")
def get_artifact_dna(
    artifact_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    cert = artifact_dna_service.get_dna_certificate(artifact_id)
    if not cert:
        return {"found": False, "message": f"No DNA certificate found for ID '{artifact_id}'."}
    return {"found": True, "certificate": cert}


@router.get("/dna/lineage/{dna_id}")
def get_dna_lineage(
    dna_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Returns the unbroken Merkle chain of custody from artifact/bundle up to the raw source dataset."""
    lineage = artifact_dna_service.get_complete_lineage(dna_id)
    return {
        "dna_id": dna_id,
        "lineage_depth": len(lineage),
        "chain_of_custody": lineage,
        "is_unbroken": len(lineage) > 0 and lineage[-1].get("artifact_type") == "dataset",
    }


@router.get("/dna/by-slo/{slo_id}")
def get_dna_by_slo(
    slo_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    certs = artifact_dna_service.list_dnas_for_slo(slo_id)
    return {"slo_id": slo_id, "certificates": certs, "count": len(certs)}


# ── Content Factory & Interactive Playground Endpoints ───────────────────────

class FactoryGenerateNotesRequest(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    slo_id: str = ""
    level: str = "Basic Education"
    custom_instructions: str = ""


class FactoryGenerateDiagramRequest(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    concept: str = ""
    notes_title: str = ""
    custom_instructions: str = ""


class FactoryGenerateActivityRequest(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    notes_title: str = ""
    custom_instructions: str = ""


class FactoryGenerateQuestionsRequest(BaseModel):
    grade: str
    subject: str
    subject_code: str = "CORE"
    strand: str
    sub_strand: str
    slo_id: str = ""
    difficulty: float = 0.65
    notes_summary: str = ""
    diagram_title: str = ""
    custom_instructions: str = ""


class FactorySaveBundleRequest(BaseModel):
    bundle_id: str
    grade: str
    subject: str
    strand: str
    sub_strand: str
    level: str = "Basic Education"
    notes: dict[str, Any] = {}
    diagram: dict[str, Any] = {}
    activities: list[Any] = []
    experiments: list[Any] = []
    questions: list[Any] = []
    review_status: str = "draft_in_factory"
    human_notes: str = ""


@router.post("/factory/generate-notes")
def factory_generate_notes(
    payload: FactoryGenerateNotesRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator

    resolved = pipeline_orchestrator.router.resolve_for_stage("notes_generation")
    template_vars = {
        "level": payload.level,
        "strand": payload.strand,
        "sub_strand": payload.sub_strand,
        "slo_id": payload.slo_id or f"{payload.grade}-{payload.subject[:3]}-01",
        "custom_instructions": payload.custom_instructions,
    }
    context = langfuse_context_service.assemble_agent_context(
        agent_name="note-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars=template_vars,
    )
    if payload.custom_instructions:
        context.messages.append({
            "role": "user",
            "content": f"ADDITIONAL REFINEMENT INSTRUCTIONS: {payload.custom_instructions}",
        })

    resp = llm_client.generate(resolved, context.messages, temperature=0.2)
    return {"notes": resp.content, "usage": resp.usage, "model": resp.model}


@router.post("/factory/generate-diagram")
def factory_generate_diagram(
    payload: FactoryGenerateDiagramRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    from ..services.diagram_dedup import diagram_deduplicator
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator

    resolved = pipeline_orchestrator.router.resolve_for_stage("diagram_generation")
    concept_name = payload.concept or f"{payload.sub_strand} model"
    context = langfuse_context_service.assemble_agent_context(
        agent_name="diagram-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars={
            "concept": concept_name,
            "notes_title": payload.notes_title or payload.sub_strand,
        },
    )
    if payload.custom_instructions:
        context.messages.append({
            "role": "user",
            "content": f"ADDITIONAL SVG DIAGRAM REFINEMENT INSTRUCTIONS: {payload.custom_instructions}",
        })

    resp = llm_client.generate(resolved, context.messages, temperature=0.1)
    svg_markup = resp.content.get("diagram_svg", "<svg xmlns='http://www.w3.org/2000/svg'></svg>")
    accessibility = resp.content.get("accessibility", {})

    dedup = diagram_deduplicator.deduplicate_and_store(
        svg_str=svg_markup,
        diagram_title=resp.content.get("diagram_title", concept_name),
        alt_text=accessibility.get("alt_text", ""),
        tactile_description=accessibility.get("tactile_description", ""),
        metadata={"grade": payload.grade, "subject": payload.subject, "strand": payload.strand},
    )

    diagram_data = {
        "diagram_id": dedup.diagram_id,
        "diagram_title": dedup.diagram_title,
        "diagram_svg": dedup.diagram_svg,
        "diagram_hash": dedup.diagram_hash,
        "storage_url": dedup.storage_url,
        "dedup_status": dedup.dedup_status,
        "accessibility": {
            "alt_text": dedup.alt_text,
            "tactile_description": dedup.tactile_description,
        },
    }
    return {"diagram": diagram_data, "usage": resp.usage, "model": resp.model}


@router.post("/factory/generate-activity")
def factory_generate_activity(
    payload: FactoryGenerateActivityRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator

    resolved = pipeline_orchestrator.router.resolve_for_stage("activity_generation")
    context = langfuse_context_service.assemble_agent_context(
        agent_name="activity-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars={
            "strand": payload.strand,
            "sub_strand": payload.sub_strand,
            "notes_title": payload.notes_title or payload.sub_strand,
        },
    )
    if payload.custom_instructions:
        context.messages.append({
            "role": "user",
            "content": f"ADDITIONAL EXPERIMENT & SAFETY REFINEMENT INSTRUCTIONS: {payload.custom_instructions}",
        })

    resp = llm_client.generate(resolved, context.messages, temperature=0.25)
    return {"activity": resp.content, "usage": resp.usage, "model": resp.model}


@router.post("/factory/generate-questions")
def factory_generate_questions(
    payload: FactoryGenerateQuestionsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator

    resolved = pipeline_orchestrator.router.resolve_for_stage("question_generation")
    context = langfuse_context_service.assemble_agent_context(
        agent_name="question-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars={
            "subject_code": payload.subject_code,
            "strand": payload.strand,
            "sub_strand": payload.sub_strand,
            "slo_id": payload.slo_id or f"{payload.grade}-{payload.subject_code}-01",
            "difficulty": payload.difficulty,
            "notes_summary": payload.notes_summary,
            "diagram_concept": payload.diagram_title,
        },
    )
    if payload.custom_instructions:
        context.messages.append({
            "role": "user",
            "content": f"ADDITIONAL QUESTION & RUBRIC REFINEMENT INSTRUCTIONS: {payload.custom_instructions}",
        })

    resp = llm_client.generate(resolved, context.messages, temperature=0.2)
    return {"questions": resp.content.get("questions", []), "usage": resp.usage, "model": resp.model}


@router.post("/factory/save-bundle")
def factory_save_bundle(
    payload: FactorySaveBundleRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    from ..infra.db import execute, to_json

    curr_dict = {
        "grade": payload.grade,
        "subject": payload.subject,
        "level": payload.level,
        "strand": payload.strand,
        "sub_strand": payload.sub_strand,
    }

    execute(
        """
        INSERT INTO substrand_resources (
            bundle_id, curriculum, notes, diagrams, activities, questions, review_audit, status, updated_at
        )
        VALUES (
            :bundle_id, CAST(:curriculum AS jsonb), CAST(:notes AS jsonb),
            CAST(:diagrams AS jsonb), CAST(:activities AS jsonb),
            CAST(:questions AS jsonb), CAST(:review_audit AS jsonb),
            :status, NOW()
        )
        ON CONFLICT (bundle_id) DO UPDATE SET
            curriculum = EXCLUDED.curriculum,
            notes = EXCLUDED.notes,
            diagrams = EXCLUDED.diagrams,
            activities = EXCLUDED.activities,
            questions = EXCLUDED.questions,
            review_audit = EXCLUDED.review_audit,
            status = EXCLUDED.status,
            updated_at = NOW()
        """,
        {
            "bundle_id": payload.bundle_id,
            "curriculum": to_json(curr_dict),
            "notes": to_json(payload.notes),
            "diagrams": to_json([payload.diagram] if payload.diagram else []),
            "activities": to_json({"activities": payload.activities, "experiments": payload.experiments}),
            "questions": to_json(payload.questions),
            "review_audit": to_json({"status": payload.review_status, "human_notes": payload.human_notes}),
            "status": payload.review_status,
        },
    )

    return {"status": "saved", "bundle_id": payload.bundle_id, "review_status": payload.review_status}


class FactoryGenerateStrandsRequest(BaseModel):
    grade: str
    subject: str
    level: str = "Basic Education"
    essence_statement: str = ""
    custom_instructions: str = ""


class FactoryGenerateSubstrandsRequest(BaseModel):
    grade: str
    subject: str
    strand_name: str
    strand_id: str = "1.0"
    level: str = "Basic Education"
    essence_statement: str = ""
    general_learning_outcomes: list[str] = []
    custom_instructions: str = ""
    design_id: str = ""


class FactorySaveSubstrandsRequest(BaseModel):
    grade: str
    subject: str
    strand_name: str
    strand_id: str = "1.0"
    design_id: str = ""
    substrands: list[dict[str, Any]]


@router.post("/factory/generate-strands")
def factory_generate_strands(
    payload: FactoryGenerateStrandsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Generates the top-level strands for a subject using Langfuse prompt management and subject design context."""
    from ..infra.db import query_one
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator

    essence_statement = payload.essence_statement
    level = payload.level

    if not essence_statement:
        row = query_one(
            """
            SELECT essence_statement, level
            FROM curriculum_designs
            WHERE (grade = :grade OR grade = :alt_grade) AND LOWER(subject) = LOWER(:subject)
            ORDER BY updated_at DESC LIMIT 1
            """,
            {"grade": payload.grade, "alt_grade": payload.grade.replace("grade-", ""), "subject": payload.subject},
        )
        if row:
            essence_statement = row.get("essence_statement") or ""
            level = row.get("level") or level

    resolved = pipeline_orchestrator.router.resolve_for_stage("notes_generation")
    context = langfuse_context_service.assemble_agent_context(
        agent_name="strand-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars={
            "level": level,
            "essence_statement": essence_statement,
            "custom_instructions": payload.custom_instructions,
        },
    )
    if payload.custom_instructions:
        context.messages.append({
            "role": "user",
            "content": f"ADDITIONAL STRAND INSTRUCTIONS: {payload.custom_instructions}",
        })

    resp = llm_client.generate(resolved, context.messages, temperature=0.2)
    strands = resp.content.get("strands", []) if isinstance(resp.content, dict) else []
    return {"subject": payload.subject, "grade": payload.grade, "strands": strands, "usage": resp.usage, "model": resp.model}


@router.post("/factory/generate-substrands")
def factory_generate_substrands(
    payload: FactoryGenerateSubstrandsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Generates detailed sub-strands with SLOs, hours, diagrams, experiments, and hazard protocols using curriculum design blueprint context."""
    from ..infra.db import query_one
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator

    essence_stmt = payload.essence_statement
    gen_outcomes = payload.general_learning_outcomes
    level = payload.level

    # Look up previous curriculum design context from database if not supplied
    row = query_one(
        """
        SELECT design_id, subject, level, essence_statement, general_learning_outcomes
        FROM curriculum_designs
        WHERE (grade = :grade OR grade = :alt_grade) AND LOWER(subject) = LOWER(:subject)
        ORDER BY updated_at DESC LIMIT 1
        """,
        {"grade": payload.grade, "alt_grade": payload.grade.replace("grade-", ""), "subject": payload.subject},
    )
    if row:
        if not essence_stmt:
            essence_stmt = row.get("essence_statement") or ""
        if not gen_outcomes:
            gen_outcomes = row.get("general_learning_outcomes") or []
        if level == "Basic Education" and row.get("level"):
            level = row.get("level")

    outcomes_str = "\n".join([f"- {o}" for o in gen_outcomes]) if gen_outcomes else "Standard KICD BECF Outcomes."

    resolved = pipeline_orchestrator.router.resolve_for_stage("notes_generation")
    context = langfuse_context_service.assemble_agent_context(
        agent_name="substrand-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars={
            "level": level,
            "essence_statement": essence_stmt or f"Comprehensive curriculum design for {payload.subject} ({payload.grade}).",
            "general_learning_outcomes": outcomes_str,
            "strand": payload.strand_name,
            "custom_instructions": payload.custom_instructions,
        },
    )

    # Ensure explicit design context is present in messages
    context.messages.append({
        "role": "user",
        "content": (
            f"CURRICULUM BLUEPRINT CONTEXT FOR {payload.subject.upper()}:\n"
            f"Level: {level}\n"
            f"Essence Statement: {essence_stmt}\n"
            f"General Outcomes:\n{outcomes_str}\n\n"
            f"TARGET STRAND TO GENERATE SUB-STRANDS FOR: {payload.strand_name}\n"
            f"ADDITIONAL DIRECTIVES: {payload.custom_instructions}"
        ),
    })

    resp = llm_client.generate(resolved, context.messages, temperature=0.2)
    sub_strands = resp.content.get("sub_strands", []) if isinstance(resp.content, dict) else []
    return {
        "subject": payload.subject,
        "grade": payload.grade,
        "strand_name": payload.strand_name,
        "sub_strands": sub_strands,
        "essence_statement_used": essence_stmt,
        "usage": resp.usage,
        "model": resp.model,
    }


@router.post("/factory/save-substrands")
def factory_save_substrands(
    payload: FactorySaveSubstrandsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Saves generated sub-strands for a strand to PostgreSQL database."""
    from ..infra.db import execute, to_json

    saved_count = 0
    design_id = payload.design_id or f"cd_{payload.grade}_{payload.subject.lower()[:4]}"

    for ss in payload.substrands:
        sub_id = str(ss.get("sub_strand_id") or ss.get("id") or "1.1")
        sub_name = str(ss.get("sub_strand_name") or ss.get("name") or sub_id)
        hours = str(ss.get("allocated_hours") or ss.get("hours") or "4 hours")
        slos = ss.get("slos", [])
        learning_exp = ss.get("learning_experiences", [])
        kiqs = ss.get("key_inquiry_questions", [])
        competencies = ss.get("core_competencies", [])
        vals = ss.get("values", [])
        rubrics = ss.get("assessment_rubrics", {})
        diagrams = ss.get("required_diagrams", [])
        experiments = ss.get("experiments", [])
        safety_hazards = ss.get("safety_hazards_to_check", [])

        prompt_context = {
            "subject": payload.subject,
            "grade": payload.grade,
            "strand": payload.strand_name,
            "sub_strand": sub_name,
            "allocated_hours": hours,
            "slos": slos,
            "kiqs": kiqs,
            "diagram_guidance": diagrams,
            "experiment_guidance": experiments,
            "safety_hazard_criteria": safety_hazards,
        }

        execute(
            """
            INSERT INTO curriculum_substrands (
                design_id, grade, subject, strand_id, strand_name, sub_strand_id, sub_strand_name,
                allocated_hours, slos, learning_experiences, key_inquiry_questions,
                core_competencies, values, assessment_rubrics, required_diagrams,
                experiments, pedagogical_guidance, prompt_context, updated_at
            )
            VALUES (
                :design_id, :grade, :subject, :strand_id, :strand_name, :sub_strand_id, :sub_strand_name,
                :allocated_hours, CAST(:slos AS jsonb), CAST(:learning_exp AS jsonb),
                CAST(:kiqs AS jsonb), CAST(:competencies AS jsonb), CAST(:values AS jsonb),
                CAST(:rubrics AS jsonb), CAST(:diagrams AS jsonb), CAST(:experiments AS jsonb),
                CAST(:pedagogical AS jsonb), CAST(:prompt_context AS jsonb), NOW()
            )
            ON CONFLICT (grade, subject, strand_name, sub_strand_name) DO UPDATE SET
                design_id = EXCLUDED.design_id,
                strand_id = EXCLUDED.strand_id,
                sub_strand_id = EXCLUDED.sub_strand_id,
                allocated_hours = EXCLUDED.allocated_hours,
                slos = EXCLUDED.slos,
                learning_experiences = EXCLUDED.learning_experiences,
                key_inquiry_questions = EXCLUDED.key_inquiry_questions,
                core_competencies = EXCLUDED.core_competencies,
                values = EXCLUDED.values,
                assessment_rubrics = EXCLUDED.assessment_rubrics,
                required_diagrams = EXCLUDED.required_diagrams,
                experiments = EXCLUDED.experiments,
                pedagogical_guidance = EXCLUDED.pedagogical_guidance,
                prompt_context = EXCLUDED.prompt_context,
                updated_at = NOW()
            """,
            {
                "design_id": design_id,
                "grade": payload.grade,
                "subject": payload.subject,
                "strand_id": payload.strand_id,
                "strand_name": payload.strand_name,
                "sub_strand_id": sub_id,
                "sub_strand_name": sub_name,
                "allocated_hours": hours,
                "slos": to_json([{"id": f"{payload.grade}-{payload.subject[:3]}-{sub_id}-{idx+1}", "text": s} if isinstance(s, str) else s for idx, s in enumerate(slos)]),
                "learning_exp": to_json(learning_exp),
                "kiqs": to_json(kiqs),
                "competencies": to_json(competencies),
                "values": to_json(vals),
                "rubrics": to_json(rubrics),
                "diagrams": to_json(diagrams),
                "experiments": to_json(experiments),
                "pedagogical": to_json({"safety_hazards_to_check": safety_hazards}),
                "prompt_context": to_json(prompt_context),
            },
        )
        saved_count += 1

    return {"status": "saved", "saved_count": saved_count, "strand_name": payload.strand_name}

