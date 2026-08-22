from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..services.auth import AuthContext, require_roles
from ..services.targets import target_service

router = APIRouter(prefix="/api/v1/targets", tags=["Daily Generation Targets"])


class ConfigureTargetRequest(BaseModel):
    target_date: str = Field(default_factory=lambda: str(date.today()))
    target_count: int = Field(default=100, ge=1, le=10000)
    grade_breakdown: dict[str, int] = Field(default_factory=dict)


@router.get("/today")
def get_today_target(_: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer"))) -> dict[str, Any]:
    today = date.today()
    return target_service.get_or_create_daily_target(today)


@router.get("/{target_date}")
def get_target_by_date(
    target_date: str,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    try:
        tdate = date.fromisoformat(target_date)
    except ValueError:
        tdate = date.today()
    return target_service.get_or_create_daily_target(tdate)


@router.post("/configure")
def configure_target(
    payload: ConfigureTargetRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    try:
        tdate = date.fromisoformat(payload.target_date)
    except ValueError:
        tdate = date.today()

    return target_service.configure_target(
        target_date=tdate,
        target_count=payload.target_count,
        grade_breakdown=payload.grade_breakdown,
    )
