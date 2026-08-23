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


@router.get("/designs")
def list_curriculum_designs(
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    designs = fetch_all(
        """
        SELECT cd.design_id, cd.subject, cd.subject_code, cd.grade, cd.level,
               cd.essence_statement, cd.general_learning_outcomes, cd.metadata,
               cd.created_at, cd.updated_at,
               COUNT(cs.id) as substrand_count
        FROM curriculum_designs cd
        LEFT JOIN curriculum_substrands cs ON cd.design_id = cs.design_id
        GROUP BY cd.design_id
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
