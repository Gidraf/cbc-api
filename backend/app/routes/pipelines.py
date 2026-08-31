"""The pipeline board: grades as projects, subjects as branches, stages as steps.

Everything needed to answer "where is this grade?" existed and was spread
across five screens. This is one place to look, and one place to change what a
stage has to pass before its output moves on.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..services import pipeline_board, stage_policy
from ..services.auth import AuthContext, require_roles

logger = logging.getLogger("cbc-pipelines-api")

router = APIRouter(prefix="/api/v1/pipelines", tags=["pipelines"])


@router.get("")
def list_projects(
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """Every grade that has anything in it, and its state at a glance."""
    return {"projects": pipeline_board.projects(),
            "stages": [p.to_dict() for p in stage_policy.all_policies()]}


@router.get("/policies")
def list_policies(
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """What each stage has to pass, and why that is the default."""
    return {"policies": [p.to_dict() for p in stage_policy.all_policies()],
            "stages": list(stage_policy.STAGES)}


class PolicyRequest(BaseModel):
    """One stage's gate. Anything left out keeps its current value."""

    required_layers: list[int] | None = None
    min_vendors: int | None = None
    overall_target: int | None = None
    dimension_target: int | None = None
    requires_human: bool | None = None
    blocks_downstream: bool | None = None
    max_refine_cycles: int | None = None


@router.put("/policies/{stage}")
def set_policy(
    stage: str,
    payload: PolicyRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Change what one stage has to pass.

    Per stage on purpose. One rule for the whole pipeline meant an operator
    either ran a full two-vendor review chain on reading a strand list out of a
    table, or turned the gate off — and lost it for the lesson plan too.
    """
    changes = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not changes:
        return {"policy": stage_policy.for_stage(stage).to_dict(),
                "changed": False}
    updated = stage_policy.save(stage, changes,
                                updated_by=getattr(auth, "subject", ""))
    return {"policy": updated.to_dict(), "changed": True}


@router.delete("/policies/{stage}")
def reset_policy(
    stage: str,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Back to the default, so a stage can be un-fiddled with."""
    return {"policy": stage_policy.reset(stage).to_dict(), "changed": True}


@router.get("/{grade}")
def read_project(
    grade: str,
    subject: str = Query("", description="One branch, rather than all of them"),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """One grade, stage by stage, subject by subject."""
    if subject:
        return {"grade": grade,
                "subjects": [pipeline_board.branch(grade, subject).to_dict()]}
    return pipeline_board.project(grade).to_dict()
