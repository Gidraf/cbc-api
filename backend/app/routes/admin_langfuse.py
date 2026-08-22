from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..services.auth import AuthContext, require_roles
from ..services.langfuse_context import langfuse_context_service
from ..services.validation import validate_grade_dataset

router = APIRouter(prefix="/api/v1/admin/langfuse", tags=["Admin Langfuse Datasets"])


class UploadContextRequest(BaseModel):
    subject: str
    subject_code: str = ""
    essence_statement: str = ""
    strands: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}


class PreviewContextRequest(BaseModel):
    grade: str
    subject: str
    agent_name: str = "note-generator"
    template_vars: dict[str, Any] = {}


@router.get("/datasets")
def list_datasets(_: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer"))) -> dict[str, Any]:
    datasets = langfuse_context_service.list_datasets()
    return {"datasets": datasets}


@router.get("/datasets/{grade}")
def get_grade_dataset(
    grade: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    grade_slug = validate_grade_dataset(grade)
    items = langfuse_context_service.get_grade_dataset(grade_slug)
    return {"grade": grade_slug, "items": items}


@router.get("/datasets/{grade}/{subject}")
def get_subject_context(
    grade: str,
    subject: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    grade_slug = validate_grade_dataset(grade)
    context = langfuse_context_service.get_subject_context(grade_slug, subject)
    return {"grade": grade_slug, "subject": subject, "context": context}


@router.post("/datasets/{grade}")
def upload_subject_context(
    grade: str,
    payload: UploadContextRequest,
    _: AuthContext = Depends(require_roles("admin")),
) -> dict[str, Any]:
    grade_slug = validate_grade_dataset(grade)
    result = langfuse_context_service.upload_dataset_item(grade_slug, payload.model_dump())
    return result


@router.get("/context/master-preview")
def preview_master_context(
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    master = langfuse_context_service.get_master_context()
    return {"master_context": master}


@router.post("/context/preview")
def preview_assembled_context(
    payload: PreviewContextRequest,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    grade_slug = validate_grade_dataset(payload.grade)
    compiled = langfuse_context_service.assemble_agent_context(
        agent_name=payload.agent_name,
        grade_slug=grade_slug,
        subject=payload.subject,
        template_vars=payload.template_vars,
    )
    return {
        "prompt_name": compiled.prompt_name,
        "prompt_version": compiled.prompt_version,
        "prompt_label": compiled.prompt_label,
        "prompt_hash": compiled.prompt_hash,
        "messages": compiled.messages,
    }
