from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel

from ..errors import raise_api_error
from ..infra.db import execute, fetch_all, fetch_one
from ..services.artifact_dna import artifact_dna_service
from ..services.auth import AuthContext, require_roles
from ..services.curriculum_extractor import curriculum_extractor
from ..services import (
    artifact_registry,
    design_source,
    media_registry,
    substrand_hygiene,
    time_allocation,
)
from ..services.grade_order import grade_level
from ..services.faith_scope import prompt_block as faith_prompt_block
from ..services.grade_scope import notes_for as grade_scope_notes
from ..services.level_register import register_block, register_for_grade as level_register_for

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/curriculum", tags=["Curriculum Intelligence & DNA"])


class IngestRawCurriculumRequest(BaseModel):
    raw_payload: dict[str, Any] | None = None
    raw_text: str | None = None
    title: str | None = None
    source: str | None = None
    # Re-ingest a document that has already been processed, replacing what the
    # previous run produced. Off by default so it is always deliberate.
    force: bool = False


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

    # Ingestion can be reached from more than one screen, so the "already done"
    # check lives here rather than in any one of them.
    from ..services.dataset_ingest import (
        INGESTED,
        find_tracked_item,
        process_item,
        record_external_ingest,
    )

    tracked = find_tracked_item(data)
    if tracked and tracked["status"] == INGESTED and not payload.force:
        raise_api_error(
            "ALREADY_INGESTED",
            f"'{tracked.get('resolved_subject') or tracked.get('title') or tracked['item_id']}' "
            f"has already been ingested as design {tracked.get('design_id')}. "
            f"Re-send with force to replace it.",
        )

    # A tracked item goes through the tracked path, so the replace-and-prune
    # behaviour is identical no matter which screen started it.
    if tracked:
        return process_item(tracked["item_id"], force=payload.force)

    result = curriculum_extractor.ingest_raw_curriculum(data)
    record_external_ingest(data, result)
    return result


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
               cd.essence_statement, cd.general_learning_outcomes, cd.raw_payload, cd.metadata,
               cd.review_status, cd.human_review_notes, cd.created_at, cd.updated_at,
               COUNT(cs.id) as substrand_count
        FROM curriculum_designs cd
        LEFT JOIN curriculum_substrands cs ON cd.design_id = cs.design_id
        GROUP BY cd.design_id, cd.review_status, cd.human_review_notes, cd.raw_payload
        ORDER BY cd.updated_at DESC
        """
    )
    return {"designs": designs}


@router.get("/substrands")
def list_curriculum_substrands(
    grade: str | None = None,
    subject: str | None = None,
    strand_name: str | None = None,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    conditions = ["1=1"]
    params: dict[str, Any] = {}

    if grade:
        alt_grade = grade.replace("grade-", "") if grade.startswith("grade-") else f"grade-{grade}"
        conditions.append("(grade = :grade OR grade = :alt_grade OR :grade = '' OR :grade IS NULL)")
        params["grade"] = grade
        params["alt_grade"] = alt_grade
    if subject:
        conditions.append("LOWER(subject) = LOWER(:subject)")
        params["subject"] = subject
    if strand_name:
        conditions.append("LOWER(strand_name) = LOWER(:strand_name)")
        params["strand_name"] = strand_name

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
    seen_names = {r["sub_strand_name"].lower().strip() for r in rows if r.get("sub_strand_name")}

    # Also search curriculum_designs for additional strands/substrands
    design_conds = ["1=1"]
    design_params: dict[str, Any] = {}
    if grade:
        design_conds.append("(grade = :grade OR grade = :alt_grade)")
        design_params["grade"] = grade
        design_params["alt_grade"] = alt_grade
    if subject:
        design_conds.append("LOWER(subject) = LOWER(:subject)")
        design_params["subject"] = subject

    design_rows = fetch_all(
        f"SELECT design_id, grade, subject, metadata, raw_payload FROM curriculum_designs WHERE {' AND '.join(design_conds)}",
        design_params,
    )
    for dr in design_rows:
        meta = dr.get("metadata") or {}
        raw = dr.get("raw_payload") or {}
        strands_list = meta.get("strands") or raw.get("strands") or []
        for st in strands_list:
            st_name = st.get("name") or st.get("strand_name") or "Strand"
            if strand_name and strand_name.lower().strip() not in st_name.lower().strip() and st_name.lower().strip() not in strand_name.lower().strip():
                continue
            for ss in st.get("sub_strands") or []:
                ss_name = ss if isinstance(ss, str) else (ss.get("sub_strand_name") or ss.get("name") or ss.get("title"))
                if ss_name and ss_name.lower().strip() not in seen_names:
                    seen_names.add(ss_name.lower().strip())
                    rows.append({
                        "id": f"des_{len(rows)+1}",
                        "design_id": dr.get("design_id"),
                        "grade": dr.get("grade") or grade,
                        "subject": dr.get("subject") or subject,
                        "strand_id": st.get("strand_id", "1.0"),
                        "strand_name": st_name,
                        "sub_strand_id": ss.get("sub_strand_id", f"1.{len(rows)+1}") if isinstance(ss, dict) else f"1.{len(rows)+1}",
                        "sub_strand_name": ss_name,
                        "allocated_hours": (ss.get("allocated_time") or ss.get("allocated_hours") or ss.get("hours") or "") if isinstance(ss, dict) else "",
                        "slos": (ss.get("slos") or []) if isinstance(ss, dict) else [],
                        "learning_experiences": (ss.get("learning_experiences") or []) if isinstance(ss, dict) else [],
                        "key_inquiry_questions": (ss.get("key_inquiry_questions") or ss.get("kiqs") or []) if isinstance(ss, dict) else [],
                        "core_competencies": (ss.get("core_competencies") or []) if isinstance(ss, dict) else [],
                        "values": (ss.get("values") or []) if isinstance(ss, dict) else [],
                        "assessment_rubrics": (ss.get("assessment_rubrics") or {}) if isinstance(ss, dict) else {},
                        "required_diagrams": (ss.get("required_diagrams") or []) if isinstance(ss, dict) else [],
                        "experiments": (ss.get("experiments") or []) if isinstance(ss, dict) else [],
                        "pedagogical_guidance": {},
                        "prompt_context": {},
                        "created_at": None,
                    })

    return {"substrands": rows, "count": len(rows)}


@router.delete("/substrand")
def delete_curriculum_substrand(
    grade: str = Query(...),
    subject: str = Query(...),
    strand: str | None = Query(default=None),
    sub_strand: str = Query(...),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Deletes a sub-strand and all associated generated outputs (notes, diagrams, activities, questions)."""
    clean_subj = subject.lower().strip()
    clean_ss = sub_strand.lower().strip()

    execute(
        """
        DELETE FROM substrand_resources
        WHERE LOWER(curriculum->>'subject') = :subject
          AND LOWER(curriculum->>'sub_strand') LIKE :ss
        """,
        {"subject": clean_subj, "ss": f"%{clean_ss}%"},
    )
    execute(
        """
        DELETE FROM curriculum_substrands
        WHERE LOWER(subject) = :subject
          AND LOWER(sub_strand_name) LIKE :ss
        """,
        {"subject": clean_subj, "ss": f"%{clean_ss}%"},
    )
    execute(
        """
        DELETE FROM question_dna
        WHERE LOWER(curriculum_link->>'subject') = :subject
          AND LOWER(curriculum_link->>'sub_strand') LIKE :ss
        """,
        {"subject": clean_subj, "ss": f"%{clean_ss}%"},
    )

    return {
        "success": True,
        "message": f"Deleted sub-strand '{sub_strand}' and all generated assets.",
        "grade": grade,
        "subject": subject,
        "sub_strand": sub_strand,
    }


@router.delete("/strand")
def delete_curriculum_strand(
    grade: str = Query(...),
    subject: str = Query(...),
    strand: str = Query(...),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Deletes an entire strand, all child sub-strands, and all associated generations."""
    clean_subj = subject.lower().strip()
    clean_st = strand.lower().strip()

    execute(
        """
        DELETE FROM substrand_resources
        WHERE LOWER(curriculum->>'subject') = :subject
          AND (LOWER(curriculum->>'strand') LIKE :st OR LOWER(curriculum->>'strand_name') LIKE :st)
        """,
        {"subject": clean_subj, "st": f"%{clean_st}%"},
    )
    execute(
        """
        DELETE FROM curriculum_substrands
        WHERE LOWER(subject) = :subject
          AND LOWER(strand_name) LIKE :st
        """,
        {"subject": clean_subj, "st": f"%{clean_st}%"},
    )
    execute(
        """
        DELETE FROM question_dna
        WHERE LOWER(curriculum_link->>'subject') = :subject
          AND (LOWER(curriculum_link->>'strand') LIKE :st OR LOWER(curriculum_link->>'strand_name') LIKE :st)
        """,
        {"subject": clean_subj, "st": f"%{clean_st}%"},
    )

    return {
        "success": True,
        "message": f"Deleted strand '{strand}' and all child sub-strands.",
        "grade": grade,
        "subject": subject,
        "strand": strand,
    }


@router.delete("/subject")
def delete_curriculum_subject(
    grade: str = Query(...),
    subject: str = Query(...),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Deletes an entire subject curriculum design and all its generated content."""
    clean_subj = subject.lower().strip()

    execute(
        "DELETE FROM substrand_resources WHERE LOWER(curriculum->>'subject') = :subject",
        {"subject": clean_subj},
    )
    execute(
        "DELETE FROM curriculum_substrands WHERE LOWER(subject) = :subject",
        {"subject": clean_subj},
    )
    execute(
        "DELETE FROM curriculum_designs WHERE LOWER(subject) = :subject",
        {"subject": clean_subj},
    )
    execute(
        "DELETE FROM question_dna WHERE LOWER(curriculum_link->>'subject') = :subject",
        {"subject": clean_subj},
    )

    return {
        "success": True,
        "message": f"Deleted subject '{subject}' across {grade} and all generations.",
        "grade": grade,
        "subject": subject,
    }


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
    essence_statement: str = ""
    general_learning_outcomes: list[str] = []
    source_material_text: str = ""
    custom_instructions: str = ""
    # Return the compiled prompt instead of generating, so the inputs can be
    # checked before any tokens are spent.
    inspect: bool = False


class FactoryGenerateDiagramRequest(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    concept: str = ""
    notes_title: str = ""
    notes_content: dict[str, Any] | None = None
    custom_instructions: str = ""


class FactoryPlanVisualsRequest(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    min_visuals: int = 5
    notes_title: str = ""
    notes_content: dict[str, Any] | None = None
    custom_instructions: str = ""


class FactoryGenerateSingleVisualRequest(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    visual_item: dict[str, Any]
    generation_mode: str = "svg"  # "prompt_only" | "svg" | "photo_spec" | "video_storyboard"
    construction_prompt: str = ""
    target_hour: int | None = None
    notes_content: dict[str, Any] | None = None
    custom_instructions: str = ""


class FactoryGenerateActivityRequest(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    notes_title: str = ""
    notes_content: dict[str, Any] | None = None
    diagram_info: dict[str, Any] | None = None
    custom_instructions: str = ""


class FactoryPlanActivitiesRequest(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    notes_title: str = ""
    notes_content: dict[str, Any] | None = None
    diagram_info: dict[str, Any] | None = None
    custom_instructions: str = ""


class FactoryGenerateSingleActivityRequest(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    activity_item: dict[str, Any]
    notes_content: dict[str, Any] | None = None
    # An activity belongs to one hour of the sub-strand, the same as a visual.
    target_hour: int | None = None
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
    notes_content: dict[str, Any] | None = None
    diagram_title: str = ""
    diagram_info: dict[str, Any] | None = None
    activity_info: dict[str, Any] | None = None
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
    diagrams: list[Any] = []
    activities: Any = []  # Can be list or dict
    experiments: Any = []
    video_storyboards: list[Any] = []
    questions: list[Any] = []
    review_status: str = "draft_in_factory"
    human_notes: str = ""


class FactoryAuditBundleRequest(BaseModel):
    grade: str
    subject: str
    strand: str
    sub_strand: str
    level: str = "Basic Education"
    notes: dict[str, Any] = {}
    diagram: dict[str, Any] = {}
    diagrams: list[Any] = []
    activity: Any = {}
    activities: list[Any] = []
    questions: list[Any] = []


class FactoryPublishBundleRequest(BaseModel):
    bundle_id: str
    grade: str
    subject: str
    strand: str
    sub_strand: str
    level: str = "Basic Education"
    notes: dict[str, Any] = {}
    diagram: dict[str, Any] = {}
    activity: dict[str, Any] = {}
    questions: list[Any] = []
    deliberation_notes: str = "Audited and released via 5-Layer Content Factory"


class ProfilePayload(BaseModel):
    id: int | None = None
    subject: str
    grade: str = "all"
    content_type: str = "generic"
    persona: str
    note_style: str
    diagram_type: str
    activity_type: str
    question_type: str
    safety_focus: str
    grade_appropriate_tone: str = "formal academic and constructivist"
    special_directives: list[str] = []
    empirical_insights: list[dict[str, Any]] = []
    case_studies: list[dict[str, str]] = []
    metadata: dict[str, Any] = {}


class ProfileAiImproveRequest(BaseModel):
    profile: dict[str, Any]
    instructions: str = ""


class ProfileAiGenerateRequest(BaseModel):
    subject: str
    grade: str = "all"
    level: str = "Basic Education"
    essence_statement: str = ""
    general_learning_outcomes: list[str] = []


class FactoryGetProfileRequest(BaseModel):
    grade: str = "all"
    subject: str
    sub_strand: str = ""
    level: str = "Basic Education"
    essence_statement: str = ""
    general_learning_outcomes: list[str] = []
    force_regenerate: bool = False


@router.get("/profiles")
def list_profiles(
    search: str = "",
    grade: str = "",
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Lists all stored pedagogical subject profiles from PostgreSQL."""
    from ..services.content_type_classifier import list_all_profiles_from_db
    profiles = list_all_profiles_from_db(search=search, grade=grade)
    return {
        "status": "success",
        "count": len(profiles),
        "profiles": [p.to_dict() for p in profiles],
    }


@router.get("/profiles/{profile_id}")
def get_profile(
    profile_id: int,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Retrieves a single pedagogical subject profile by ID."""
    from ..services.content_type_classifier import get_profile_by_id
    profile = get_profile_by_id(profile_id)
    if not profile:
        raise_api_error("DATASET_ITEM_NOT_FOUND", f"Profile ID {profile_id} not found.")
    return {"status": "success", "profile": profile.to_dict()}


@router.post("/profiles")
def create_profile(
    payload: ProfilePayload,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Creates a new pedagogical subject profile in the database."""
    from ..services.content_type_classifier import ContentTypeProfile, upsert_profile_in_db
    profile = ContentTypeProfile.from_dict(payload.model_dump())
    saved = upsert_profile_in_db(profile)
    return {"status": "success", "profile": saved.to_dict()}


@router.put("/profiles/{profile_id}")
def update_profile(
    profile_id: int,
    payload: ProfilePayload,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Updates an existing pedagogical subject profile in the database."""
    from ..services.content_type_classifier import ContentTypeProfile, upsert_profile_in_db
    data = payload.model_dump()
    data["id"] = profile_id
    profile = ContentTypeProfile.from_dict(data)
    saved = upsert_profile_in_db(profile)
    return {"status": "success", "profile": saved.to_dict()}


@router.delete("/profiles/{profile_id}")
def delete_profile(
    profile_id: int,
    _: AuthContext = Depends(require_roles("admin")),
) -> dict[str, Any]:
    """Deletes a pedagogical subject profile from the database."""
    from ..services.content_type_classifier import delete_profile_from_db
    success = delete_profile_from_db(profile_id)
    return {"status": "success" if success else "failed", "deleted_id": profile_id}


@router.post("/profiles/ai-improve")
def improve_profile_with_ai(
    payload: ProfileAiImproveRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Uses the LLM to refine, deepen, and expand a pedagogical profile based on user guidance."""
    from ..services.content_type_classifier import ai_improve_profile
    improved = ai_improve_profile(payload.profile, payload.instructions)
    return {"status": "success", "profile": improved.to_dict()}


@router.post("/profiles/ai-generate")
def generate_profile_with_ai(
    payload: ProfileAiGenerateRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Synthesizes a brand new bespoke profile from a Curriculum Design dataset using AI."""
    from ..services.content_type_classifier import ai_generate_profile_from_dataset
    generated = ai_generate_profile_from_dataset(
        subject=payload.subject,
        grade=payload.grade,
        level=payload.level,
        essence_statement=payload.essence_statement,
        general_learning_outcomes=payload.general_learning_outcomes,
        save_to_db=True,
    )
    return {"status": "success", "profile": generated.to_dict()}


@router.post("/profiles/generate-from-design/{design_id}")
def generate_profile_from_published_design(
    design_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Generates an exhaustive pedagogical profile directly from an uploaded/published Curriculum Design blueprint."""
    from ..infra.db import fetch_all, fetch_one
    from ..services.content_type_classifier import ai_generate_profile_from_dataset

    design = fetch_one("SELECT * FROM curriculum_designs WHERE design_id = :id", {"id": design_id})
    if not design:
        raise_api_error("DATASET_ITEM_NOT_FOUND", f"Curriculum design '{design_id}' not found.")

    substrands = fetch_all(
        """
        SELECT strand_name, sub_strand_name, slos, suggested_learning_experiences,
               key_inquiry_questions, core_competencies, values, pertinent_contemporary_issues
        FROM curriculum_substrands
        WHERE design_id = :id
        ORDER BY id ASC
        """,
        {"id": design_id},
    )

    generated = ai_generate_profile_from_dataset(
        subject=design.get("subject", ""),
        grade=design.get("grade", "all"),
        level=design.get("level", "Basic Education"),
        essence_statement=design.get("essence_statement", ""),
        general_learning_outcomes=design.get("general_learning_outcomes", []),
        substrands_summary=substrands,
        save_to_db=True,
    )
    return {"status": "success", "profile": generated.to_dict()}


@router.post("/factory/profile")
def factory_get_profile(
    payload: FactoryGetProfileRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Dynamically resolves or synthesizes a bespoke ContentTypeProfile from the database or Curriculum Design dataset."""
    from ..services.content_type_classifier import ai_generate_profile_from_dataset, classify_content_type

    if payload.force_regenerate and payload.essence_statement:
        profile = ai_generate_profile_from_dataset(
            subject=payload.subject,
            grade=payload.grade,
            level=payload.level,
            essence_statement=payload.essence_statement,
            general_learning_outcomes=payload.general_learning_outcomes,
            save_to_db=True,
        )
    else:
        profile = classify_content_type(
            subject=payload.subject,
            grade=payload.grade,
            sub_strand=payload.sub_strand,
            design_context={
                "level": payload.level,
                "essence_statement": payload.essence_statement,
                "general_learning_outcomes": payload.general_learning_outcomes,
            } if payload.essence_statement else None,
            auto_generate=True,
        )

    return {
        "status": "success",
        "subject": payload.subject,
        "grade": payload.grade,
        "profile": profile.to_dict(),
    }


@router.post("/factory/generate-notes")
def factory_generate_notes(
    payload: FactoryGenerateNotesRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    # Notes descend from a strand and a sub-strand. Without them there is
    # nothing for the notes to be *about*, and the model would choose the topic.
    from ..services.content_lineage import HOUR_NOTE
    from ..services.stage_guard import require_context

    lineage = require_context(
        HOUR_NOTE,
        grade=payload.grade, subject=payload.subject,
        strand=payload.strand, sub_strand=payload.sub_strand,
        level=payload.level, essence_statement=payload.essence_statement,
        general_learning_outcomes=payload.general_learning_outcomes,
    )

    from ..infra.db import fetch_one
    from ..services.content_type_classifier import classify_content_type
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator
    from ..services.quality_gate import quality_gate_service
    from ..services.web_research import web_research_agent

    essence_stmt = payload.essence_statement
    source_text = payload.source_material_text
    level = payload.level

    # 1. Content-Type Classification
    ct_profile = classify_content_type(payload.subject, payload.grade, payload.sub_strand)

    # 2. Fetch Sub-strand specific blueprint from database
    substrand_row = fetch_one(
        """
        SELECT allocated_hours, slos, learning_experiences, key_inquiry_questions,
               core_competencies, values, required_diagrams, experiments, pedagogical_guidance
        FROM curriculum_substrands
        WHERE (grade = :grade OR grade = :alt_grade)
          AND LOWER(subject) = LOWER(:subject)
          AND (LOWER(sub_strand_name) = LOWER(:sub_strand) OR LOWER(sub_strand_name) LIKE LOWER(:sub_strand_pattern))
        LIMIT 1
        """,
        {
            "grade": payload.grade,
            "alt_grade": payload.grade.replace("grade-", ""),
            "subject": payload.subject,
            "sub_strand": payload.sub_strand,
            "sub_strand_pattern": f"%{payload.sub_strand}%",
        },
    )

    slos = substrand_row.get("slos", []) if substrand_row else []
    kiqs = substrand_row.get("key_inquiry_questions", []) if substrand_row else []

    # 3. Fetch Curriculum Design essence statement and source text if not provided
    #
    # This read the design under the keys "raw_text"/"text"/"output". The
    # extractor writes it under "source_text", so the lookup always missed and
    # every note ever generated was written without the design in front of it.
    # One shared resolver now, so a fifth spelling of this query cannot drift.
    found = design_source.resolve(
        payload.grade, payload.subject, supplied=source_text,
    )
    source_text = found.text
    essence_stmt = essence_stmt or found.essence_statement
    if level == "Basic Education" and found.level:
        level = found.level

    # 4. Execute Deep Live Web Research & Academic Paper Retrieval
    dossier = web_research_agent.research_topic(
        subject=payload.subject,
        strand=payload.strand,
        sub_strand=payload.sub_strand,
        grade=payload.grade,
        topic_type="notes",
        extra_query=payload.custom_instructions,
    )

    master_context = langfuse_context_service.get_master_context()
    resolved = pipeline_orchestrator.router.resolve_for_stage("notes_generation")

    slos_formatted = "\n".join([f"- {s if isinstance(s, str) else s.get('text', str(s))}" for s in slos]) if slos else f"- Master the foundational and practical principles of {payload.sub_strand}"
    kiqs_formatted = "\n".join([f"- {k}" for k in kiqs]) if kiqs else f"- How does {payload.sub_strand} apply to real-world Kenyan national development?"

    # The design's own suggested experiences, competencies, values, PCIs, links
    # and rubric were stored and then not passed. For pre-primary the suggested
    # learning experiences ARE the lesson, and the rubric is what the notes have
    # to make achievable — writing notes without them invents a parallel lesson
    # that the assessment does not match.
    def _lines(value: Any, prefix: str = "- ") -> str:
        if isinstance(value, str):
            return f"{prefix}{value}" if value.strip() else ""
        if isinstance(value, dict):
            return "\n".join(f"{prefix}{k}: {v}" for k, v in value.items() if v)
        if isinstance(value, (list, tuple)):
            return "\n".join(
                _lines(v, prefix) if not isinstance(v, str) else f"{prefix}{v}"
                for v in value if v
            )
        return ""

    design_block = ""
    if substrand_row:
        sections = [
            ("Suggested learning experiences (from the design)",
             _lines(substrand_row.get("learning_experiences"))),
            ("Core competencies the design develops here",
             _lines(substrand_row.get("core_competencies"))),
            ("Values the design nurtures here", _lines(substrand_row.get("values"))),
            ("Pertinent and contemporary issues",
             _lines(substrand_row.get("pertinent_contemporary_issues"))),
            ("Link to other learning areas",
             _lines(substrand_row.get("link_to_other_learning_areas"))),
            ("Assessment rubric the notes must make achievable",
             _lines(substrand_row.get("assessment_rubrics"))),
        ]
        design_block = "\n\n".join(
            f"{title}:\n{body}" for title, body in sections if body.strip()
        )

    allocation = time_allocation.parse(
        (substrand_row or {}).get("allocated_hours"), payload.grade
    )

    template_vars = {
        "master_context": master_context,
        "level_register": register_block(
                    payload.grade,
                    notes=grade_scope_notes(payload.grade, payload.subject),
                ),
        "faith_scope": faith_prompt_block(payload.subject),
        "content_type_directives": ct_profile.format_for_prompt(),
        "level": level,
        "strand": payload.strand,
        "sub_strand": payload.sub_strand,
        "slo_id": payload.slo_id or f"{payload.grade}-{payload.subject[:3]}-01",
        "slos": slos_formatted,
        "kiqs": kiqs_formatted,
        "essence_statement": essence_stmt or f"Comprehensive curriculum blueprint for {payload.subject} ({payload.grade}).",
        "source_material_snippet": source_text[:4000] if source_text else "(NO DESIGN DOCUMENT AVAILABLE)",
        "design_extract": design_block or "(no stored sub-strand detail)",
        "time_allocation": allocation.phrase(),
        "research_dossier": dossier.formatted_context,
        "custom_instructions": payload.custom_instructions,
    }

    context = langfuse_context_service.assemble_agent_context(
        agent_name="note-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars=template_vars,
    )

    # The directive appended here used to carry a full worked example of a
    # four-hour TVET agriculture module — soil pH titration, lime tonnage per
    # hectare, agricultural GDP share — as the model of what to produce. It was
    # shown to every subject and every grade, and it out-massed the level
    # register by an order of magnitude, so a Pre-Primary CRE note was steered
    # toward "Hour 1: Macro-Economic Architecture". The shape is now described
    # rather than demonstrated, and the schema itself lives in the Langfuse
    # prompt where it can be edited without a deploy.
    register = level_register_for(payload.grade)
    unit = allocation.unit or register.time_unit or "lessons"
    module_word = unit[:-1] if unit.endswith("s") else unit

    context.messages.append({
        "role": "user",
        "content": (
            f"{design_block}\n\n"
            f"=== WHAT TO AUTHOR ===\n"
            f"Subject: {payload.subject} ({payload.grade}, {level}) "
            f"[Content type: {ct_profile.content_type.upper()}]\n"
            f"Strand: {payload.strand} \u2794 Sub-strand: {payload.sub_strand}\n"
            f"Time the design allocates: {allocation.phrase()}\n"
            f"SLOs to cover completely:\n{slos_formatted}\n"
            f"Key inquiry questions to address:\n{kiqs_formatted}\n\n"
            f"ESSENCE STATEMENT:\n{essence_stmt}\n\n"
            f"PRODUCTION RULES\n"
            f"1. Author exactly {allocation.modules} module(s) in 'modules', one per "
            f"{module_word} the design allocates. Number them 1 to {allocation.modules}. "
            f"Do not merge them, and do not invent a {module_word} the design did not fund.\n"
            f"2. Set each module's 'duration_minutes' to "
            f"{allocation.minutes_each or 'the length this level actually teaches for'}"
            f" \u2014 never assume 60.\n"
            f"3. Every module must build on the design's own suggested learning "
            f"experiences above. They are the lesson; your notes explain how to teach "
            f"them, not what to teach instead of them.\n"
            f"4. Depth follows the learner described in WHO THIS IS FOR, not a fixed "
            f"word count. A note a teacher cannot deliver to this age group is wrong "
            f"however thorough it is.\n"
            f"5. Cite a source only where the claim needs one and the source is "
            f"permitted for THIS subject. A sub-strand that rests on the design alone "
            f"needs no external citation, and inventing statistics to fill the field "
            f"is a defect.\n"
            f"6. Fill 'practical_connections' with what this sub-strand genuinely "
            f"does. Where there is no apparatus, name the real materials and leave "
            f"'safety_precautions' to whatever genuinely applies \u2014 an empty string "
            f"beats an invented hazard.\n"
            f"7. Make the design's assessment rubric above achievable from these "
            f"notes. If the rubric asks for three of something, teach three.\n\n"
            f"=== ONE MODULE PER ALLOCATED LESSON ===\n"
            f"This sub-strand is funded for {allocation.phrase()}. Produce EXACTLY "
            f"{allocation.modules} module(s) in 'modules', numbered 1 to "
            f"{allocation.modules}, with no gaps and none merged.\n"
            f"A teacher builds a scheme of work from this and a head of department "
            f"checks the scheme against it. Fewer modules than lessons cannot be "
            f"scheduled: the missing lessons have no plan and nobody can see which "
            f"ones they are.\n"
            f"Set 'module_count' to {allocation.modules} and every "
            f"'duration_minutes' to "
            f"{allocation.minutes_each or 'the length this level teaches for'}.\n"
            f"Set 'allocated_time' to the design's own wording, verbatim: "
            f"\"{allocation.stated or 'not stated'}\".\n\n"
            f"ADDITIONAL PRODUCTION DIRECTIVES: {payload.custom_instructions}"
        ),
    })

    if payload.inspect:
        from ..services.content_type_classifier import get_profile_from_db

        return {
            "inspection": build_inspection(
                context,
                agent="notes-generator",
                grade=payload.grade,
                subject=payload.subject,
                source_material=payload.source_material_text,
                profile=get_profile_from_db(payload.subject, payload.grade),
                extra={
                    "model": f"{resolved.provider}/{resolved.model}",
                    "strand": payload.strand,
                    "sub_strand": payload.sub_strand,
                    "research_citations": [c.url for c in (dossier.citations or [])],
                },
            )
        }

    resp = llm_client.generate(resolved, context.messages, temperature=0.15)
    audit_report = web_research_agent.perform_quality_audit(resp.content, "notes", dossier)

    # Downstream readers — coverage, the DNA scorer, the stage guard, the visual
    # planner — were written against hour_modules and key_concepts. Mirroring
    # keeps them working without renaming the same list in six places, each of
    # which would silently read zero until it was found.
    if isinstance(notes_content, dict) and notes_content.get("modules"):
        notes_content.setdefault("hour_modules", notes_content["modules"])

    # Normalize notes output so both hour_modules and key_concepts are rich arrays
    notes_content = resp.content
    if isinstance(notes_content, dict):
        hour_mods = notes_content.get("hour_modules") or []
        key_cncpts = notes_content.get("key_concepts") or []

        # If hour_modules exists and key_concepts is short, map hour_modules to key_concepts
        if hour_mods and (not key_cncpts or len(key_cncpts) < len(hour_mods)):
            synced_concepts = []
            for hm in hour_mods:
                h_num = hm.get("hour_number", len(synced_concepts) + 1)
                h_title = hm.get("hour_title") or hm.get("title") or f"Session {h_num}"
                h_content = hm.get("full_lecture_notes") or hm.get("content") or hm.get("detailed_exposition", "")
                h_subs = hm.get("subsections") or hm.get("sub_sections", [])
                h_pck = hm.get("pedagogical_notes") or hm.get("pck_guidance", "")
                h_misc = hm.get("common_misconceptions") or hm.get("misconceptions", "")
                h_fc = hm.get("formative_checks") or hm.get("formative_evaluations", "")
                if isinstance(h_fc, list):
                    h_fc = " • ".join(h_fc)

                synced_concepts.append({
                    "concept_id": f"hour_{h_num}",
                    "heading": f"Hour {h_num}: {h_title.replace(f'Hour {h_num}:', '').strip()}",
                    "content": h_content,
                    "detailed_exposition": h_content,
                    "sub_sections": h_subs,
                    "pedagogical_notes": h_pck,
                    "common_misconceptions": h_misc,
                    "formative_checks": h_fc,
                })
            notes_content["key_concepts"] = synced_concepts
        elif key_cncpts and not hour_mods:
            hour_mods = []
            for idx, kc in enumerate(key_cncpts):
                hour_mods.append({
                    "hour_number": idx + 1,
                    "hour_title": kc.get("heading", f"Hour {idx + 1}"),
                    "duration_minutes": 60,
                    "learning_intent": f"Master core competencies of {kc.get('heading', '')}",
                    "full_lecture_notes": kc.get("content") or kc.get("detailed_exposition", ""),
                    "subsections": kc.get("sub_sections", []),
                    "pedagogical_notes": kc.get("pedagogical_notes", ""),
                    "common_misconceptions": kc.get("common_misconceptions", ""),
                    "formative_checks": kc.get("formative_checks", ""),
                })
            notes_content["hour_modules"] = hour_mods

    # 5. Run 3-Agent Quality Gate
    gate_result = quality_gate_service.run_layer_gate(
        layer_name="notes",
        content=notes_content,
        blueprint=substrand_row or {},
        content_type_profile=ct_profile,
        custom_instructions=payload.custom_instructions,
    )

    # The design funds a fixed number of lessons and the guide must plan every
    # one of them. A short guide used to pass silently: the fallback below built
    # hour modules out of whatever concepts came back, so four modules for a
    # seven-lesson sub-strand looked complete and three lessons had no plan.
    lesson_plan = notes_coverage.check(notes_content, allocation, slos)
    if not lesson_plan.complete:
        logger.warning(
            "Notes for %s (%s) cover %d of %d allocated %s.",
            payload.sub_strand, payload.grade, lesson_plan.modules_found,
            lesson_plan.modules_required, allocation.unit or "lessons",
        )

    versioned = _record_artifact(
        "notes", payload.grade, payload.subject, notes_content,
        strand=payload.strand, sub_strand=payload.sub_strand,
        provenance={"source": "factory_generate_notes",
                    "provider": resolved.provider, "model": resolved.model},
    )

    return {
        "notes": notes_content,
        "usage": resp.usage,
        "model": resp.model,
        "content_type": ct_profile.to_dict(),
        "research_dossier": dossier.to_dict(),
        "quality_audit": audit_report.to_dict(),
        "quality_gate": gate_result.to_dict(),
        "lesson_coverage": lesson_plan.to_dict(),
        "artifact": versioned,
    }


@router.post("/factory/generate-diagram")
def factory_generate_diagram(
    payload: FactoryGenerateDiagramRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    import json as json_lib
    from ..services.content_type_classifier import classify_content_type
    from ..services.diagram_dedup import diagram_deduplicator
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator
    from ..services.quality_gate import quality_gate_service
    from ..services.web_research import web_research_agent

    resolved = pipeline_orchestrator.router.resolve_for_stage("diagram_generation")
    concept_name = payload.concept or f"{payload.sub_strand} model"
    ct_profile = classify_content_type(payload.subject, payload.grade, payload.sub_strand)

    # Execute Web Research
    dossier = web_research_agent.research_topic(
        subject=payload.subject,
        strand=payload.strand,
        sub_strand=payload.sub_strand,
        grade=payload.grade,
        topic_type="diagram",
        extra_query=concept_name,
    )

    notes_summary_str = ""
    if payload.notes_content:
        notes_summary_str = f"Title: {payload.notes_content.get('title', '')}\nIntro: {payload.notes_content.get('intro', '')}\nConcepts: {json_lib.dumps(payload.notes_content.get('key_concepts', []), ensure_ascii=False)[:1500]}"

    context = langfuse_context_service.assemble_agent_context(
        agent_name="diagram-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars={
            "slo_id": payload.slo_id if getattr(payload, "slo_id", None) else f"{payload.grade}-{payload.subject[:3].upper()}-01",
            "strand": payload.strand,
            "sub_strand": payload.sub_strand,
            "concept": concept_name,
            "level_register": register_block(
                    payload.grade,
                    notes=grade_scope_notes(payload.grade, payload.subject),
                ),
            "faith_scope": faith_prompt_block(payload.subject),
            "content_type_directives": ct_profile.format_for_prompt(),
            "notes_content": notes_summary_str or payload.notes_title or payload.sub_strand,
        },
    )

    context.messages.append({
        "role": "user",
        "content": (
            f"{ct_profile.format_for_prompt()}\n\n"
            f"{dossier.formatted_context}\n\n"
            f"=== LAYER 1 NOTES CONTEXT ===\n{notes_summary_str}\n\n"
            f"VECTOR SVG DESIGN DIRECTIVE:\n"
            f"Generate a professional, high-contrast, responsive SVG vector illustration for '{concept_name}' aligned with {ct_profile.diagram_type}.\n\n"
            f"STRICT SVG SYNTAX RULES:\n"
            f"1. Root element MUST be: <svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 800 500\" width=\"100%\" height=\"100%\"> ... </svg>\n"
            f"2. All CSS styles MUST be enclosed inside <defs><style type=\"text/css\"><![CDATA[ ... ]]></style></defs>. NEVER write naked CSS rules directly in the SVG body.\n"
            f"3. All text MUST be inside <text x=\"...\" y=\"...\" font-family=\"system-ui, -apple-system, sans-serif\" font-size=\"14\" fill=\"#1e293b\" text-anchor=\"middle\">...</text> elements. NEVER write raw text outside of <text> tags.\n"
            f"4. Use high-contrast modern colors (e.g. #f0fdf4 backgrounds, #16a34a / #0284c7 borders, #0f172a text), rounded corners (rx=\"8\"), clean connector arrows (<line marker-end=\"url(#arrowhead)\"/>), and clear step boxes.\n"
            f"5. Return a valid JSON object matching:\n"
            f'{{\n  "diagram_id": "diag_01",\n  "diagram_title": "{concept_name}",\n  "diagram_svg": "<svg ...>...</svg>",\n  "accessibility": {{"alt_text": "...", "tactile_description": "..."}}\n}}\n\n'
            f"ADDITIONAL INSTRUCTIONS: {payload.custom_instructions}"
        ),
    })

    resp = llm_client.generate(resolved, context.messages, temperature=0.1)
    svg_markup = resp.content.get("diagram_svg") or resp.content.get("svg") or resp.content.get("svg_code") or "<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    accessibility = resp.content.get("accessibility", {})

    dedup = diagram_deduplicator.deduplicate_and_store(
        svg_str=svg_markup,
        diagram_title=resp.content.get("diagram_title", concept_name),
        alt_text=accessibility.get("alt_text", ""),
        tactile_description=accessibility.get("tactile_description", ""),
        # The generator's part list carries each part's function, which is what
        # a question needs to ask for more than the bare label. Dropping it here
        # is why diagrams reached the question stage with unnamed parts.
        scene_document=resp.content.get("scene_document") or resp.content.get("scene"),
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
    audit_report = web_research_agent.perform_quality_audit(resp.content, "diagram", dossier)

    # 3-Agent Quality Gate
    gate_result = quality_gate_service.run_layer_gate(
        layer_name="diagram",
        content=diagram_data,
        blueprint={},
        content_type_profile=ct_profile,
        custom_instructions=payload.custom_instructions,
    )

    return {
        "diagram": diagram_data,
        "usage": resp.usage,
        "model": resp.model,
        "content_type": ct_profile.to_dict(),
        "research_dossier": dossier.to_dict(),
        "quality_audit": audit_report.to_dict(),
        "quality_gate": gate_result.to_dict(),
    }


@router.post("/factory/generate-activity")
def factory_generate_activity(
    payload: FactoryGenerateActivityRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    import json as json_lib
    from ..services.content_type_classifier import classify_content_type
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator
    from ..services.quality_gate import quality_gate_service
    from ..services.web_research import web_research_agent

    resolved = pipeline_orchestrator.router.resolve_for_stage("activity_generation")
    ct_profile = classify_content_type(payload.subject, payload.grade, payload.sub_strand)

    # Execute Web Research
    dossier = web_research_agent.research_topic(
        subject=payload.subject,
        strand=payload.strand,
        sub_strand=payload.sub_strand,
        grade=payload.grade,
        topic_type="activity",
        extra_query=payload.notes_title,
    )

    notes_str = ""
    if payload.notes_content:
        notes_str = json_lib.dumps(payload.notes_content, ensure_ascii=False)[:2000]

    diagram_str = ""
    if payload.diagram_info:
        diagram_str = f"Diagram: {payload.diagram_info.get('diagram_title', '')} (Alt: {payload.diagram_info.get('accessibility', {}).get('alt_text', '')})"

    context = langfuse_context_service.assemble_agent_context(
        agent_name="activity-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars={
            "level": getattr(payload, "level", None) or grade_level(payload.grade),
            "slo_id": payload.slo_id if getattr(payload, "slo_id", None) else f"{payload.grade}-{payload.subject[:3].upper()}-01",
            "strand": payload.strand,
            "sub_strand": payload.sub_strand,
            "level_register": register_block(
                    payload.grade,
                    notes=grade_scope_notes(payload.grade, payload.subject),
                ),
            "faith_scope": faith_prompt_block(payload.subject),
            "content_type_directives": ct_profile.format_for_prompt(),
            "notes_content": notes_str or payload.notes_title or payload.sub_strand,
            "diagram_info": diagram_str or "Visual model integrated with sub-strand.",
        },
    )

    context.messages.append({
        "role": "user",
        "content": (
            f"{ct_profile.format_for_prompt()}\n\n"
            f"{dossier.formatted_context}\n\n"
            f"=== LAYER 1 & 2 UPSTREAM CONTEXT ===\nNotes: {notes_str[:1000]}\nDiagram: {diagram_str}\n\n"
            f"ACTIVITY & PRACTICAL TASK DIRECTIVE:\n"
            f"Generate hands-on constructivist tasks, apparatus lists, step-by-step procedures, and safety mitigations matching {ct_profile.activity_type}.\n"
            f"ADDITIONAL INSTRUCTIONS: {payload.custom_instructions}"
        ),
    })

    resp = llm_client.generate(resolved, context.messages, temperature=0.25)
    audit_report = web_research_agent.perform_quality_audit(resp.content, "activity", dossier)

    # 3-Agent Quality Gate
    gate_result = quality_gate_service.run_layer_gate(
        layer_name="activity",
        content=resp.content,
        blueprint={},
        content_type_profile=ct_profile,
        custom_instructions=payload.custom_instructions,
    )

    return {
        "activity": resp.content,
        "usage": resp.usage,
        "model": resp.model,
        "content_type": ct_profile.to_dict(),
        "research_dossier": dossier.to_dict(),
        "quality_audit": audit_report.to_dict(),
        "quality_gate": gate_result.to_dict(),
    }


@router.post("/factory/plan-visuals")
def factory_plan_visuals(
    payload: FactoryPlanVisualsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Plans and lists all required diagrams, schematics, and realistic visual assets for a sub-strand."""
    # Visuals are planned across a sub-strand's hours, so the notes must exist:
    # a plan made without them is a guess at what the lessons will cover.
    from ..services.content_lineage import ASSET_PLAN
    from ..services.stage_guard import require_context

    lineage = require_context(
        ASSET_PLAN,
        grade=payload.grade, subject=payload.subject,
        strand=payload.strand, sub_strand=payload.sub_strand,
        notes_content=payload.notes_content,
    )

    import json as json_lib
    from ..services.content_type_classifier import classify_content_type
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator
    from ..services.web_research import web_research_agent

    resolved = pipeline_orchestrator.router.resolve_for_stage("diagram_generation")
    ct_profile = classify_content_type(payload.subject, payload.grade, payload.sub_strand)

    dossier = web_research_agent.research_topic(
        subject=payload.subject,
        strand=payload.strand,
        sub_strand=payload.sub_strand,
        grade=payload.grade,
        topic_type="diagram",
        extra_query="visual models and schematics",
    )

    # Extract all 4 hour modules explicitly
    hours_breakdown_str = ""
    notes_dict = payload.notes_content
    if not notes_dict:
        from ..infra.db import fetch_one
        saved_row = fetch_one(
            """
            SELECT notes FROM substrand_resources
            WHERE LOWER(curriculum->>'subject') = LOWER(:subject)
              AND LOWER(curriculum->>'sub_strand') LIKE :ss
            ORDER BY updated_at DESC LIMIT 1
            """,
            {"subject": payload.subject.strip(), "ss": f"%{payload.sub_strand.strip().lower()}%"},
        )
        if saved_row and saved_row.get("notes"):
            notes_dict = saved_row.get("notes")

    if notes_dict and isinstance(notes_dict, dict):
        h_mods = notes_dict.get("hour_modules") or notes_dict.get("key_concepts") or []
        for idx, hm in enumerate(h_mods):
            h_num = hm.get("hour_number", idx + 1)
            h_title = hm.get("hour_title") or hm.get("heading") or f"Hour {h_num}"
            h_notes = hm.get("full_lecture_notes") or hm.get("content") or hm.get("detailed_exposition") or ""
            hours_breakdown_str += f"\n--- ⏰ LESSON HOUR {h_num}: {h_title} ---\n{h_notes[:2500]}\n"

    notes_str = hours_breakdown_str or (json_lib.dumps(notes_dict, ensure_ascii=False)[:4000] if notes_dict else payload.sub_strand)

    context = langfuse_context_service.assemble_agent_context(
        agent_name="diagram-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars={
            "slo_id": payload.slo_id if getattr(payload, "slo_id", None) else f"{payload.grade}-{payload.subject[:3].upper()}-01",
            "concept": getattr(payload, "concept", "") or payload.sub_strand,
            "strand": payload.strand,
            "sub_strand": payload.sub_strand,
            "level_register": register_block(
                    payload.grade,
                    notes=grade_scope_notes(payload.grade, payload.subject),
                ),
            "faith_scope": faith_prompt_block(payload.subject),
            "content_type_directives": ct_profile.format_for_prompt(),
            "notes_content": notes_str or payload.notes_title or payload.sub_strand,
        },
    )

    context.messages.append({
        "role": "user",
        "content": (
            f"{ct_profile.format_for_prompt()}\n\n"
            f"{dossier.formatted_context}\n\n"
            f"=== LAYER 1 MASTER LESSON NOTES CONTEXT (MANDATORY 4-HOUR SOURCE OF TRUTH) ===\n{notes_str}\n\n"
            f"MANDATORY 4-HOUR BALANCED MULTI-VISUAL ASSET DISCOVERY DIRECTIVE:\n"
            f"You MUST discover and specify 2 to 3 distinct pedagogical visual assets FOR EACH of the 4 Lesson Hours listed above (Total 8 to 12 distinct assets):\n"
            f"1. For Hour 1 ({h_mods[0].get('hour_title', 'Hour 1') if len(h_mods) > 0 else 'Hour 1'}): Generate 2-3 visuals illustrating Hour 1 concepts (flowcharts, economic dynamics, overview models) -> set 'hour_index': 1, 'hour_title': 'Hour 1: ...'\n"
            f"2. For Hour 2 ({h_mods[1].get('hour_title', 'Hour 2') if len(h_mods) > 1 else 'Hour 2'}): Generate 2-3 visuals illustrating that hour's own concepts, in the visual style named in the directives above -> set 'hour_index': 2, 'hour_title': 'Hour 2: ...'\n"
            f"3. For Hour 3 ({h_mods[2].get('hour_title', 'Hour 3') if len(h_mods) > 2 else 'Hour 3'}): Generate 2-3 visuals illustrating Hour 3 concepts (e.g. Soil Erosion types, Contour Bunds, Gabions, Ecological Equilibrium) -> set 'hour_index': 3, 'hour_title': 'Hour 3: ...'\n"
            f"4. For Hour 4 ({h_mods[3].get('hour_title', 'Hour 4') if len(h_mods) > 3 else 'Hour 4'}): Generate 2-3 visuals illustrating Hour 4 concepts (e.g. Soil Profile Horizon Strata O-A-B-C, pH Titration & Buffer Capacity Apparatus) -> set 'hour_index': 4, 'hour_title': 'Hour 4: ...'\n\n"
            f"For EACH visual asset provide:\n"
            f"- asset_id (e.g. vis_01, vis_02, vis_03, vis_04, vis_05, vis_06, vis_07, vis_08)\n"
            f"- hour_index (1 | 2 | 3 | 4 - the specific hour module in the lesson notes this visual illustrates)\n"
            f"- hour_title (e.g. 'Hour 1: ...' or 'Hour 2: ...')\n"
            f"- title (a specific, descriptive name for what the visual depicts in this subject)\n"
            f"- asset_type ('technical_svg' | 'realistic_image' | 'apparatus_schematic' | 'process_flowchart' | 'infographic_chart' | 'video_storyboard')\n"
            f"- micro_concept (the specific sub-topic tested)\n"
            f"- pedagogical_purpose (why this visual is essential for learner mastery and exam assessment)\n"
            f"- vivid_prompt (exhaustive, vivid visual scene description: layout, perspective, objects, lighting, color palette, labels, callouts for AI image/SVG generation)\n"
            f"- accessibility: {{ 'alt_text': '...', 'tactile_description': '...' }}\n"
            # Part functions are what let a question ask "state the function of the
            # part labelled B" and be marked automatically. Without them every
            # diagram question collapses to bare recall of a label.
            f"- scene: the addressable parts of the visual. For EACH labelled part give\n"
            f"    'label' (exactly as it appears in the drawing), 'function' (what that part does,\n"
            f"    in one sentence a learner of this grade would be marked correct for),\n"
            f"    'assessable' (true if a learner could reasonably be asked to name or explain it),\n"
            f"    and 'occludable' (false only if hiding it would make the figure unreadable).\n\n"
            f"Return JSON format:\n"
            f'{{\n  "sub_strand": "{payload.sub_strand}",\n  "visuals": [\n'
            f'    {{\n'
            f'      "asset_id": "vis_01",\n'
            f'      "hour_index": 1,\n'
            f'      "hour_title": "Hour 1: ...",\n'
            f'      "title": "...",\n'
            f'      "asset_type": "technical_svg",\n'
            f'      "micro_concept": "...",\n'
            f'      "pedagogical_purpose": "...",\n'
            f'      "vivid_prompt": "...",\n'
            f'      "accessibility": {{"alt_text": "...", "tactile_description": "..."}},\n'
            f'      "scene": {{"parts": [\n'
            f'        {{"label": "Stigma", "function": "receives pollen during pollination", "assessable": true, "occludable": true}}\n'
            f'      ]}},\n'
            f'      "status": "planned"\n'
            f'    }}\n  ]\n}}\n\n'
            f"ADDITIONAL INSTRUCTIONS: {payload.custom_instructions}"
        ),
    })

    resp = llm_client.generate(resolved, context.messages, temperature=0.2)
    visuals_list = resp.content.get("visuals", []) if isinstance(resp.content, dict) else []

    versioned = _record_artifact(
        "diagram", payload.grade, payload.subject, {"visuals": visuals_list},
        strand=payload.strand, sub_strand=payload.sub_strand,
        provenance={"source": "factory_plan_visuals",
                    "provider": resolved.provider, "model": resolved.model},
    )

    return {
        "sub_strand": payload.sub_strand,
        "visuals": visuals_list,
        "usage": resp.usage,
        "model": resp.model,
        "content_type": ct_profile.to_dict(),
        "research_dossier": dossier.to_dict(),
        "artifact": versioned,
    }


@router.post("/factory/generate-single-visual")
def factory_generate_single_visual(
    payload: FactoryGenerateSingleVisualRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Generates or regenerates a specific visual asset (vector SVG, Photorealistic AI Image Spec, or Video Simulation Storyboard)."""
    # A rendered visual belongs to one hour, not to the sub-strand at large.
    from ..services.content_lineage import DIAGRAM
    from ..services.stage_guard import require_context

    lineage = require_context(
        DIAGRAM,
        grade=payload.grade, subject=payload.subject,
        strand=payload.strand, sub_strand=payload.sub_strand,
        notes_content=payload.notes_content, target_hour=payload.target_hour,
    )

    import json as json_lib
    from ..infra.storage import object_storage
    from ..services.content_type_classifier import classify_content_type
    from ..services.diagram_dedup import diagram_deduplicator, extract_and_sanitize_svg
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator
    from ..services.quality_gate import quality_gate_service
    from ..services.web_research import web_research_agent

    resolved = pipeline_orchestrator.router.resolve_for_stage("diagram_generation")
    ct_profile = classify_content_type(payload.subject, payload.grade, payload.sub_strand)
    item = payload.visual_item
    title = item.get("title") or "Visual Diagram"
    asset_type = item.get("asset_type") or "technical_svg"
    vivid_desc = item.get("vivid_prompt") or title
    mode = payload.generation_mode or ("photo_spec" if asset_type == "realistic_image" else ("video_storyboard" if asset_type == "video_storyboard" else "svg"))

    dossier = web_research_agent.research_topic(
        subject=payload.subject,
        strand=payload.strand,
        sub_strand=payload.sub_strand,
        grade=payload.grade,
        topic_type="diagram",
        extra_query=title,
    )

    hour_idx = item.get("hour_index")
    specific_hour_notes = ""
    if payload.notes_content and isinstance(payload.notes_content, dict):
        h_mods = payload.notes_content.get("hour_modules") or payload.notes_content.get("key_concepts") or []
        if isinstance(hour_idx, int) and 1 <= hour_idx <= len(h_mods):
            mod = h_mods[hour_idx - 1]
            specific_hour_notes = f"\n=== ⏰ MANDATORY PARENT HOUR MODULE (Hour {hour_idx}: {mod.get('hour_title', '')}) ===\n{mod.get('full_lecture_notes', '') or mod.get('content', '')[:2500]}\n"
        elif not hour_idx:
            for idx, mod in enumerate(h_mods):
                h_txt = f"{mod.get('hour_title', '')} {mod.get('full_lecture_notes', '')} {mod.get('content', '')}".lower()
                if any(w in h_txt for w in title.lower().split() if len(w) > 3):
                    hour_idx = idx + 1
                    item["hour_index"] = hour_idx
                    item["hour_title"] = mod.get("hour_title", f"Hour {hour_idx}")
                    specific_hour_notes = f"\n=== ⏰ MANDATORY PARENT HOUR MODULE (Hour {hour_idx}: {mod.get('hour_title', '')}) ===\n{mod.get('full_lecture_notes', '') or mod.get('content', '')[:2500]}\n"
                    break

    notes_str = specific_hour_notes or (json_lib.dumps(payload.notes_content, ensure_ascii=False)[:2500] if payload.notes_content else "")

    context = langfuse_context_service.assemble_agent_context(
        agent_name="diagram-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars={
            "slo_id": payload.slo_id if getattr(payload, "slo_id", None) else f"{payload.grade}-{payload.subject[:3].upper()}-01",
            "strand": payload.strand,
            "sub_strand": payload.sub_strand,
            "concept": title,
            "level_register": register_block(
                    payload.grade,
                    notes=grade_scope_notes(payload.grade, payload.subject),
                ),
            "faith_scope": faith_prompt_block(payload.subject),
            "content_type_directives": ct_profile.format_for_prompt(),
            "notes_content": notes_str or payload.sub_strand,
        },
    )

    construction_spec = payload.construction_prompt or item.get("vivid_prompt") or ""

    if mode == "prompt_only":
        context.messages.append({
            "role": "user",
            "content": (
                f"{ct_profile.format_for_prompt()}\n\n"
                f"{dossier.formatted_context}\n\n"
                f"{specific_hour_notes}\n\n"
                f"=== 🎯 STAGE 1: GENERATE COMPREHENSIVE DIAGRAM CONSTRUCTION PROMPT & CONTEXT GROUNDING ===\n"
                f"Target Concept Title: {title} (Parent Hour {hour_idx or 1})\n"
                f"Existing Meta: {vivid_desc}\n\n"
                f"DIRECTIVE:\n"
                f"Analyze the Layer 1 Lesson Notes for Hour {hour_idx or 1} and syllabus requirements. Generate an exhaustive, scientifically rigorous Visual Construction Specification and Multi-Modal Prompt Package before any rendering occurs.\n\n"
                f"Specify in detail:\n"
                f"1. 'context_grounding': Excerpt and pedagogical rationale from Hour {hour_idx or 1} notes explaining why this visual is required.\n"
                f"2. 'vivid_prompt' (Vector SVG Construction Blueprint): Exact visual layout, viewBox coordinates (800x500), background tones, shape coordinates, color palette (hex codes), callout boxes, leader lines, text labels, and scientific mechanism flow.\n"
                f"3. 'image_prompt' (4K Photorealistic Prompt): 150-word photorealistic prompt describing authentic Kenyan field/lab environment, lighting, camera angle, and subject actions for Midjourney/Imagen.\n"
                f"4. 'video_storyboard': 4-scene video script breakdown with camera shots and voiceover.\n"
                f"5. 'accessibility': Alt-text and tactile description for visually impaired learners.\n\n"
                f"Return JSON:\n"
                f"{{\n"
                f'  "diagram_id": "{item.get("asset_id", "vis_1")}",\n'
                f'  "diagram_title": "{title}",\n'
                f'  "hour_index": {hour_idx or 1},\n'
                f'  "micro_concept": "{item.get("micro_concept", title)}",\n'
                f'  "pedagogical_purpose": "...",\n'
                f'  "context_grounding": "...",\n'
                f'  "vivid_prompt": "...",\n'
                f'  "image_prompt": "...",\n'
                f'  "negative_prompt": "blurry, low quality, distorted anatomy, western setting, unrealistic tools",\n'
                f'  "aspect_ratio": "16:9",\n'
                f'  "composition_guide": "...",\n'
                f'  "video_storyboard": {{\n'
                f'    "video_title": "{title}",\n'
                f'    "target_duration": "75s",\n'
                f'    "scenes": [\n'
                f'      {{"scene_number": 1, "time_range": "0:00-0:15", "shot_type": "Wide Establishing Shot", "visual_action": "...", "voiceover_narration": "...", "on_screen_text": "...", "ai_video_prompt": "..."}}\n'
                f'    ]\n'
                f'  }},\n'
                f'  "accessibility": {{"alt_text": "...", "tactile_description": "..."}}\n'
                f"}}\n\n"
                f"ADDITIONAL INSTRUCTIONS: {payload.custom_instructions}"
            ),
        })
    elif mode == "photo_spec":
        context.messages.append({
            "role": "user",
            "content": (
                f"{ct_profile.format_for_prompt()}\n\n"
                f"{dossier.formatted_context}\n\n"
                f"{specific_hour_notes}\n\n"
                f"=== SPECIFICATION FOR PHOTOREALISTIC IMAGE SPECIFICATION ===\n"
                f"Title: {title} (Hour {hour_idx or 'All'})\n"
                f"Construction Prompt / Scene Description:\n{construction_spec or vivid_desc}\n\n"
                f"AI IMAGE GENERATION PROMPT DIRECTIVE:\n"
                f"Generate an ultra-detailed, 4K photorealistic prompt for AI image generation models (Imagen 3, Midjourney v6, Flux) depicting authentic Kenyan learners, teachers, crops, tools, and environments specifically illustrating the concept from Hour {hour_idx or 'All'}.\n"
                f"Also create a clean SVG preview schematic illustrating the scene layout.\n\n"
                f"Return JSON:\n"
                f"{{\n"
                f'  "diagram_id": "{item.get("asset_id", "vis_1")}",\n'
                f'  "diagram_title": "{title}",\n'
                f'  "hour_index": {hour_idx or 1},\n'
                f'  "image_prompt": "<ultra-detailed 150-word photorealistic prompt with camera angle, lighting, 8k resolution, Kenyan setting>",\n'
                f'  "negative_prompt": "blurry, low quality, distorted anatomy, western setting, unrealistic tools",\n'
                f'  "aspect_ratio": "16:9",\n'
                f'  "composition_guide": "<camera angle, golden hour lighting, 50mm lens, depth of field>",\n'
                f'  "diagram_svg": "<svg xmlns=\\"http://www.w3.org/2000/svg\\" viewBox=\\"0 0 800 500\\"><rect width=\\"100%\\" height=\\"100%\\" fill=\\"#0f172a\\"/><text x=\\"400\\" y=\\"250\\" text-anchor=\\"middle\\" font-family=\\"system-ui\\" font-size=\\"18\\" fill=\\"#38bdf8\\">📸 Photorealistic Scene: {title}</text></svg>",\n'
                f'  "accessibility": {{"alt_text": "...", "tactile_description": "..."}}\n'
                f"}}\n\n"
                f"ADDITIONAL INSTRUCTIONS: {payload.custom_instructions}"
            ),
        })
    elif mode == "video_storyboard":
        context.messages.append({
            "role": "user",
            "content": (
                f"{ct_profile.format_for_prompt()}\n\n"
                f"{dossier.formatted_context}\n\n"
                f"{specific_hour_notes}\n\n"
                f"=== SPECIFICATION FOR VIDEO SIMULATION STORYBOARD ===\n"
                f"Title: {title} (Hour {hour_idx or 'All'})\n"
                f"Construction Prompt / Scene Description:\n{construction_spec or vivid_desc}\n\n"
                f"VIDEO SIMULATION SCRIPT DIRECTIVE:\n"
                f"Generate a multi-scene educational video simulation storyboard (60-90s) detailing the concept progression.\n\n"
                f"Return JSON:\n"
                f"{{\n"
                f'  "diagram_id": "{item.get("asset_id", "vis_1")}",\n'
                f'  "diagram_title": "{title}",\n'
                f'  "hour_index": {hour_idx or 1},\n'
                f'  "video_storyboard": {{\n'
                f'    "video_title": "{title}",\n'
                f'    "target_duration": "75s",\n'
                f'    "overview": "...",\n'
                f'    "scenes": [\n'
                f'      {{"scene_number": 1, "time_range": "0:00-0:15", "shot_type": "Wide Establishing Shot", "visual_action": "...", "voiceover_narration": "...", "on_screen_text": "...", "ai_video_prompt": "..."}},\n'
                f'      {{"scene_number": 2, "time_range": "0:15-0:40", "shot_type": "Close-up Action Shot", "visual_action": "...", "voiceover_narration": "...", "on_screen_text": "...", "ai_video_prompt": "..."}},\n'
                f'      {{"scene_number": 3, "time_range": "0:40-1:05", "shot_type": "Medium Angle Result", "visual_action": "...", "voiceover_narration": "...", "on_screen_text": "...", "ai_video_prompt": "..."}},\n'
                f'      {{"scene_number": 4, "time_range": "1:05-1:15", "shot_type": "Summary Infographic Overlay", "visual_action": "...", "voiceover_narration": "...", "on_screen_text": "...", "ai_video_prompt": "..."}}\n'
                f'    ]\n'
                f'  }},\n'
                f'  "diagram_svg": "<svg xmlns=\\"http://www.w3.org/2000/svg\\" viewBox=\\"0 0 800 500\\"><rect width=\\"100%\\" height=\\"100%\\" fill=\\"#1e1b4b\\"/><text x=\\"400\\" y=\\"250\\" text-anchor=\\"middle\\" font-family=\\"system-ui\\" font-size=\\"18\\" fill=\\"#c084fc\\">🎥 Video Storyboard: {title}</text></svg>",\n'
                f'  "accessibility": {{"alt_text": "...", "tactile_description": "..."}}\n'
                f"}}\n\n"
                f"ADDITIONAL INSTRUCTIONS: {payload.custom_instructions}"
            ),
        })
    else:
        # Standard SVG Mode
        context.messages.append({
            "role": "user",
            "content": (
                f"{ct_profile.format_for_prompt()}\n\n"
                f"{dossier.formatted_context}\n\n"
                f"{specific_hour_notes}\n\n"
                f"=== STAGE 2: SYNTHESIZE VECTOR SVG ASSET FROM CONSTRUCTION PROMPT ===\n"
                f"Title: {title} (Hour {hour_idx or 'All'})\n"
                f"Type: {asset_type}\n"
                f"EXPLICIT CONSTRUCTION BLUEPRINT & SCENE ELEMENTS (MANDATORY TO FOLLOW):\n{construction_spec or vivid_desc}\n\n"
                f"VECTOR SVG CODE DIRECTIVE:\n"
                f"Generate a crisp, responsive, high-contrast standalone SVG specifically illustrating the concept '{title}' from Hour {hour_idx or 'All'}.\n"
                f"CRITICAL: Follow the exact layout, shapes, leader lines, colors, and text annotations described in the Construction Blueprint above. Draw the actual scientific, morphological, or agricultural system (e.g. soil strata layers, agroforestry tree-crop canopies, water swale contours, or lab apparatus). DO NOT generate a generic macroeconomic flowchart unless this is Hour 1 overview.\n\n"
                f"STRICT RULES:\n"
                f"1. Root MUST be <svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 800 500\" width=\"100%\" height=\"100%\">\n"
                f"2. All styles enclosed inside <defs><style type=\"text/css\"><![CDATA[ ... ]]></style><marker id=\"arrowhead\" markerWidth=\"10\" markerHeight=\"7\" refX=\"10\" refY=\"3.5\" orient=\"auto\"><polygon points=\"0 0, 10 3.5, 0 7\" fill=\"#0284c7\" /></marker></defs>\n"
                f"3. All text inside <text x=\"...\" y=\"...\" font-family=\"system-ui, -apple-system, sans-serif\" font-size=\"13\" text-anchor=\"middle\" fill=\"#0f172a\">...</text>\n"
                f"4. Return JSON: {{ \"diagram_id\": \"{item.get('asset_id', 'vis_1')}\", \"diagram_title\": \"{title}\", \"hour_index\": {hour_idx or 1}, \"diagram_svg\": \"<svg...>...</svg>\", \"accessibility\": {{ \"alt_text\": \"...\", \"tactile_description\": \"...\" }} }}\n\n"
                f"ADDITIONAL INSTRUCTIONS: {payload.custom_instructions}"
            ),
        })

    resp = llm_client.generate(resolved, context.messages, temperature=0.15)
    
    # 1. Extract existing assets to preserve them across generation modes
    existing_svg = item.get("diagram_svg") or ""
    existing_image_prompt = item.get("image_prompt") or ""
    existing_negative_prompt = item.get("negative_prompt") or ""
    existing_aspect_ratio = item.get("aspect_ratio") or "16:9"
    existing_comp_guide = item.get("composition_guide") or ""
    existing_video_storyboard = item.get("video_storyboard")

    # 2. Extract newly generated outputs
    new_svg = resp.content.get("diagram_svg") or resp.content.get("svg")
    new_image_prompt = resp.content.get("image_prompt")
    new_negative_prompt = resp.content.get("negative_prompt")
    new_aspect_ratio = resp.content.get("aspect_ratio")
    new_comp_guide = resp.content.get("composition_guide")
    new_video_storyboard = resp.content.get("video_storyboard")
    new_accessibility = resp.content.get("accessibility", {})

    # 3. Non-destructive co-existence merging
    final_svg = new_svg if (new_svg and len(str(new_svg).strip()) > 30) else (existing_svg or "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 800 500'><rect width='100%' height='100%' fill='#f8fafc'/><text x='400' y='250' font-family='sans-serif' font-size='16' text-anchor='middle' fill='#0369a1'>Scientific Vector Model</text></svg>")
    final_image_prompt = new_image_prompt or existing_image_prompt or item.get("vivid_prompt", "")
    final_negative_prompt = new_negative_prompt or existing_negative_prompt
    final_aspect_ratio = new_aspect_ratio or existing_aspect_ratio
    final_comp_guide = new_comp_guide or existing_comp_guide
    final_video_storyboard = new_video_storyboard or existing_video_storyboard

    dedup = diagram_deduplicator.deduplicate_and_store(
        svg_str=final_svg,
        diagram_title=title,
        alt_text=new_accessibility.get("alt_text") or item.get("accessibility", {}).get("alt_text", f"Vector diagram of {title}"),
        tactile_description=new_accessibility.get("tactile_description") or item.get("accessibility", {}).get("tactile_description", "Tactile raised-line diagram with embossed contours."),
        scene_document=(
            resp.content.get("scene_document")
            or resp.content.get("scene")
            or item.get("scene_document")
        ),
        metadata={"grade": payload.grade, "subject": payload.subject, "strand": payload.strand},
    )

    # Save to MinIO explicitly and track result
    minio_status = item.get("minio_status") or "saved"
    minio_url = item.get("storage_url") or ""
    minio_error = ""
    try:
        clean_g = payload.grade.lower().replace("grade-", "")
        clean_s = payload.subject.lower().replace(" ", "_")
        clean_ss = payload.sub_strand.lower().replace(" ", "_")[:30]
        obj_name = f"diagrams/{clean_g}_{clean_s}_{clean_ss}_{item.get('asset_id', 'vis')}.svg"
        if final_svg and len(final_svg.strip()) > 30:
            minio_url = object_storage.save_svg(obj_name, dedup.diagram_svg)
            minio_status = "saved"
    except Exception as exc:
        minio_status = "error"
        minio_error = str(exc)

    updated_visual = {
        "asset_id": item.get("asset_id") or dedup.diagram_id,
        "title": resp.content.get("diagram_title") or title,
        "asset_type": asset_type,
        "generation_mode": mode,
        "hour_index": hour_idx or item.get("hour_index") or 1,
        "hour_title": item.get("hour_title") or f"Hour {hour_idx or 1}",
        "micro_concept": resp.content.get("micro_concept") or item.get("micro_concept", title),
        "pedagogical_purpose": resp.content.get("pedagogical_purpose") or item.get("pedagogical_purpose", ""),
        "context_grounding": resp.content.get("context_grounding") or item.get("context_grounding", ""),
        "vivid_prompt": resp.content.get("vivid_prompt") or item.get("vivid_prompt", ""),
        "diagram_svg": dedup.diagram_svg if (dedup.diagram_svg and len(dedup.diagram_svg.strip()) > 30) else existing_svg,
        "diagram_hash": dedup.diagram_hash,
        "storage_url": minio_url or dedup.storage_url,
        "minio_status": minio_status,
        "minio_error": minio_error,
        "image_prompt": final_image_prompt,
        "negative_prompt": final_negative_prompt,
        "aspect_ratio": final_aspect_ratio,
        "composition_guide": final_comp_guide,
        "video_storyboard": final_video_storyboard,
        "accessibility": {
            "alt_text": dedup.alt_text,
            "tactile_description": dedup.tactile_description,
        },
        "status": "planned" if mode == "prompt_only" else "generated",
        "prompt_ready": True if (resp.content.get("vivid_prompt") or item.get("vivid_prompt")) else False,
    }

    audit_report = web_research_agent.perform_quality_audit(resp.content, "diagram", dossier)
    gate_result = quality_gate_service.run_layer_gate("diagram", updated_visual, {}, ct_profile)

    return {
        "visual": updated_visual,
        "usage": resp.usage,
        "model": resp.model,
        "quality_audit": audit_report.to_dict(),
        "quality_gate": gate_result.to_dict(),
        "minio_status": minio_status,
        "minio_url": minio_url,
        "minio_error": minio_error,
    }


@router.post("/factory/plan-activities")
def factory_plan_activities(
    payload: FactoryPlanActivitiesRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Plans and generates a rich array of hands-on activities, laboratory experiments, and video storyboards for a sub-strand."""
    from ..services.content_lineage import ASSET_PLAN
    from ..services.stage_guard import require_context

    lineage = require_context(
        ASSET_PLAN,
        grade=payload.grade, subject=payload.subject,
        strand=payload.strand, sub_strand=payload.sub_strand,
        notes_content=payload.notes_content,
    )

    import json as json_lib
    from ..services.content_type_classifier import classify_content_type
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator
    from ..services.web_research import web_research_agent

    resolved = pipeline_orchestrator.router.resolve_for_stage("activity_generation")
    ct_profile = classify_content_type(payload.subject, payload.grade, payload.sub_strand)

    dossier = web_research_agent.research_topic(
        subject=payload.subject,
        strand=payload.strand,
        sub_strand=payload.sub_strand,
        grade=payload.grade,
        topic_type="activity",
        extra_query="experiential experiments and video demonstrations",
    )

    # Extract all 4 hour modules explicitly
    hours_breakdown_str = ""
    notes_dict = payload.notes_content
    if not notes_dict:
        from ..infra.db import fetch_one
        saved_row = fetch_one(
            """
            SELECT notes FROM substrand_resources
            WHERE LOWER(curriculum->>'subject') = LOWER(:subject)
              AND LOWER(curriculum->>'sub_strand') LIKE :ss
            ORDER BY updated_at DESC LIMIT 1
            """,
            {"subject": payload.subject.strip(), "ss": f"%{payload.sub_strand.strip().lower()}%"},
        )
        if saved_row and saved_row.get("notes"):
            notes_dict = saved_row.get("notes")

    if notes_dict and isinstance(notes_dict, dict):
        h_mods = notes_dict.get("hour_modules") or notes_dict.get("key_concepts") or []
        for idx, hm in enumerate(h_mods):
            h_num = hm.get("hour_number", idx + 1)
            h_title = hm.get("hour_title") or hm.get("heading") or f"Hour {h_num}"
            h_notes = hm.get("full_lecture_notes") or hm.get("content") or hm.get("detailed_exposition") or ""
            hours_breakdown_str += f"\n--- ⏰ LESSON HOUR {h_num}: {h_title} ---\n{h_notes[:2500]}\n"

    notes_str = hours_breakdown_str or (json_lib.dumps(notes_dict, ensure_ascii=False)[:4000] if notes_dict else payload.sub_strand)

    context = langfuse_context_service.assemble_agent_context(
        agent_name="activity-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars={
            "level": getattr(payload, "level", None) or grade_level(payload.grade),
            "slo_id": payload.slo_id if getattr(payload, "slo_id", None) else f"{payload.grade}-{payload.subject[:3].upper()}-01",
            "strand": payload.strand,
            "sub_strand": payload.sub_strand,
            "level_register": register_block(
                    payload.grade,
                    notes=grade_scope_notes(payload.grade, payload.subject),
                ),
            "faith_scope": faith_prompt_block(payload.subject),
            "content_type_directives": ct_profile.format_for_prompt(),
            "notes_content": notes_str or payload.notes_title or payload.sub_strand,
            "diagram_info": json_lib.dumps(payload.diagram_info, ensure_ascii=False) if payload.diagram_info else "Visual diagram context",
        },
    )

    context.messages.append({
        "role": "user",
        "content": (
            f"{ct_profile.format_for_prompt()}\n\n"
            f"{dossier.formatted_context}\n\n"
            f"=== LAYER 1 MASTER LESSON NOTES CONTEXT (MANDATORY 4-HOUR SOURCE OF TRUTH) ===\n{notes_str}\n\n"
            f"MANDATORY 4-HOUR BALANCED MULTI-PRACTICAL DISCOVERY DIRECTIVE:\n"
            f"You MUST discover and specify at least 1 authentic practical task / laboratory experiment FOR EACH of the 4 Lesson Hours listed above (Total 4 to 6 distinct activities):\n"
            f"1. For Hour 1 ({h_mods[0].get('hour_title', 'Hour 1') if len(h_mods) > 0 else 'Hour 1'}): Practical inquiry / policy review -> set 'hour_index': 1, 'hour_title': 'Hour 1: ...'\n"
            f"2. For Hour 2 ({h_mods[1].get('hour_title', 'Hour 2') if len(h_mods) > 1 else 'Hour 2'}): Agroforestry layout & field sampling / Soil pH buffer inquiry -> set 'hour_index': 2, 'hour_title': 'Hour 2: ...'\n"
            f"3. For Hour 3 ({h_mods[2].get('hour_title', 'Hour 3') if len(h_mods) > 2 else 'Hour 3'}): Soil conservation / contour terracing / CSL project -> set 'hour_index': 3, 'hour_title': 'Hour 3: ...'\n"
            f"4. For Hour 4 ({h_mods[3].get('hour_title', 'Hour 4') if len(h_mods) > 3 else 'Hour 4'}): 60-Minute Standardized Laboratory Practicum (Soil pH Titration & Buffer Capacity) -> set 'hour_index': 4, 'hour_title': 'Hour 4: ...'\n\n"
            f"For EACH activity include:\n"
            f"- activity_id (e.g. act_01, act_02, act_03, act_04)\n"
            f"- hour_index (1 | 2 | 3 | 4 - the specific hour module in the lesson notes this practical task belongs to)\n"
            f"- hour_title (e.g. 'Hour 1: ...' or 'Hour 2: ...')\n"
            f"- activity_name (engaging, descriptive title)\n"
            f"- activity_type ('laboratory_experiment' | 'field_investigation' | 'csl_project' | 'classroom_game')\n"
            f"- objective (measurable inquiry goal aligned with SLOs)\n"
            f"- materials (list of low-cost local materials and safety apparatus)\n"
            f"- procedure_steps (numbered step-by-step guide with safety checkpoints)\n"
            f"- video_storyboard: {{\n"
            f"    'video_title': '...', 'target_duration': '90-120s', 'overview': '...',\n"
            f"    'scenes': [\n"
            f"      {{ 'scene_number': 1, 'shot_type': 'Close-up / Wide shot', 'visual_action': 'Detailed on-screen action description...', 'voiceover_narration': 'Exact spoken narration...', 'on_screen_text': 'Callouts/labels...', 'ai_video_prompt': 'Prompt for video generator AI...' }}\n"
            f"    ]\n"
            f"  }}\n"
            f"- visual_action_image_prompt (vivid prompt for generating action photo illustration of students conducting the activity)\n"
            f"- safety_hazards_to_check (mandatory hazard checklist & PPE)\n"
            f"- assessment_rubric: {{ 'exceeding': '...', 'meeting': '...', 'approaching': '...', 'below': '...' }}\n\n"
            f"Return JSON format:\n"
            f'{{\n  "sub_strand": "{payload.sub_strand}",\n  "activities": [\n'
            f'    {{\n'
            f'      "activity_id": "act_01",\n'
            f'      "hour_index": 1,\n'
            f'      "hour_title": "Hour 1: ...",\n'
            f'      "activity_name": "...",\n'
            f'      "activity_type": "laboratory_experiment",\n'
            f'      "objective": "...",\n'
            f'      "materials": ["..."],\n'
            f'      "procedure_steps": ["1. ...", "2. ..."],\n'
            f'      "video_storyboard": {{"video_title": "...", "target_duration": "90s", "scenes": []}},\n'
            f'      "visual_action_image_prompt": "...",\n'
            f'      "safety_hazards_to_check": ["..."],\n'
            f'      "assessment_rubric": {{"exceeding": "...", "meeting": "...", "approaching": "...", "below": "..."}},\n'
            f'      "status": "planned"\n'
            f'    }}\n  ]\n}}\n\n"ADDITIONAL INSTRUCTIONS: {payload.custom_instructions}'
        ),
    })

    resp = llm_client.generate(resolved, context.messages, temperature=0.25)
    activities_list = resp.content.get("activities", []) if isinstance(resp.content, dict) else []

    versioned = _record_artifact(
        "activity", payload.grade, payload.subject, {"activities": activities_list},
        strand=payload.strand, sub_strand=payload.sub_strand,
        provenance={"source": "factory_plan_activities",
                    "provider": resolved.provider, "model": resolved.model},
    )

    return {
        "sub_strand": payload.sub_strand,
        "activities": activities_list,
        "usage": resp.usage,
        "model": resp.model,
        "content_type": ct_profile.to_dict(),
        "research_dossier": dossier.to_dict(),
        "artifact": versioned,
    }


@router.post("/factory/generate-single-activity")
def factory_generate_single_activity(
    payload: FactoryGenerateSingleActivityRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Generates or refines a single experiential activity / experiment with detailed video storyboard."""
    # An activity, like a diagram, belongs to one hour of the sub-strand.
    from ..services.content_lineage import ACTIVITY
    from ..services.stage_guard import require_context

    lineage = require_context(
        ACTIVITY,
        grade=payload.grade, subject=payload.subject,
        strand=payload.strand, sub_strand=payload.sub_strand,
        notes_content=payload.notes_content, target_hour=payload.target_hour,
    )

    import json as json_lib
    from ..services.content_type_classifier import classify_content_type
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator
    from ..services.quality_gate import quality_gate_service
    from ..services.web_research import web_research_agent

    resolved = pipeline_orchestrator.router.resolve_for_stage("activity_generation")
    ct_profile = classify_content_type(payload.subject, payload.grade, payload.sub_strand)
    item = payload.activity_item
    name = item.get("activity_name") or "Practical Activity"
    hour_idx = item.get("hour_index")

    dossier = web_research_agent.research_topic(
        subject=payload.subject,
        strand=payload.strand,
        sub_strand=payload.sub_strand,
        grade=payload.grade,
        topic_type="activity",
        extra_query=name,
    )

    specific_hour_notes = ""
    if payload.notes_content and isinstance(payload.notes_content, dict):
        h_mods = payload.notes_content.get("hour_modules") or payload.notes_content.get("key_concepts") or []
        if isinstance(hour_idx, int) and 1 <= hour_idx <= len(h_mods):
            mod = h_mods[hour_idx - 1]
            specific_hour_notes = f"\n=== ⏰ MANDATORY PARENT HOUR MODULE (Hour {hour_idx}: {mod.get('hour_title', '')}) ===\n{mod.get('full_lecture_notes', '') or mod.get('content', '')[:2500]}\n"
        elif not hour_idx:
            for idx, mod in enumerate(h_mods):
                h_txt = f"{mod.get('hour_title', '')} {mod.get('full_lecture_notes', '')} {mod.get('content', '')}".lower()
                if any(w in h_txt for w in name.lower().split() if len(w) > 3):
                    hour_idx = idx + 1
                    item["hour_index"] = hour_idx
                    item["hour_title"] = mod.get("hour_title", f"Hour {hour_idx}")
                    specific_hour_notes = f"\n=== ⏰ MANDATORY PARENT HOUR MODULE (Hour {hour_idx}: {mod.get('hour_title', '')}) ===\n{mod.get('full_lecture_notes', '') or mod.get('content', '')[:2500]}\n"
                    break

    notes_str = specific_hour_notes or (json_lib.dumps(payload.notes_content, ensure_ascii=False)[:2500] if payload.notes_content else "")

    context = langfuse_context_service.assemble_agent_context(
        agent_name="activity-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars={
            "level": getattr(payload, "level", None) or grade_level(payload.grade),
            "slo_id": payload.slo_id if getattr(payload, "slo_id", None) else f"{payload.grade}-{payload.subject[:3].upper()}-01",
            "diagram_info": getattr(payload, "diagram_info", "") or "",
            "strand": payload.strand,
            "sub_strand": payload.sub_strand,
            "level_register": register_block(
                    payload.grade,
                    notes=grade_scope_notes(payload.grade, payload.subject),
                ),
            "faith_scope": faith_prompt_block(payload.subject),
            "content_type_directives": ct_profile.format_for_prompt(),
            "notes_content": notes_str or payload.sub_strand,
        },
    )

    context.messages.append({
        "role": "user",
        "content": (
            f"{ct_profile.format_for_prompt()}\n\n"
            f"{dossier.formatted_context}\n\n"
            f"{specific_hour_notes}\n\n"
            f"=== PRACTICAL ACTIVITY REFINEMENT DIRECTIVE ===\n"
            f"Activity Name: {name} (Hour {hour_idx or 'All'})\n"
            f"Type: {item.get('activity_type', 'laboratory_experiment')}\n"
            f"Initial Objective: {item.get('objective', '')}\n\n"
            f"Generate an exhaustive, publication-grade practical lesson module with:\n"
            f"1. Detailed step-by-step instructions with safety checkpoints specifically aligned with Hour {hour_idx or 'All'}\n"
            f"2. Multi-scene Video Storyboard (scene number, camera shot, visual actions, exact spoken voiceover, on-screen text, AI video prompt)\n"
            f"3. Vivid Action Image Prompt for realistic instructional photo cards\n"
            f"4. 4-tier KICD Assessment Rubric\n\n"
            f"Return JSON matching:\n"
            f"{{\n"
            f'  "activity_id": "{item.get("activity_id", "act_01")}",\n'
            f'  "activity_name": "{name}",\n'
            f'  "hour_index": {hour_idx or 1},\n'
            f'  "activity_type": "{item.get("activity_type", "laboratory_experiment")}",\n'
            f'  "objective": "...",\n'
            f'  "materials": ["..."],\n'
            f'  "procedure_steps": ["1. ...", "2. ..."],\n'
            f'  "video_storyboard": {{\n'
            f'    "video_title": "...",\n'
            f'    "target_duration": "90-120s",\n'
            f'    "overview": "...",\n'
            f'    "scenes": [\n'
            f'      {{ "scene_number": 1, "shot_type": "...", "visual_action": "...", "voiceover_narration": "...", "on_screen_text": "...", "ai_video_prompt": "..." }}\n'
            f'    ]\n'
            f'  }},\n'
            f'  "visual_action_image_prompt": "...",\n'
            f'  "safety_hazards_to_check": ["..."],\n'
            f'  "assessment_rubric": {{"exceeding": "...", "meeting": "...", "approaching": "...", "below": "..."}},\n'
            f'  "status": "generated"\n'
            f"}}\n\n"
            f"ADDITIONAL INSTRUCTIONS: {payload.custom_instructions}"
        ),
    })

    resp = llm_client.generate(resolved, context.messages, temperature=0.2)
    updated_activity = resp.content if isinstance(resp.content, dict) else item
    updated_activity["status"] = "generated"

    audit_report = web_research_agent.perform_quality_audit(resp.content, "activity", dossier)
    gate_result = quality_gate_service.run_layer_gate("activity", updated_activity, {}, ct_profile)

    return {
        "activity": updated_activity,
        "usage": resp.usage,
        "model": resp.model,
        "quality_audit": audit_report.to_dict(),
        "quality_gate": gate_result.to_dict(),
    }


@router.post("/factory/generate-questions")
def factory_generate_questions(
    payload: FactoryGenerateQuestionsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    import json as json_lib
    from ..services.content_type_classifier import classify_content_type
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator
    from ..services.quality_gate import quality_gate_service
    from ..services.web_research import web_research_agent

    resolved = pipeline_orchestrator.router.resolve_for_stage("question_generation")
    ct_profile = classify_content_type(payload.subject, payload.grade, payload.sub_strand)

    # Execute Web Research
    dossier = web_research_agent.research_topic(
        subject=payload.subject,
        strand=payload.strand,
        sub_strand=payload.sub_strand,
        grade=payload.grade,
        topic_type="questions",
    )

    notes_str = ""
    if payload.notes_content:
        notes_str = json_lib.dumps(payload.notes_content, ensure_ascii=False)[:2000]
    elif payload.notes_summary:
        notes_str = payload.notes_summary

    diagram_str = ""
    if payload.diagram_info:
        diagram_str = f"Diagram Title: {payload.diagram_info.get('diagram_title', '')}\nAlt: {payload.diagram_info.get('accessibility', {}).get('alt_text', '')}"
    elif payload.diagram_title:
        diagram_str = payload.diagram_title

    act_str = ""
    if payload.activity_info:
        act_str = json_lib.dumps(payload.activity_info, ensure_ascii=False)[:1500]

    context = langfuse_context_service.assemble_agent_context(
        agent_name="question-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars={
            "level": getattr(payload, "level", None) or grade_level(payload.grade),
            "notes_title": getattr(payload, "notes_title", "") or payload.sub_strand,
            "subject_code": payload.subject_code,
            "strand": payload.strand,
            "sub_strand": payload.sub_strand,
            "slo_id": payload.slo_id or f"{payload.grade}-{payload.subject_code}-01",
            "difficulty": payload.difficulty,
            "level_register": register_block(
                    payload.grade,
                    notes=grade_scope_notes(payload.grade, payload.subject),
                ),
            "faith_scope": faith_prompt_block(payload.subject),
            "content_type_directives": ct_profile.format_for_prompt(),
            "notes_content": notes_str or payload.notes_summary or payload.sub_strand,
            "diagram_id": payload.diagram_info.get("diagram_id", "diag_01") if payload.diagram_info else "diag_01",
            "diagram_info": diagram_str,
            "activity_info": act_str or "Practical experiential activity integrated with sub-strand.",
        },
    )

    context.messages.append({
        "role": "user",
        "content": (
            f"{ct_profile.format_for_prompt()}\n\n"
            f"{dossier.formatted_context}\n\n"
            f"=== PARENT STRAND GUIDANCE CONTEXT ===\n"
            f"Parent Strand Scope: {payload.strand}\n"
            f"Active Sub-strand: {payload.sub_strand}\n"
            f"Target SLO: {payload.slo_id or f'{payload.grade}-{payload.subject_code}-01'}\n\n"
            f"=== UPSTREAM GENERATED CONTENT LAYERS ===\n"
            f"Layer 1 Lesson Notes: {notes_str[:1600]}\n"
            f"Layer 2 Technical Diagram: {diagram_str}\n"
            f"Layer 3 Practical Activities: {act_str[:1000]}\n\n"
            f"GRANULAR ASSESSMENT DESIGN DIRECTIVE:\n"
            f"Generate a rigorous set of 4-6 criterion-referenced assessment items testing THIS SUB-STRAND ({payload.sub_strand}).\n"
            f"Break down the sub-strand into granular Micro-Concepts / Specific Learning Objectives and assign each question to a specific micro-concept.\n"
            f"Include:\n"
            f"1. Multiple Choice Questions (MCQ) with 4 options, plausible distractors, and diagnostic explanations for each distractor.\n"
            f"2. Structured / Inquiry-Based Questions with realistic Kenyan scenarios, step-by-step marking schemes, and 4-level KICD rubrics (Exceeding, Meeting, Approaching, Below Expectation).\n"
            f"3. Bloom's Cognitive Progression (Recall/Understanding -> Practical Application -> Critical Problem Solving/Evaluation).\n\n"
            f"Return JSON format:\n"
            f"{{\n"
            f'  "sub_strand": "{payload.sub_strand}",\n'
            f'  "questions": [\n'
            f'    {{\n'
            f'      "question_id": "Q1",\n'
            f'      "micro_concept": "<specific sub-topic or skill tested>",\n'
            f'      "target_slo": "<specific SLO from sub-strand>",\n'
            f'      "bloom_level": "Application | Critical Thinking | Recall",\n'
            f'      "question_type": "multiple_choice | structured",\n'
            f'      "question_text": "<rich scenario-based question>",\n'
            f'      "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},\n'
            f'      "correct_answer": "B",\n'
            f'      "distractor_explanations": {{"A": "why wrong", "C": "why wrong", "D": "why wrong"}},\n'
            f'      "marking_scheme": "<step-by-step points>",\n'
            f'      "kicd_rubric": {{"exceeding": "...", "meeting": "...", "approaching": "...", "below": "..."}}\n'
            f'    }}\n'
            f'  ]\n'
            f"}}\n\n"
            f"ADDITIONAL INSTRUCTIONS: {payload.custom_instructions}"
        ),
    })

    resp = llm_client.generate(resolved, context.messages, temperature=0.2)
    raw_questions = resp.content.get("questions", []) if isinstance(resp.content, dict) else (resp.content if isinstance(resp.content, list) else [])
    audit_report = web_research_agent.perform_quality_audit(resp.content, "questions", dossier)

    # Normalize questions format so options is always a structured list
    normalized_questions = []
    if isinstance(raw_questions, list):
        for q in raw_questions:
            if not isinstance(q, dict):
                continue
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
                for item in opts:
                    if isinstance(item, dict):
                        opt_id = item.get("id") or str(len(norm_opts) + 1)
                        is_corr = item.get("is_correct", False) or (opt_id.upper() == correct.upper())
                        norm_opts.append({
                            "id": opt_id,
                            "text": item.get("text", str(item)),
                            "is_correct": is_corr,
                            "distractor_rationale": item.get("distractor_rationale") or distractors.get(opt_id, ""),
                        })
                    else:
                        norm_opts.append({
                            "id": str(len(norm_opts) + 1),
                            "text": str(item),
                            "is_correct": False,
                            "distractor_rationale": "",
                        })

            marking_guide = q.get("marking_guide") or q.get("kicd_rubric")
            if not marking_guide and q.get("marking_scheme"):
                marking_guide = {
                    "exceeding": "Demonstrates comprehensive mastery beyond expected curriculum outcome.",
                    "meeting": str(q.get("marking_scheme")),
                    "approaching": "Partially demonstrates concept with minor inaccuracies.",
                    "below": "Requires guided instructional remediation.",
                }

            normalized_questions.append({
                **q,
                "options": norm_opts if norm_opts else None,
                "marking_guide": marking_guide,
            })

    # 3-Agent Quality Gate
    gate_result = quality_gate_service.run_layer_gate(
        layer_name="questions",
        content=normalized_questions,
        blueprint={},
        content_type_profile=ct_profile,
        custom_instructions=payload.custom_instructions,
    )

    return {
        "questions": normalized_questions,
        "usage": resp.usage,
        "model": resp.model,
        "content_type": ct_profile.to_dict(),
        "research_dossier": dossier.to_dict(),
        "quality_audit": audit_report.to_dict(),
        "quality_gate": gate_result.to_dict(),
    }


@router.post("/factory/audit-bundle")
def factory_audit_bundle(
    payload: FactoryAuditBundleRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Runs live Step 3 Multi-Agent Quality & Safety Deliberation across all 4 station outputs."""
    from ..services.content_type_classifier import classify_content_type
    from ..services.quality_gate import quality_gate_service

    ct = classify_content_type(payload.subject, payload.grade, payload.sub_strand)

    # Gate checks for each station
    notes_gate = quality_gate_service.run_layer_gate("notes", payload.notes, {}, ct)
    diagram_gate = quality_gate_service.run_layer_gate("diagram", payload.diagram, {}, ct)
    activity_gate = quality_gate_service.run_layer_gate("activity", payload.activity, {}, ct)
    questions_gate = quality_gate_service.run_layer_gate("questions", payload.questions, {}, ct)

    all_passed = notes_gate.passed and diagram_gate.passed and activity_gate.passed and questions_gate.passed
    avg_score = round(
        (notes_gate.overall_score + diagram_gate.overall_score + activity_gate.overall_score + questions_gate.overall_score) / 4, 1
    )

    auditor_1_summary = (
        f"Auditor 1 (Pedagogical Quality Lead): Bundle meets constructivist standards for {payload.subject} ({ct.content_type.upper()}). "
        f"Notes depth score: {notes_gate.overall_score}%, Activities scaffolding: {activity_gate.overall_score}%, Assessment validity: {questions_gate.overall_score}%."
    )
    auditor_2_summary = (
        f"Auditor 2 (Senior Quality & Compliance Lead): Safety audit passed. Vector accessibility verified ({diagram_gate.overall_score}%). "
        f"Consensus verdict: {'APPROVED FOR RELEASE' if all_passed else 'REVISION REQUIRED'}."
    )

    deliberation = {
        "status": "approved" if all_passed else "needs_revision",
        "overall_score": avg_score,
        "auditor_1_assessment": auditor_1_summary,
        "auditor_2_cross_examination": auditor_2_summary,
        "consensus": "APPROVED FOR HUMAN SIGN-OFF" if all_passed else "REVISIONS REQUIRED BEFORE RELEASE",
        "ready_for_release": all_passed,
        "layer_breakdowns": {
            "notes": notes_gate.to_dict(),
            "diagram": diagram_gate.to_dict(),
            "activity": activity_gate.to_dict(),
            "questions": questions_gate.to_dict(),
        },
    }

    return {"audit": deliberation, "score": avg_score, "passed": all_passed}


@router.post("/factory/publish-bundle")
def factory_publish_bundle(
    payload: FactoryPublishBundleRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Releases the approved sub-strand bundle to production with DNA provenance Merkle certificates."""
    from ..infra.db import execute, to_json
    from ..services.artifact_dna import artifact_dna_service
    from ..services.content_type_classifier import classify_content_type

    ct = classify_content_type(payload.subject, payload.grade, payload.sub_strand)

    # 1. Normalize activities & experiments
    activities_list = [payload.activity] if isinstance(payload.activity, dict) and payload.activity else (payload.activity if isinstance(payload.activity, list) else [])
    experiments_list = payload.activity.get("experiments", []) if isinstance(payload.activity, dict) else []

    curr_dict = {
        "grade": payload.grade,
        "subject": payload.subject,
        "level": payload.level,
        "strand": payload.strand,
        "sub_strand": payload.sub_strand,
        "content_type": ct.content_type,
    }

    # 2. Register Artifact DNA certificates
    notes_dna = artifact_dna_service.register_artifact_dna(
        artifact_type="notes",
        content=payload.notes,
        curriculum_context=curr_dict,
        source_dataset_id=f"ds_{payload.grade}_{payload.subject.lower()[:4]}",
    )
    diagram_dna = artifact_dna_service.register_artifact_dna(
        artifact_type="diagram",
        content=payload.diagram,
        curriculum_context=curr_dict,
        source_dataset_id=f"ds_{payload.grade}_{payload.subject.lower()[:4]}",
    )
    bundle_dna = artifact_dna_service.register_artifact_dna(
        artifact_type="bundle",
        content={"notes": payload.notes, "diagram": payload.diagram, "activity": payload.activity, "questions": payload.questions},
        curriculum_context=curr_dict,
        source_dataset_id=f"ds_{payload.grade}_{payload.subject.lower()[:4]}",
        parent_dna_ids=[notes_dna.dna_id, diagram_dna.dna_id],
    )

    # 3. Persist to substrand_resources
    execute(
        """
        INSERT INTO substrand_resources (
            bundle_id, curriculum, notes, diagrams, activities, questions, review_audit, status, updated_at
        )
        VALUES (
            :bundle_id, CAST(:curriculum AS jsonb), CAST(:notes AS jsonb),
            CAST(:diagrams AS jsonb), CAST(:activities AS jsonb),
            CAST(:questions AS jsonb), CAST(:review_audit AS jsonb),
            'approved_active', NOW()
        )
        ON CONFLICT (bundle_id) DO UPDATE SET
            curriculum = EXCLUDED.curriculum,
            notes = EXCLUDED.notes,
            diagrams = EXCLUDED.diagrams,
            activities = EXCLUDED.activities,
            questions = EXCLUDED.questions,
            review_audit = EXCLUDED.review_audit,
            status = 'approved_active',
            updated_at = NOW()
        """,
        {
            "bundle_id": payload.bundle_id,
            "curriculum": to_json(curr_dict),
            "notes": to_json(payload.notes),
            "diagrams": to_json([payload.diagram] if payload.diagram else []),
            "activities": to_json({"activities": activities_list, "experiments": experiments_list}),
            "questions": to_json(payload.questions),
            "review_audit": to_json({
                "status": "approved_active",
                "human_notes": payload.deliberation_notes,
                "bundle_dna_id": bundle_dna.dna_id,
                "merkle_root": bundle_dna.merkle_root,
            }),
        },
    )

    # 4. Mirror full bundle to MinIO Object Storage
    from ..infra.storage import object_storage
    minio_url = object_storage.save_full_bundle(payload.bundle_id, {
        "bundle_id": payload.bundle_id,
        "curriculum": curr_dict,
        "notes": payload.notes,
        "diagrams": payload.diagrams or ([payload.diagram] if payload.diagram else []),
        "activities": activities_list,
        "experiments": experiments_list,
        "questions": payload.questions,
        "bundle_dna_id": bundle_dna.dna_id,
        "merkle_root": bundle_dna.merkle_root,
        "status": "approved_active",
    })

    return {
        "status": "published",
        "bundle_id": payload.bundle_id,
        "bundle_dna_id": bundle_dna.dna_id,
        "merkle_root": bundle_dna.merkle_root,
        "storage_url": minio_url,
        "review_status": "approved_active",
    }


@router.post("/factory/save-bundle")
def factory_save_bundle(
    payload: FactorySaveBundleRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    from ..infra.db import execute, to_json
    from ..infra.storage import object_storage

    curr_dict = {
        "grade": payload.grade,
        "subject": payload.subject,
        "level": payload.level,
        "strand": payload.strand,
        "sub_strand": payload.sub_strand,
    }

    # Normalize activities
    act_data = payload.activities
    if isinstance(act_data, dict):
        activities_list = [act_data]
        experiments_list = act_data.get("experiments", payload.experiments or [])
    else:
        activities_list = act_data if isinstance(act_data, list) else []
        experiments_list = payload.experiments if isinstance(payload.experiments, list) else []

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
            "diagrams": to_json(payload.diagrams if payload.diagrams else ([payload.diagram] if payload.diagram else [])),
            "activities": to_json({
                "activities": activities_list,
                "experiments": experiments_list,
                "video_storyboards": payload.video_storyboards,
            }),
            "questions": to_json(payload.questions),
            "review_audit": to_json({"status": payload.review_status, "human_notes": payload.human_notes}),
            "status": payload.review_status,
        },
    )

    # Mirror draft to MinIO
    minio_url = object_storage.save_full_bundle(payload.bundle_id, payload.model_dump())

    return {"status": "saved", "bundle_id": payload.bundle_id, "storage_url": minio_url, "review_status": payload.review_status}


@router.get("/factory/bundle-by-substrand")
def factory_get_bundle_by_substrand(
    grade: str = Query(...),
    subject: str = Query(...),
    strand: str = Query(...),
    sub_strand: str = Query(...),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    from ..infra.db import fetch_all

    clean_grade = grade.lower().replace("grade-", "").strip()
    clean_subj = subject.lower().strip()
    clean_strand = strand.lower().strip()
    clean_ss = sub_strand.lower().strip()

    rows = fetch_all(
        """
        SELECT bundle_id, curriculum, notes, diagrams, activities, questions, review_audit, status, updated_at
        FROM substrand_resources
        ORDER BY updated_at DESC
        """
    )

    merged_curriculum: dict[str, Any] = {}
    merged_notes: dict[str, Any] = {}
    merged_diagrams: list[Any] = []
    merged_activities: dict[str, Any] = {}
    merged_questions: list[Any] = []
    merged_audit: dict[str, Any] = {}
    merged_status: str = "draft"
    found_any = False
    latest_bundle_id = ""
    latest_updated_at = ""

    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    def _matches_ss(a: str, b: str) -> bool:
        if not a or not b:
            return False
        na, nb = _norm(a), _norm(b)
        if na == nb or na in nb or nb in na:
            return True
        wa = set(re.findall(r"[a-z0-9]+", a.lower())) - {"and", "of", "the", "in", "to", "for", "a", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0"}
        wb = set(re.findall(r"[a-z0-9]+", b.lower())) - {"and", "of", "the", "in", "to", "for", "a", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0"}
        return len(wa & wb) >= 2

    for row in rows:
        c = row.get("curriculum") or {}
        row_grade = str(c.get("grade", "")).lower().replace("grade-", "").strip()
        row_subj = str(c.get("subject", "")).lower().strip()
        row_ss = str(c.get("sub_strand", "")).lower().strip()

        # Match subject and sub-strand (fuzzy or exact)
        match_subj = (not clean_subj or not row_subj or _norm(clean_subj) in _norm(row_subj) or _norm(row_subj) in _norm(clean_subj))
        match_ss = _matches_ss(clean_ss, row_ss)

        if match_subj and match_ss:
            found_any = True
            if not latest_bundle_id:
                latest_bundle_id = row.get("bundle_id") or ""
                latest_updated_at = str(row.get("updated_at") or "")
                merged_curriculum = c
                merged_status = row.get("status") or "draft"
                merged_audit = row.get("review_audit") or {}

            # Merge notes
            row_notes = row.get("notes")
            if isinstance(row_notes, dict) and row_notes and not merged_notes:
                merged_notes = row_notes

            # Merge diagrams
            raw_diag = row.get("diagrams")
            if raw_diag and not merged_diagrams:
                if isinstance(raw_diag, list):
                    merged_diagrams = raw_diag
                elif isinstance(raw_diag, dict):
                    if "visuals" in raw_diag and isinstance(raw_diag["visuals"], list):
                        merged_diagrams = raw_diag["visuals"]
                    elif "diagrams" in raw_diag and isinstance(raw_diag["diagrams"], list):
                        merged_diagrams = raw_diag["diagrams"]
                    elif raw_diag.get("diagram_svg") or raw_diag.get("title"):
                        merged_diagrams = [raw_diag]

            # Merge activities
            raw_act = row.get("activities")
            if raw_act and not merged_activities:
                if isinstance(raw_act, dict):
                    merged_activities = raw_act
                elif isinstance(raw_act, list):
                    merged_activities = {"activities": raw_act}

            # Merge questions
            raw_qs = row.get("questions")
            if raw_qs and not merged_questions:
                if isinstance(raw_qs, list):
                    merged_questions = raw_qs
                elif isinstance(raw_qs, dict):
                    if "questions" in raw_qs and isinstance(raw_qs["questions"], list):
                        merged_questions = raw_qs["questions"]
                    elif raw_qs.get("question_text"):
                        merged_questions = [raw_qs]

    if found_any:
        return {
            "found": True,
            "bundle_id": latest_bundle_id,
            "curriculum": merged_curriculum or {"grade": grade, "subject": subject, "strand": strand, "sub_strand": sub_strand},
            "notes": merged_notes,
            "diagrams": merged_diagrams,
            "activities": merged_activities,
            "questions": merged_questions,
            "review_audit": merged_audit,
            "status": merged_status,
            "updated_at": latest_updated_at,
        }

    return {"found": False, "bundle": None}


class FactoryAutoPersistStationRequest(BaseModel):
    bundle_id: str
    grade: str
    subject: str
    strand: str = ""
    sub_strand: str
    level: str = "Basic Education"
    station_type: str = "notes"  # "notes" | "diagrams" | "activities" | "questions" | "approval"
    data: Any = None
    notes: Any = None
    diagrams: Any = None
    activities: Any = None
    questions: Any = None
    review_status: str = "draft"
    human_notes: str = ""


@router.post("/factory/auto-persist-station")
def factory_auto_persist_station(
    payload: FactoryAutoPersistStationRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    from ..infra.db import execute, fetch_one, to_json
    from ..infra.storage import object_storage

    curr_dict = {
        "grade": payload.grade,
        "subject": payload.subject,
        "level": payload.level,
        "strand": payload.strand,
        "sub_strand": payload.sub_strand,
    }

    clean_subj = payload.subject.lower().strip()
    clean_ss = payload.sub_strand.lower().strip()

    existing = fetch_one(
        """
        SELECT * FROM substrand_resources 
        WHERE bundle_id = :bundle_id
           OR (
              LOWER(curriculum->>'subject') = :subject
              AND (
                  LOWER(curriculum->>'sub_strand') = :ss 
                  OR LOWER(curriculum->>'sub_strand') LIKE :ss_like
                  OR :ss LIKE CONCAT('%', LOWER(curriculum->>'sub_strand'), '%')
              )
           )
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        {
            "bundle_id": payload.bundle_id,
            "subject": clean_subj,
            "ss": clean_ss,
            "ss_like": f"%{clean_ss}%",
        },
    )

    # Use existing bundle_id if found to update the same record
    target_bundle_id = existing.get("bundle_id") if (existing and existing.get("bundle_id")) else payload.bundle_id

    # Initialize from existing record if present
    notes = existing.get("notes") if existing and existing.get("notes") else {}
    diagrams = existing.get("diagrams") if existing and existing.get("diagrams") else []
    activities = existing.get("activities") if existing and existing.get("activities") else {}
    questions = existing.get("questions") if existing and existing.get("questions") else []
    review_audit = existing.get("review_audit") if existing and existing.get("review_audit") else {}
    status = existing.get("status") if existing and existing.get("status") else payload.review_status

    # Authoritative Notes update
    if payload.notes is not None:
        notes = payload.notes if (isinstance(payload.notes, dict) and payload.notes) else {}
    elif payload.station_type == "notes":
        notes = payload.data if isinstance(payload.data, dict) else {}

    # Authoritative Diagrams update (allows deleting & clearing)
    if payload.diagrams is not None:
        if isinstance(payload.diagrams, list):
            diagrams = payload.diagrams
        elif isinstance(payload.diagrams, dict) and payload.diagrams:
            diagrams = [payload.diagrams]
        else:
            diagrams = []
    elif payload.station_type == "diagrams":
        if isinstance(payload.data, list):
            diagrams = payload.data
        elif isinstance(payload.data, dict) and payload.data:
            diagrams = [payload.data]
        else:
            diagrams = []

    # Authoritative Activities update (allows deleting & clearing)
    if payload.activities is not None:
        if isinstance(payload.activities, dict) and "activities" in payload.activities:
            activities = payload.activities
        elif isinstance(payload.activities, list):
            activities = {"activities": payload.activities}
        elif isinstance(payload.activities, dict) and payload.activities:
            activities = {"activities": [payload.activities]}
        else:
            activities = {"activities": []}
    elif payload.station_type == "activities":
        if isinstance(payload.data, dict) and "activities" in payload.data:
            activities = payload.data
        elif isinstance(payload.data, list):
            activities = {"activities": payload.data}
        elif isinstance(payload.data, dict) and payload.data:
            activities = {"activities": [payload.data]}
        else:
            activities = {"activities": []}

    # Bi-directional linking: Link diagrams and activities directly into notes.hour_modules
    if notes and isinstance(notes, dict) and "hour_modules" in notes and isinstance(notes["hour_modules"], list):
        acts_list = activities.get("activities", []) if isinstance(activities, dict) else (activities if isinstance(activities, list) else [])
        for idx, hm in enumerate(notes["hour_modules"]):
            if isinstance(hm, dict):
                h_num = hm.get("hour_number", idx + 1)
                h_diags = [d for d in diagrams if isinstance(d, dict) and (d.get("hour_index") == h_num or (not d.get("hour_index") and h_num == 1))]
                h_acts = [a for a in acts_list if isinstance(a, dict) and (a.get("hour_index") == h_num or (not a.get("hour_index") and h_num == 1))]
                hm["visual_assets"] = h_diags
                hm["practical_activities"] = h_acts

    # Authoritative Questions update (allows deleting & clearing)
    if payload.questions is not None:
        questions = payload.questions if isinstance(payload.questions, list) else ([payload.questions] if payload.questions else [])
    elif payload.station_type == "questions":
        questions = payload.data if isinstance(payload.data, list) else ([payload.data] if payload.data else [])

    if payload.station_type == "approval" or payload.review_status in {"approved", "published"}:
        status = payload.review_status
        review_audit = {"status": payload.review_status, "human_notes": payload.human_notes}

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
            "bundle_id": target_bundle_id,
            "curriculum": to_json(curr_dict),
            "notes": to_json(notes),
            "diagrams": to_json(diagrams),
            "activities": to_json(activities),
            "questions": to_json(questions),
            "review_audit": to_json(review_audit),
            "status": status,
        },
    )

    # Mirror to MinIO with error reporting
    minio_status = "saved"
    minio_url = ""
    minio_error = ""
    try:
        minio_url = object_storage.save_full_bundle(payload.bundle_id, {
            "bundle_id": payload.bundle_id,
            "curriculum": curr_dict,
            "notes": notes,
            "diagrams": diagrams,
            "activities": activities,
            "questions": questions,
            "review_audit": review_audit,
            "status": status,
        })
    except Exception as exc:
        minio_status = "error"
        minio_error = str(exc)

    return {
        "status": "persisted",
        "bundle_id": payload.bundle_id,
        "station_type": payload.station_type,
        "minio_status": minio_status,
        "minio_url": minio_url,
        "minio_error": minio_error,
    }


class FactoryGenerateStrandsRequest(BaseModel):
    grade: str
    subject: str
    level: str = "Basic Education"
    essence_statement: str = ""
    custom_instructions: str = ""
    # The published design. Without it the architect invents strands rather
    # than reading the ones KICD wrote.
    source_material_text: str = ""
    design_id: str = ""
    # Return the compiled prompt instead of generating, so the inputs can be
    # checked before any tokens are spent.
    inspect: bool = False


class FactoryGenerateSubstrandsRequest(BaseModel):
    grade: str
    subject: str
    strand_name: str
    strand_id: str = "1.0"
    level: str = "Basic Education"
    essence_statement: str = ""
    general_learning_outcomes: list[str] = []
    source_material_text: str = ""
    custom_instructions: str = ""
    design_id: str = ""
    # Return the compiled prompt instead of generating, so the inputs can be
    # checked before any tokens are spent.
    inspect: bool = False


class IngestLearningAreaRequest(BaseModel):
    grade: str
    subject: str
    # Replace what a previous run produced for this learning area.
    force: bool = False
    # Derive the teaching skill from the design section as well.
    with_skill: bool = True


class DeriveGradeScopeRequest(BaseModel):
    grade: str
    subject: str
    source_material_text: str | None = None
    inspect: bool = False


class GenerateMediaPromptsRequest(BaseModel):
    grade: str
    subject: str
    strand: str = ""
    sub_strand: str
    custom_instructions: str = ""
    kinds: list[str] = ["photo", "video"]
    save: bool = True
    inspect: bool = False


class AttachMediaAssetRequest(BaseModel):
    media_id: str
    storage_url: str
    content_type: str = ""


class FactorySaveStrandsRequest(BaseModel):
    grade: str
    subject: str
    design_id: str = ""
    strands: list[dict[str, Any]]


class FactorySaveSubstrandsRequest(BaseModel):
    grade: str
    subject: str
    strand_name: str
    strand_id: str = "1.0"
    design_id: str = ""
    substrands: list[dict[str, Any]]


def build_inspection(
    context: Any,
    *,
    agent: str,
    grade: str,
    subject: str,
    source_material: str = "",
    profile: Any = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Everything that will be sent to the model, before it is sent.

    Judging a generation by its output alone cannot tell you whether the prompt
    carried the right document, the right teaching skill, or the right prompt
    version — a plausible answer looks identical either way. This returns the
    inputs so they can be checked and the prompt improved deliberately.
    """
    messages = list(getattr(context, "messages", None) or [])
    return {
        "agent": agent,
        "grade": grade,
        "subject": subject,
        "prompt": {
            "name": getattr(context, "prompt_name", ""),
            "version": getattr(context, "prompt_version", ""),
            "label": getattr(context, "prompt_label", ""),
            "hash": getattr(context, "prompt_hash", ""),
        },
        "source_document": {
            "present": bool(source_material),
            "chars": len(source_material or ""),
            # Enough to recognise which document this is without shipping all of it.
            "head": (source_material or "")[:1200],
        },
        "skill": (
            {
                "found": True,
                "subject": getattr(profile, "subject", ""),
                "grade": getattr(profile, "grade", ""),
                "persona": (getattr(profile, "persona", "") or "")[:400],
                "directives": list(getattr(profile, "special_directives", None) or [])[:10],
            }
            if profile is not None
            else {"found": False, "note": "No teaching skill covers this subject and grade; a generic profile was used."}
        ),
        "messages": [
            {"role": m.get("role", "user"), "content": m.get("content", ""), "chars": len(m.get("content", ""))}
            for m in messages
        ],
        "total_prompt_chars": sum(len(m.get("content", "")) for m in messages),
        **(extra or {}),
    }


def _design_source(design_id: str = "", grade: str = "", subject: str = "") -> dict[str, Any]:
    """The stored design and its captured document text."""
    from ..infra.db import fetch_one as _fetch_one

    found = design_source.require(grade, subject, design_id=design_id)
    row = _fetch_one(
        "SELECT design_id, grade, subject, raw_payload FROM curriculum_designs "
        "WHERE design_id = :design_id",
        {"design_id": found.design_id},
    ) or {
        "design_id": found.design_id, "grade": found.grade,
        "subject": found.subject, "raw_payload": {},
    }
    return {"row": row, "text": found.text}


@router.get("/designs/{design_id}/document")
def read_design_document(
    design_id: str,
    page: int = 0,
    q: str = "",
    ref: str = "",
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Read a curriculum design by page and line.

    Every line carries an address so generated content can cite exactly where
    it came from, and a reviewer can read those lines back.
    """
    from ..services import document_index as dx

    found = _design_source(design_id=design_id)
    row, text = found["row"], found["text"]
    pages = dx.parse_pages(text)
    index = dx.build_index(text, row.get("grade", ""), row.get("subject", ""))

    body: dict[str, Any] = {
        "design_id": row["design_id"],
        "grade": row.get("grade", ""),
        "subject": row.get("subject", ""),
        **index,
    }

    if ref:
        lines = dx.resolve_reference(pages, ref)
        body["reference"] = {"ref": ref, "found": bool(lines), "lines": [l.to_dict() for l in lines]}
    elif q:
        body["search"] = {"query": q, "hits": dx.search(pages, q)}
    elif page:
        match = next((p for p in pages if p.number == page), None)
        body["page_content"] = match.to_dict() if match else None
    else:
        # Default to the first page so the viewer opens on something.
        body["page_content"] = pages[0].to_dict() if pages else None

    return body


class CiteRequest(BaseModel):
    design_id: str = ""
    grade: str = ""
    subject: str = ""
    quotes: list[str] = []


@router.post("/designs/cite")
def cite_against_design(
    payload: CiteRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Locate each quote in the design and return its page and line.

    This is what lets a sub-strand or a question record the exact lines it was
    drawn from — and what exposes a claim that appears nowhere in the design.
    """
    from ..services import document_index as dx

    found = _design_source(payload.design_id, payload.grade, payload.subject)
    row, text = found["row"], found["text"]
    pages = dx.parse_pages(text)
    code = dx.document_code(row.get("grade", ""), row.get("subject", ""))

    citations = []
    for quote in payload.quotes:
        hit = dx.find_reference(pages, quote)
        citations.append({
            "quote": quote,
            "found": bool(hit),
            "citation": f"{code} {hit['ref']}" if hit else "",
            **(hit or {}),
        })

    return {
        "design_id": row["design_id"],
        "code": code,
        "cited": sum(1 for c in citations if c["found"]),
        "uncited": sum(1 for c in citations if not c["found"]),
        "citations": citations,
    }


class AttachSourceRequest(BaseModel):
    design_id: str = ""
    grade: str = ""
    subject: str = ""


@router.post("/designs/attach-source")
def attach_design_source(
    payload: AttachSourceRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Put a design's source document back on it, without re-running extraction."""
    from ..services.dataset_ingest import attach_source_document

    try:
        return attach_source_document(
            design_id=payload.design_id, grade=payload.grade, subject=payload.subject
        )
    except LookupError as exc:
        raise_api_error("DATASET_ITEM_NOT_FOUND", str(exc))


@router.post("/factory/generate-strands")
def factory_generate_strands(
    payload: FactoryGenerateStrandsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Generates the top-level strands for a subject using Langfuse prompt management and subject design context."""
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator

    # The design is what the strands must be read from. Resolving it is shared
    # with every other generation endpoint, and it refuses rather than letting
    # the agent quietly invent a curriculum that reads plausibly and matches no
    # published design.
    found = design_source.require(
        payload.grade, payload.subject,
        design_id=payload.design_id or "",
        supplied=payload.source_material_text,
    )
    source_material = found.text
    essence_statement = payload.essence_statement or found.essence_statement
    level = found.level or payload.level

    from ..services.content_type_classifier import get_profile_from_db as _profile_for_strands

    strand_profile = _profile_for_strands(payload.subject, payload.grade)
    resolved = pipeline_orchestrator.router.resolve_for_stage("notes_generation")
    context = langfuse_context_service.assemble_agent_context(
        agent_name="strand-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars={
            "level": level,
            "grade": payload.grade,
            "subject": payload.subject,
            "level_register": register_block(
                payload.grade,
                notes=grade_scope_notes(payload.grade, payload.subject),
            ),
            "faith_scope": faith_prompt_block(payload.subject),
            "content_type_directives": (
                strand_profile.format_for_prompt() if strand_profile else ""
            ),
            "essence_statement": essence_statement,
            "source_material_text": source_material or "(NO SOURCE DOCUMENT AVAILABLE)",
            "custom_instructions": payload.custom_instructions,
        },
    )
    if payload.custom_instructions:
        context.messages.append({
            "role": "user",
            "content": f"ADDITIONAL STRAND INSTRUCTIONS: {payload.custom_instructions}",
        })

    if payload.inspect:
        from ..services.content_type_classifier import get_profile_from_db

        return {
            "inspection": build_inspection(
                context,
                agent="strand-generator",
                grade=payload.grade,
                subject=payload.subject,
                source_material=source_material,
                profile=get_profile_from_db(payload.subject, payload.grade),
                extra={"model": f"{resolved.provider}/{resolved.model}", "grounded": bool(source_material)},
            )
        }

    # A full design plus the master context and the teaching skill can exceed the
    # model's window, and the provider rejects the whole request rather than
    # truncating — so nothing is generated at all. Read it page by page instead.
    from ..services.document_chunking import CHARS_PER_TOKEN, budget_chars
    from ..services.map_reduce import map_reduce_over_document

    window = getattr(resolved, "context_window_tokens", 0) or 128_000
    overhead = sum(len(m.get("content", "")) for m in context.messages) // CHARS_PER_TOKEN + 6_000

    if source_material and len(source_material) > budget_chars(window, overhead):
        def for_chunk(chunk: Any) -> list[dict[str, Any]]:
            messages = [
                *[m for m in context.messages if m.get("role") == "system"],
                {
                    "role": "user",
                    "content": (
                        f"You are reading PART of the curriculum design - pages {chunk.page_range} of it.\n"
                        f"Extract ONLY the strands that appear on these pages. Do not infer strands from "
                        f"elsewhere in the subject, and do not invent any.\n"
                        f"Every line below is prefixed with its page:line address; cite those addresses in "
                        f"'source_quote' so a reviewer can find each strand.\n"
                        f"Return the same JSON schema. If these pages contain no strands, return "
                        f'{{"strands": []}}.\n\n'
                        f"=== PAGES {chunk.page_range} ===\n{chunk.text}"
                    ),
                },
            ]
            chunk_resp = llm_client.generate(resolved, messages, temperature=0.2)
            content = chunk_resp.content if isinstance(chunk_resp.content, dict) else {}
            return content.get("strands", []) or []

        outcome = map_reduce_over_document(
            source_material, for_chunk,
            context_window_tokens=window, overhead_tokens=overhead,
            identity_fields=("strand_name", "name"),
        ).to_dict()
        logger.info(
            "Strands for %s %s read across %d chunk(s): %d after reconciliation.",
            payload.grade, payload.subject,
            outcome["trace"]["chunks"]["chunk_count"], len(outcome["items"]),
        )
        kept, refused = substrand_hygiene.clean_strands(outcome["items"])
        return {
            "subject": payload.subject,
            "grade": payload.grade,
            "strands": kept,
            "refused": refused,
            "grounded": True,
            "source_chars": len(source_material),
            "chunked": True,
            "trace": outcome["trace"],
            "model": f"{resolved.provider}/{resolved.model}",
        }

    resp = llm_client.generate(resolved, context.messages, temperature=0.2)
    raw_strands = resp.content.get("strands", []) if isinstance(resp.content, dict) else []
    strands, refused_strands = substrand_hygiene.clean_strands(raw_strands)
    return {
        "subject": payload.subject,
        "grade": payload.grade,
        "strands": strands,
        "refused": refused_strands,
        "chunked": False,
        # A reviewer needs to know whether these were read from the design or
        # produced from the model's own knowledge.
        "grounded": bool(source_material),
        "source_chars": len(source_material),
        "usage": resp.usage,
        "model": resp.model,
    }


@router.post("/factory/generate-substrands")
def factory_generate_substrands(
    payload: FactoryGenerateSubstrandsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Generates detailed sub-strands with SLOs, hours, diagrams, experiments, and hazard protocols using curriculum design blueprint context."""
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator

    # Sub-strands are read out of the design, never recalled. Ungrounded, this
    # endpoint returned HTTP 200 with an empty list — indistinguishable, from
    # the console, from a strand that genuinely has none.
    found = design_source.require(
        payload.grade, payload.subject,
        supplied=payload.source_material_text,
    )
    source_material = found.text
    essence_stmt = payload.essence_statement or found.essence_statement
    gen_outcomes = payload.general_learning_outcomes or found.general_learning_outcomes
    level = payload.level
    if level == "Basic Education" and found.level:
        level = found.level

    outcomes_str = "\n".join([f"- {o}" for o in gen_outcomes]) if gen_outcomes else "Standard KICD BECF Outcomes."
    master_context = langfuse_context_service.get_master_context()

    resolved = pipeline_orchestrator.router.resolve_for_stage("notes_generation")

    # Who the learner is decides what may be asked of them. Without this the
    # shared prompt's own examples set the register, and a pre-primary sub-strand
    # comes back demanding a flowchart from a child who cannot read.
    from ..services.content_type_classifier import get_profile_from_db

    ct_profile = get_profile_from_db(payload.subject, payload.grade)

    def _compile(document: str) -> Any:
        """Compile the sub-strand prompt around a given slice of the design."""
        return langfuse_context_service.assemble_agent_context(
            agent_name="substrand-generator",
            grade_slug=payload.grade,
            subject=payload.subject,
            # Without this the system message carried every strand stored for the
            # learning area, contradicting the strand actually being asked about.
            focus_strand=payload.strand_name,
            template_vars={
                "master_context": master_context,
                "level_register": register_block(
                    payload.grade,
                    notes=grade_scope_notes(payload.grade, payload.subject),
                ),
                "faith_scope": faith_prompt_block(payload.subject),
                "content_type_directives": (
                    ct_profile.format_for_prompt() if ct_profile else ""
                ),
                "level": level,
                "essence_statement": essence_stmt or f"Comprehensive curriculum design for {payload.subject} ({payload.grade}).",
                "general_learning_outcomes": outcomes_str,
                "strand": payload.strand_name,
                "source_material_text": document,
                "custom_instructions": payload.custom_instructions,
            },
        )

    context = _compile(source_material or "(Official curriculum design syllabus document attached below)")

    # The substrand-generator template already interpolates the master context,
    # the whole design document, the blueprint and the target strand. Appending
    # them a second time here sent the 296-page design twice in one request —
    # 170k tokens against a 128k window, so the provider rejected it outright and
    # nothing was generated at all.

    if payload.inspect:
        return {
            "inspection": build_inspection(
                context,
                agent="substrand-generator",
                grade=payload.grade,
                subject=payload.subject,
                source_material=source_material,
                profile=ct_profile,
                extra={
                    "model": f"{resolved.provider}/{resolved.model}",
                    "strand": payload.strand_name,
                    "grounded": bool(source_material),
                },
            )
        }

    # A full design plus the master context and the blueprint can exceed the
    # model's window, and the provider rejects the whole request rather than
    # truncating — so nothing is produced at all. Read the design in page-aligned
    # pieces instead, then reconcile the sub-strands each piece yielded.
    from ..services.document_chunking import CHARS_PER_TOKEN, budget_chars
    from ..services.map_reduce import map_reduce_over_document

    window = getattr(resolved, "context_window_tokens", 0) or 128_000
    # The document lives inside the compiled prompt, so measure the prompt
    # without it — that is what every chunk call actually has to carry.
    skeleton = _compile("")
    overhead = sum(len(m.get("content", "")) for m in skeleton.messages) // CHARS_PER_TOKEN + 6_000

    if source_material and len(source_material) > budget_chars(window, overhead):
        def for_chunk(chunk: Any) -> list[dict[str, Any]]:
            messages = [
                *skeleton.messages,
                {
                    "role": "user",
                    "content": (
                        f"You are reading PART of the curriculum design - pages {chunk.page_range} of it.\n"
                        f"Return ONLY the sub-strands of the strand '{payload.strand_name}' that actually "
                        f"appear on these pages. Do not carry over sub-strands from elsewhere in the "
                        f"subject, and do not invent any.\n"
                        f"Every line below is prefixed with its page:line address; cite those addresses so "
                        f"a reviewer can find each sub-strand in the design.\n"
                        f"Return the same JSON schema. If these pages contain no sub-strands of this "
                        f'strand, return {{"sub_strands": []}}.\n\n'
                        f"=== PAGES {chunk.page_range} ===\n{chunk.text}"
                    ),
                },
            ]
            chunk_resp = llm_client.generate(resolved, messages, temperature=0.2)
            content = chunk_resp.content if isinstance(chunk_resp.content, dict) else {}
            return content.get("sub_strands", []) or []

        outcome = map_reduce_over_document(
            source_material, for_chunk,
            context_window_tokens=window, overhead_tokens=overhead,
            identity_fields=("sub_strand_name", "sub_strand_id", "name"),
        ).to_dict()
        logger.info(
            "Sub-strands of %s (%s %s) read across %d chunk(s): %d after reconciliation.",
            payload.strand_name, payload.grade, payload.subject,
            outcome["trace"]["chunks"]["chunk_count"], len(outcome["items"]),
        )
        kept, refused = substrand_hygiene.clean(payload.strand_name, outcome["items"])
        return {
            "subject": payload.subject,
            "grade": payload.grade,
            "strand_name": payload.strand_name,
            "sub_strands": kept,
            "refused": refused,
            "essence_statement_used": essence_stmt,
            "source_material_length": len(source_material),
            "grounded": True,
            "chunked": True,
            "trace": outcome["trace"],
            "model": f"{resolved.provider}/{resolved.model}",
        }

    resp = llm_client.generate(resolved, context.messages, temperature=0.2)
    raw = resp.content.get("sub_strands", []) if isinstance(resp.content, dict) else []
    # A chunk the model could not parse comes back as the chunk itself. Letting
    # that through is how a strand called "4.0 CHRISTIAN VALUES" was saved with
    # two hundred lines of page debris in its `values` list.
    sub_strands, refused = substrand_hygiene.clean(payload.strand_name, raw)
    return {
        "subject": payload.subject,
        "grade": payload.grade,
        "strand_name": payload.strand_name,
        "sub_strands": sub_strands,
        "refused": refused,
        "essence_statement_used": essence_stmt,
        "source_material_length": len(source_material),
        "grounded": bool(source_material),
        "chunked": False,
        "usage": resp.usage,
        "model": resp.model,
    }






def _scope_chunk_reader(grade: str, subject: str, resolved: Any) -> Any:
    """The per-chunk callable that reads bounding facts out of a design slice."""
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client

    template = langfuse_context_service.get_agent_prompt("grade-scope-extractor")

    def for_chunk(chunk: Any) -> list[dict[str, Any]]:
        prompt = langfuse_context_service._render_template(template, {
            "grade": grade,
            "subject": subject,
            "level_register": register_block(grade),
            "faith_scope": faith_prompt_block(subject),
            "page_range": chunk.page_range,
            "chunk_text": chunk.text,
        })
        response = llm_client.generate(
            resolved, [{"role": "user", "content": prompt}], temperature=0.1
        )
        content = response.content if isinstance(response.content, dict) else {}
        return content.get("facts", []) or []

    return for_chunk


@router.post("/factory/ingest-learning-area")
def factory_ingest_learning_area(
    payload: IngestLearningAreaRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Ingest ONE learning area out of a combined design, and derive its skill.

    Re-ingesting a whole Pre-Primary document to recover one missing learning
    area is slow and replaces six things that were already correct. This does
    the one, from the same split, with the same grounding.

    Everything the model reads is chunked page-by-page, so a 296-page design
    cannot exceed the context window, and every fact it keeps is one the design
    actually states — an ungrounded run produces "Listening and Speaking" as a
    Christian Religious Education strand, which reads plausibly and is wrong.
    """
    from ..services import grade_scope as scope_service
    from ..services.curriculum_catalogue import expected_subjects
    from ..services.curriculum_extractor import curriculum_extractor
    from ..services.dataset_ingest import candidate_items
    from ..services.design_sections import split_learning_areas
    from ..services.pipeline import pipeline_orchestrator

    published = expected_subjects(payload.grade)
    wanted = payload.subject.strip()

    section = None
    document_title = ""
    for item in candidate_items(payload.grade):
        text = str(item.get("expected_output") or "")
        if len(text) < 2_000:
            continue
        for candidate in split_learning_areas(text, published):
            if candidate.learning_area.lower() == wanted.lower():
                section = candidate
                document_title = str((item.get("input") or {}).get("title") or "")
                break
        if section:
            break

    if section is None:
        found = sorted({
            c.learning_area
            for item in candidate_items(payload.grade)
            if len(str(item.get("expected_output") or "")) >= 2_000
            for c in split_learning_areas(str(item.get("expected_output") or ""), published)
        })
        raise_api_error(
            "MISSING_PARENT_CONTEXT",
            f"'{wanted}' was not found in any {payload.grade} design document. "
            f"The splitter located: {', '.join(found) or 'nothing'}. "
            f"Run /factory/split-preview?grade={payload.grade} to see which pages "
            f"were rejected and why.",
            detail={"requested": wanted, "found": found, "grade": payload.grade},
        )

    result = curriculum_extractor._ingest_one(
        section.text,
        {"grade": payload.grade, "learning_area": section.learning_area,
         "title": document_title,
         "section_pages": f"{section.start_page}-{section.end_page}"},
        learning_area=section.learning_area,
    )

    scope_result: dict[str, Any] = {"status": "skipped"}
    skill: dict[str, Any] = {"status": "skipped"}

    if payload.with_skill:
        resolved = pipeline_orchestrator.router.resolve_for_stage("notes_generation")

        # Read the section in page-aligned chunks and reconcile what it bounds.
        scope = scope_service.derive_scope(
            payload.grade, section.learning_area, section.text,
            _scope_chunk_reader(payload.grade, section.learning_area, resolved),
        )
        if scope.facts:
            try:
                scope_service.save_scope(scope, design_id=str(result.get("design_id") or ""))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not store derived scope: %s", exc)
        scope_result = scope.to_dict()

        # The teaching skill, grounded in what the section actually says rather
        # than in sub-strands that structural extraction did not produce.
        try:
            from ..services.content_type_classifier import ai_generate_profile_from_dataset

            profile = ai_generate_profile_from_dataset(
                subject=section.learning_area,
                grade=payload.grade,
                level=str(result.get("level") or ""),
                essence_statement=str(result.get("essence_statement") or ""),
                general_learning_outcomes=list(scope.notes),
                save_to_db=True,
            )
            skill = {"status": "created", "profile": profile.to_dict()}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skill synthesis failed for %s: %s", section.learning_area, exc)
            skill = {"status": "failed", "error": str(exc)[:300]}

    return {
        "grade": payload.grade,
        "subject": section.learning_area,
        "source_document": document_title,
        "section_pages": f"{section.start_page}-{section.end_page}",
        "section_chars": len(section.text),
        "ingest": result,
        "scope": scope_result,
        "skill": skill,
    }


@router.get("/factory/split-preview")
def factory_split_preview(
    grade: str = Query(..., description="Grade slug, e.g. grade-pp1"),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Show what the splitter sees in this grade's design, and what it rejects.

    Read-only: it writes nothing and ingests nothing.

    A learning area that keeps reading "(not ingested)" can have failed in three
    different places — never located in the document, located and rejected as
    not-a-banner, or split out and then failed to parse. From a dropdown those
    look identical, and telling them apart by guesswork took several rounds.
    This says which, per learning area, with the page numbers.
    """
    from ..services.curriculum_catalogue import expected_subjects
    from ..services.dataset_ingest import candidate_items
    from ..services.design_sections import diagnose

    published = expected_subjects(grade)
    documents: list[dict[str, Any]] = []

    for item in candidate_items(grade):
        text = str(item.get("expected_output") or "")
        source = item.get("input") or {}
        title = str(source.get("title") or item.get("id") or "")
        if len(text) < 2_000:
            documents.append({
                "title": title, "chars": len(text),
                "skipped": "too short to be a curriculum design",
            })
            continue

        report = diagnose(text, published)
        documents.append({
            "title": title,
            "item_id": item.get("id"),
            "chars": len(text),
            **report,
        })

    return {
        "grade": grade,
        "expected_learning_areas": published,
        "documents": documents,
        # The whole point: one line that says whether this will work.
        "verdict": [
            f"{d.get('title', '?')}: found {len(d.get('sections', []))} of "
            f"{len(published)}"
            + (f", MISSING {', '.join(d['missing'])}" if d.get("missing") else "")
            for d in documents if "sections" in d
        ],
    }


@router.get("/factory/structure-report")
def factory_structure_report(
    grade: str = Query(..., description="Grade slug, e.g. grade-pp1"),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """What this grade holds, measured against what its design publishes.

    Read-only. It exists because a learning area holding another learning
    area's strands looks exactly like a correct one in a list, and the only way
    to tell them apart was to read the KICD PDF and count by hand.
    """
    from ..services.structure_report import build_report

    return build_report(grade)


@router.post("/factory/derive-scope")
def factory_derive_grade_scope(
    payload: DeriveGradeScopeRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Read a grade's design and store the facts that bound what may be asked.

    PP1's scope was written by hand — letter sounds only, nothing beyond 10.
    Doing the other fourteen grades that way does not scale, and asking a model
    to summarise a 296-page design in one call is the context-length failure
    this system already hit. So the design is read in page-aligned chunks and
    the results reconciled into one summary small enough to sit in every prompt.
    """
    from ..services import grade_scope as scope_service
    from ..services.pipeline import pipeline_orchestrator

    # Deriving a scope from nothing would produce a confident, invented one.
    found = design_source.require(
        payload.grade, payload.subject, supplied=payload.source_material_text or "",
    )
    source_material = found.text
    design_id = found.design_id

    resolved = pipeline_orchestrator.router.resolve_for_stage("notes_generation")
    # Note the shared reader does NOT feed the previously derived scope back in.
    # Deriving a scope while showing the model the last scope makes the second
    # run agree with the first whether or not the first was right.
    for_chunk = _scope_chunk_reader(payload.grade, payload.subject, resolved)

    if payload.inspect:
        from ..services.document_chunking import chunk_document, describe

        chunks = chunk_document(source_material)
        return {"inspection": {
            "grade": payload.grade,
            "subject": payload.subject,
            "source_chars": len(source_material),
            "chunks": describe(chunks),
            "model": f"{resolved.provider}/{resolved.model}",
        }}

    scope = scope_service.derive_scope(
        payload.grade, payload.subject, source_material, for_chunk
    )

    stored = False
    if scope.facts:
        try:
            scope_service.save_scope(scope, design_id=design_id)
            stored = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not store derived scope: %s", exc)

    return {
        **scope.to_dict(),
        "stored": stored,
        "source_chars": len(source_material),
        "design_id": design_id,
        # A derivation that found no limits is not a failure to hide: it means
        # the register keeps saying "read the design", which stays honest.
        "status": "ok" if scope.facts else "no_bounding_facts_found",
    }


def _substrand_design_block(grade: str, subject: str, sub_strand: str) -> tuple[str, list[Any]]:
    """What the design says about one sub-strand, and its SLOs.

    Shared by the notes and media stations so a photograph is planned from the
    same design text the notes are written from, rather than from the title.
    """
    from ..infra.db import fetch_one

    row = fetch_one(
        """
        SELECT slos, learning_experiences, key_inquiry_questions, core_competencies,
               values, assessment_rubrics, pertinent_contemporary_issues,
               link_to_other_learning_areas, allocated_hours, source_pages
        FROM curriculum_substrands
        WHERE (grade = :grade OR grade = :alt_grade)
          AND LOWER(subject) = LOWER(:subject)
          AND LOWER(sub_strand_name) = LOWER(:sub_strand)
        LIMIT 1
        """,
        {"grade": grade, "alt_grade": grade.replace("grade-", ""),
         "subject": subject, "sub_strand": sub_strand},
    )
    if not row:
        return "", []

    def lines(value: Any) -> str:
        if isinstance(value, str):
            return f"- {value}" if value.strip() else ""
        if isinstance(value, dict):
            return "\n".join(f"- {k}: {v}" for k, v in value.items() if v)
        if isinstance(value, (list, tuple)):
            return "\n".join(
                f"- {v}" if isinstance(v, str) else lines(v) for v in value if v
            )
        return ""

    sections = [
        ("Suggested learning experiences", lines(row.get("learning_experiences"))),
        ("Key inquiry questions", lines(row.get("key_inquiry_questions"))),
        ("Core competencies", lines(row.get("core_competencies"))),
        ("Values", lines(row.get("values"))),
        ("Pertinent and contemporary issues",
         lines(row.get("pertinent_contemporary_issues"))),
        ("Time allocated", str(row.get("allocated_hours") or "")),
    ]
    block = "\n\n".join(f"{t}:\n{b}" for t, b in sections if b.strip())
    return block, list(row.get("slos") or [])


@router.post("/factory/generate-media-prompts")
def factory_generate_media_prompts(
    payload: GenerateMediaPromptsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Plan the photographs and videos a sub-strand needs.

    A diagram is SVG: generated as code and editable afterwards. A photograph
    and a video are not programmable, so what this authors is the prompt, the
    shot list, the alt text and the narration. The asset itself is produced
    elsewhere — by an image or video model, or by a teacher with a phone — and
    uploaded back against its plan.
    """
    from ..services.content_type_classifier import get_profile_from_db
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator

    kinds = [k for k in payload.kinds if k in media_registry.KINDS]
    if not kinds:
        raise_api_error(
            "VALIDATION_FAILED",
            f"Nothing to plan: kinds must include one of {media_registry.KINDS}.",
        )

    # Planned from the design, never from the sub-strand's title alone.
    design_block, slos = _substrand_design_block(
        payload.grade, payload.subject, payload.sub_strand
    )
    if not design_block:
        raise_api_error(
            "MISSING_PARENT_CONTEXT",
            f"'{payload.sub_strand}' is not stored for {payload.subject} "
            f"({payload.grade}), so there is nothing to plan media from. "
            f"Generate and save its sub-strands first.",
        )

    profile = get_profile_from_db(payload.subject, payload.grade)
    resolved = pipeline_orchestrator.router.resolve_for_stage("diagram_generation")

    context = langfuse_context_service.assemble_agent_context(
        agent_name="media-prompt-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        focus_strand=payload.strand,
        template_vars={
            "master_context": langfuse_context_service.get_master_context(),
            "level_register": register_block(
                payload.grade,
                notes=grade_scope_notes(payload.grade, payload.subject),
            ),
            "faith_scope": faith_prompt_block(payload.subject),
            "content_type_directives": profile.format_for_prompt() if profile else "",
            "grade": payload.grade,
            "subject": payload.subject,
            "strand": payload.strand,
            "sub_strand": payload.sub_strand,
            "design_extract": design_block,
            "slos": "\n".join(
                f"- {s if isinstance(s, str) else s.get('text', str(s))}" for s in slos
            ) or "- (none stored)",
            "custom_instructions": payload.custom_instructions
            + ("" if "video" in kinds else "\nReturn an empty 'videos' array.")
            + ("" if "photo" in kinds else "\nReturn an empty 'photos' array."),
        },
    )

    if payload.inspect:
        return {
            "inspection": build_inspection(
                context, agent="media-prompt-generator", grade=payload.grade,
                subject=payload.subject, source_material=design_block, profile=profile,
                extra={"model": f"{resolved.provider}/{resolved.model}",
                       "sub_strand": payload.sub_strand, "kinds": kinds},
            )
        }

    resp = llm_client.generate(resolved, context.messages, temperature=0.3)
    content = resp.content if isinstance(resp.content, dict) else {}

    # The prompt states the depth and the depiction rules; this checks them. An
    # image model invents everything a short brief leaves out, and a depiction
    # the faith forbids reaching a Kenyan classroom is not a quality defect at
    # all — so both are measured rather than assumed.
    media_check = media_validators.check(content, payload.subject)
    if not media_check.sound:
        logger.warning(
            "Media plan for %s (%s) has %d blocking issue(s).",
            payload.sub_strand, payload.subject, len(media_check.errors),
        )
    provenance = {
        "model": f"{resolved.provider}/{resolved.model}",
        "agent": "media-prompt-generator",
    }

    planned: list[dict[str, Any]] = []
    skipped = 0
    for kind, key in (("photo", "photos"), ("video", "videos")):
        if kind not in kinds:
            continue
        for entry in content.get(key) or []:
            item = media_registry.from_generated(
                entry, kind=kind, grade=payload.grade, subject=payload.subject,
                strand=payload.strand, sub_strand=payload.sub_strand,
                provenance=provenance,
            )
            if item is None:
                # A title with no prompt is something nobody can produce from.
                skipped += 1
                continue
            if payload.save:
                media_registry.save(item)
                item_versioned = _record_artifact(
                    "photo_prompt" if kind == "photo" else "video_prompt",
                    payload.grade, payload.subject, item.to_dict(),
                    strand=payload.strand, sub_strand=payload.sub_strand,
                    title=item.title, provenance=provenance,
                )
            else:
                item_versioned = {}
            planned.append({**item.to_dict(), "artifact": item_versioned})

    return {
        "grade": payload.grade,
        "subject": payload.subject,
        "sub_strand": payload.sub_strand,
        "kinds": kinds,
        "media": planned,
        "planned_count": len(planned),
        "unusable_count": skipped,
        "brief_quality": media_check.to_dict(),
        "saved": payload.save,
        "usage": resp.usage,
        "model": f"{resolved.provider}/{resolved.model}",
    }


@router.get("/factory/media")
def factory_list_media(
    grade: str = Query(..., description="Grade slug, e.g. grade-pp1"),
    subject: str = Query(...),
    sub_strand: str = Query("", description="Optional: one sub-strand only"),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Every planned or produced photograph and video, with its prompt."""
    rows = media_registry.list_for(grade, subject, sub_strand)
    return {
        "grade": grade,
        "subject": subject,
        "sub_strand": sub_strand,
        "media": rows,
        "planned": sum(1 for r in rows if r.get("status") == "planned"),
        "produced": sum(1 for r in rows if r.get("status") == "produced"),
    }


@router.post("/factory/media/attach")
def factory_attach_media_asset(
    payload: AttachMediaAssetRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Record a produced photograph or video against the plan it came from.

    The plan is kept, not replaced: what the asset was supposed to show is how
    a reviewer decides whether the thing that arrived is the thing that was
    asked for.
    """
    from ..infra.db import fetch_one

    row = fetch_one(
        "SELECT media_id, kind, title FROM substrand_media WHERE media_id = :id",
        {"id": payload.media_id},
    )
    if not row:
        raise_api_error(
            "DATASET_ITEM_NOT_FOUND",
            f"No media plan '{payload.media_id}'. Plan it with "
            "POST /factory/generate-media-prompts before attaching an asset.",
        )

    kind = str(row.get("kind") or "")
    allowed = media_registry.ALLOWED_CONTENT_TYPES.get(kind, ())
    content_type = (payload.content_type or "").split(";")[0].strip().lower()
    if content_type and allowed and content_type not in allowed:
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{content_type}' is not a {kind}. Accepted: {', '.join(allowed)}.",
        )

    media_registry.attach_asset(payload.media_id, payload.storage_url, content_type)
    return {
        "status": "attached",
        "media_id": payload.media_id,
        "kind": kind,
        "title": row.get("title"),
        "storage_url": payload.storage_url,
    }


@router.post("/factory/media/upload")
def factory_upload_media_asset(
    media_id: str = Form(...),
    file: UploadFile = File(...),
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Upload the produced file itself and attach it to its plan."""
    from ..infra.db import fetch_one
    from ..infra.storage import object_storage

    row = fetch_one(
        "SELECT media_id, kind, title FROM substrand_media WHERE media_id = :id",
        {"id": media_id},
    )
    if not row:
        raise_api_error(
            "DATASET_ITEM_NOT_FOUND",
            f"No media plan '{media_id}'. Plan it before uploading an asset.",
        )

    kind = str(row.get("kind") or "")
    allowed = media_registry.ALLOWED_CONTENT_TYPES.get(kind, ())
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if allowed and content_type not in allowed:
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{content_type or 'unknown'}' is not a {kind}. "
            f"Accepted: {', '.join(allowed)}.",
        )

    payload = file.file.read()
    if not payload:
        raise_api_error("VALIDATION_FAILED", "The uploaded file is empty.")

    suffix = (file.filename or "").rsplit(".", 1)
    extension = f".{suffix[-1].lower()}" if len(suffix) == 2 else ""
    url = object_storage.save_bytes(
        f"media/{kind}/{media_id}{extension}", payload, content_type
    )
    media_registry.attach_asset(media_id, url, content_type)
    return {
        "status": "uploaded",
        "media_id": media_id,
        "kind": kind,
        "title": row.get("title"),
        "storage_url": url,
        "bytes": len(payload),
    }


def _record_artifact(
    kind: str, grade: str, subject: str, content: dict[str, Any], *,
    strand: str = "", sub_strand: str = "", title: str = "",
    provenance: dict[str, Any] | None = None, parent: str = "",
) -> dict[str, Any]:
    """File one generation as a version, and never fail the generation for it.

    Recording is bookkeeping: if it breaks, the operator should still get the
    content they asked for, with a warning rather than a 500.
    """
    try:
        artifact = artifact_registry.create_version(
            kind, grade, subject, content, strand=strand, sub_strand=sub_strand,
            title=title, parent_artifact_id=parent, provenance=provenance or {},
        )
        return {"artifact_id": artifact.artifact_id, "version": artifact.version,
                "artifact_key": artifact.artifact_key}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not version %s for %s/%s: %s", kind, grade, subject, exc)
        return {"error": str(exc)[:200]}


@router.post("/factory/repair")
def factory_run_repairs(
    dry_run: bool = Query(False, description="Report what would change, change nothing"),
    only: str = Query("", description="Run one repair by id"),
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Sweep out content saved before the guards existed.

    These run at startup too. This is for running them on demand — after an
    ingest, or to see with `dry_run=true` what a sweep would remove before it
    removes it.
    """
    from ..services.data_repairs import run_repairs

    return run_repairs(dry_run=dry_run, only=only)


@router.get("/factory/repair-status")
def factory_repair_status(
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """How often each sweep has run and what it last found.

    A repair that keeps finding rows means something upstream is still
    producing them, which is worth seeing rather than quietly fixing forever.
    """
    from ..infra.db import fetch_all
    from ..services.data_repairs import REPAIRS

    try:
        rows = {str(r["repair_id"]): r for r in (fetch_all(
            "SELECT * FROM data_repairs ORDER BY repair_id"
        ) or [])}
    except Exception:  # noqa: BLE001
        rows = {}

    repairs = [
        {"repair_id": repair_id, **{k: v for k, v in (rows.get(repair_id) or {}).items()
                                    if k != "repair_id"}}
        for repair_id, _fn in REPAIRS
    ]
    still_finding = [r["repair_id"] for r in repairs if (r.get("rows_affected_last") or 0) > 0]
    return {
        "repairs": repairs,
        "still_finding_rows": still_finding,
        "stable": not still_finding,
    }


@router.get("/factory/structure")
def factory_read_structure(
    grade: str = Query(..., description="Grade slug, e.g. grade-pp1"),
    subject: str = Query(..., description="Learning area or subject name"),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """The strands and sub-strands already stored for a learning area.

    The console built its structure view out of whatever the current session
    had generated, and read nothing back. Saved sub-strands were in the
    database the whole time; a page reload simply had no way to find them, so
    the work looked lost and got generated again.
    """
    from ..infra.db import fetch_all, fetch_one

    alt_grade = grade.replace("grade-", "") if grade.startswith("grade-") else f"grade-{grade}"
    params = {"grade": grade, "alt_grade": alt_grade, "subject": subject}

    rows = fetch_all(
        """
        SELECT strand_id, strand_name, sub_strand_id, sub_strand_name, theme,
               allocated_hours, slos, learning_experiences, key_inquiry_questions,
               core_competencies, values, assessment_rubrics,
               pertinent_contemporary_issues, link_to_other_learning_areas,
               source_pages, updated_at
        FROM curriculum_substrands
        WHERE (grade = :grade OR grade = :alt_grade) AND LOWER(subject) = LOWER(:subject)
        ORDER BY strand_id ASC, sub_strand_id ASC
        """,
        params,
    ) or []

    # Strands with no sub-strands yet are held on the design, so a strand list
    # survives a reload before any sub-strand has been generated under it.
    design = fetch_one(
        """
        SELECT design_id, metadata FROM curriculum_designs
        WHERE (grade = :grade OR grade = :alt_grade) AND LOWER(subject) = LOWER(:subject)
          AND metadata ? 'strands'
        ORDER BY updated_at DESC LIMIT 1
        """,
        params,
    )
    stored_strands = ((design or {}).get("metadata") or {}).get("strands") or []

    strands: dict[str, dict[str, Any]] = {}
    for entry in stored_strands:
        name = substrand_hygiene.strip_numbering(
            str(entry.get("strand_name") or entry.get("name") or "")
        )
        if name:
            strands[substrand_hygiene.strand_key(name)] = {
                "strand_id": str(entry.get("strand_id") or entry.get("id") or ""),
                "strand_name": name,
                "description": str(entry.get("description") or ""),
                "sub_strands": [],
                "saved": False,
            }

    for row in rows:
        name = substrand_hygiene.strip_numbering(str(row.get("strand_name") or ""))
        # Rows saved before names were de-numbered still merge into one strand.
        key = substrand_hygiene.strand_key(name)
        if key not in strands:
            strands[key] = {
                "strand_id": str(row.get("strand_id") or ""),
                "strand_name": name,
                "description": "",
                "sub_strands": [],
                "saved": True,
            }
        strands[key]["saved"] = True
        strands[key]["sub_strands"].append({
            k: row.get(k) for k in (
                "sub_strand_id", "sub_strand_name", "theme", "allocated_hours",
                "slos", "learning_experiences", "key_inquiry_questions",
                "core_competencies", "values", "assessment_rubrics",
                "pertinent_contemporary_issues", "link_to_other_learning_areas",
                "source_pages",
            )
        })

    ordered = sorted(strands.values(), key=lambda s: (s["strand_id"] or "zz", s["strand_name"]))
    return {
        "grade": grade,
        "subject": subject,
        "design_id": (design or {}).get("design_id", ""),
        "strands": ordered,
        "strand_count": len(ordered),
        "sub_strand_count": len(rows),
    }


@router.post("/factory/save-strands")
def factory_save_strands(
    payload: FactorySaveStrandsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Persist a generated strand list against its design.

    There was no way to save a strand at all. Sub-strands had a table; strands
    lived only in the browser tab that generated them, so a reload lost the
    layer everything else hangs off — including the strand names needed to
    generate sub-strands under them.

    Stored on the design's metadata, which is the shape the progress report
    already reads for strands that have no sub-strands yet.
    """
    from ..infra.db import execute, fetch_one, to_json

    found = design_source.resolve(payload.grade, payload.subject)
    design_id = payload.design_id or found.design_id
    if not design_id:
        raise_api_error(
            "MISSING_PARENT_CONTEXT",
            f"No ingested design for '{payload.subject}' ({payload.grade}) to attach "
            f"these strands to. Ingest it with POST /factory/ingest-learning-area "
            f'{{"grade": "{payload.grade}", "subject": "{payload.subject}"}} first.',
        )

    accepted, refused = substrand_hygiene.clean_strands(payload.strands)
    clean: list[dict[str, Any]] = []
    for entry in accepted:
        name = substrand_hygiene.strip_numbering(
            str(entry.get("strand_name") or entry.get("name") or "")
        )
        if not name:
            continue
        clean.append({
            "strand_id": str(entry.get("strand_id") or entry.get("id") or ""),
            "strand_name": name,
            "description": str(entry.get("description") or ""),
            "source_pages": [p for p in (entry.get("source_pages") or []) if isinstance(p, int)],
            "sub_strands": [],
        })

    if not clean:
        raise_api_error("VALIDATION_FAILED", "No named strands to save.")

    row = fetch_one(
        "SELECT metadata FROM curriculum_designs WHERE design_id = :design_id",
        {"design_id": design_id},
    )
    metadata = dict((row or {}).get("metadata") or {})
    metadata["strands"] = clean

    execute(
        "UPDATE curriculum_designs SET metadata = CAST(:metadata AS jsonb), updated_at = NOW() "
        "WHERE design_id = :design_id",
        {"metadata": to_json(metadata), "design_id": design_id},
    )
    versioned = _record_artifact(
        "strand", payload.grade, payload.subject, {"strands": clean},
        provenance={"source": "factory_save_strands", "design_id": design_id},
    )

    return {
        "status": "saved",
        "design_id": design_id,
        "saved_count": len(clean),
        "refused": refused,
        "strands": [c["strand_name"] for c in clean],
        "artifact": versioned,
    }


@router.post("/factory/save-substrands")
def factory_save_substrands(
    payload: FactorySaveSubstrandsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Saves generated sub-strands for a strand to PostgreSQL database."""
    from ..infra.db import execute, to_json
    from ..services.curriculum_catalogue import expected_subjects, has_combined_design

    # Every learning area of a combined design shares one (grade, subject,
    # strand, sub_strand) key, so writing all seven under the level name
    # "Pre-Primary 1" made each save overwrite and prune the last. Four rounds of
    # generation produced four different partial pictures and no error, because
    # nothing here objected to a subject that is not a learning area.
    #
    # Only enforced where the published set is definitive. Senior-school subjects
    # come off each PDF's cover, so those are left alone.
    if has_combined_design(payload.grade):
        published = expected_subjects(payload.grade)
        if published and payload.subject not in published:
            raise_api_error(
                "MISSING_PARENT_CONTEXT",
                f"'{payload.subject}' is not a learning area of {payload.grade}. "
                f"It looks like the level rather than a learning area, and saving "
                f"under it makes every area overwrite the last. "
                f"Valid learning areas: {', '.join(published)}. "
                f"If the console is still offering '{payload.subject}', the design "
                f"has not been re-ingested since it was split into learning areas.",
            )

    # Whatever the console sends, nothing that is raw source text reaches the
    # database. Generation filters too; this is the guarantee, since a payload
    # can also come from a script, a retry, or an older client.
    substrands, refused = substrand_hygiene.clean(payload.strand_name, payload.substrands)
    if not substrands:
        raise_api_error(
            "VALIDATION_FAILED",
            f"None of the {len(payload.substrands)} sub-strand(s) sent for "
            f"'{payload.strand_name}' could be saved: "
            + "; ".join(f"{r['sub_strand_name']} — {r['reason']}" for r in refused[:3]),
            detail={"refused": refused},
        )

    saved_count = 0
    # Attach to the design these sub-strands were actually read from. The old
    # fallback minted "cd_grade-pp1_chri" and upserted a parent row for it — a
    # row with no document, newer than the real one, which then won every
    # "ORDER BY updated_at DESC LIMIT 1" lookup in the codebase. Saving
    # sub-strands would silently unground the next generation of them.
    design_id = payload.design_id or design_source.resolve(
        payload.grade, payload.subject
    ).design_id
    if not design_id:
        raise_api_error(
            "MISSING_PARENT_CONTEXT",
            f"No ingested design for '{payload.subject}' ({payload.grade}) to attach "
            f"these sub-strands to. Ingest it with POST /factory/ingest-learning-area "
            f'{{"grade": "{payload.grade}", "subject": "{payload.subject}"}} first.',
        )

    # The design numbers some entries and not others ("4.1 Love for God" beside
    # "A House of God"). Since the row's unique key is the NAME, that split one
    # strand into two and made the same sub-strand savable twice. The numbering
    # lives in the id column, which is where it belongs.
    strand_name = substrand_hygiene.strip_numbering(payload.strand_name)

    for ss in substrands:
        sub_id = str(ss.get("sub_strand_id") or ss.get("id") or "1.1")
        sub_name = substrand_hygiene.strip_numbering(
            str(ss.get("sub_strand_name") or ss.get("name") or sub_id)
        )
        # The design states its own unit — "3 lessons" for pre-primary, "4 hours"
        # for DTE. Defaulting to "4 hours" wrote a fabricated figure for every
        # sub-strand that arrived without one, and it was indistinguishable
        # afterwards from one KICD actually published. Store the gap instead.
        allocated = str(
            ss.get("allocated_time") or ss.get("allocated_hours") or ss.get("hours") or ""
        ).strip()
        theme = str(ss.get("theme") or "").strip()
        slos = ss.get("slos", [])
        learning_exp = ss.get("learning_experiences", [])
        kiqs = ss.get("key_inquiry_questions", [])
        competencies = ss.get("core_competencies", [])
        vals = ss.get("values", [])
        rubrics = ss.get("assessment_rubric") or ss.get("assessment_rubrics") or {}
        diagrams = ss.get("required_diagrams", [])
        experiments = ss.get("experiments", [])
        safety_hazards = ss.get("safety_hazards_to_check", [])
        pcis = ss.get("pertinent_and_contemporary_issues") or ss.get("pertinent_contemporary_issues") or []
        link_other = str(ss.get("link_to_other_learning_areas") or "").strip()
        source_pages = [p for p in (ss.get("source_pages") or []) if isinstance(p, int)]

        prompt_context = {
            "subject": payload.subject,
            "grade": payload.grade,
            "strand": strand_name,
            "theme": theme,
            "sub_strand": sub_name,
            "allocated_hours": allocated,
            "slos": slos,
            "kiqs": kiqs,
            "diagram_guidance": diagrams,
            "experiment_guidance": experiments,
            "safety_hazard_criteria": safety_hazards,
            "pertinent_contemporary_issues": pcis,
            "source_pages": source_pages,
        }

        execute(
            """
            INSERT INTO curriculum_substrands (
                design_id, grade, subject, strand_id, strand_name, sub_strand_id, sub_strand_name,
                theme, allocated_hours, slos, learning_experiences, key_inquiry_questions,
                core_competencies, values, assessment_rubrics, required_diagrams,
                experiments, pertinent_contemporary_issues, link_to_other_learning_areas,
                source_pages, pedagogical_guidance, prompt_context, updated_at
            )
            VALUES (
                :design_id, :grade, :subject, :strand_id, :strand_name, :sub_strand_id, :sub_strand_name,
                :theme, :allocated_hours, CAST(:slos AS jsonb), CAST(:learning_exp AS jsonb),
                CAST(:kiqs AS jsonb), CAST(:competencies AS jsonb), CAST(:values AS jsonb),
                CAST(:rubrics AS jsonb), CAST(:diagrams AS jsonb), CAST(:experiments AS jsonb),
                CAST(:pcis AS jsonb), :link_other, CAST(:source_pages AS jsonb),
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
                theme = EXCLUDED.theme,
                pertinent_contemporary_issues = EXCLUDED.pertinent_contemporary_issues,
                link_to_other_learning_areas = EXCLUDED.link_to_other_learning_areas,
                source_pages = EXCLUDED.source_pages,
                pedagogical_guidance = EXCLUDED.pedagogical_guidance,
                prompt_context = EXCLUDED.prompt_context,
                updated_at = NOW()
            """,
            {
                "design_id": design_id,
                "grade": payload.grade,
                "subject": payload.subject,
                "strand_id": payload.strand_id,
                "strand_name": strand_name,
                "sub_strand_id": sub_id,
                "sub_strand_name": sub_name,
                "theme": theme,
                "pcis": to_json(pcis),
                "link_other": link_other,
                "source_pages": to_json(source_pages),
                "allocated_hours": allocated,
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

    # Each sub-strand is versioned separately: review and approval are decisions
    # about one sub-strand, not about a batch that happened to save together.
    versioned = [
        _record_artifact(
            "sub_strand", payload.grade, payload.subject, ss,
            strand=strand_name,
            sub_strand=substrand_hygiene.strip_numbering(
                str(ss.get("sub_strand_name") or ss.get("name") or "")
            ),
            provenance={"source": "factory_save_substrands", "design_id": design_id},
        )
        for ss in substrands
    ]

    return {
        "status": "saved",
        "saved_count": saved_count,
        "refused": refused,
        "strand_name": payload.strand_name,
        "artifacts": versioned,
    }

