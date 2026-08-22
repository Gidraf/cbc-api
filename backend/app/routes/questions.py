from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..errors import raise_api_error
from ..services.auth import AuthContext, require_roles
from ..services.question_dna import question_dna_service

router = APIRouter(prefix="/api/v1/questions", tags=["Question Bank & DNA"])


class QuestionActionRequest(BaseModel):
    action: Literal["re-create", "regenerate", "re-review"]


@router.get("")
def list_questions(
    grade: str | None = Query(default=None),
    subject: str | None = Query(default=None),
    strand: str | None = Query(default=None),
    question_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
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


@router.get("/{question_id}/dna")
def get_question_dna(
    question_id: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    return question_dna_service.get_question(question_id)


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
