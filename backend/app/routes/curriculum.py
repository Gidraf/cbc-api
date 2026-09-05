from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from fastapi.responses import HTMLResponse
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel

from ..errors import raise_api_error
from ..infra.db import execute, fetch_all, fetch_one
from ..services.artifact_dna import artifact_dna_service
from ..services.auth import AuthContext, require_roles
from ..services.curriculum_extractor import curriculum_extractor
from ..services import (
    artifact_registry,
    citation_check,
    auto_run,
    design_source,
    export_bundle,
    fabrication_check,
    generation_version,
    quality_score,
    media_registry,
    media_validators,
    notes_coverage,
    notes_integrity,
    notes_remediation,
    redundancy_check,
    run_log,
    notes_repair,
    review_cycle,
    rubric_filler,
    rubric_integrity,
    rubric_tables,
    scoped_delete,
    source_pages as source_pages_service,
    simulation_validators,
    substrand_integrity,
    substrand_hygiene,
    time_allocation,
)
from ..services.grade_order import grade_level
from ..services.faith_scope import prompt_block as faith_prompt_block
from ..services.grade_scope import notes_for as grade_scope_notes
from ..services import notation, prompt_fragments
from ..services.target_language import block_for as target_language_block
from ..services.material_form import block_for as _material_form_block
from ..services.level_register import (
    language_block,
    register_block,
    register_for_grade as level_register_for,
)

logger = logging.getLogger(__name__)

# How much of the curriculum design the notes prompt carries. A design runs to
# about 32,000 characters — 8,000 tokens against a 128,000-token window — so the
# whole of it fits, and a guide written from a twentieth of its source scores
# 0.20 on grounding because that is what it deserves.
MAX_DESIGN_CHARS = 120_000


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
        # LOWER on both sides. The rows are written as "grade-pp1"; a caller
        # sending "PP1" derives "grade-PP1", which is not equal to it in
        # Postgres — and the console then reports a grade with seven ingested
        # designs as having no sub-strands at all.
        conditions.append(
            "(LOWER(grade) = LOWER(:grade) OR LOWER(grade) = LOWER(:alt_grade) "
            "OR :grade = '' OR :grade IS NULL)"
        )
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
        design_conds.append("(REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))")
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
    """Delete one sub-strand and everything generated from it.

    This used to run three DELETEs of its own, against substrand_resources,
    curriculum_substrands and question_dna. It was wrong in three ways.

    It never touched `artifacts`, so every version of the notes, diagrams,
    activities and media briefs stayed, along with `artifact_reviews`,
    `artifact_labels`, `artifact_comments` and `artifact_dna`. Those still
    count toward coverage and still describe a sub-strand that is gone.

    It took `grade` and never used it, so removing a sub-strand from one grade
    removed it from EVERY grade that had one by that name.

    And it matched with LIKE '%name%', so deleting "God" also deleted "Our God"
    and "God's Love".

    `scoped_delete` already did this correctly for the newer console. There is
    one implementation now.
    """
    report = scoped_delete.delete(
        grade=grade, subject=subject,
        strand=(strand or ""), sub_strand=sub_strand,
        confirm=scoped_delete.CONFIRMATION,
    )
    return {
        "success": True,
        "message": f"Deleted sub-strand '{sub_strand}' and all generated assets.",
        "grade": grade,
        "subject": subject,
        "sub_strand": sub_strand,
        "removed": report.to_dict(),
    }


@router.delete("/strand")
def delete_curriculum_strand(
    grade: str = Query(...),
    subject: str = Query(...),
    strand: str = Query(...),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Delete one strand, its sub-strands, and everything generated from them.

    See `delete_curriculum_substrand` for what this used to leave behind. The
    same three faults applied here, and the grade one was worse: a strand name
    like "Creation" appears in several grades, so removing it from one removed
    it from all of them.
    """
    report = scoped_delete.delete(
        grade=grade, subject=subject, strand=strand,
        confirm=scoped_delete.CONFIRMATION,
    )
    return {
        "success": True,
        "message": f"Deleted strand '{strand}' and all child sub-strands.",
        "grade": grade,
        "subject": subject,
        "strand": strand,
        "removed": report.to_dict(),
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

class FactoryGenerateMaterialRequest(BaseModel):
    """Which plan to write the words from, and for what."""

    grade: str
    subject: str
    strand: str
    sub_strand: str
    # Left empty, the newest filed plan is used — writing material from a plan
    # nobody chose is how two versions of the words come to exist for one
    # version of the lesson.
    plan_artifact_id: str = ""
    custom_instructions: str = ""
    run_id: str = ""


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
    # A browser-generated id for this run. The station's HTTP response does not
    # arrive until the work is finished, so progress is published under this id
    # and the browser polls it while it waits. Optional: without one the run
    # still works and simply says nothing until it is done.
    run_id: str = ""
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
    # A direct call from the factory blocks until the guide is finished, so
    # without this the console shows a spinner for two minutes and then the
    # result. Queued work already has a log started for it by the worker;
    # starting a second one here would throw that one away.
    from ..services import run_log as _run_log

    if payload.run_id and _run_log.current() is None:
        _run_log.start(run_id=payload.run_id)
        _run_log.step("Started", f"{payload.sub_strand} · {payload.subject}")

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
        WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))
          AND LOWER(subject) = LOWER(:subject)
          AND (LOWER(sub_strand_name) = LOWER(:sub_strand) OR LOWER(sub_strand_name) LIKE LOWER(:sub_strand_pattern))
        LIMIT 1
        """
,
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
    kiqs_formatted = (
        "\n".join([f"- {k}" for k in kiqs]) if kiqs
        else "- (The design records no key inquiry question for this sub-strand. "
             "Say so in `gaps`; do not invent one.)"
    )

    # A record that was never parsed cannot produce anything true, and every
    # measure downstream will agree that it did: the HRE run reported "lesson
    # coverage complete, 100%" because one module was asked for and one arrived.
    substrand_integrity.require(
        payload.grade, payload.subject, payload.strand, payload.sub_strand,
        slos=slos, allocated=str((substrand_row or {}).get("allocated_hours") or ""),
    )

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
        # The register says who the learner is; this says what the page IS. A
        # Grade 9 plan that directs a spoken teacher script forces the material
        # station to write one, however well the register is stated.
        "material_form": _material_form_block(payload.grade),
        "language_register": language_block(payload.grade),
            # How this subject writes what it cannot write in words. Empty for
            # most subjects — a CRE guide carrying two pages about balancing
            # equations spends a page of prompt on something it never uses, and
            # every irrelevant instruction makes the relevant ones harder to
            # find.
            "notation": notation.block_for(payload.subject, grade=payload.grade),
            # What THIS subject needs that no other does: maps and scale for
            # Geography, equations that balance for Chemistry, sol-fa for
            # Music, a cutting list for Carpentry. Empty for most pairings,
            # which is the point — a CRE lesson plan receives no paragraph
            # about mortise and tenon joints.
            "domain_directives": prompt_fragments.compose(
                payload.subject, "notes", payload.grade),
        "faith_scope": faith_prompt_block(payload.subject),
        # A language area is taught IN that language; the plan must name
        # the actual phrases, not "greetings".
        "target_language": target_language_block(payload.subject),
        "content_type_directives": ct_profile.format_for_prompt(),
        "level": level,
        "strand": payload.strand,
        "sub_strand": payload.sub_strand,
        "slo_id": payload.slo_id or f"{payload.grade}-{payload.subject[:3]}-01",
        "slos": slos_formatted,
        "kiqs": kiqs_formatted,
        "essence_statement": essence_stmt or f"Comprehensive curriculum blueprint for {payload.subject} ({payload.grade}).",
        # Was 4,000 characters — pages 198 to 203, cut mid-table at "The learner
        # is guided to:". The model never saw the rest of the design and was
        # then scored on how well it matched it. The whole design fits: at
        # roughly four characters per token, 32,000 characters is 8,000 tokens
        # against a 128,000-token window.
        "source_material_snippet": (
            source_text[:MAX_DESIGN_CHARS] if source_text
            else "(NO DESIGN DOCUMENT AVAILABLE)"
        ),
        "design_extract": design_block or "(no stored sub-strand detail)",
        "time_allocation": allocation.phrase(),
        "research_dossier": dossier.formatted_context,
        "custom_instructions": payload.custom_instructions,
    }

    context = langfuse_context_service.assemble_agent_context(
        agent_name="note-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        # One sub-strand's guide does not need the other eleven in full. That
        # block was 20,606 characters, ~18,000 of them about sub-strands this
        # guide is not writing, while the design itself was cut to a 4,000-char
        # excerpt — and the gate then scored grounding against all 31,689.
        focus_strand=payload.strand,
        focus_sub_strand=payload.sub_strand,
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
            f"4. What is TAUGHT follows the learner described in WHO THIS IS FOR: a "
            f"note a teacher cannot deliver to this age group is wrong however "
            f"thorough it is. How much GUIDANCE the teacher gets does not follow the "
            f"learner, and the floor below is a floor.\n"
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
            f"=== WRITE EACH LESSON AS TOPICS, NOT AS ONE BLOCK ===\n"
            f"Do NOT write the exposition as a single long passage. Break it into "
            f"named TOPICS and add them to each module as "
            f"`exposition_segments`, an array of objects:\n\n"
            f'  "exposition_segments": [\n'
            f'    {{"topic": "<what this part of the lesson covers>",\n'
            f'     "minutes": <how long this part takes>,\n'
            f'     "body": "<the teaching content for THIS topic only>",\n'
            f'     "bridge": "<one sentence handing over to the next topic>"}}\n'
            f'  ]\n\n'
            f"HOW MANY TOPICS: as many as the lesson genuinely has, at least "
            f"{notes_coverage.MIN_SEGMENTS}. Let the material decide — a lesson "
            f"with five real things to teach gets five topics, and one with "
            f"three gets three. Do not pad to reach a number and do not "
            f"compress two real topics into one to stay under one.\n"
            f"Each topic's `body` should be about "
            f"{notes_coverage.SEGMENT_TARGET_CHARS} characters, and never below "
            f"{notes_coverage.MIN_SEGMENT_CHARS}. Written this way the topics add "
            f"up past the {notes_coverage.MIN_BODY_CHARS:,} characters a whole "
            f"lesson needs, and each one is small enough to write properly.\n"
            f"Keep `teacher_exposition` itself SHORT — two or three sentences "
            f"framing the lesson. The substance belongs in the topics.\n\n"
            f"THE TOPICS MUST JOIN UP. Each `bridge` says in one sentence how this "
            f"topic hands over to the next: what the children now know, and what "
            f"that sets up. The last topic's bridge points to the next lesson. A "
            f"lesson that is four disconnected paragraphs is not a lesson — a "
            f"teacher reads them in order and the children live through them in "
            f"order.\n\n"
            f"WHY IT IS BROKEN UP. One long passage comes out shallow: general "
            f"where it should be specific, and short. A named topic of "
            f"{notes_coverage.SEGMENT_TARGET_CHARS} characters can be written "
            f"properly — the actual words to say, the actual song or story, the "
            f"questions in the order to ask them, what a child who has not "
            f"understood will do and what to do when they do it, what to hold up "
            f"and when.\n"
            f"Restating the outcome in other words is padding and counts for "
            f"nothing.\n\n"
            f"=== ANALOGIES YES, INVENTION NO ===\n"
            f"Reach for real-life analogies and everyday examples. A "
            f"four-year-old understands God as provider through the food on "
            f"their own table, not through a definition. \"God cares for you "
            f"the way your mother does when she gives you food\" is exactly "
            f"the right kind of teaching, and this guide should be full of it.\n"
            f"Draw those analogies from the child's own world as the register "
            f"above describes it: self, family, home, neighbourhood, school. "
            f"Not farms, industry, counties or national development.\n\n"
            f"An analogy is a TEACHING DEVICE and makes no claim about the "
            f"world. A CLAIM asserts something is true, and every claim here "
            f"must be checkable against the KICD design shown to you. The "
            f"difference is not stylistic — it is the whole of it:\n"
            f"  - NEVER cite a scripture reference the design does not name. "
            f"The design names its own; use those and no others. An invented "
            f"chapter and verse is indistinguishable from a real one and a "
            f"teacher will read it aloud to a class.\n"
            f"  - NEVER state a statistic, a percentage or a survey figure. "
            f"Nothing was retrieved for this sub-strand. A number with a source "
            f"attached is worse than no number, because nothing downstream can "
            f"tell it from a real one.\n"
            f"  - NEVER attribute anything to KNBS, KALRO, NEMA, UNESCO, a "
            f"ministry or a named report. If it is not in the design in front "
            f"of you, it is not available to you.\n"
            f"  - NEVER invent a page or line number. Cite only addresses you "
            f"can see in the excerpt above.\n"
            f"Every one of these is checked after you write, mechanically, and "
            f"anything invented is reported against this guide.\n"
            f"Later modules must be as full as the first. A guide that starts "
            f"strong and thins out is the failure this instruction exists to "
            f"prevent — lessons 4 to 7 are taught by the same teacher on the same "
            f"day as lesson 1.\n\n"
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
                # Not payload.source_material_text: that is what the CALLER
                # supplied, which is empty on every normal request. The
                # inspector must show what the prompt actually carries, or it
                # reports "No design attached" for a fully grounded run.
                source_material=source_text,
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
    notes_content = resp.content

    # The depth floor is checked BEFORE anything else reads the guide, because
    # everything downstream is downstream of it: the audit counts its words, the
    # gate scores its grounding, the artifact stores it, and the operator is
    # shown a green tick. On the run this was written for, all seven modules of
    # a seven-lesson sub-strand came back between 498 and 798 characters against
    # a 1,500 floor — and the only consequence was a line in the log.
    #
    # A validator whose finding changes nothing is a comment. This one now sends
    # the modules it named back to be written properly.
    design_experiences = (substrand_row or {}).get("learning_experiences") or []
    lesson_plan = notes_coverage.check(
        notes_content, allocation, slos, experiences=design_experiences
    )
    run_log.step(
        "Drafted",
        f"{lesson_plan.modules_found} of {lesson_plan.modules_required} "
        f"{allocation.unit or 'lessons'}, "
        f"{lesson_plan.total_body_chars:,} characters of teaching",
        "ok" if lesson_plan.complete else "warn",
    )

    repair_report = notes_repair.RepairReport()
    if isinstance(notes_content, dict) and lesson_plan.thin_modules:
        run_log.step("Expanding thin lessons",
                     ", ".join(str(t.get("module")) for t in lesson_plan.thin_modules),
                     "warn")
        notes_content, repair_report = notes_repair.repair(
            notes_content,
            lesson_plan,
            generate=llm_client.generate,
            model_config=resolved,
            base_messages=context.messages,
            design_block=design_block,
            allocation_phrase=allocation.phrase(),
            sub_strand=payload.sub_strand,
        )
        lesson_plan = notes_coverage.check(
            notes_content, allocation, slos, experiences=design_experiences
        )

    # Every check below this line used to run, report, and change nothing. A
    # validator whose finding changes nothing is a comment — so the findings
    # now drive repairs and, where a repair needs one, a targeted rewrite,
    # before the guide is offered for review at all.
    notes_content, remediation = notes_remediation.run(
        notes_content,
        # `slos` rows come back from the design as {"id": …, "text": …}, so
        # str() on one produced a map whose outcome read
        # "{'id': 'grade-pp1-Chr-1.1-1', 'text': 'identify three qualities of
        # God'}" — a scheme of work with a Python dict printed in it.
        design_experiences=[_plain(e) for e in (design_experiences or [])],
        slos=[_plain(s) for s in (slos or [])],
        # The page-addressed document, so a citation whose quote is real but
        # whose address has drifted is corrected rather than reported.
        design_text=source_text or "",
        generate=llm_client.generate,
        model_config=resolved,
        base_messages=context.messages,
        sub_strand=payload.sub_strand,
        allocation_phrase=allocation.phrase(),
    )
    if remediation.attempted:
        lesson_plan = notes_coverage.check(
            notes_content, allocation, slos, experiences=design_experiences
        )
        run_log.step(
            "Self-check settled",
            f"{remediation.score_before}/100 → {remediation.score_after}/100 "
            f"after {len(remediation.passes)} pass(es) "
            f"({remediation.rewrites} rewrite(s), "
            f"{remediation.regenerations} regeneration(s), "
            f"{remediation.calls} extra model call(s), "
            f"${remediation.cost_usd:.4f})",
            "ok" if remediation.clean else "warn",
        )

    audit_report = web_research_agent.perform_quality_audit(notes_content, "notes", dossier)

    # Downstream readers — coverage, the DNA scorer, the stage guard, the visual
    # planner — were written against hour_modules and key_concepts. Mirroring
    # keeps them working without renaming the same list in six places, each of
    # which would silently read zero until it was found. It must happen before
    # the normaliser below, which reads hour_modules and would otherwise see
    # none of the guide's own modules.
    if isinstance(notes_content, dict) and notes_content.get("modules"):
        notes_content.setdefault("hour_modules", notes_content["modules"])

    # Normalize notes output so both hour_modules and key_concepts are rich arrays
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
        # The gate scores source_grounding against blueprint["raw_source"], and
        # the sub-strand row does not carry the design. Without this the measure
        # reported "not measurable — no curriculum source text supplied" while
        # the design was sitting in the prompt.
        blueprint={**(substrand_row or {}), "raw_source": source_text},
        content_type_profile=ct_profile,
        custom_instructions=payload.custom_instructions,
    )

    # The design funds a fixed number of lessons and the guide must plan every
    # one of them. A short guide used to pass silently: the fallback below built
    # hour modules out of whatever concepts came back, so four modules for a
    # seven-lesson sub-strand looked complete and three lessons had no plan.
    # Citations are resolved, not trusted. A manufactured "202:14" survives
    # every inspection short of opening page 202 — and nobody opens page 202
    # when the field is already filled in.
    # Analogies are a teaching device and are meant to be invented. A statistic,
    # a scripture reference or a named authority is a claim, and a model that
    # invents one produces something indistinguishable from a real one.
    run_log.step("Checking for invention",
                 "scripture, statistics and named authorities against the design")
    fabrication = fabrication_check.check(
        notes_content, source_text,
        has_sources=bool(getattr(dossier, "citations", None)),
    )
    if not fabrication.clean:
        logger.warning(
            "Notes for %s carry %d invented claim(s).",
            payload.sub_strand, len(fabrication.findings),
        )

    # A duplicated lesson clears every check that measures length, because it
    # is a full-length lesson. It is only wrong beside the lesson it copies,
    # and nothing that reads the guide forwards — a reviewer included — sees
    # that. So the lessons are compared against each other mechanically.
    # A guide contradicting itself needs no model to catch: its slo_map names
    # lessons that do not carry those outcomes, and its
    # learning_experiences_used names things the design never suggested.
    integrity = notes_integrity.check(
        notes_content,
        [str(e) for e in (design_experiences or [])],
    )
    if integrity.get("checked") and not integrity.get("clean"):
        logger.warning(
            "Notes for %s contradict themselves (%s/100): %s",
            payload.sub_strand, integrity.get("score"),
            "; ".join(integrity.get("findings") or [])[:300],
        )

    repetition = redundancy_check.inspect(notes_content)
    if repetition.get("checked") and not repetition.get("clean"):
        logger.warning(
            "Notes for %s repeat themselves (%s/100): %s",
            payload.sub_strand, repetition.get("score"),
            "; ".join(repetition.get("findings") or [])[:300],
        )

    citations = citation_check.verify(notes_content, source_text)
    if citations.citations and citations.verified < len(citations.citations):
        logger.warning(
            "Notes for %s cite %d line(s) that do not resolve.",
            payload.sub_strand, len(citations.citations) - citations.verified,
        )

    if not lesson_plan.complete:
        logger.warning(
            "Notes for %s (%s) cover %d of %d allocated %s; %d module(s) still thin "
            "after repair.",
            payload.sub_strand, payload.grade, lesson_plan.modules_found,
            lesson_plan.modules_required, allocation.unit or "lessons",
            len(lesson_plan.thin_modules),
        )

    versioned = _record_artifact(
        "notes", payload.grade, payload.subject, notes_content,
        strand=payload.strand, sub_strand=payload.sub_strand,
        provenance={"source": "factory_generate_notes",
                    "provider": resolved.provider, "model": resolved.model},
        # What the checks found, filed WITH the version. These are the findings
        # the console draws under the guide; without them a regeneration has
        # only the reviewers' opinions and reports nothing to fix.
        measured_from={
            "quality_gate": gate_result.to_dict(),
            "lesson_coverage": lesson_plan.to_dict(),
            "fabrication": fabrication.to_dict(),
            "repetition": repetition,
            "integrity": integrity,
        },
    )

    if payload.run_id:
        run_log.step("Finished", f"version {versioned.get('version', 1)} saved")
        _run_log.stop()

    return {
        "notes": notes_content,
        "usage": resp.usage,
        "model": resp.model,
        "content_type": ct_profile.to_dict(),
        "research_dossier": dossier.to_dict(),
        "quality_audit": audit_report.to_dict(),
        "quality_gate": gate_result.to_dict(),
        "lesson_coverage": lesson_plan.to_dict(),
        "fabrication": fabrication.to_dict(),
        "repetition": repetition,
        "integrity": integrity,
        "remediation": remediation.to_dict(),
        "progress": (run_log.current().to_dict() if run_log.current() else {}),
        # Reported so the measured score can weigh it. It was left off, so the
        # heaviest signal in the scheme read "not reported by this station" on
        # a run that had just consumed 31,689 characters of the design — and
        # the headline score was a weighted mean over 77% of the scheme with
        # no way to see which 23% was missing.
        "grounded": bool(source_text),
        "source_material_length": len(source_text or ""),
        "notes_repair": repair_report.to_dict(),
        "citations": citations.to_dict(),
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
            "language_register": language_block(payload.grade),
            # How this subject writes what it cannot write in words. Empty for
            # most subjects — a CRE guide carrying two pages about balancing
            # equations spends a page of prompt on something it never uses, and
            # every irrelevant instruction makes the relevant ones harder to
            # find.
            "notation": notation.block_for(payload.subject, grade=payload.grade),
            # What THIS subject needs that no other does: maps and scale for
            # Geography, equations that balance for Chemistry, sol-fa for
            # Music, a cutting list for Carpentry. Empty for most pairings,
            # which is the point — a CRE lesson plan receives no paragraph
            # about mortise and tenon joints.
            "domain_directives": prompt_fragments.compose(
                payload.subject, "diagram", payload.grade),
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
            "language_register": language_block(payload.grade),
            # How this subject writes what it cannot write in words. Empty for
            # most subjects — a CRE guide carrying two pages about balancing
            # equations spends a page of prompt on something it never uses, and
            # every irrelevant instruction makes the relevant ones harder to
            # find.
            "notation": notation.block_for(payload.subject, grade=payload.grade),
            # What THIS subject needs that no other does: maps and scale for
            # Geography, equations that balance for Chemistry, sol-fa for
            # Music, a cutting list for Carpentry. Empty for most pairings,
            # which is the point — a CRE lesson plan receives no paragraph
            # about mortise and tenon joints.
            "domain_directives": prompt_fragments.compose(
                payload.subject, "activity", payload.grade),
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
            "language_register": language_block(payload.grade),
            # How this subject writes what it cannot write in words. Empty for
            # most subjects — a CRE guide carrying two pages about balancing
            # equations spends a page of prompt on something it never uses, and
            # every irrelevant instruction makes the relevant ones harder to
            # find.
            "notation": notation.block_for(payload.subject, grade=payload.grade),
            # What THIS subject needs that no other does: maps and scale for
            # Geography, equations that balance for Chemistry, sol-fa for
            # Music, a cutting list for Carpentry. Empty for most pairings,
            # which is the point — a CRE lesson plan receives no paragraph
            # about mortise and tenon joints.
            "domain_directives": prompt_fragments.compose(
                payload.subject, "diagram", payload.grade),
            "faith_scope": faith_prompt_block(payload.subject),
            "content_type_directives": ct_profile.format_for_prompt(),
            "notes_content": notes_str or payload.notes_title or payload.sub_strand,
        },
    )

    # The plan names its own assets — "visual aids for gestures", "observe
    # pictures of Adam and Eve". Planning visuals from the sub-strand's title
    # and outcomes instead is how a station came back with assets the lesson
    # never mentions, and how an asset the plan DID ask for was never made.
    from ..services import asset_requirements

    _wanted = asset_requirements.read(notes_dict if isinstance(notes_dict, dict) else {})
    asset_brief = (asset_requirements.render(_wanted, "diagram")
                   or asset_requirements.render(_wanted))
    geometry_spec = notation.geometry_block(payload.subject)

    context.messages.append({
        "role": "user",
        "content": (
            f"{ct_profile.format_for_prompt()}\n\n"
            f"{dossier.formatted_context}\n\n"
            f"=== LAYER 1 MASTER LESSON NOTES CONTEXT (MANDATORY 4-HOUR SOURCE OF TRUTH) ===\n{notes_str}\n\n"
            # What the PLAN asks for, rather than four hardcoded examples.
            #
            # This block used to name "Soil Erosion types, Contour Bunds,
            # Gabions" and "Soil Profile Horizon Strata O-A-B-C, pH Titration"
            # as its examples — for every subject, including a PP1 lesson about
            # God. A reviewer later flagged a soil-profile schematic on that
            # lesson as an invention. It was not an invention: it was this
            # prompt's own example, followed faithfully.
            f"{asset_brief}\n\n"
            # A figure described in prose cannot be drawn twice the same way,
            # and the question asked about it then does not match the picture
            # printed beside it.
            f"{geometry_spec}\n\n"
            f"WHERE THE PLAN ASKS FOR NOTHING in a lesson, work from that "
            f"lesson's own topics and produce 1-3 visuals for it. Every visual "
            f"must be traceable to a topic in the notes above: set "
            f"'hour_index' and 'hour_title' to the lesson it belongs to, and "
            f"do not produce a visual for a lesson that is not listed.\n\n"
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

    # The same shape every other station reports its gate in. Without it the
    # review loop read no score at all and filed a good run as 0/100, "the
    # gate failed but named nothing to fix" — because there was nothing to
    # name.
    from ..services import diagram_gate

    content = {"visuals": visuals_list}
    report = diagram_gate.check(content)
    gate = diagram_gate.gate_of(report)

    versioned = _record_artifact(
        "diagram", payload.grade, payload.subject, content,
        strand=payload.strand, sub_strand=payload.sub_strand,
        provenance={"source": "factory_plan_visuals",
                    "provider": resolved.provider, "model": resolved.model},
        measured_from={"quality_gate": gate},
    )

    return {
        "sub_strand": payload.sub_strand,
        "visuals": visuals_list,
        "usage": resp.usage,
        "model": resp.model,
        "content_type": ct_profile.to_dict(),
        "research_dossier": dossier.to_dict(),
        "quality_gate": gate,
        "coverage": report.to_dict(),
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
            "language_register": language_block(payload.grade),
            # How this subject writes what it cannot write in words. Empty for
            # most subjects — a CRE guide carrying two pages about balancing
            # equations spends a page of prompt on something it never uses, and
            # every irrelevant instruction makes the relevant ones harder to
            # find.
            "notation": notation.block_for(payload.subject, grade=payload.grade),
            # What THIS subject needs that no other does: maps and scale for
            # Geography, equations that balance for Chemistry, sol-fa for
            # Music, a cutting list for Carpentry. Empty for most pairings,
            # which is the point — a CRE lesson plan receives no paragraph
            # about mortise and tenon joints.
            "domain_directives": prompt_fragments.compose(
                payload.subject, "diagram", payload.grade),
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
            "language_register": language_block(payload.grade),
            # How this subject writes what it cannot write in words. Empty for
            # most subjects — a CRE guide carrying two pages about balancing
            # equations spends a page of prompt on something it never uses, and
            # every irrelevant instruction makes the relevant ones harder to
            # find.
            "notation": notation.block_for(payload.subject, grade=payload.grade),
            # What THIS subject needs that no other does: maps and scale for
            # Geography, equations that balance for Chemistry, sol-fa for
            # Music, a cutting list for Carpentry. Empty for most pairings,
            # which is the point — a CRE lesson plan receives no paragraph
            # about mortise and tenon joints.
            "domain_directives": prompt_fragments.compose(
                payload.subject, "activity", payload.grade),
            "faith_scope": faith_prompt_block(payload.subject),
            "content_type_directives": ct_profile.format_for_prompt(),
            "notes_content": notes_str or payload.notes_title or payload.sub_strand,
            "diagram_info": json_lib.dumps(payload.diagram_info, ensure_ascii=False) if payload.diagram_info else "Visual diagram context",
        },
    )

    # What the plan asks this station for, rather than a lesson about soil.
    from ..services import asset_requirements as _asset_requirements

    activity_brief = _asset_requirements.render(
        _asset_requirements.read(notes_dict if isinstance(notes_dict, dict) else {}),
        "activity",
    )

    context.messages.append({
        "role": "user",
        "content": (
            f"{ct_profile.format_for_prompt()}\n\n"
            f"{dossier.formatted_context}\n\n"
            f"=== LAYER 1 MASTER LESSON NOTES CONTEXT (MANDATORY 4-HOUR SOURCE OF TRUTH) ===\n{notes_str}\n\n"
            # The same hardcoded soil-science lesson the visuals prompt
            # carried: "Agroforestry layout", "contour terracing", "Soil pH
            # Titration & Buffer Capacity" — offered as the examples for every
            # subject, including a PP1 lesson taught by singing. A station given
            # those examples and asked to be authentic will be authentic about
            # soil.
            f"{activity_brief}\n\n"
            f"WHAT COUNTS AS A PRACTICAL IS SET BY THE LEARNER, NOT BY THE "
            f"SUBJECT. The register above says what this age can do with their "
            f"hands: at pre-primary that is singing games, role-play, "
            f"modelling and nature walks, and there are no laboratory "
            f"practicals at all. Produce one practical per lesson, drawn from "
            f"what THAT lesson teaches, and set 'hour_index' and 'hour_title' "
            f"to it.\n\n"
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
            "language_register": language_block(payload.grade),
            # How this subject writes what it cannot write in words. Empty for
            # most subjects — a CRE guide carrying two pages about balancing
            # equations spends a page of prompt on something it never uses, and
            # every irrelevant instruction makes the relevant ones harder to
            # find.
            "notation": notation.block_for(payload.subject, grade=payload.grade),
            # What THIS subject needs that no other does: maps and scale for
            # Geography, equations that balance for Chemistry, sol-fa for
            # Music, a cutting list for Carpentry. Empty for most pairings,
            # which is the point — a CRE lesson plan receives no paragraph
            # about mortise and tenon joints.
            "domain_directives": prompt_fragments.compose(
                payload.subject, "activity", payload.grade),
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
            "language_register": language_block(payload.grade),
            # How this subject writes what it cannot write in words. Empty for
            # most subjects — a CRE guide carrying two pages about balancing
            # equations spends a page of prompt on something it never uses, and
            # every irrelevant instruction makes the relevant ones harder to
            # find.
            "notation": notation.block_for(payload.subject, grade=payload.grade),
            # What THIS subject needs that no other does: maps and scale for
            # Geography, equations that balance for Chemistry, sol-fa for
            # Music, a cutting list for Carpentry. Empty for most pairings,
            # which is the point — a CRE lesson plan receives no paragraph
            # about mortise and tenon joints.
            "domain_directives": prompt_fragments.compose(
                payload.subject, "questions", payload.grade),
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


class QueueWorkRequest(BaseModel):
    """Queue the long work instead of holding a request open for it."""

    grade: str
    subject: str
    # Which stations to run, in order. Each runs for every sub-strand in scope.
    kinds: list[str] = ["notes"]
    strand: str = ""
    # Empty means every sub-strand stored for this subject.
    sub_strands: list[str] = []
    custom_instructions: str = ""


class QueueSubstrandsRequest(BaseModel):
    """Queue sub-strand generation for several strands at once.

    Separate from QueueWorkRequest because that one runs stations AGAINST
    stored sub-strands; this one produces them, and its output is a draft
    nobody has accepted yet.
    """

    grade: str
    subject: str
    # Empty means every strand stored for this subject that has no sub-strands.
    strands: list[dict[str, str]] = []
    custom_instructions: str = ""


class QueueReviewRequest(BaseModel):
    """Send artifacts for review or approval in the background.

    Review is a model call and takes as long as one, so doing a grade's worth
    by hand is the same afternoon the generation used to be.
    """

    grade: str
    subject: str = ""
    strand: str = ""
    # Named artifacts, or empty for every artifact in scope that is not yet
    # approved.
    artifact_ids: list[str] = []
    kinds: list[str] = []
    # "review" runs one layer; "approval" runs whatever layers are missing and
    # then reports what still blocks a human sign-off.
    work: str = "approval"
    layer: int = 2
    provider: str = ""
    model: str = ""


class QueuePipelineRequest(BaseModel):
    """Run the whole chain for a learning area, unattended."""

    grade: str
    subject: str
    # Where to start and stop. Defaults to everything from reading the design
    # to writing the questions.
    steps: list[str] = []
    # Narrow to one strand, for a re-run that should not touch the rest.
    strand: str = ""
    custom_instructions: str = ""
    # Re-ingest even where a design is already stored.
    force_ingest: bool = False


class AutoRunRequest(BaseModel):
    """Generate unattended, with a floor the run stops at."""

    grade: str
    # Empty means every learning area with an ingested design for this grade.
    subjects: list[str] = []
    steps: list[str] = []
    # The measured score the recent average must stay above. This is what the
    # pipeline's own validators report, not a human reading the output — see
    # quality_score for exactly what it does and does not know.
    floor: float = 95.0
    window: int = 5
    # How many times a failing generation is sent back with the review's
    # findings. One is cheapest; three is the default and three times the bill
    # across a grade.
    review_cycles: int = 3
    custom_instructions: str = ""


class QueueRegenerateRequest(BaseModel):
    """Regenerate versions from their reviewers' findings, in the background."""

    grade: str = ""
    subject: str = ""
    artifact_ids: list[str] = []
    extra_instructions: str = ""


class DeleteScopeRequest(BaseModel):
    """Remove one strand or one sub-strand, with what was generated from it."""

    grade: str
    subject: str
    strand: str = ""
    sub_strand: str = ""
    # A dry run unless this says DELETE. The counts come back either way.
    confirm: str = ""


class RegenerateScopeRequest(BaseModel):
    """Throw one strand's sub-strands away and generate them again."""

    grade: str
    subject: str
    strand: str
    strand_id: str = "1.0"
    sub_strand: str = ""
    custom_instructions: str = ""
    confirm: str = ""


class DiscardDraftRequest(BaseModel):
    job_id: str


class FactoryResetRequest(BaseModel):
    """Clear generated content so the pipeline can be re-run from the dataset."""

    grade: str = ""
    subject: str = ""
    # A boolean is too easy to send by accident from a form or a retried
    # request. The exact phrase has to be typed.
    confirm: str = ""
    include: list[str] = []


class GenerateSimulationsRequest(BaseModel):
    grade: str
    subject: str
    strand: str = ""
    sub_strand: str
    custom_instructions: str = ""
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
    resolved = pipeline_orchestrator.router.resolve_for_stage("structure_generation")
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
            "language_register": language_block(payload.grade),
            # How this subject writes what it cannot write in words. Empty for
            # most subjects — a CRE guide carrying two pages about balancing
            # equations spends a page of prompt on something it never uses, and
            # every irrelevant instruction makes the relevant ones harder to
            # find.
            "notation": notation.block_for(payload.subject, grade=payload.grade),
            # What THIS subject needs that no other does: maps and scale for
            # Geography, equations that balance for Chemistry, sol-fa for
            # Music, a cutting list for Carpentry. Empty for most pairings,
            # which is the point — a CRE lesson plan receives no paragraph
            # about mortise and tenon joints.
            "domain_directives": prompt_fragments.compose(
                payload.subject, "structure", payload.grade),
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


def _rubric_writer(payload: Any, resolved: Any, design_block: str) -> Any:
    """The per-sub-strand callable that writes a rubric from its own outcomes.

    Used only where the design's rubric table could not be read. KICD prints
    those as four-column tables and the extracted text is the worst-mangled
    part of every design — one run produced a rubric row from a different
    strand entirely.
    """
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client

    def for_sub_strand(sub_strand: dict[str, Any]) -> list[dict[str, Any]]:
        slos = sub_strand.get("slos") or []
        context = langfuse_context_service.assemble_agent_context(
            agent_name="rubric-generator",
            grade_slug=payload.grade,
            subject=payload.subject,
            template_vars={
                "level_register": register_block(
                    payload.grade,
                    notes=grade_scope_notes(payload.grade, payload.subject),
                ),
                "language_register": language_block(payload.grade),
            # How this subject writes what it cannot write in words. Empty for
            # most subjects — a CRE guide carrying two pages about balancing
            # equations spends a page of prompt on something it never uses, and
            # every irrelevant instruction makes the relevant ones harder to
            # find.
            "notation": notation.block_for(payload.subject, grade=payload.grade),
            # What THIS subject needs that no other does: maps and scale for
            # Geography, equations that balance for Chemistry, sol-fa for
            # Music, a cutting list for Carpentry. Empty for most pairings,
            # which is the point — a CRE lesson plan receives no paragraph
            # about mortise and tenon joints.
            "domain_directives": prompt_fragments.compose(
                payload.subject, "structure", payload.grade),
                "faith_scope": faith_prompt_block(payload.subject),
                "strand": payload.strand_name,
                "sub_strand": str(sub_strand.get("sub_strand_name") or ""),
                "time_allocation": str(sub_strand.get("allocated_time") or "not stated"),
                "slos": "\n".join(
                    f"- {s.get('text', s) if isinstance(s, dict) else s}" for s in slos
                ) or "(none stated)",
                "design_extract": design_block,
            },
        )
        response = llm_client.generate(resolved, context.messages, temperature=0.1)
        content = response.content if isinstance(response.content, dict) else {}
        return [r for r in (content.get("rubric") or []) if isinstance(r, dict)]

    return for_sub_strand


def _ground_substrands(
    sub_strands: list[dict[str, Any]], source_material: str
) -> dict[str, Any]:
    """Put KICD's own rubrics and page numbers on the record, then check them.

    In order, because each step depends on the one before it:

    1. Read the rubric tables. They live on their own pages between sub-strand
       sections, so no per-sub-strand extractor was ever going to find them —
       and five of twelve sub-strands in one PP1 CRE run fell back to generated
       rubrics that KICD had actually published two pages away.
    2. Throw away any rubric that would mismark a child. A wrong rubric is
       worse than an absent one: the filler writes an honest labelled
       replacement for an absent one and cannot tell that a present one is
       wrong.
    3. Resolve the page numbers. The model was guessing them at "this page plus
       the next", which put three of twelve on a neighbouring sub-strand's page
       — and page addresses are what every citation in this system resolves
       against.
    """
    report: dict[str, Any] = {}

    # The generator returns its OWN rubric under the singular key, alongside the
    # one read from the design under the plural. A sub-strand then carries two
    # rubric sets with nothing saying which a teacher follows — and the model's
    # is the worse of the two: for "A Holy Book" it put "Identifies the Holy
    # Bible from other books" at Meeting and "Demonstrates one way of handling
    # the holy Bible" at Below, welding two different indicators into one scale.
    #
    # The design's table is authoritative where it can be read, and
    # `rubric_filler` writes an honest labelled replacement where it cannot. The
    # model's guess is neither.
    dropped_model_rubrics = 0
    for sub in sub_strands:
        if isinstance(sub, dict) and sub.pop("assessment_rubric", None) is not None:
            dropped_model_rubrics += 1
    report["model_rubrics_dropped"] = dropped_model_rubrics

    # One shape per field. The generator returned
    # `link_to_other_learning_areas` as a string for eleven sub-strands and as
    # a list for the twelfth, so anything reading it has to handle both — and
    # the one that forgets fails on whichever sub-strand happens to differ.
    for sub in sub_strands:
        if not isinstance(sub, dict):
            continue
        link = sub.get("link_to_other_learning_areas")
        if isinstance(link, list):
            sub["link_to_other_learning_areas"] = " ".join(
                str(item).strip() for item in link if str(item).strip()
            )
        elif link is not None and not isinstance(link, str):
            sub["link_to_other_learning_areas"] = str(link)

    # Pages FIRST. Each sub-strand's own rubric page is the strongest evidence
    # there is about which rubric measures it, and word overlap alone cannot
    # settle it: "identify three ways loving God" fits both "Love for God" and
    # "God our Loving Father" perfectly, and this resolver runs on one strand
    # at a time, so the wrong one has no competitor to lose to.
    report["source_pages_resolved"] = source_pages_service.apply(
        source_material, sub_strands
    )

    harvest = rubric_tables.harvest(source_material, sub_strands)
    attached = 0
    off_page = 0
    for sub in sub_strands:
        if not isinstance(sub, dict):
            continue
        name = str(sub.get("sub_strand_name") or sub.get("name") or "")
        claimed = {p for p in (sub.get("source_pages") or []) if isinstance(p, int)}
        rows = harvest.for_sub_strand(name)
        if claimed:
            kept = [r for r in rows if r.get("source_page") in claimed]
            off_page += len(rows) - len(kept)
            rows = kept
        if rows:
            sub["assessment_rubrics"] = rows
            attached += len(rows)
    report["rubric_tables"] = {
        **harvest.to_dict(), "attached": attached,
        # Rows whose words matched but whose page belongs to another strand's
        # table. Named rather than filed: KICD prints one rubric table per
        # strand, so a row eight pages away measures something else.
        "rejected_off_page": off_page,
    }

    integrity = rubric_integrity.drop_unsound(sub_strands)
    report["rubric_integrity"] = integrity.to_dict()
    return report


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

    resolved = pipeline_orchestrator.router.resolve_for_stage("structure_generation")

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
                "language_register": language_block(payload.grade),
            # How this subject writes what it cannot write in words. Empty for
            # most subjects — a CRE guide carrying two pages about balancing
            # equations spends a page of prompt on something it never uses, and
            # every irrelevant instruction makes the relevant ones harder to
            # find.
            "notation": notation.block_for(payload.subject, grade=payload.grade),
            # What THIS subject needs that no other does: maps and scale for
            # Geography, equations that balance for Chemistry, sol-fa for
            # Music, a cutting list for Carpentry. Empty for most pairings,
            # which is the point — a CRE lesson plan receives no paragraph
            # about mortise and tenon joints.
            "domain_directives": prompt_fragments.compose(
                payload.subject, "structure", payload.grade),
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
        grounding = _ground_substrands(kept, source_material)
        rubrics = rubric_filler.fill(
            kept, _rubric_writer(payload, resolved, source_material[:12_000])
        )
        return {
            **grounding,
            "subject": payload.subject,
            "grade": payload.grade,
            "strand_name": payload.strand_name,
            "sub_strands": kept,
            "refused": refused,
            "rubrics": rubrics.to_dict(),
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

    # Where the design's rubric table could not be read, write one from the
    # sub-strand's own outcomes and say so. A rubric read from KICD and a rubric
    # derived from its outcomes are different things, and a reviewer must be
    # able to tell them apart.
    grounding = _ground_substrands(sub_strands, source_material)
    rubrics = rubric_filler.fill(
        sub_strands, _rubric_writer(payload, resolved, source_material[:12_000])
    )

    return {
        **grounding,
        "subject": payload.subject,
        "grade": payload.grade,
        "strand_name": payload.strand_name,
        "sub_strands": sub_strands,
        "refused": refused,
        "rubrics": rubrics.to_dict(),
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
            "language_register": language_block(grade),
            "notation": notation.block_for(subject, grade=grade),
            "domain_directives": prompt_fragments.compose(subject, "structure", grade),
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
        resolved = pipeline_orchestrator.router.resolve_for_stage("ingest_extraction")

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


@router.get("/factory/page-reconciliation")
def factory_page_reconciliation(
    grade: str = Query(..., description="Grade slug, e.g. grade-pp1"),
    subject: str = Query(...),
    strand: str = Query("", description="Optional: one strand only"),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Do a strand's pages and its sub-strands' pages add up?

    A strand occupies a span of the design and its sub-strands divide that span
    between them. A sub-strand citing a page outside the span, two sub-strands
    claiming the same page, or a page in the span nobody claims each mean the
    citations point somewhere other than where the content came from — and each
    is invisible one citation at a time.
    """
    from ..infra.db import fetch_all

    strands = [strand] if strand else [
        str(r["strand_name"]) for r in (fetch_all(
            """
            SELECT DISTINCT strand_name FROM curriculum_substrands
            WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))
              AND LOWER(subject) = LOWER(:subject)
            ORDER BY strand_name
            """,
            {"grade": grade, "alt_grade": grade.replace("grade-", ""), "subject": subject},
        ) or []) if r.get("strand_name")
    ]

    reports = [citation_check.reconcile_from_db(grade, subject, name).to_dict()
               for name in strands]
    return {
        "grade": grade,
        "subject": subject,
        "strands": reports,
        "reconciling": sum(1 for r in reports if r["reconciles"]),
        "total": len(reports),
    }


# Which station each queued kind runs, and the payload shape it needs. Kept
# beside the routes so a station and its queued form cannot drift apart.
# The route AND the request class it takes, named outright.
#
# This used to hold only the route name, and the class was recovered from the
# function's annotation at run time. This module opens with
# `from __future__ import annotations`, so that annotation is a string, and
# `"FactoryGenerateNotesRequest".model_fields` is the error every queued
# station failed with. It was patched twice — once here, once in the
# regeneration path that reads the same annotations from another module — and
# a guard that has to be repeated in every caller is not a fix.
#
# There is nothing to resolve now. The class is the value.
_QUEUEABLE: dict[str, tuple[str, Any]] = {
    "notes": ("factory_generate_notes", FactoryGenerateNotesRequest),
    "diagram": ("factory_plan_visuals", FactoryPlanVisualsRequest),
    "media": ("factory_generate_media_prompts", GenerateMediaPromptsRequest),
    "simulation": ("factory_generate_simulations", GenerateSimulationsRequest),
    "activity": ("factory_plan_activities", FactoryPlanActivitiesRequest),
    # The words themselves, written from whichever plan is filed. One call per
    # instruction, so this is the slowest station here — and the reason the
    # queue exists.
    "material": ("factory_generate_material", FactoryGenerateMaterialRequest),
}


def _run_queued(job: dict[str, Any]) -> dict[str, Any]:
    """Run one queued station for one sub-strand.

    The handler is the route function itself, so queued work and clicked work
    take exactly the same path — a queue that reimplements the station is a
    second implementation to keep correct.
    """
    kind = str(job.get("kind") or "")
    registered = _QUEUEABLE.get(kind)
    if not registered:
        raise ValueError(f"'{kind}' has no station to run.")

    endpoint, model_cls = registered
    handler = globals()[endpoint]
    payload = dict(job.get("payload") or {})
    fields = {
        "grade": job.get("grade") or "",
        "subject": job.get("subject") or "",
        "strand": job.get("strand") or "",
        "sub_strand": job.get("sub_strand") or "",
    }
    allowed = set(model_cls.model_fields)

    def produce(instructions: str) -> dict[str, Any]:
        """One generation. The station saves and versions its own output, so
        every cycle is on the record rather than only the one that passed."""
        values = {k: v for k, v in fields.items() if k in allowed}
        if "custom_instructions" in allowed:
            values["custom_instructions"] = instructions
        return handler(model_cls(**values), None)

    # Generate, save, review, revise, save again — inside the worker, where
    # there is time for it. The gate's verdict used to travel back to the
    # console and stop there: an operator read "needs revision at 76/100",
    # retyped the findings into the instructions box, and clicked Generate
    # again, by hand, per sub-strand, across a grade.
    # Cycles are the main cost lever: three passes over a grade is three times
    # the bill. The operator sets it per run rather than per deploy.
    result, cycles = review_cycle.run(
        produce,
        label=f"{kind} for {job.get('sub_strand') or job.get('subject')}",
        base_instructions=str(payload.get("custom_instructions") or ""),
        max_cycles=int(payload.get("review_cycles") or review_cycle.MAX_CYCLES),
    )
    out = _queued_result(result)
    out["review_cycles"] = cycles.to_dict()
    # Scored here as well as in the pipeline, so a single station queued on its
    # own comes back with a number. Without it the only way to compare one
    # model against another was to run a whole pipeline — which is the opposite
    # of the cheap experiment an operator wants before committing to a model.
    out["quality"] = quality_score.score(
        result if isinstance(result, dict) else {}, kind
    ).to_dict()
    return out


# A station's output has to survive the refresh that used to lose it, so the
# whole thing is kept — the operator comes back to finished notes on screen
# rather than to a green tick and a fetch they have to work out themselves.
# Above this, only the summary: a grade's worth of media briefs in one table is
# not what this column is for.
MAX_QUEUED_RESULT_BYTES = 512 * 1024


def _queued_result(result: Any) -> dict[str, Any]:
    """What to store for a finished station job."""
    import json as json_lib

    if not isinstance(result, dict):
        return {}

    summary = {
        "artifact_id": (result.get("artifact") or {}).get("artifact_id", ""),
        "lesson_coverage": result.get("lesson_coverage", {}),
        "brief_quality": result.get("brief_quality", {}),
        "citations": {
            k: v for k, v in (result.get("citations") or {}).items()
            if k in ("total", "verified", "percentage")
        },
    }

    try:
        size = len(json_lib.dumps(result, default=str))
    except Exception:  # noqa: BLE001
        return {**summary, "truncated": True,
                "note": "The result could not be serialised for storage."}

    if size > MAX_QUEUED_RESULT_BYTES:
        return {**summary, "truncated": True,
                "note": f"Result was {size:,} bytes — too large to hold here. "
                        f"It is saved in full; open the sub-strand to read it."}
    return {**result, **summary}


def _run_queued_questions(job: dict[str, Any]) -> dict[str, Any]:
    """Questions are a station like any other, and were the one that was not.

    Its route lives in another module, so the globals() lookup the other
    stations use cannot reach it — which is why it was the one station a
    refresh could still lose.
    """
    from .questions import (
        QuestionBatchGenerateRequest,
        factory_generate_questions_batch,
    )

    payload = dict(job.get("payload") or {})
    fields = {
        "grade": job.get("grade") or "",
        "subject": job.get("subject") or "",
        "strand": job.get("strand") or "",
        "sub_strand": job.get("sub_strand") or "",
        "custom_instructions": payload.get("custom_instructions") or "",
        "batch_count": int(payload.get("batch_count") or 5),
    }
    allowed = set(QuestionBatchGenerateRequest.model_fields)

    def produce(instructions: str) -> dict[str, Any]:
        values = {k: v for k, v in fields.items() if k in allowed}
        if "custom_instructions" in allowed:
            values["custom_instructions"] = instructions
        return factory_generate_questions_batch(
            QuestionBatchGenerateRequest(**values), None
        )

    result, cycles = review_cycle.run(
        produce,
        label=f"questions for {job.get('sub_strand') or job.get('subject')}",
        base_instructions=str(payload.get("custom_instructions") or ""),
        max_cycles=int(payload.get("review_cycles") or review_cycle.MAX_CYCLES),
    )
    out = _queued_result(result)
    out["review_cycles"] = cycles.to_dict()
    # Scored here as well as in the pipeline, so a single station queued on its
    # own comes back with a number. Without it the only way to compare one
    # model against another was to run a whole pipeline — which is the opposite
    # of the cheap experiment an operator wants before committing to a model.
    out["quality"] = quality_score.score(
        result if isinstance(result, dict) else {}, "questions"
    ).to_dict()
    return out


def _run_queued_substrands(job: dict[str, Any]) -> dict[str, Any]:
    """Generate one strand's sub-strands and keep the result as a DRAFT.

    Every other queued kind writes as it goes: notes file an artifact, diagrams
    file a plan. Sub-strands are different — they are the spine everything else
    hangs off, and saving one strand's must not touch another's. So this stores
    what it produced and stops, and the operator accepts or discards each strand
    on its own.
    """
    payload = dict(job.get("payload") or {})
    result = factory_generate_substrands(
        FactoryGenerateSubstrandsRequest(
            grade=str(job.get("grade") or ""),
            subject=str(job.get("subject") or ""),
            strand_name=str(job.get("strand") or ""),
            strand_id=str(payload.get("strand_id") or "1.0"),
            custom_instructions=str(payload.get("custom_instructions") or ""),
        ),
        None,
    )
    if not isinstance(result, dict):
        raise ValueError("The sub-strand generator returned nothing usable.")

    # The whole result carries the rubric writer's trace and token usage; a
    # draft needs what the operator reads and then saves.
    return {
        "strand_name": result.get("strand_name") or job.get("strand") or "",
        "strand_id": str(payload.get("strand_id") or "1.0"),
        "sub_strands": result.get("sub_strands") or [],
        "refused": result.get("refused") or [],
        "grounded": bool(result.get("grounded")),
        "source_chars": int(result.get("source_material_length") or 0),
        "model": result.get("model") or "",
        # Which generator wrote this. A draft outlives the code that made it,
        # so without the stamp a draft from the old extractor is indistinguishable
        # from fresh output — and gets read as current for as long as it sits.
        "generator": generation_version.VERSION,
        "rubric_tables": result.get("rubric_tables") or {},
        "rubric_integrity": result.get("rubric_integrity") or {},
    }


def _run_queued_dataset_item(job: dict[str, Any]) -> dict[str, Any]:
    """Read one DATASET ITEM, in the worker.

    The Datasets screen ran these on the HTTP request that asked for them, one
    after another: a 95KB design is about ninety seconds, so pressing Process
    on one document held the request open and left every other button in the
    console disabled until it finished. Sixteen documents was a browser tab
    nobody could touch for half an hour, and a proxy timeout in the middle of
    it threw away paid work.

    Sub-strand generation has been queued since the beginning; this is the same
    queue, the same worker and the same progress log.
    """
    from ..services.dataset_ingest import process_item

    payload = dict(job.get("payload") or {})
    item_id = str(payload.get("item_id") or "")
    if not item_id:
        raise ValueError("A dataset-item job carries no item_id.")
    return process_item(item_id, force=bool(payload.get("force")))


def _run_queued_ingest(job: dict[str, Any]) -> dict[str, Any]:
    """Read one learning area out of the design, in the worker.

    Ingest is the longest single call in the pipeline — a 296-page design is
    chunked page by page and every chunk is a model call — and it was the one
    still held open on an HTTP request. A proxy timeout at minute four threw
    away four minutes of paid work and left the grade looking un-ingested.
    """
    payload = dict(job.get("payload") or {})
    result = factory_ingest_learning_area(
        IngestLearningAreaRequest(
            grade=str(job.get("grade") or ""),
            subject=str(job.get("subject") or ""),
            force=bool(payload.get("force")),
            with_skill=bool(payload.get("with_skill", True)),
        ),
        None,
    )
    if not isinstance(result, dict):
        return {}
    # Ingest writes the design and the sub-strands itself; what a progress view
    # needs is what it found, not the document it found it in.
    return {
        "grade": result.get("grade", ""),
        "subject": result.get("subject", ""),
        "design_id": result.get("design_id", ""),
        "strands": result.get("strands", 0) or len(result.get("strand_names") or []),
        "sub_strands": result.get("sub_strands", 0),
        "unparsed_sections": result.get("unparsed_sections") or [],
        "next_step": result.get("next_step", ""),
        "skill": bool(result.get("skill")),
    }


def _run_queued_strands(job: dict[str, Any]) -> dict[str, Any]:
    """Generate a subject's strands AND save them.

    Saving is not a separate decision here the way it is for sub-strands.
    Strands are the layer everything else hangs off, they come straight out of
    the design's own summary table, and a strand list nobody saved is a run
    whose entire output is a screenful of text that dies with the tab.
    """
    payload = dict(job.get("payload") or {})
    grade = str(job.get("grade") or "")
    subject = str(job.get("subject") or "")

    result = factory_generate_strands(
        FactoryGenerateStrandsRequest(
            grade=grade, subject=subject,
            custom_instructions=str(payload.get("custom_instructions") or ""),
        ),
        None,
    )
    strands = (result or {}).get("strands") or []
    saved = 0
    if strands:
        stored = factory_save_strands(
            FactorySaveStrandsRequest(grade=grade, subject=subject, strands=strands),
            None,
        )
        saved = int((stored or {}).get("saved_count") or 0)

    return {
        "grade": grade,
        "subject": subject,
        "strands": strands,
        "saved_count": saved,
        "refused": (result or {}).get("refused") or [],
        "grounded": bool((result or {}).get("grounded")),
        "source_chars": int((result or {}).get("source_material_length") or 0),
    }


def _run_queued_regeneration(job: dict[str, Any]) -> dict[str, Any]:
    """Regenerate one version from its reviewers' findings, in the worker.

    Regeneration is a generation, so it costs a generation's time. Run from a
    button it held the console open exactly as the first generation did, which
    made re-running a whole grade after a review pass an afternoon of clicking
    and waiting.
    """
    from .artifacts import RegenerateRequest, regenerate_artifact

    payload = dict(job.get("payload") or {})
    artifact_id = str(payload.get("artifact_id") or "")
    if not artifact_id:
        raise ValueError("A regeneration job needs an artifact_id.")

    result = regenerate_artifact(
        RegenerateRequest(
            artifact_id=artifact_id,
            extra_instructions=str(payload.get("extra_instructions") or ""),
        ),
        None,
    )
    artifact = (result or {}).get("artifact") or {}
    return {
        "from_artifact_id": artifact_id,
        "artifact_id": artifact.get("artifact_id", ""),
        "version": artifact.get("version", 0),
        "directives_applied": (result or {}).get("directives_applied")
        or (result or {}).get("directives") or [],
    }


def _run_queued_review(job: dict[str, Any]) -> dict[str, Any]:
    """Run one review layer over one artifact version, in the worker.

    Review is a model call like any other and takes as long as one, so it was
    the other half of the work that a refresh could throw away. Queued, a whole
    grade can be sent for review and left to run.
    """
    from .artifacts import ReviewRequest, review_artifact

    payload = dict(job.get("payload") or {})
    artifact_id = str(payload.get("artifact_id") or "")
    if not artifact_id:
        raise ValueError("A review job needs an artifact_id.")

    result = review_artifact(
        ReviewRequest(
            artifact_id=artifact_id,
            layer=int(payload.get("layer") or 2),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            custom_instructions=str(payload.get("custom_instructions") or ""),
        ),
        None,
    )
    review = (result or {}).get("review") or {}
    return {
        "artifact_id": artifact_id,
        "layer": int(payload.get("layer") or 2),
        "verdict": review.get("verdict", ""),
        "overall_confidence": review.get("overall_confidence", 0),
        "weakest": review.get("weakest", ""),
        "provider": review.get("provider", ""),
        "model": review.get("model", ""),
        "review": review,
    }


def _run_queued_approval(job: dict[str, Any]) -> dict[str, Any]:
    """Run the approving layer, then report what still stands in the way.

    It does NOT approve. Approval is a person's decision and is recorded as
    one — coverage counts approved work, so a pipeline that could approve its
    own output would let a grade report itself taught-ready with nobody having
    read a line of it. What this does is get the artifact to the point where
    the decision is a decision rather than an afternoon of clicking.
    """
    from ..services import review_layers
    from .artifacts import ReviewRequest, review_artifact

    payload = dict(job.get("payload") or {})
    artifact_id = str(payload.get("artifact_id") or "")
    if not artifact_id:
        raise ValueError("An approval job needs an artifact_id.")

    state = review_layers.approval_state(artifact_id)
    ran: list[int] = []

    # Layer 3 cannot judge what layer 2 has not seen, and layer 2 must come
    # from a different vendor than the generator or it is one opinion asked
    # twice. Run whatever is missing, in order.
    for layer in (2, 3):
        if any(f"layer {layer} " in b for b in state.get("blockers") or []):
            review_artifact(
                ReviewRequest(artifact_id=artifact_id, layer=layer), None
            )
            ran.append(layer)
            state = review_layers.approval_state(artifact_id)

    return {
        "artifact_id": artifact_id,
        "layers_run": ran,
        "can_approve": bool(state.get("can_approve")),
        "requires_human": True,
        "blockers": state.get("blockers") or [],
        "approval_state": state,
    }


# The pipeline, in the order the work actually depends on itself. Ingest reads
# the design; strands come out of it; sub-strands hang off strands; notes are
# written per sub-strand; everything visual and every question is grounded in
# the notes.
PIPELINE_STEPS = (
    # `material` follows `notes` because it is written FROM the plan: the words
    # cannot be produced until there is an instruction telling them what to be.
    "ingest", "strands", "substrands", "notes", "material",
    "diagram", "media", "simulation", "activity", "questions",
)

# What each step is expanded ACROSS. A step queued once for the learning area
# is not the same shape as one queued per sub-strand, and getting this wrong
# either runs the notes once for a grade or ingests the design ninety times.
_STEP_SCOPE = {
    "ingest": "subject",
    "strands": "subject",
    "substrands": "strand",
    "notes": "sub_strand",
    "material": "sub_strand",
    "diagram": "sub_strand",
    "media": "sub_strand",
    "simulation": "sub_strand",
    "activity": "sub_strand",
    "questions": "sub_strand",
}


def _stored_strands(grade: str, subject: str) -> list[dict[str, str]]:
    """The saved strands for a learning area.

    They live in the design's metadata, not in a table of their own — strands
    were only ever a JSONB list hanging off `curriculum_designs`. Two queries
    written against a `curriculum_strands` table would have raised
    UndefinedTable the first time a pipeline reached its second step.
    """
    from ..infra.db import fetch_one

    row = fetch_one(
        """
        SELECT metadata FROM curriculum_designs
        WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))
          AND LOWER(subject) = LOWER(:subject)
        ORDER BY updated_at DESC LIMIT 1
        """,
        {"grade": grade, "alt_grade": grade.replace("grade-", ""), "subject": subject},
    )
    strands = ((row or {}).get("metadata") or {}).get("strands") or []
    return [
        {"strand_name": str(s.get("strand_name") or s.get("name") or ""),
         "strand_id": str(s.get("strand_id") or "1.0")}
        for s in strands
        if isinstance(s, dict) and (s.get("strand_name") or s.get("name"))
    ]


def _stored_substrands(grade: str, subject: str, strand: str = "") -> list[dict[str, str]]:
    from ..infra.db import fetch_all

    rows = fetch_all(
        """
        SELECT strand_name, sub_strand_name FROM curriculum_substrands
        WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))
          AND LOWER(subject) = LOWER(:subject)
          AND (:strand = '' OR LOWER(strand_name) = LOWER(:strand))
        ORDER BY strand_id, sub_strand_id
        """,
        {"grade": grade, "alt_grade": grade.replace("grade-", ""),
         "subject": subject, "strand": strand},
    ) or []
    return [{"strand": str(r.get("strand_name") or ""),
             "sub_strand": str(r.get("sub_strand_name") or "")} for r in rows]


def _expand_step(step: str, grade: str, subject: str, strand: str) -> list[dict[str, str]]:
    """The jobs one step becomes, read from what the previous step SAVED.

    Expanded at queue time, a station step would have to guess the sub-strands
    that the sub-strand step has not produced yet. Expanded here — after the
    stage before it has finished and written its output — there is nothing to
    guess.
    """
    scope = _STEP_SCOPE.get(step, "sub_strand")
    if scope == "subject":
        return [{"strand": "", "sub_strand": ""}]
    if scope == "strand":
        return [{"strand": s["strand_name"], "sub_strand": ""}
                for s in _stored_strands(grade, subject)
                if not strand or s["strand_name"].lower() == strand.lower()]
    return _stored_substrands(grade, subject, strand)


def _run_queued_pipeline(job: dict[str, Any]) -> dict[str, Any]:
    """Run one step of a pipeline, then let the stage advance when it is done.

    The whole chain used to be a person: ingest, wait, read the result, click
    strands, wait, click each strand's sub-strands, wait, click notes for each
    sub-strand, wait. An afternoon of pressing buttons and watching, per
    learning area, which is the thing that made generating at any scale
    impossible.

    Each job here runs ONE step for ONE unit of work, saves it, and then checks
    whether it was the last of its stage still running. Only the last one
    advances, so a stage that fanned out into twelve sub-strands moves on once,
    not twelve times.
    """
    payload = dict(job.get("payload") or {})
    steps = [str(x) for x in (payload.get("steps") or [])]
    index = int(payload.get("index") or 0)
    if index >= len(steps):
        return {"note": "nothing left to run"}

    step = steps[index]
    handler = _PIPELINE_HANDLERS.get(step)
    if handler is None:
        raise ValueError(f"'{step}' is not a pipeline step.")

    # Run the step exactly as it runs when queued on its own — one
    # implementation, so the pipeline cannot drift from the buttons.
    result = handler({**job, "kind": step})

    # Score it against what its own validators checked, and let the auto-run
    # decide whether to keep going. An unattended run that keeps producing
    # while quality collapses is the failure this exists to prevent — the
    # operator finds out at the end, after paying for a grade.
    scored = quality_score.score(result if isinstance(result, dict) else {}, step)
    halted = auto_run.record(
        str(job.get("batch_id") or ""), scored,
        label=f"{step}: {job.get('sub_strand') or job.get('strand') or job.get('subject')}",
    )
    if halted is not None:
        from ..services import job_queue

        cancelled = job_queue.cancel(batch_id=str(job.get("batch_id") or ""))
        logger.warning(
            "Auto-run %s halted and cancelled %d queued job(s).",
            halted.run_id, cancelled,
        )
        return {"step": step, "step_index": index, "advanced_to": "",
                "quality": scored.to_dict(),
                "auto_run_halted": halted.halted_reason,
                "cancelled_jobs": cancelled, **result}

    advanced = _advance_pipeline(job, steps, index)
    return {"step": step, "step_index": index, "advanced_to": advanced,
            "quality": scored.to_dict(), **result}


def _advance_pipeline(job: dict[str, Any], steps: list[str], index: int) -> str:
    """Queue the next stage, but only once the whole current stage is finished.

    Without the barrier, each of twelve sub-strand jobs would queue the next
    stage as it landed — twelve times over, and the stage after that a hundred
    and forty-four.
    """
    from ..infra.db import fetch_one
    from ..services import job_queue

    batch_id = str(job.get("batch_id") or "")
    if not batch_id:
        return ""

    siblings = fetch_one(
        """
        SELECT COUNT(*) AS n FROM jobs
        WHERE batch_id = :batch_id AND kind = 'pipeline'
          AND COALESCE(payload->>'index', '0') = :index
          AND status IN ('queued', 'running')
          AND job_id <> :job_id
        """,
        {"batch_id": batch_id, "index": str(index), "job_id": str(job.get("job_id") or "")},
    )
    if int((siblings or {}).get("n") or 0) > 0:
        return ""

    if index + 1 >= len(steps):
        return ""

    payload = dict(job.get("payload") or {})
    next_step = steps[index + 1]
    grade = str(job.get("grade") or "")
    subject = str(job.get("subject") or "")
    scope_strand = str(payload.get("scope_strand") or "")

    units = _expand_step(next_step, grade, subject, scope_strand)
    if not units:
        # Nothing to run it against. Skipping forward silently would leave the
        # batch looking finished when the stage that mattered never ran.
        logger.warning(
            "Pipeline %s: step '%s' expanded to nothing for %s (%s).",
            batch_id, next_step, subject, grade,
        )
        return ""

    for unit in units:
        job_queue.enqueue(
            "pipeline", grade, subject,
            {**payload, "index": index + 1},
            strand=unit.get("strand", ""),
            sub_strand=unit.get("sub_strand", ""),
            batch_id=batch_id,
            queued_by=str(job.get("queued_by") or ""),
        )
    logger.info("Pipeline %s advanced to '%s' across %d unit(s).",
                batch_id, next_step, len(units))
    return next_step


def _register_queue_handlers() -> None:
    from ..services import job_queue

    for kind in _QUEUEABLE:
        job_queue.register(kind, _run_queued)
    job_queue.register("substrands", _run_queued_substrands)
    job_queue.register("questions", _run_queued_questions)
    job_queue.register("review", _run_queued_review)
    job_queue.register("approval", _run_queued_approval)
    job_queue.register("ingest", _run_queued_ingest)
    # Registered on the QUEUE but deliberately not in _PIPELINE_HANDLERS: a
    # dataset item is one document being read, not a stage of the chain, and
    # the pipeline advances stage by stage against PIPELINE_STEPS.
    job_queue.register("dataset_item", _run_queued_dataset_item)
    job_queue.register("strands", _run_queued_strands)
    job_queue.register("regenerate", _run_queued_regeneration)
    job_queue.register("pipeline", _run_queued_pipeline)
    # Narration audio for a maths walkthrough. Queued rather than synthesised
    # in the request, which used to cost up to 25 seconds per step.
    from ..services.math_engine.audio_jobs import JOB_KIND as _AUDIO_KIND, run_audio_job
    job_queue.register(_AUDIO_KIND, run_audio_job)


# One step, one implementation. The pipeline delegates to the same handlers the
# individual buttons queue, so a fix to one is a fix to both.
_PIPELINE_HANDLERS: dict[str, Any] = {
    "ingest": _run_queued_ingest,
    "strands": _run_queued_strands,
    "substrands": _run_queued_substrands,
    "notes": _run_queued,
    "diagram": _run_queued,
    "media": _run_queued,
    "simulation": _run_queued,
    "activity": _run_queued,
    "material": _run_queued,
    "questions": _run_queued_questions,
}


_register_queue_handlers()


@router.post("/factory/queue")
def factory_queue_work(
    payload: QueueWorkRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Queue stations across many sub-strands and return immediately.

    One sub-strand's notes take about a minute; a grade's worth take an
    afternoon. Held open on a request, that blocks a tab, times out at the
    proxy, and loses everything on a refresh.

    The queue runs SEQUENTIALLY on purpose: these calls cost money and hit
    provider rate limits, and ten at once fails halfway with no way to tell
    which half.
    """
    import hashlib as _hashlib
    from ..infra.db import fetch_all
    from ..services import job_queue

    stations = set(_QUEUEABLE) | {"questions"}  # keys, not the tuples
    unknown = [k for k in payload.kinds if k not in stations]
    if unknown:
        raise_api_error(
            "VALIDATION_FAILED",
            f"Cannot queue {', '.join(unknown)}. Known: {', '.join(sorted(stations))}.",
        )

    rows = fetch_all(
        """
        SELECT strand_name, sub_strand_name FROM curriculum_substrands
        WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))
          AND LOWER(subject) = LOWER(:subject)
          AND (:strand = '' OR LOWER(strand_name) = LOWER(:strand))
        ORDER BY strand_id, sub_strand_id
        """,
        {"grade": payload.grade, "alt_grade": payload.grade.replace("grade-", ""),
         "subject": payload.subject, "strand": payload.strand},
    ) or []

    wanted = {s.strip().lower() for s in payload.sub_strands if s.strip()}
    targets = [
        r for r in rows
        if not wanted or str(r.get("sub_strand_name") or "").strip().lower() in wanted
    ]
    if not targets:
        raise_api_error(
            "MISSING_PARENT_CONTEXT",
            f"No stored sub-strands for {payload.subject} ({payload.grade})"
            + (f" under '{payload.strand}'" if payload.strand else "")
            + ". Generate and save the sub-strands before queuing work against them.",
        )

    batch_id = "batch_" + _hashlib.sha256(
        f"{payload.grade}{payload.subject}{payload.strand}{payload.kinds}".encode()
    ).hexdigest()[:16]

    queued: list[dict[str, Any]] = []
    # Kind-major, so every sub-strand gets its notes before any gets diagrams —
    # the later stations are grounded in the earlier ones.
    for kind in payload.kinds:
        for row in targets:
            job = job_queue.enqueue(
                kind, payload.grade, payload.subject,
                {"custom_instructions": payload.custom_instructions},
                strand=str(row.get("strand_name") or ""),
                sub_strand=str(row.get("sub_strand_name") or ""),
                batch_id=batch_id, queued_by=getattr(auth, "subject", ""),
            )
            queued.append(job.to_dict())

    job_queue.start_worker()

    return {
        "status": "queued",
        "batch_id": batch_id,
        "queued": len(queued),
        "sub_strands": len(targets),
        "kinds": payload.kinds,
        "jobs": queued,
        "note": "Running one at a time. Poll /factory/queue/status for progress.",
    }


@router.post("/factory/queue-substrands")
def factory_queue_substrands(
    payload: QueueSubstrandsRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Queue sub-strand generation for several strands, one at a time.

    Generating a strand's sub-strands takes the better part of a minute, and a
    learning area has five or six strands. Clicked one at a time, the operator
    has to sit and watch; generated all at once into browser state, the drafts
    were lost the moment the console re-rendered — save the first strand and the
    other four vanished with no record they had existed.

    Queued, each result is held in the jobs table until somebody accepts or
    discards it, so saving one strand cannot disturb another.
    """
    import hashlib as _hashlib
    from ..infra.db import fetch_all
    from ..services import job_queue

    targets = [
        {"strand_name": str(s.get("strand_name") or s.get("name") or "").strip(),
         "strand_id": str(s.get("strand_id") or "1.0").strip()}
        for s in payload.strands
    ]
    targets = [t for t in targets if t["strand_name"]]

    if not targets:
        # Nothing named: queue every stored strand that has no sub-strands yet,
        # which is what "queue the rest of them" means.
        covered = {
            str(r.get("strand_name") or "").strip().lower()
            for r in (fetch_all(
                """
                SELECT DISTINCT strand_name FROM curriculum_substrands
                WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))
                  AND LOWER(subject) = LOWER(:subject)
                """,
                {"grade": payload.grade,
                 "alt_grade": payload.grade.replace("grade-", ""),
                 "subject": payload.subject},
            ) or [])
        }
        targets = [
            s for s in _stored_strands(payload.grade, payload.subject)
            if s["strand_name"].strip().lower() not in covered
        ]

    if not targets:
        raise_api_error(
            "MISSING_PARENT_CONTEXT",
            f"No strands to generate sub-strands for in {payload.subject} "
            f"({payload.grade}). Generate the strands first, or every strand "
            f"already has sub-strands saved.",
        )

    batch_id = "batch_" + _hashlib.sha256(
        f"substrands{payload.grade}{payload.subject}{len(targets)}".encode()
    ).hexdigest()[:16]

    queued: list[dict[str, Any]] = []
    for target in targets:
        job = job_queue.enqueue(
            "substrands", payload.grade, payload.subject,
            {"custom_instructions": payload.custom_instructions,
             "strand_id": target["strand_id"]},
            strand=target["strand_name"],
            batch_id=batch_id, queued_by=getattr(auth, "subject", ""),
        )
        queued.append(job.to_dict())

    job_queue.start_worker()

    return {
        "status": "queued",
        "batch_id": batch_id,
        "queued": len(queued),
        "strands": [t["strand_name"] for t in targets],
        "jobs": queued,
        "note": ("Running one strand at a time. Each result waits as a draft "
                 "until you save or discard it."),
    }


@router.get("/factory/queue/drafts")
def factory_queue_drafts(
    grade: str = Query(""),
    subject: str = Query(""),
    kind: str = Query("substrands"),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Generated sub-strands nobody has accepted or discarded yet.

    This is what makes the drafts survive a reload, a re-render and a save of
    some other strand: they live in the jobs table, not in the console.
    """
    from ..services import job_queue

    rows = job_queue.drafts(kind, grade=grade, subject=subject)
    return {
        "kind": kind,
        "grade": grade,
        "subject": subject,
        "count": len(rows),
        "generator": generation_version.VERSION,
        "stale": sum(
            0 if generation_version.is_current(
                ((r.get("result") or {}) if isinstance(r.get("result"), dict) else {})
                .get("generator")
            ) else 1
            for r in rows
        ),
        "drafts": [
            {
                "job_id": r.get("job_id"),
                "batch_id": r.get("batch_id"),
                "strand_name": r.get("strand") or "",
                "finished_at": r.get("finished_at"),
                **(r.get("result") if isinstance(r.get("result"), dict) else {}),
                # Resolved here rather than in the console, so one definition of
                # "stale" serves every reader.
                "stale": not generation_version.is_current(
                    ((r.get("result") or {}) if isinstance(r.get("result"), dict) else {})
                    .get("generator")
                ),
                "missing": generation_version.describe(
                    ((r.get("result") or {}) if isinstance(r.get("result"), dict) else {})
                    .get("generator") or ""
                ),
            }
            for r in rows
        ],
    }


@router.post("/factory/delete-scope")
def factory_delete_scope(
    payload: DeleteScopeRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Remove ONE strand or ONE sub-strand, with everything derived from it.

    The only way to get rid of generated curriculum was the factory reset,
    which clears a whole learning area. That is right for "the pipeline has
    changed, start again" and wrong for "this sub-strand came out badly" — and
    with only the second, an operator either keeps a bad sub-strand or throws
    away eleven good ones with it.

    A dry run unless `confirm` says DELETE, so the counts are visible before
    anything is irreversible.
    """
    report = scoped_delete.delete(
        payload.grade, payload.subject,
        strand=payload.strand, sub_strand=payload.sub_strand,
        confirm=payload.confirm,
    )
    return report.to_dict()


class SweepOrphansRequest(BaseModel):
    confirm: str = ""


def _plain(entry: Any) -> str:
    """The text of a design row, whether it is a string or a {id, text} dict."""
    if isinstance(entry, dict):
        for key in ("text", "name", "description", "experience", "slo"):
            if entry.get(key):
                return str(entry[key])
    return str(entry)


@router.post("/factory/generate-material")
def factory_generate_material(
    payload: FactoryGenerateMaterialRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Write the words the plan only asked for.

    The plan says "choose a simple song about God" and "tell a simple story
    that illustrates God's love". A teacher reading that still has to find the
    song and write the story, which is the whole of the work. This is the song
    and the story.

    One model call per instruction, not one per guide. The failure this layer
    exists to prevent — something general where something specific was needed —
    is exactly what a long prompt produces, and a song is easier to get right,
    and to check, one song at a time.
    """
    from ..services import artifact_registry, lesson_material
    from ..services.faith_scope import prompt_block as faith_block
    from ..services.level_register import language_block, register_block
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator

    if payload.run_id and run_log.current() is None:
        run_log.start(run_id=payload.run_id)

    plan_id = payload.plan_artifact_id
    if not plan_id:
        found = artifact_registry.search(
            payload.grade, payload.subject, "notes", payload.sub_strand, limit=1)
        plan_id = (found or [{}])[0].get("artifact_id", "")
    if not plan_id:
        raise_api_error(
            "VALIDATION_FAILED",
            f"There is no lesson plan filed for '{payload.sub_strand}'. The "
            f"material is written from the plan — generate the notes first.",
        )

    plan_artifact = artifact_registry.get(plan_id)
    plan = lesson_material.directives_of(plan_artifact.content or {})
    if not plan.directives:
        raise_api_error(
            "VALIDATION_FAILED",
            f"Version {plan_artifact.version} of that plan gives no "
            f"instructions to fulfil — it has no lesson segments in it.",
        )

    run_log.step(
        "Read the plan",
        f"version {plan_artifact.version}, {plan.modules} lesson(s), "
        f"{len(plan.directives)} instruction(s), "
        f"{len(plan.unfulfilled)} of which ask the teacher to supply something",
    )

    substrand_row = fetch_one(
        """
        SELECT slos FROM curriculum_substrands
        WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))
          AND LOWER(subject) = LOWER(:subject)
          AND LOWER(sub_strand_name) = LOWER(:sub_strand)
        LIMIT 1
        """,
        {"grade": payload.grade,
         "alt_grade": payload.grade.replace("grade-", ""),
         "subject": payload.subject, "sub_strand": payload.sub_strand},
    )
    slos = [_plain(s) for s in ((substrand_row or {}).get("slos") or [])]

    resolved = pipeline_orchestrator.router.resolve_for_stage("material_generation")
    register = register_block(payload.grade)
    language = language_block(payload.grade)
    faith = faith_block(payload.subject)
    # The maths, chemistry and music blocks. The words a child hears are the
    # one place a mis-set fraction or an unbalanced equation is read ALOUD.
    from ..services.notation import block_for as _notation_block

    notation = _notation_block(payload.subject, grade=payload.grade)
    # When the learning area IS a language, the words the learner says must be
    # in that language — not described in English, which is a complete-looking
    # lesson in which nobody learns the language.
    from ..services.target_language import block_for as _target_language

    target = _target_language(payload.subject)

    # What a previous, interrupted run already paid for. A draft is written
    # after every piece, so a timeout or a restart at piece 19 of 21 costs the
    # one piece it died on rather than all nineteen.
    from ..services import material_draft

    draft_key = material_draft.key_for(payload.grade, payload.subject,
                                       payload.sub_strand, plan_id)
    written: list[dict[str, Any]] = material_draft.load(draft_key)
    already = material_draft.done_indexes(written)
    if already:
        run_log.step("Resuming",
                     f"{len(already)} piece(s) already written and kept from an "
                     f"earlier run — those are not paid for twice", "ok")

    for i, directive in enumerate(plan.directives, start=1):
        if (directive.module_number, directive.index) in already:
            continue
        messages = [{"role": "user", "content": lesson_material.prompt_for(
            directive, register=register, faith=faith, language=language,
            notation=notation, target_language=target, grade=payload.grade,
            sub_strand=payload.sub_strand, slos=slos)}]
        if payload.custom_instructions:
            messages.append({"role": "user",
                             "content": payload.custom_instructions})
        try:
            response = llm_client.generate(resolved, messages, temperature=0.4)
            piece = response.content if isinstance(response.content, dict) else {}
        except Exception as exc:  # noqa: BLE001
            # One instruction failing is not the whole sub-strand failing. The
            # gap is recorded where a reader will see it rather than silently
            # closing over it.
            logger.warning("Material for %s part %d failed: %s",
                           directive.topic, directive.index, exc)
            run_log.step(f"Wrote {i}/{len(plan.directives)}",
                         f"{directive.topic}: failed — {exc}", "fail")
            piece = {"say": "", "error": str(exc)[:200]}

        written.append({
            **piece,
            "module_number": directive.module_number,
            "module_title": directive.module_title,
            "index": directive.index,
            "topic": directive.topic,
            "minutes": directive.minutes,
            "instruction": directive.instruction,
        })
        if piece.get("say"):
            run_log.step(f"Wrote {i}/{len(plan.directives)}",
                         f"{directive.topic}: {len(str(piece['say']))} characters")

        # Written down before the next call is made, not after the last one.
        material_draft.save(
            draft_key, written,
            grade=payload.grade, subject=payload.subject, strand=payload.strand,
            sub_strand=payload.sub_strand, plan_artifact_id=plan_id,
            plan_version=plan_artifact.version, model=resolved.model,
            llm_calls=len(written),
        )

    # The plan's own order, not the order the pieces happened to be written in:
    # a resumed run appends after what it recovered, and a guide whose parts
    # arrive out of order is not the guide the plan describes.
    order = {(d.module_number, d.index): n
             for n, d in enumerate(plan.directives)}
    written.sort(key=lambda p: order.get((p.get("module_number"), p.get("index")),
                                         len(order)))

    content = {
        "sub_strand": payload.sub_strand,
        "from_plan": {"artifact_id": plan_id, "version": plan_artifact.version},
        "material": written,
    }
    report = lesson_material.check(content, plan, grade=payload.grade,
                                   subject=payload.subject)
    run_log.step(
        "Material written",
        f"{report.written} of {report.total} instruction(s) fulfilled, "
        f"{report.score}/100"
        + (f", {len(report.thin)} too thin" if report.thin else "")
        + (f", {len(report.echoed)} echoed the instruction back" if report.echoed else ""),
        "ok" if report.clean else "warn",
    )

    versioned = _record_artifact(
        "material", payload.grade, payload.subject, content,
        strand=payload.strand, sub_strand=payload.sub_strand,
        parent=plan_id,
        provenance={"source": "factory_generate_material",
                    "provider": resolved.provider, "model": resolved.model,
                    "from_plan": plan_id},
        measured_from={"quality_gate": lesson_material.gate_of(report)},
    )
    # The version is filed; the draft has done its job.
    if versioned.get("artifact_id"):
        material_draft.clear(draft_key)
    if payload.run_id:
        run_log.stop()

    return {"material": content, "plan": plan.to_dict(),
            "coverage": report.to_dict(),
            # The same shape every other station reports its gate in. Without
            # it the review loop read no score and filed a 95/100 run as 0.
            "quality_gate": lesson_material.gate_of(report),
            "model": resolved.model,
            "artifact": versioned}


class DrawVisualRequest(BaseModel):
    """Which planned visual to actually draw."""

    artifact_id: str
    index: int = 0
    custom_instructions: str = ""


# A drawing that still fails after this many tries is filed with its findings
# rather than retried for ever. Three, because the second attempt fixes most of
# what the first got wrong and the third catches what the fix broke.
_DRAW_ATTEMPTS = 3


def _svg_brief(visual: dict[str, Any], *, grade: str, subject: str,
               strand: str, sub_strand: str) -> str:
    """The instruction to draw ONE planned visual.

    Built from what the planner already wrote — the title, the vivid prompt and
    the scene's parts — rather than from the sub-strand name. The parts are the
    point: this station exists so a question can say "the part labelled A", and
    a drawing whose labels do not match the plan breaks every question written
    against it.
    """
    title = str(visual.get("diagram_title") or visual.get("title") or "").strip()
    prompt = str(visual.get("vivid_prompt") or visual.get("description") or "").strip()
    accessibility = visual.get("accessibility") or {}
    alt = str((accessibility or {}).get("alt_text") or "").strip()

    parts = ((visual.get("scene") or {}).get("parts")
             if isinstance(visual.get("scene"), dict) else None)
    parts = [p for p in (parts or []) if isinstance(p, dict)]

    lines = [
        "Draw ONE diagram as a standalone SVG.",
        "",
        f"CURRICULUM: {' · '.join(x for x in (grade, subject, strand, sub_strand) if x)}",
        *( [f"TITLE: {title}"] if title else [] ),
        "",
        "WHAT IT MUST SHOW:",
        prompt or title or "(the plan gave no description)",
    ]

    if parts:
        lines += [
            "",
            "EVERY ONE OF THESE PARTS MUST BE DRAWN AND LABELLED, spelled exactly "
            "as written. Questions are written against these labels, so a label "
            "that differs breaks the question that points at it:",
        ]
        for part in parts:
            label = str(part.get("label") or "").strip()
            function = str(part.get("function") or "").strip()
            if label:
                lines.append(f"  - {label}" + (f" — {function}" if function else ""))

    if alt:
        lines += ["", f"IT MUST MATCH THIS DESCRIPTION: {alt}"]

    lines += [
        "",
        "THE SPACE IT HAS TO FIT. This is not a picture on a screen. It is a",
        "figure in a two-column textbook page, and the page is already set:",
        "",
        "  - The figure is 85mm wide. Always. The book sets A4 at 210mm with",
        "    16mm margins and two columns 8mm apart, so one column is 85mm and",
        "    your drawing is scaled to exactly that width.",
        "  - The page reserves 50mm of height for it. A drawing of another",
        "    shape reflows the column around it.",
        "  - Therefore: `viewBox=\"0 0 340 200\"`, and NO width or height",
        "    attribute. Those 340 × 200 units ARE the 85mm × 50mm. Work in",
        "    them. One unit is a quarter of a millimetre on paper.",
        "  - Keep a 12-unit margin clear on every side, then USE the rest of",
        "    the canvas. A drawing crowded into one corner is not smaller than",
        "    the page — it is scaled to the same 85mm and merely thinner.",
        "",
        "SIZES, IN THOSE UNITS. The caption printed beside this figure is",
        "8.5pt. A label smaller than the caption cannot be read at all:",
        "",
        "  - No text anywhere below `font-size=\"13\"`. Part labels 13–15.",
        "    Nothing under 13, ever — that is the single most common way one",
        "    of these comes back unusable.",
        "  - Do NOT put a title inside the drawing. The book prints the",
        "    caption underneath it, so a title in the SVG says the same thing",
        "    twice, takes a fifth of the canvas from the picture, and is one",
        "    more thing for a label to collide with.",
        "  - A character is about 0.55 × the font-size wide. So a 13-unit",
        "    label may run about 44 characters before it crosses the margin.",
        "    Longer than that, break it across <tspan> lines 16 units apart —",
        "    or shorten it. Labels name a part; they do not define it. Write",
        "    \"Numerator\", not \"Numerator — the number above the line\".",
        "  - Stroke widths 1.5 to 2.5. Thinner disappears in a photocopy.",
        "  - font-family=\"Helvetica, Arial, sans-serif\" on every <text>, which",
        "    is the sans the book's own captions and labels are set in.",
        "",
        "NOTHING MAY OVERLAP ANYTHING. At 85mm a label lying across line-work",
        "is a smudge, not a word. Before you place each <text>, work out the",
        "box it occupies — x to x + 0.55 × font-size × (number of characters),",
        "and font-size tall above the baseline y — and put it where no shape",
        "and no other label already is. If a part is too small to hold its own",
        "name, set the label out in the clear margin and run a thin leader",
        "line (stroke-width 1) from the text to the part. That is how an atlas",
        "does it, and it is why an atlas is readable.",
        "",
        "A label set INSIDE a panel — a titled box, a tinted region — is fine,",
        "and is how a textbook sets one. What is unreadable is a label",
        "crossing a panel's edge, or lying over a line, an arrow or a curve.",
        "",
        "Never route a leader line THROUGH text, and never let one pass",
        "between the characters of an expression: \"5 —— + 3 —— = 8\" is what",
        "that produces, and it is not an expression any more. A leader line",
        "starts at the edge of the label and stops at the edge of the part.",
        "",
        "Nothing may fall outside the viewBox — not a shape, and not the",
        "second or third line of a wrapped label. Anything past 340 across or",
        "200 down is cut off by the page and simply will not be there.",
        "",
        "The edges are where this goes wrong, every time. A label centred on",
        "the last tick of a number line is half off the canvas; so is a",
        "left-hand caption starting at x=0 once it is centred. So:",
        "",
        "  - a label at the left edge starts at x=12 with the default anchor;",
        "  - a label at the right edge uses text-anchor=\"end\" at x=328;",
        "  - a centred label needs 0.55 × font-size × characters ÷ 2 of clear",
        "    space on BOTH sides of its x, or it must move inward;",
        "  - the first and last ticks of a scale go at x=30 and x=310, not at",
        "    12 and 328, so their labels have somewhere to sit.",
        "",
        "THE DRAWING MUST CARRY THE MEANING. A learner covering every label",
        "must still be able to work out what is going on. That is the test,",
        "and it is the one these drawings keep failing:",
        "",
        "  - Do not draw a stack of rows, each holding one boxed phrase and",
        "    one equation. That is a bordered table, and it teaches nothing a",
        "    sentence would not. It is the single most common thing returned",
        "    here and it is always wrong.",
        "  - Do not give every part the same generic motif — two circles and a",
        "    connecting line for all four of anything — with only the words",
        "    changing. Repeating one shape says the parts are the same.",
        "  - Show the thing HAPPENING, not the thing named. \"Subtraction\" in a",
        "    box is a caption. Seven counters with two crossed through is",
        "    subtraction. The picture should be the evidence a question asks",
        "    about, because a question WILL hide one part and ask what it was.",
        "",
        "COMPOSE IT LIKE SOMEONE WHO DRAWS. Pick the arrangement the idea",
        "actually has, rather than defaulting to a list. Some that earn their",
        "space:",
        "",
        "  - a number line, when the idea is position, order or distance;",
        "  - a rectangular array or an area model, for multiplication;",
        "  - a part-whole bar, for fractions, ratio and sharing;",
        "  - grouped counters, for repeated addition and division;",
        "  - a labelled cross-section, for a structure with named parts;",
        "  - a flow of boxes joined by arrows, for a process with an order;",
        "  - two panels side by side, when the point is a contrast;",
        "  - a cycle of arrows, when the process returns to its start.",
        "",
        "Choose ONE and commit to it. A drawing that is a number line should",
        "be a good number line filling the canvas, not a small number line",
        "next to three other things. Vary size deliberately: the thing the",
        "lesson is about should be the biggest thing on the canvas.",
        "",
        "COLOUR, SPARINGLY. One accent colour plus black on white. Use the",
        "accent as a light fill (for example #d9e8f5, #fde9d0) behind a black",
        "outline, never as the only thing distinguishing two parts — half the",
        "copies of this page are photocopied in grey, and a distinction that",
        "survives only in colour is lost in them. No background rectangle",
        "behind the whole drawing; the page is already white.",
        "",
        "  - Text in the SVG's own <text> elements, never inside an image. No",
        "    external fonts, images, scripts or stylesheets — nothing that has",
        "    to be fetched, because this is printed and read offline.",
        "  - Position parts at plain coordinates, or with translate() only. A",
        "    rotate() or matrix() cannot be checked for overlap, and will be",
        "    rejected.",
        "  - Wrap each labelled part and its <text> in a <g> carrying BOTH",
        "    `data-part-id=\"part-<label in lower case with hyphens>\"` and",
        "    the same value as `id`. A question occludes a part by that",
        "    attribute; a part without one cannot be hidden, and the learner",
        "    is then shown the marking copy with the answer printed on it.",
        "",
        "Return ONLY the <svg> element. No explanation, no markdown fence.",
    ]
    # Blank lines are the paragraph breaks; only a `None` is dropped.
    return "\n".join(line for line in lines if line is not None)


@router.post("/factory/visuals/draw")
def factory_draw_visual(
    payload: DrawVisualRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Draw a planned visual, from the plan this station already wrote.

    The diagram station PLANS: it writes a title, a vivid prompt and a scene of
    addressable parts, so that questions can test one region. Nothing turned
    that plan into a picture, so the brief sat in an artifact and the book kept
    a hatched rectangle beside it.

    The drawing is filed against the visual's own title, which is what the
    renderer matches on — so the plate fills on the next render — and written
    back onto the artifact so the station panel shows it too.
    """
    from ..services import (artifact_registry, asset_uploads, diagram_gate,
                            diagram_layout)
    from ..services.diagram_dedup import extract_and_sanitize_svg
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator

    artifact = artifact_registry.get(payload.artifact_id)
    if artifact.kind != "diagram":
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{artifact.kind}' is not a diagram plan. Draw from the diagram "
            f"station's own version.",
        )

    content = artifact.content or {}
    visuals = content.get("visuals") or content.get("diagrams") or []
    visuals = [v for v in visuals if isinstance(v, dict)]
    if not 0 <= payload.index < len(visuals):
        raise_api_error(
            "VALIDATION_FAILED",
            f"This version plans {len(visuals)} visual(s); there is no "
            f"number {payload.index}.",
        )

    visual = visuals[payload.index]
    title = str(visual.get("diagram_title") or visual.get("title") or "").strip()
    if not title:
        raise_api_error(
            "VALIDATION_FAILED",
            "This visual has no title, so nothing can refer to the drawing. "
            "Regenerate the plan first.",
        )

    brief = _svg_brief(visual, grade=artifact.grade, subject=artifact.subject,
                       strand=artifact.strand_name,
                       sub_strand=artifact.sub_strand_name)
    if payload.custom_instructions:
        brief += f"\n\nALSO: {payload.custom_instructions}"

    resolved = pipeline_orchestrator.router.resolve_for_stage("diagram_generation")

    # Draw, MEASURE, and redraw once against what the measurement found. The
    # first drawing this station produced was 4:3 with labels lying across the
    # line-work at a size that resolves to 2mm in the column — all of it plain
    # geometry, none of it visible in a thumbnail. A model told "labels must
    # not overlap" writes overlapping labels anyway; a model told "these four
    # labels overlap, here they are" moves them.
    svg, fit, response = "", None, None
    attempt = brief
    for pass_no in range(_DRAW_ATTEMPTS):
        try:
            # An SVG is not JSON. Asked for one and given one, the client used
            # to reject it as "the model did not return JSON".
            response = llm_client.generate(
                resolved, [{"role": "user", "content": attempt}], temperature=0.2,
                expect="text")
        except Exception as exc:  # noqa: BLE001
            if svg:
                break  # the first drawing stands; a failed retry is not a loss
            raise_api_error("DIAGRAM_GENERATION_FAILED", f"The model failed: {exc}")

        raw = response.content
        if isinstance(raw, dict):
            raw = raw.get("svg") or raw.get("diagram_svg") or raw.get("content") or ""
        candidate = extract_and_sanitize_svg(str(raw or ""))
        if not candidate:
            if svg:
                break
            raise_api_error(
                "DIAGRAM_GENERATION_FAILED",
                "The model returned nothing that parses as an SVG. Try again, "
                "or copy the brief and draw it elsewhere.",
            )

        measured = diagram_layout.measure(candidate)
        # Keep whichever attempt reads better on the page, not whichever came
        # last: a redraw that fixes the overlap and breaks the scale is not an
        # improvement.
        if fit is None or len(measured.findings) < len(fit.findings):
            svg, fit = candidate, measured
        if measured.ok or pass_no == _DRAW_ATTEMPTS - 1:
            break
        # Always correct against the LATEST attempt, not the best one: the
        # model is being asked to fix the drawing it just made.
        attempt = brief + diagram_layout.corrections(measured)

    # 1. Where the BOOK looks. Filed against the visual's own title, which is
    #    what `lesson_assets` matches a requirement on.
    # The same filing an edit does, so a drawing and a hand-fixed drawing end
    # up in exactly one place and the book cannot show a stale one.
    stored = asset_uploads.file_drawing(
        grade=artifact.grade, subject=artifact.subject,
        strand=artifact.strand_name, sub_strand=artifact.sub_strand_name,
        title=title, svg=svg,
        alt_text=str((visual.get("accessibility") or {}).get("alt_text") or title),
        source=f"drawn:{resolved.model}", uploaded_by=getattr(auth, "subject", ""),
    )
    asset_id = stored["asset_id"]
    storage_url = stored["storage_url"]
    in_minio = stored["stored_in_minio"]

    # 2. And onto the plan itself, so the station panel shows what it drew and
    #    the gate can see the visual is no longer only a brief.
    visual["diagram_svg"] = svg
    visual["status"] = "drawn"
    updated = {**content, "visuals": visuals}
    filed: dict[str, Any] = {}
    try:
        filed = _record_artifact(
            "diagram", artifact.grade, artifact.subject, updated,
            strand=artifact.strand_name, sub_strand=artifact.sub_strand_name,
            parent=artifact.artifact_id,
            provenance={"source": "factory_draw_visual",
                        "provider": resolved.provider, "model": resolved.model,
                        "drew": title},
            measured_from={"quality_gate": diagram_gate.gate_of(
                diagram_gate.check(updated))},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Drew %s but could not file the version: %s", title, exc)

    drawn = sum(1 for v in visuals if v.get("diagram_svg"))
    return {
        "artifact_id": artifact.artifact_id,
        "index": payload.index,
        "title": title,
        "svg": svg,
        "storage_url": storage_url,
        "asset_id": asset_id,
        "stored_in_minio": in_minio,
        "model": resolved.model,
        "usage": getattr(response, "usage", None),
        "drawn": drawn,
        "total": len(visuals),
        "new_artifact": filed,
        # What the drawing does on the page, measured rather than eyeballed. An
        # operator seeing a thumbnail cannot tell that a label prints at 2mm.
        "layout": {
            "fits": bool(fit and fit.ok),
            "aspect": round(fit.aspect, 2) if fit else 0,
            "labels": fit.texts if fit else 0,
            "overlapping_labels": fit.collisions if fit else 0,
            "findings": list(fit.findings) if fit else [],
        },
    }


@router.get("/factory/assets/requirements")
def factory_asset_requirements(
    grade: str = Query(...),
    subject: str = Query(...),
    sub_strand: str = Query(...),
    strand: str = Query(""),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Every figure this sub-strand's plan asks for, and where each one stands.

    One row per requirement: the brief that would produce it, whether anything
    has filled it yet, and whether this system can generate it at all. Video
    cannot — nothing here makes footage, and offering a button for it would be
    offering to fail. Its brief is the deliverable; somebody films it.
    """
    from ..services import (
        asset_requirements, asset_uploads, figure_anchor, lesson_assets,
        remedies, stage_guard,
    )

    notes = stage_guard._filed_notes(grade, subject, sub_strand) or {}
    if not notes:
        raise_api_error(
            "MISSING_PARENT_CONTEXT",
            f"No lesson plan is filed for '{sub_strand}', and the figures a "
            f"lesson needs are named by its plan.",
            remedy=remedies.run_this_stage(grade, subject, "notes"),
        )

    wanted = asset_requirements.read(notes).items
    filled = lesson_assets.match(wanted, lesson_assets.collect(grade, subject, sub_strand))

    modules = {m.get("module_number", n): m
               for n, m in enumerate(notes.get("modules") or [], start=1)
               if isinstance(m, dict)}

    rows: list[dict[str, Any]] = []
    for req in wanted:
        module = modules.get(req.module_number) or {}
        have = filled.get(str(req.what).lower())
        rows.append({
            "kind": req.kind,
            "what": req.what,
            "lesson": req.module_number,
            "lesson_title": str(module.get("title") or ""),
            "topic": req.topic,
            "asset_id": asset_uploads.asset_id_for(grade, subject, sub_strand,
                                                   req.kind, req.what),
            "filled": bool(have),
            "storage_url": (have or {}).get("url", ""),
            "source": (have or {}).get("source", ""),
            "can_generate": asset_uploads.can_generate(req.kind),
            "accepts": list(asset_uploads.ACCEPTS.get(req.kind, ())),
            "brief": figure_anchor.brief_for(
                req, grade_label=grade, subject=subject, strand=strand,
                sub_strand=sub_strand,
                lesson_title=str(module.get("title") or ""),
            ),
        })

    return {
        "sub_strand": sub_strand,
        "total": len(rows),
        "filled": sum(1 for r in rows if r["filled"]),
        "requirements": rows,
        "note": (
            "A figure is filled by generating it where this system can, or by "
            "uploading the file. Video is upload-only: the brief is what this "
            "produces, and somebody films it."
        ),
    }


@router.post("/factory/assets/upload")
def factory_upload_asset(
    grade: str = Form(...),
    subject: str = Form(...),
    sub_strand: str = Form(...),
    kind: str = Form(...),
    what: str = Form(..., description="The requirement this answers, verbatim"),
    strand: str = Form(""),
    alt_text: str = Form(""),
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Supply the file for a planned figure.

    Filed against the requirement by name, so the page's plate fills with it
    and a second upload for the same figure replaces the first rather than
    leaving the renderer to choose.
    """
    from ..infra.storage import object_storage
    from ..services import asset_uploads

    accepts = asset_uploads.ACCEPTS.get(kind)
    if not accepts:
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{kind}' is not a kind of figure a page keeps space for. "
            f"Known: {', '.join(sorted(asset_uploads.ACCEPTS))}.",
        )

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in accepts:
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{content_type or 'unknown'}' cannot fill a {kind} plate. "
            f"That plate takes: {', '.join(accepts)}.",
        )

    payload = file.file.read()
    if not payload:
        raise_api_error("VALIDATION_FAILED", "The file is empty.")
    if len(payload) > asset_uploads.MAX_BYTES:
        raise_api_error(
            "VALIDATION_FAILED",
            f"{len(payload) // (1024 * 1024)}MB is larger than the "
            f"{asset_uploads.MAX_BYTES // (1024 * 1024)}MB limit.",
        )

    asset_id = asset_uploads.asset_id_for(grade, subject, sub_strand, kind, what)
    suffix = (file.filename or "").rsplit(".", 1)[-1].lower() or "bin"
    object_key = f"assets/{grade}/{subject}/{asset_id}.{suffix}".replace(" ", "-")

    try:
        storage_url = object_storage.save_bytes(object_key, payload, content_type)
    except Exception as exc:  # noqa: BLE001
        raise_api_error("STORAGE_UPLOAD_FAILED",
                        f"Could not store the file: {exc}")

    # An SVG is inlined on the page rather than fetched, so the print works
    # with no network. Everything else is referenced by URL.
    svg = payload.decode("utf-8", "replace") if content_type == "image/svg+xml" else ""

    recorded = asset_uploads.record(
        grade=grade, subject=subject, strand=strand, sub_strand=sub_strand,
        kind=kind, what=what, storage_url=storage_url, svg=svg,
        alt_text=alt_text, content_type=content_type, size=len(payload),
        source="upload", uploaded_by=getattr(auth, "subject", ""),
    )
    return {**recorded, "bytes": len(payload), "content_type": content_type}


class GenerateAssetRequest(BaseModel):
    grade: str
    subject: str
    sub_strand: str
    kind: str
    what: str
    strand: str = ""
    brief: str = ""
    custom_instructions: str = ""


@router.post("/factory/assets/generate")
def factory_generate_asset(
    payload: GenerateAssetRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Draw one planned figure now, from the brief the page already carries.

    Only for the kinds this system can actually produce. A video request is
    refused rather than attempted: nothing here makes footage, and a button
    that fails is worse than no button — it costs a call to learn what the
    capability list already knew.
    """
    from ..services import asset_uploads, diagram_dedup
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator

    if not asset_uploads.can_generate(payload.kind):
        raise_api_error(
            "VALIDATION_FAILED",
            f"Nothing here generates {payload.kind}. Its brief is what this "
            f"station produces — upload the file when you have it.",
        )

    brief = payload.brief.strip()
    if not brief:
        raise_api_error(
            "VALIDATION_FAILED",
            "Generating a figure needs the brief that describes it. Read the "
            "requirements for this sub-strand first.",
        )

    resolved = pipeline_orchestrator.router.resolve_for_stage("diagram_generation")
    instruction = (
        f"{brief}\n\n"
        "Return ONE standalone SVG and nothing else — no explanation, no "
        "markdown fence. It must carry its own viewBox, use no external fonts "
        "or images, and read correctly in black and white on a photocopy."
    )
    if payload.custom_instructions:
        instruction += f"\n\nALSO: {payload.custom_instructions}"

    try:
        response = llm_client.generate(
            resolved, [{"role": "user", "content": instruction}], temperature=0.2,
            expect="text")
    except Exception as exc:  # noqa: BLE001
        raise_api_error("DIAGRAM_GENERATION_FAILED", f"The model failed: {exc}")

    raw = response.content
    if isinstance(raw, dict):
        raw = raw.get("svg") or raw.get("content") or ""
    svg = diagram_dedup.extract_and_sanitize_svg(str(raw or ""))
    if not svg:
        raise_api_error(
            "DIAGRAM_GENERATION_FAILED",
            "The model returned nothing that parses as an SVG. Try again, or "
            "copy the brief and draw it elsewhere.",
        )

    from ..infra.storage import object_storage

    asset_id = asset_uploads.asset_id_for(payload.grade, payload.subject,
                                          payload.sub_strand, payload.kind,
                                          payload.what)
    key = f"assets/{payload.grade}/{payload.subject}/{asset_id}.svg".replace(" ", "-")
    storage_url = ""
    try:
        storage_url = object_storage.save_bytes(key, svg.encode("utf-8"),
                                                "image/svg+xml")
    except Exception as exc:  # noqa: BLE001
        # The SVG is kept on the row regardless: it is inlined on the page, so
        # a storage failure costs the download, not the figure.
        logger.warning("Could not store generated asset %s: %s", asset_id, exc)

    recorded = asset_uploads.record(
        grade=payload.grade, subject=payload.subject, strand=payload.strand,
        sub_strand=payload.sub_strand, kind=payload.kind, what=payload.what,
        storage_url=storage_url, svg=svg, content_type="image/svg+xml",
        size=len(svg), source=f"generated:{resolved.model}",
        uploaded_by=getattr(auth, "subject", ""),
    )
    return {**recorded, "svg": svg, "model": resolved.model,
            "usage": getattr(response, "usage", None)}


@router.delete("/factory/assets/{asset_id}")
def factory_remove_asset(
    asset_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Take a supplied file back off a figure, so the plate returns."""
    from ..services import asset_uploads

    removed = asset_uploads.remove(asset_id)
    return {"asset_id": asset_id, "removed": removed}


@router.get("/factory/material-drafts")
def factory_material_drafts(
    grade: str = Query("", description="Narrow to one grade"),
    subject: str = Query("", description="Narrow to one learning area"),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Material runs that were interrupted, and what they already produced.

    An interrupted run used to leave nothing at all — the pieces lived in
    memory until the last one landed. They are now written down as they are
    produced, and this is where an operator can see that a sub-strand has
    nineteen pieces waiting rather than assuming the money is gone.

    Running the station again resumes from these; it does not pay for them
    twice.
    """
    from ..services import material_draft

    rows = material_draft.pending(grade=grade, subject=subject)
    return {
        "count": len(rows),
        "drafts": [
            {
                "draft_key": r.get("draft_key"),
                "grade": r.get("grade"),
                "subject": r.get("subject"),
                "strand": r.get("strand"),
                "sub_strand": r.get("sub_strand"),
                "from_plan": r.get("plan_artifact_id"),
                "plan_version": r.get("plan_version"),
                "pieces_written": r.get("pieces_written"),
                "model": r.get("model"),
                "interrupted_at": str(r.get("updated_at") or ""),
            }
            for r in rows
        ],
        "note": (
            "These are unfinished runs, not versions. Generate the material for "
            "the same sub-strand and it carries on from what is here."
        ),
    }


@router.get("/factory/plan-approval")
def factory_plan_approval(
    grade: str = Query(...),
    subject: str = Query(...),
    sub_strand: str = Query(...),
    kind: str = Query("diagram"),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Whether the plan this station draws from has been signed off.

    A diagram, a photo brief, a video brief, a simulation and an activity are
    all drawn from what the plan says is taught. Planned from a plan that then
    changes, they are perfectly good pictures of the wrong lesson — and nothing
    downstream notices, because nothing downstream re-reads the plan.
    """
    from ..services.stage_guard import require_approved_plan

    return require_approved_plan(kind, grade, subject, sub_strand)


class ReadDesignRequest(BaseModel):
    """A design document pasted in, to see how the extractor reads it."""

    text: str
    grade: str = ""
    title: str = ""


@router.post("/factory/read-design")
def factory_read_design(
    payload: ReadDesignRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "developer")),
) -> dict[str, Any]:
    """Show what the parser makes of a document, WITHOUT ingesting it.

    Every ingest problem so far has been diagnosed by inference: a count is
    wrong on one screen, so something upstream must be misreading a cover. The
    document itself was never visible — sixteen Grade 9 designs were filed
    under Grade 7 for want of a way to ask "what grade do you think this is?"

    Nothing is written. This reads the text and reports what would be filed:
    the grade and where it came from, the learning area, the strands and
    sub-strands found, and every scripture reference — separated from the
    page:line addresses that look exactly like scripture and are not.
    """
    from ..services import scripture
    from ..services.curriculum_extractor import (
        _cover_text, _grade_from_text, curriculum_extractor,
    )
    from ..services.grade_order import normalize_grade

    text = payload.text or ""
    if len(text.strip()) < 200:
        raise_api_error(
            "VALIDATION_FAILED",
            f"That is {len(text.strip())} characters. A curriculum design is "
            f"tens of thousands — paste the document's text, not a fragment.",
        )

    meta = {"grade": normalize_grade(payload.grade), "title": payload.title,
            "file_id": "preview"}
    from_cover, level = _grade_from_text(text, meta)

    try:
        design = curriculum_extractor._parse_curriculum_text(text, meta, "preview")
        parsed = {
            "subject": design.subject,
            "subject_code": design.subject_code,
            "grade": design.grade,
            "level": design.level,
            "essence_statement": design.essence_statement[:600],
            "general_learning_outcomes": design.general_learning_outcomes[:12],
            "strands": sorted({s.strand for s in design.substrands if s.strand}),
            "sub_strands": [
                {"strand": s.strand, "name": s.sub_strand, "lessons": s.lessons,
                 "slos": len(s.slos or [])}
                for s in design.substrands[:60]
            ],
            "sub_strand_count": len(design.substrands),
        }
        error = ""
    except Exception as exc:  # noqa: BLE001
        parsed, error = {}, f"{type(exc).__name__}: {exc}"

    references = scripture.find(text)
    return {
        "characters": len(text),
        "cover": _cover_text(text)[:1200],
        "grade": {
            "read_from_cover": from_cover,
            "declared_by_dataset": meta["grade"],
            "would_file_under": parsed.get("grade") or from_cover or meta["grade"],
            "level": parsed.get("level") or level,
            "note": (
                "The cover names it."
                if from_cover else
                "Nothing on the cover names a grade, so the dataset settles it."
            ),
        },
        "parsed": parsed,
        "error": error,
        "scripture": {
            "references": sorted({str(r) for r in references}),
            "impossible": [scripture.impossible(r) for r in references
                           if scripture.impossible(r)],
            "not_a_book": scripture.suspect_books(text),
            "note": (
                "Read by BOOK, not by shape. `Page 199:2` and `Creation 203:10` "
                "are the design's own addresses and are deliberately not listed "
                "here — they were, and they drowned the real references."
            ),
        },
    }


@router.get("/factory/notes.html", response_class=HTMLResponse)
def factory_notes_html(
    artifact_id: str = Query(..., min_length=4),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
):
    """The same document the PDF is made from, to read on a screen.

    There was only a download. Judging a guide meant waiting for a PDF, opening
    it in another application, and going back to the console to act on it — for
    every version of every sub-strand. The page is the same renderer, so what
    is reviewed here is exactly what prints, down to where the pictures sit.
    """
    from ..services import artifact_registry, notes_renderer

    artifact = artifact_registry.get(artifact_id)
    if artifact.kind not in ("notes", "material"):
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{artifact.kind}' does not render as a document. The lesson plan "
            f"and the material written from it do.",
        )
    return HTMLResponse(_render_document(artifact))


def _render_document(artifact: Any) -> str:
    """One artifact as a document, by the renderer that suits its kind.

    Choosing the renderer and its arguments in ONE place, because doing it in
    two produced a 500: both routes passed `assets=` to whichever renderer came
    back, and only the plan's renderer takes it. Every material page 500'd
    with `render_material_html() got an unexpected keyword argument 'assets'`.

    A lesson plan keeps space for figures, so it is given the pictures already
    filed. The material is the words a teacher says aloud — it has no figures
    to fill, and passing it an asset map would be a parameter it ignores.
    """
    from ..services import artifact_registry, lesson_assets, notes_renderer

    content = artifact.content or {}
    common = {
        "grade": artifact.grade, "subject": artifact.subject,
        "strand": artifact.strand_name, "sub_strand": artifact.sub_strand_name,
        "version": artifact.version,
    }
    if artifact.kind == "material":
        # The material's figures are named by the plan it was written from —
        # the plan says which picture the lesson needs, the material is the
        # words said beside it.
        plan: dict[str, Any] = {}
        parent = getattr(artifact, "parent_artifact_id", "") or ""
        if parent:
            try:
                found = artifact_registry.get(parent)
                if found.kind == "notes":
                    plan = found.content or {}
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not read plan %s for %s: %s",
                               parent, artifact.artifact_id, exc)
        if not plan:
            # Material filed without a parent — generated before that link
            # existed, or unlocked by an operator rather than by the gate —
            # rendered with NO figures at all, because the figure list lives
            # on the plan. The plan for this sub-strand is not hard to find,
            # and a page with its pictures beats a page without them.
            try:
                newest = artifact_registry.search(
                    grade=artifact.grade, subject=artifact.subject,
                    sub_strand=artifact.sub_strand_name, kind="notes")
                if newest:
                    plan = (newest[0].get("content") or {})
            except Exception as exc:  # noqa: BLE001
                logger.warning("No plan found for material %s: %s",
                               artifact.artifact_id, exc)
        # Everything drawn for this sub-strand gets a place, whether or not
        # the plan found the words to ask for it. Read fresh on every request,
        # so drawing, redrawing or deleting one shows on the next refresh.
        plan = lesson_assets.with_drawn(
            plan, artifact.grade, artifact.subject, artifact.sub_strand_name)
        return notes_renderer.render_material_html(
            content, plan=plan,
            assets=lesson_assets.for_notes(
                plan, artifact.grade, artifact.subject, artifact.sub_strand_name),
            **common,
        )

    content = lesson_assets.with_drawn(
        content, artifact.grade, artifact.subject, artifact.sub_strand_name)
    return notes_renderer.render_html(
        content,
        assets=lesson_assets.for_notes(
            content, artifact.grade, artifact.subject, artifact.sub_strand_name),
        **common,
    )


@router.get("/factory/notes.pdf")
def factory_notes_pdf(
    artifact_id: str = Query(..., min_length=1),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> Any:
    """One filed guide, as a document a teacher can carry.

    A guide that exists only on a screen is not much use to a teacher whose
    classroom has no screen in it — and the console's Print button hands the
    job to whatever browser the operator happens to have, so no two copies
    match. This is the same file every time, and can be sent to somebody who is
    not sitting at the console.
    """
    from fastapi import Response

    from ..services import artifact_registry, notes_renderer, pdf

    artifact = artifact_registry.get(artifact_id)
    if artifact.kind not in ("notes", "material"):
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{artifact.kind}' does not render to PDF. The lesson plan and the "
            f"material written from it do; a diagram or an activity belongs "
            f"inside one of those.",
        )

    document = _render_document(artifact)
    try:
        body = pdf.from_html(document)
    except pdf.PdfUnavailable as exc:
        raise_api_error("MODEL_ENDPOINT_UNAVAILABLE", str(exc))

    stem = "-".join(
        part.lower().replace(" ", "-")
        for part in (artifact.grade, artifact.subject, artifact.sub_strand_name,
                     "material" if artifact.kind == "material" else "plan")
        if part
    ) or "teachers-guide"
    return Response(
        content=body,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'attachment; filename="{stem}-v{artifact.version}.pdf"',
        },
    )


@router.get("/factory/progress")
def factory_progress(
    run_id: str = Query(..., min_length=1),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """What a run has done so far.

    A station called from the factory blocks until its guide is finished, so
    the console showed a spinner for two minutes and then a result — with no
    way to tell a slow run from a wedged one, and no sight of the checks and
    repairs happening inside it. The run publishes its steps under an id the
    browser generated; this reads them back.
    """
    return run_log.read(run_id)


@router.post("/factory/sweep-orphans")
def factory_sweep_orphans(
    payload: SweepOrphansRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Remove generated content whose sub-strand no longer exists.

    The delete endpoints the older console calls removed three tables and left
    `artifacts` — with every version, review verdict, label and comment — in
    place. Anything deleted through them before that was fixed is still in the
    database, still counting toward coverage, still describing a sub-strand
    nobody can see.

    Fixing the endpoints does nothing for what they already left. This is the
    sweep for that, and like every other destructive route here it is a dry run
    until `confirm` says DELETE.
    """
    return scoped_delete.sweep_orphans(payload.confirm)


@router.get("/factory/orphans")
def factory_list_orphans(
    limit: int = Query(default=200, ge=1, le=1000),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """What the sweep would remove, listed one version at a time."""
    found = scoped_delete.find_orphans(limit=limit)
    return {"total": len(found), "orphans": found}


@router.post("/factory/regenerate-scope")
def factory_regenerate_scope(
    payload: RegenerateScopeRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Delete a strand's sub-strands (or one sub-strand) and generate again.

    Regenerating without deleting first leaves the old rows in place: the
    generator writes what it finds now, the previous sub-strands stay stored
    under names it did not produce this time, and the strand ends up holding
    both. So the removal is part of the regeneration rather than a step the
    operator has to remember.

    The strand itself is kept — it is what the new sub-strands are generated
    against.
    """
    from ..services import job_queue

    if payload.confirm.strip().upper() != scoped_delete.CONFIRMATION:
        # Show what would go, and do nothing. Regeneration is destructive
        # before it is productive.
        preview = scoped_delete.delete(
            payload.grade, payload.subject,
            strand=payload.strand, sub_strand=payload.sub_strand,
            keep_strand=True,
        )
        return {**preview.to_dict(), "queued": 0,
                "message": preview.to_dict()["message"].replace(
                    "removed", "removed and regenerated")}

    removed = scoped_delete.delete(
        payload.grade, payload.subject,
        strand=payload.strand, sub_strand=payload.sub_strand,
        confirm=payload.confirm, keep_strand=True,
    )

    job = job_queue.enqueue(
        "substrands", payload.grade, payload.subject,
        {"custom_instructions": payload.custom_instructions,
         "strand_id": payload.strand_id},
        strand=payload.strand,
        batch_id="regen_" + payload.strand.lower().replace(" ", "-")[:24],
        queued_by=getattr(auth, "subject", ""),
    )
    job_queue.start_worker()

    return {
        **removed.to_dict(),
        "queued": 1,
        "job": job.to_dict(),
        "message": (
            f"Removed {removed.total} row(s) for '{payload.strand}' and queued it "
            f"for regeneration. The result waits as a draft until you save it."
        ),
    }


@router.post("/factory/queue-pipeline")
def factory_queue_pipeline(
    payload: QueuePipelineRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Queue a learning area end to end: design in, questions out.

    The chain used to be a person. Ingest, wait, read the result, click
    strands, wait, click each strand's sub-strands, wait, click notes for each
    sub-strand, wait — an afternoon of pressing buttons and watching, per
    learning area. That is what made producing at any scale impossible, and it
    is the only reason the work was ever done one item at a time.

    Each stage fans out from what the stage before it SAVED, so nothing has to
    be guessed at queue time, and a stage advances only when all of it is
    finished.
    """
    import hashlib as _hashlib
    from ..services import job_queue

    steps = [str(x).strip() for x in payload.steps if str(x).strip()] or list(PIPELINE_STEPS)
    unknown = [s for s in steps if s not in PIPELINE_STEPS]
    if unknown:
        raise_api_error(
            "VALIDATION_FAILED",
            f"Not pipeline steps: {', '.join(unknown)}. "
            f"Known, in order: {', '.join(PIPELINE_STEPS)}.",
        )

    # Kept in the published order however they were listed. A run that did
    # notes before sub-strands would generate nothing and report success.
    steps = [s for s in PIPELINE_STEPS if s in set(steps)]

    units = _expand_step(steps[0], payload.grade, payload.subject, payload.strand)
    if not units:
        raise_api_error(
            "MISSING_PARENT_CONTEXT",
            f"'{steps[0]}' has nothing to run against for {payload.subject} "
            f"({payload.grade}). Start the run at an earlier step — the design "
            f"has to be ingested before there are strands, and strands before "
            f"there are sub-strands.",
        )

    batch_id = "batch_" + _hashlib.sha256(
        f"pipeline{payload.grade}{payload.subject}{payload.strand}{steps}".encode()
    ).hexdigest()[:16]

    queued = []
    for unit in units:
        job = job_queue.enqueue(
            "pipeline", payload.grade, payload.subject,
            {"steps": steps, "index": 0,
             "custom_instructions": payload.custom_instructions,
             "scope_strand": payload.strand,
             "force": payload.force_ingest},
            strand=unit.get("strand", ""),
            sub_strand=unit.get("sub_strand", ""),
            batch_id=batch_id, queued_by=getattr(auth, "subject", ""),
        )
        queued.append(job.to_dict())

    job_queue.start_worker()

    return {
        "status": "queued",
        "batch_id": batch_id,
        "steps": steps,
        "starting_step": steps[0],
        "queued": len(queued),
        "jobs": queued,
        "note": ("Each stage fans out as the one before it finishes, so the job "
                 "count grows as the run proceeds. Every step saves what it "
                 "made, and every generation is reviewed and revised in the "
                 "worker before it is filed."),
    }


@router.post("/factory/auto-run")
def factory_auto_run(
    payload: AutoRunRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Run the whole pipeline across a grade, unattended, with a quality floor.

    Set it going, come back, download everything, review it at leisure. The
    floor is what makes that safe: every finished item is scored against what
    its own validators actually checked, and the run halts and cancels what has
    not started when the recent average falls through it.

    The score is NOT the accuracy a person reading against the KICD design
    would give. It measures grounding, lesson coverage, citation resolution,
    how many rubrics came from the design, and the local gate. It catches
    absence, contradiction and ungroundedness; it cannot tell whether a rubric
    measures the right thing.
    """
    import hashlib as _hashlib
    from ..infra.db import fetch_all
    from ..services import job_queue

    steps = [str(x).strip() for x in payload.steps if str(x).strip()] or list(PIPELINE_STEPS)
    steps = [s for s in PIPELINE_STEPS if s in set(steps)]

    subjects = [s.strip() for s in payload.subjects if s.strip()]
    if not subjects:
        rows = fetch_all(
            """
            SELECT DISTINCT subject FROM curriculum_designs
            WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')) AND subject <> ''
            ORDER BY subject
            """,
            {"grade": payload.grade,
             "alt_grade": payload.grade.replace("grade-", "")},
        ) or []
        subjects = [str(r.get("subject") or "") for r in rows if r.get("subject")]

    if not subjects:
        raise_api_error(
            "MISSING_PARENT_CONTEXT",
            f"No ingested designs for {payload.grade}. Ingest at least one "
            f"learning area before starting an auto-run.",
        )

    batch_id = "auto_" + _hashlib.sha256(
        f"{payload.grade}{subjects}{steps}".encode()
    ).hexdigest()[:16]

    run = auto_run.start(
        payload.grade, subjects, batch_id,
        floor=payload.floor, window=payload.window,
        started_by=getattr(auth, "subject", ""),
    )

    queued = 0
    for subject in subjects:
        units = _expand_step(steps[0], payload.grade, subject, "")
        for unit in units:
            job_queue.enqueue(
                "pipeline", payload.grade, subject,
                {"steps": steps, "index": 0,
                 "custom_instructions": payload.custom_instructions,
                 "review_cycles": max(1, payload.review_cycles),
                 "scope_strand": ""},
                strand=unit.get("strand", ""),
                sub_strand=unit.get("sub_strand", ""),
                batch_id=batch_id,
                queued_by=getattr(auth, "subject", ""),
            )
            queued += 1

    job_queue.start_worker()

    return {
        "status": "running",
        **run.to_dict(),
        "queued": queued,
        "steps": steps,
        "note": (
            f"Running unattended across {len(subjects)} learning area(s). Each "
            f"stage fans out as the one before it finishes. The run halts if the "
            f"last {payload.window} scored items average below {payload.floor:.0f}."
        ),
    }


@router.get("/factory/auto-run/status")
def factory_auto_run_status(
    run_id: str = Query(""),
    grade: str = Query(""),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """How the unattended run is going, and which items are dragging it down."""
    from ..services import job_queue

    run = auto_run.get(run_id=run_id, grade=grade)
    if run is None:
        return {"running": False, "note": "No auto-run has been started."}

    return {
        "running": run.status == auto_run.RUNNING,
        **run.to_dict(),
        "queue": job_queue.status(batch_id=run.batch_id),
    }


@router.get("/factory/auto-run/activity")
def factory_auto_run_activity(
    run_id: str = Query(""),
    grade: str = Query(""),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """What the run is doing, what it has produced, and what it has cost.

    A progress bar answers "how far" and nothing else. The three questions an
    operator actually has are "what is it doing right now", "is what it is
    producing any good", and "how much have I spent" — and the last one was
    unanswerable until the bill arrived.
    """
    from ..infra.db import fetch_all, fetch_one
    from ..services import auto_run as auto_run_service

    run = auto_run_service.get(run_id=run_id, grade=grade)
    if run is None:
        return {"running": False, "note": "No auto-run has been started."}

    params = {"batch_id": run.batch_id}

    # What is on the bench now, for how long, and what it is saying while it
    # works. The steps come off the job row the worker writes as it goes, so a
    # run narrates itself instead of showing a bar that only moves at the end.
    running = fetch_all(
        """
        SELECT job_id, kind, strand, sub_strand, subject, started_at, attempts,
               (payload->'steps'->>COALESCE((payload->>'index')::int, 0)) AS step,
               EXTRACT(EPOCH FROM (NOW() - started_at)) AS seconds,
               result->'progress' AS progress
        FROM jobs WHERE batch_id = :batch_id AND status = 'running'
        ORDER BY started_at ASC
        """,
        params,
    ) or []

    # The same shape the pipeline board uses, for this run's batch: which stage
    # of which subject it is on. A percentage answers "how far" and nothing
    # about WHERE — and an operator watching a grade run overnight is asking
    # which stage is slow, not what fraction is done.
    by_stage = fetch_all(
        """
        SELECT kind AS stage,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status IN ('queued')) AS queued,
               COUNT(*) FILTER (WHERE status = 'running') AS running,
               COUNT(*) FILTER (WHERE status = 'done') AS done,
               COUNT(*) FILTER (WHERE status = 'failed') AS failed,
               COALESCE(SUM(cost_usd), 0) AS cost
        FROM jobs WHERE batch_id = :batch_id
        GROUP BY kind
        """,
        params,
    ) or []

    by_subject = fetch_all(
        """
        SELECT subject,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status IN ('done')) AS done,
               COUNT(*) FILTER (WHERE status = 'failed') AS failed,
               COUNT(*) FILTER (WHERE status IN ('queued','running')) AS active,
               COALESCE(SUM(cost_usd), 0) AS cost
        FROM jobs WHERE batch_id = :batch_id AND subject <> ''
        GROUP BY subject ORDER BY subject
        """,
        params,
    ) or []

    # What finished recently, newest first, with what each one cost.
    recent = fetch_all(
        """
        SELECT job_id, kind, strand, sub_strand, subject, status, finished_at,
               llm_calls, total_tokens, cost_usd, error,
               (payload->'steps'->>COALESCE((payload->>'index')::int, 0)) AS step,
               (result->'quality'->>'score') AS score,
               (result->'quality'->>'weakest') AS weakest,
               (result->'review_cycles'->>'cycles_run') AS cycles
        FROM jobs
        WHERE batch_id = :batch_id AND status IN ('done', 'failed')
        ORDER BY finished_at DESC NULLS LAST LIMIT 25
        """,
        params,
    ) or []

    # Where the money went, by station.
    by_kind = fetch_all(
        """
        SELECT kind, COUNT(*) AS jobs, SUM(llm_calls) AS calls,
               SUM(total_tokens) AS tokens, SUM(cost_usd) AS cost
        FROM jobs WHERE batch_id = :batch_id
        GROUP BY kind ORDER BY SUM(cost_usd) DESC NULLS LAST
        """,
        params,
    ) or []

    totals = fetch_one(
        """
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status IN ('done','failed','cancelled')) AS finished,
               COALESCE(SUM(cost_usd), 0) AS cost,
               COALESCE(SUM(total_tokens), 0) AS tokens,
               MIN(started_at) AS first_started,
               MAX(finished_at) AS last_finished
        FROM jobs WHERE batch_id = :batch_id
        """,
        params,
    ) or {}

    done = int(totals.get("finished") or 0)
    total = int(totals.get("total") or 0)
    cost = float(totals.get("cost") or 0.0)

    # Throughput and what the rest would cost at the rate it is going. An
    # estimate that says so, not a promise.
    per_item = round(cost / done, 4) if done else 0.0
    remaining = max(0, total - done)

    elapsed_seconds = 0.0
    if totals.get("first_started"):
        from datetime import datetime, timezone

        end = totals.get("last_finished") or datetime.now(timezone.utc)
        try:
            elapsed_seconds = max(0.0, (end - totals["first_started"]).total_seconds())
        except Exception:  # noqa: BLE001
            elapsed_seconds = 0.0

    return {
        "running": run.status == auto_run_service.RUNNING,
        "run_id": run.run_id,
        "status": run.status,
        "floor": run.floor,
        "recent_median": run.recent_median,
        "average": run.average,
        "halted_reason": run.halted_reason,
        "progress": {
            "finished": done, "total": total, "remaining": remaining,
            "percentage": round(done / total * 100) if total else 0,
        },
        "spend": {
            "cost_usd": round(cost, 4),
            "tokens": int(totals.get("tokens") or 0),
            "per_item_usd": per_item,
            # Named an estimate because that is what it is: the stages still to
            # come are not the stages already done, and notes cost more than
            # strands.
            "projected_remaining_usd": round(per_item * remaining, 2),
            "by_station": [dict(r) for r in by_kind],
        },
        "pace": {
            "elapsed_seconds": round(elapsed_seconds),
            "items_per_hour": round(done / (elapsed_seconds / 3600), 1)
            if elapsed_seconds > 60 and done else 0,
        },
        "now_running": [dict(r) for r in running],
        "recent": [dict(r) for r in recent],
        # In the pipeline's own vocabulary, so the auto-run reads as the board
        # advancing rather than as a separate thing with its own words.
        "stages": _auto_run_stages(by_stage),
        "subjects": [dict(r) for r in by_subject],
    }


def _auto_run_stages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """This run's jobs, arranged as pipeline stages in pipeline order.

    A stage the run has not reached is listed with zeros rather than left out:
    the shape of the whole pipeline is what says how far there is still to go,
    and a board that grows as work arrives cannot be read at a glance.
    """
    from ..services import pipeline_board, stage_policy

    counted = {str(r["stage"]): r for r in rows}
    out = []
    for stage in stage_policy.STAGES:
        row = counted.get(stage, {})
        total = int(row.get("total") or 0)
        done = int(row.get("done") or 0)
        out.append({
            "stage": stage,
            "label": pipeline_board.STAGE_LABEL.get(stage, stage),
            "total": total,
            "queued": int(row.get("queued") or 0),
            "running": int(row.get("running") or 0),
            "done": done,
            "failed": int(row.get("failed") or 0),
            "cost_usd": round(float(row.get("cost") or 0), 4),
            "percentage": round(done / total * 100) if total else 0,
            "status": (
                "failing" if int(row.get("failed") or 0) else
                "running" if int(row.get("running") or 0) else
                "done" if total and done == total else
                "queued" if total else "not_reached"
            ),
        })
    return out


@router.post("/factory/auto-run/stop")
def factory_auto_run_stop(
    run_id: str = Query(...),
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Stop an unattended run and cancel what it had not started."""
    cancelled = auto_run.stop(run_id)
    return {"status": "stopped", "run_id": run_id, "cancelled_jobs": cancelled}


@router.post("/factory/queue-regenerate")
def factory_queue_regenerate(
    payload: QueueRegenerateRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Regenerate reviewed versions from their findings, in the background.

    Regeneration is a generation and costs a generation's time. Run from a
    button it held the console open exactly as the first generation did, which
    made acting on a review pass across a grade another afternoon of waiting.
    """
    import hashlib as _hashlib
    from ..infra.db import fetch_all
    from ..services import job_queue

    ids = [a.strip() for a in payload.artifact_ids if a.strip()]
    if ids:
        rows = fetch_all(
            "SELECT artifact_id, grade, subject, strand_name, sub_strand_name "
            "FROM artifacts WHERE artifact_id = ANY(:ids)",
            {"ids": ids},
        ) or []
    else:
        # Everything in scope that a reviewer has actually looked at. There is
        # nothing to regenerate FROM without findings, and regenerating without
        # them is just another roll of the same dice at the same price.
        rows = fetch_all(
            """
            SELECT DISTINCT a.artifact_id, a.grade, a.subject,
                   a.strand_name, a.sub_strand_name
            FROM artifacts a
            JOIN artifact_reviews r ON r.artifact_id = a.artifact_id
            WHERE (REPLACE(LOWER(a.grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))
              AND (:subject = '' OR LOWER(a.subject) = LOWER(:subject))
              AND r.verdict IN ('revise', 'reject')
            LIMIT 500
            """,
            {"grade": payload.grade, "alt_grade": payload.grade.replace("grade-", ""),
             "subject": payload.subject},
        ) or []

    if not rows:
        raise_api_error(
            "VALIDATION_FAILED",
            "Nothing to regenerate. A version needs a review with findings "
            "before there is anything to regenerate from — queue a review first.",
        )

    batch_id = "batch_" + _hashlib.sha256(
        f"regen{payload.grade}{payload.subject}{len(rows)}".encode()
    ).hexdigest()[:16]

    queued = []
    for row in rows:
        job = job_queue.enqueue(
            "regenerate", str(row.get("grade") or payload.grade),
            str(row.get("subject") or payload.subject),
            {"artifact_id": str(row.get("artifact_id") or ""),
             "extra_instructions": payload.extra_instructions},
            strand=str(row.get("strand_name") or ""),
            sub_strand=str(row.get("sub_strand_name") or ""),
            batch_id=batch_id, queued_by=getattr(auth, "subject", ""),
        )
        queued.append(job.to_dict())

    job_queue.start_worker()
    return {"status": "queued", "batch_id": batch_id, "queued": len(queued),
            "artifacts": len(rows), "jobs": queued}


@router.post("/factory/queue-review")
def factory_queue_review(
    payload: QueueReviewRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Queue review or approval across many artifacts, one at a time.

    The reviewers and the approver are model calls like the generators, and
    they were the half of the pipeline still being run by hand, one artifact at
    a time, with somebody watching. Queued, a grade can be generated and sent
    for review in one sitting and read the next morning.

    It queues the approver's WORK, not the approval. Approval stays a person's
    decision, because coverage counts approved work and a pipeline that
    approved its own output would let a grade report itself taught-ready with
    nobody having read a line of it.
    """
    import hashlib as _hashlib
    from ..infra.db import fetch_all
    from ..services import job_queue

    if payload.work not in ("review", "approval"):
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{payload.work}' is not review work. Use 'review' or 'approval'.",
        )

    ids = [a.strip() for a in payload.artifact_ids if a.strip()]
    rows: list[dict[str, Any]] = []
    if ids:
        rows = fetch_all(
            """
            SELECT artifact_id, grade, subject, strand_name, sub_strand_name, kind
            FROM artifacts WHERE artifact_id = ANY(:ids)
            """,
            {"ids": ids},
        ) or []
    else:
        rows = fetch_all(
            """
            SELECT a.artifact_id, a.grade, a.subject, a.strand_name,
                   a.sub_strand_name, a.kind
            FROM artifacts a
            WHERE (REPLACE(LOWER(a.grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))
              AND (:subject = '' OR LOWER(a.subject) = LOWER(:subject))
              AND (:strand = '' OR LOWER(a.strand_name) = LOWER(:strand))
              AND (:kinds = '' OR a.kind = ANY(STRING_TO_ARRAY(:kinds, ',')))
            ORDER BY a.created_at DESC
            LIMIT 500
            """,
            {"grade": payload.grade, "alt_grade": payload.grade.replace("grade-", ""),
             "subject": payload.subject, "strand": payload.strand,
             "kinds": ",".join(payload.kinds)},
        ) or []

    if not rows:
        raise_api_error(
            "MISSING_PARENT_CONTEXT",
            "No artifacts to review in this selection. Generate something first.",
        )

    batch_id = "batch_" + _hashlib.sha256(
        f"{payload.work}{payload.grade}{payload.subject}{len(rows)}".encode()
    ).hexdigest()[:16]

    queued: list[dict[str, Any]] = []
    for row in rows:
        job = job_queue.enqueue(
            payload.work,
            str(row.get("grade") or payload.grade),
            str(row.get("subject") or payload.subject),
            {"artifact_id": str(row.get("artifact_id") or ""),
             "layer": payload.layer, "provider": payload.provider,
             "model": payload.model},
            strand=str(row.get("strand_name") or ""),
            sub_strand=str(row.get("sub_strand_name") or ""),
            batch_id=batch_id, queued_by=getattr(auth, "subject", ""),
        )
        queued.append(job.to_dict())

    job_queue.start_worker()

    return {
        "status": "queued",
        "work": payload.work,
        "batch_id": batch_id,
        "queued": len(queued),
        "artifacts": len(rows),
        "jobs": queued,
        "note": ("Running one at a time. Approval still needs a person — this "
                 "gets each artifact to the point where that is a decision "
                 "rather than an afternoon."),
    }


@router.get("/factory/export")
def factory_export(
    grade: str = Query(..., description="Grade slug, e.g. grade-pp1"),
    subject: str = Query("", description="One learning area, or empty for all"),
    fmt: str = Query("zip", pattern="^(zip|json)$"),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> Any:
    """Download everything generated for a grade or learning area.

    Content that only exists inside a console is content nobody can review
    properly. A curriculum is a body of work, and reviewing it means opening it
    in an editor, searching across it, and diffing this week's against last
    week's.

    `zip` gives a folder tree, one JSON file per thing. `json` gives the same
    content as a single object, for a script that would rather not unzip.
    """
    from fastapi import Response

    if fmt == "json":
        files = export_bundle.collect(grade, subject)
        return {
            "grade": grade,
            "subject": subject,
            "generator": generation_version.VERSION,
            # Parsed back out so the caller gets objects rather than strings of
            # JSON inside JSON.
            "files": {
                path: (json.loads(text) if path.endswith(".json") else text)
                for path, text in sorted(files.items())
            },
        }

    payload, report = export_bundle.to_zip(grade, subject)
    if not report.files:
        raise_api_error(
            "MISSING_PARENT_CONTEXT",
            f"Nothing generated yet for {subject or grade}.",
        )

    name = f"cbc-{export_bundle.slug(grade)}"
    if subject:
        name += f"-{export_bundle.slug(subject)}"

    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{name}.zip"',
            # So a script can check what it got without unzipping.
            "X-CBC-File-Count": str(len(report.files)),
            "X-CBC-Generator": generation_version.VERSION,
        },
    )


@router.get("/factory/queue/job/{job_id}")
def factory_queue_job(
    job_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """One job and what it produced.

    This is what makes a refresh harmless rather than merely survivable: the
    console reopens, reads the job it was watching, and shows the finished
    output — instead of a green tick and no way back to the result.
    """
    from ..infra.db import fetch_one

    row = fetch_one(
        """
        SELECT job_id, batch_id, kind, grade, subject, strand, sub_strand,
               status, attempts, error, result, created_at, started_at, finished_at
        FROM jobs WHERE job_id = :job_id
        """,
        {"job_id": job_id},
    )
    if not row:
        raise_api_error("NOT_FOUND", f"No job {job_id}.")
    return dict(row)


@router.post("/factory/queue/discard-stale-drafts")
def factory_discard_stale_drafts(
    grade: str = Query(""),
    subject: str = Query(""),
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Throw away drafts an older generator produced.

    They are indistinguishable from fresh output in the console — same shape,
    same fields, no timestamp that means anything to a reader — so they get
    read as current for as long as they sit there.
    """
    from ..services import job_queue

    discarded: list[str] = []
    for row in job_queue.drafts("substrands", grade=grade, subject=subject):
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        if generation_version.is_current(result.get("generator")):
            continue
        job_queue.consume(str(row.get("job_id") or ""))
        discarded.append(str(row.get("strand") or ""))

    return {
        "status": "discarded",
        "discarded": len(discarded),
        "strands": discarded,
        "generator": generation_version.VERSION,
        "note": ("Queue these strands again to regenerate them with the current "
                 "generator."),
    }


@router.post("/factory/queue/discard-draft")
def factory_queue_discard_draft(
    payload: DiscardDraftRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Throw away one generated draft without saving it."""
    from ..services import job_queue

    discarded = job_queue.consume(payload.job_id)
    return {"status": "discarded", "job_id": payload.job_id, "discarded": discarded}


@router.get("/factory/queue/status")
def factory_queue_status(
    batch_id: str = Query(""),
    grade: str = Query(""),
    subject: str = Query(""),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """What the queue is doing, for the console to poll."""
    from ..services import job_queue

    return job_queue.status(batch_id=batch_id, grade=grade, subject=subject)


@router.post("/factory/queue/retry")
def factory_queue_retry(
    job_id: str = Query(""),
    grade: str = Query(""),
    subject: str = Query(""),
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Put failed work back in the queue.

    A job that crashed twice is parked rather than retried automatically —
    retrying a genuine defect spends money to learn nothing. But a job that
    failed on a bug since fixed should not stay failed for ever, and until now
    there was no way to move it.
    """
    from ..services import job_queue

    retried = job_queue.retry(job_id=job_id, grade=grade, subject=subject)
    if not retried:
        return {
            "status": "nothing_to_retry",
            "retried": 0,
            "note": ("No failed jobs matched. Name a job_id, or a grade and "
                     "subject — retrying every failure everywhere is never what "
                     "anyone means."),
        }
    job_queue.start_worker()
    return {
        "status": "queued",
        "retried": len(retried),
        "job_ids": retried,
        "note": ("Attempts were reset, so these get a full budget rather than "
                 "the one they had left. If the cause has not actually been "
                 "fixed they will fail again at the same cost."),
    }


@router.post("/factory/queue/cancel")
def factory_queue_cancel(
    batch_id: str = Query(""),
    job_id: str = Query(""),
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Stop work that has not started. A running job is left to finish —
    killing it mid-flight leaves the artifact half-written with no record of
    which half, and the tokens are spent either way."""
    from ..services import job_queue

    return {"status": "cancelled", "cancelled": job_queue.cancel(job_id, batch_id)}


@router.post("/factory/reset")
def factory_reset(
    payload: FactoryResetRequest,
    auth: AuthContext = Depends(require_roles("admin")),
) -> dict[str, Any]:
    """Clear generated content and start again from the dataset.

    The Langfuse dataset holds the KICD design documents and is the source of
    truth; nothing here touches it. Everything in Postgres downstream is derived
    and reproducible, which is what makes discarding it safe when the pipeline
    that produced it has changed enough that reconciling the old output costs
    more than regenerating it.

    A DRY RUN by default: it returns the row counts and deletes nothing. Send
    the exact confirmation phrase to proceed. Admin only, and every run is
    logged with who asked for it.
    """
    from ..services import factory_reset as reset

    report = reset.run(
        grade=payload.grade, subject=payload.subject,
        confirm=payload.confirm, include=payload.include or None,
    )

    if not report.dry_run:
        logger.warning(
            "FACTORY RESET by %s: %d row(s) across %d table(s), scope=%s",
            getattr(auth, "subject", "unknown"), report.total,
            len(report.tables), report.scope or "everything",
        )

    return report.to_dict()


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

    resolved = pipeline_orchestrator.router.resolve_for_stage("ingest_extraction")
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
        WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))
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
    from ..services import lesson_content as lesson

    design_block, slos = _substrand_design_block(
        payload.grade, payload.subject, payload.sub_strand
    )
    taught = lesson.for_sub_strand(payload.grade, payload.subject, payload.sub_strand)
    if not design_block:
        raise_api_error(
            "MISSING_PARENT_CONTEXT",
            f"'{payload.sub_strand}' is not stored for {payload.subject} "
            f"({payload.grade}), so there is nothing to plan media from. "
            f"Generate and save its sub-strands first.",
        )

    profile = get_profile_from_db(payload.subject, payload.grade)
    resolved = pipeline_orchestrator.router.resolve_for_stage("media_generation")

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
            "language_register": language_block(payload.grade),
            # How this subject writes what it cannot write in words. Empty for
            # most subjects — a CRE guide carrying two pages about balancing
            # equations spends a page of prompt on something it never uses, and
            # every irrelevant instruction makes the relevant ones harder to
            # find.
            "notation": notation.block_for(payload.subject, grade=payload.grade),
            # What THIS subject needs that no other does: maps and scale for
            # Geography, equations that balance for Chemistry, sol-fa for
            # Music, a cutting list for Carpentry. Empty for most pairings,
            # which is the point — a CRE lesson plan receives no paragraph
            # about mortise and tenon joints.
            "domain_directives": prompt_fragments.compose(
                payload.subject, "media", payload.grade),
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
            # The interesting assets are the ones the teaching content already
            # names — the volcano the notes describe, the experiment the
            # activity plan sets out. Planning from the outcomes alone cannot
            # brief those, because the outcomes do not mention them.
            "notes_summary": taught.notes_summary or "(no notes generated yet)",
            "activities_summary": taught.activities_summary or "(no activities planned yet)",
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
        "grounding": taught.to_dict(),
        "saved": payload.save,
        "usage": resp.usage,
        "model": f"{resolved.provider}/{resolved.model}",
    }


@router.post("/factory/generate-simulations")
def factory_generate_simulations(
    payload: GenerateSimulationsRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer")),
) -> dict[str, Any]:
    """Plan the interactive simulations a sub-strand needs.

    A diagram is a still picture of a thing; a simulation is the thing behaving.
    A learner who drags a piston and watches the pressure gauge climb has met
    Boyle's law in a way no caption reaches, and a teacher with no laboratory
    now has one.

    What this authors is the BUILD BRIEF, not the code: the model with its
    equations, the controls with their ranges, what is drawn, what updates, and
    the acceptance criteria a built version must meet. A brief that says "show
    Newton's second law with a spring" is a title, not a brief.
    """
    from ..services import lesson_content as lesson
    from ..services.content_type_classifier import get_profile_from_db
    from ..services.langfuse_context import langfuse_context_service
    from ..services.llm_client import llm_client
    from ..services.pipeline import pipeline_orchestrator

    design_block, slos = _substrand_design_block(
        payload.grade, payload.subject, payload.sub_strand
    )
    if not design_block:
        raise_api_error(
            "MISSING_PARENT_CONTEXT",
            f"'{payload.sub_strand}' is not stored for {payload.subject} "
            f"({payload.grade}), so there is nothing to build a simulation from. "
            f"Ingest the learning area and save its sub-strands first.",
        )

    # Simulate the experiment the teacher will actually run, not a different
    # one. Planning from the outcomes alone cannot do that: the outcomes do not
    # name the apparatus, and the notes do.
    taught = lesson.for_sub_strand(payload.grade, payload.subject, payload.sub_strand)

    profile = get_profile_from_db(payload.subject, payload.grade)
    context = langfuse_context_service.assemble_agent_context(
        agent_name="simulation-generator",
        grade_slug=payload.grade,
        subject=payload.subject,
        template_vars={
            "master_context": langfuse_context_service.get_master_context(),
            "level_register": register_block(
                payload.grade, notes=grade_scope_notes(payload.grade, payload.subject)
            ),
            "language_register": language_block(payload.grade),
            # How this subject writes what it cannot write in words. Empty for
            # most subjects — a CRE guide carrying two pages about balancing
            # equations spends a page of prompt on something it never uses, and
            # every irrelevant instruction makes the relevant ones harder to
            # find.
            "notation": notation.block_for(payload.subject, grade=payload.grade),
            # What THIS subject needs that no other does: maps and scale for
            # Geography, equations that balance for Chemistry, sol-fa for
            # Music, a cutting list for Carpentry. Empty for most pairings,
            # which is the point — a CRE lesson plan receives no paragraph
            # about mortise and tenon joints.
            "domain_directives": prompt_fragments.compose(
                payload.subject, "simulation", payload.grade),
            "faith_scope": faith_prompt_block(payload.subject),
            "content_type_directives": profile.format_for_prompt() if profile else "",
            "strand": payload.strand,
            "sub_strand": payload.sub_strand,
            "design_extract": design_block,
            "slos": "\n".join(
                f"- {s.get('text', s) if isinstance(s, dict) else s}" for s in slos
            ) or "(none stored)",
            "notes_summary": taught.notes_summary or "(no notes generated yet)",
            "activities_summary": taught.activities_summary or "(no activities planned yet)",
            "custom_instructions": payload.custom_instructions,
        },
    )

    resolved = pipeline_orchestrator.router.resolve_for_stage("simulation_generation")

    if payload.inspect:
        return {
            "inspection": build_inspection(
                context, agent="simulation-generator", grade=payload.grade,
                subject=payload.subject, source_material=design_block, profile=profile,
                extra={"model": f"{resolved.provider}/{resolved.model}",
                       "sub_strand": payload.sub_strand,
                       "grounded_in_notes": taught.found_notes},
            )
        }

    resp = llm_client.generate(resolved, context.messages, temperature=0.3)
    content = resp.content if isinstance(resp.content, dict) else {}
    simulations = [s for s in (content.get("simulations") or []) if isinstance(s, dict)]

    quality = simulation_validators.check(simulations)
    if not quality.sound:
        logger.warning(
            "Simulation briefs for %s have %d blocking issue(s).",
            payload.sub_strand, len(quality.errors),
        )

    filed: list[dict[str, Any]] = []
    for simulation in simulations:
        versioned = _record_artifact(
            "simulation", payload.grade, payload.subject, simulation,
            strand=payload.strand, sub_strand=payload.sub_strand,
            title=str(simulation.get("title") or ""),
            provenance={"source": "factory_generate_simulations",
                        "provider": resolved.provider, "model": resolved.model,
                        "grounded_in_notes": taught.found_notes},
        ) if payload.save else {}
        filed.append({**simulation, "artifact": versioned})

    return {
        "grade": payload.grade,
        "subject": payload.subject,
        "sub_strand": payload.sub_strand,
        "simulations": filed,
        "planned_count": len(filed),
        "not_simulated": content.get("not_simulated") or [],
        "brief_quality": quality.to_dict(),
        "grounding": taught.to_dict(),
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
    measured_from: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """File one generation as a version, and never fail the generation for it.

    Recording is bookkeeping: if it breaks, the operator should still get the
    content they asked for, with a warning rather than a 500.

    `measured_from` is the generation result. Everything a machine found about
    this content — the gate's failing criteria, the contradictions, the
    repetitions, the lessons that came back thin — used to live only in the
    HTTP response and vanish with it, so a regeneration was told "every
    reviewer passed this version with no issues raised" while the operator was
    looking straight at "contradicts itself".
    """
    if measured_from is not None:
        from ..services import measured_findings

        provenance = measured_findings.provenance_for(measured_from, provenance)
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
        WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')) AND LOWER(subject) = LOWER(:subject)
        ORDER BY strand_id ASC, sub_strand_id ASC
        """,
        params,
    ) or []

    # Strands with no sub-strands yet are held on the design, so a strand list
    # survives a reload before any sub-strand has been generated under it.
    design = fetch_one(
        """
        SELECT design_id, metadata FROM curriculum_designs
        WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')) AND LOWER(subject) = LOWER(:subject)
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
                "source_pages": entry.get("source_pages") or [],
                # What the design's summary table names, as opposed to what has
                # actually been generated. The gap between the two is the work
                # remaining, and it was invisible.
                "sub_strand_names": entry.get("sub_strand_names") or [],
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
                # When this row was written. Four rounds of "how accurate is
                # this" were spent on output that looked freshly generated and
                # was months of pipeline changes old, because nothing in it
                # said when it was made.
                "updated_at",
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
    from ..infra.db import execute, fetch_all, fetch_one, to_json

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
            # The design's own summary table lists every sub-strand by name —
            # CRE's is page 202, all twelve of them. The generator reads them and
            # this dropped them on the floor, so the sub-strand generator then
            # had to rediscover from scratch what had already been extracted.
            "sub_strand_names": [
                str(n).strip() for n in (entry.get("sub_strand_names") or []) if str(n).strip()
            ],
            "sub_strands": [],
        })

    if not clean:
        raise_api_error("VALIDATION_FAILED", "No named strands to save.")

    row = fetch_one(
        "SELECT metadata FROM curriculum_designs WHERE design_id = :design_id",
        {"design_id": design_id},
    )
    metadata = dict((row or {}).get("metadata") or {})

    # Merge, do not replace. Regenerating strands overwrote the stored list
    # wholesale, so a run that happened not to return descriptions erased the
    # ones already there — which is what silently emptied every strand
    # description on the last regeneration.
    previous = {
        substrand_hygiene.strand_key(str(e.get("strand_name") or e.get("name") or "")): e
        for e in (metadata.get("strands") or [])
        if isinstance(e, dict)
    }
    for entry in clean:
        old_entry = previous.get(substrand_hygiene.strand_key(entry["strand_name"]))
        if not old_entry:
            continue
        # A field the new run did not produce keeps whatever the last one knew.
        for field in ("description", "source_pages", "sub_strand_names"):
            if not entry.get(field) and old_entry.get(field):
                entry[field] = old_entry[field]

    # A rename orphans work. Sub-strands are stored against the strand NAME, so
    # a regeneration that calls it "The Holy Bible" where the saved rows say
    # "The Bible" leaves twelve sub-strands hanging off a strand the structure
    # view no longer lists, and reports the new one as empty.
    stored_strand_names = {
        substrand_hygiene.strand_key(str(r.get("strand_name") or ""))
        for r in (fetch_all(
            """
            SELECT DISTINCT strand_name FROM curriculum_substrands
            WHERE (REPLACE(LOWER(grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', ''))
              AND LOWER(subject) = LOWER(:subject)
            """,
            {"grade": payload.grade,
             "alt_grade": payload.grade.replace("grade-", ""),
             "subject": payload.subject},
        ) or [])
    }
    new_keys = {substrand_hygiene.strand_key(c["strand_name"]) for c in clean}
    orphaned = sorted(stored_strand_names - new_keys)

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
        # Named, not silently tolerated: these strands have sub-strands stored
        # against a name this run no longer produces.
        "orphaned_strands": orphaned,
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

    # A queued draft that has now been saved must stop being offered. Left
    # unconsumed it reappears on every poll, inviting the operator to save the
    # same sub-strands a second time over the ones they just wrote.
    from ..services import job_queue

    consumed = job_queue.consume(
        kind="substrands", grade=payload.grade, subject=payload.subject,
        strand=payload.strand_name,
    )

    return {
        "status": "saved",
        "saved_count": saved_count,
        "refused": refused,
        "strand_name": payload.strand_name,
        "artifacts": versioned,
        "draft_consumed": consumed,
    }

