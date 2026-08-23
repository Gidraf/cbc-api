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
