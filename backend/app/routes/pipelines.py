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

from ..errors import raise_api_error
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


class RunRequest(BaseModel):
    """Start one stage, for a whole grade or one subject of it."""

    grade: str
    stage: str
    subject: str = ""
    # Sub-strands to run it for. Empty means every one the design funds, which
    # is the case the board exists for.
    sub_strands: list[str] = []
    custom_instructions: str = ""


@router.post("/run")
def run_stage(
    payload: RunRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Queue one stage from the board, and hand back what to watch.

    Starting work meant leaving the board, finding the factory, choosing the
    same grade and subject again, and pressing a station — and then coming back
    to find out whether it had worked. The board knows what is missing; it
    should be able to ask for it.
    """
    from ..routes import curriculum as curriculum_routes

    if payload.stage not in stage_policy.STAGES:
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{payload.stage}' is not a pipeline stage. The stages are: "
            f"{', '.join(stage_policy.STAGES)}.",
        )

    queued = curriculum_routes.factory_queue_work(
        curriculum_routes.QueueWorkRequest(
            grade=payload.grade,
            subject=payload.subject,
            kinds=[payload.stage],
            sub_strands=payload.sub_strands,
            custom_instructions=payload.custom_instructions,
        ),
        auth,
    )
    logger.info("Board queued %s for %s/%s: %s job(s).",
                payload.stage, payload.grade, payload.subject or "every subject",
                (queued or {}).get("queued"))
    return {**queued, "stage": payload.stage,
            "grade": payload.grade, "subject": payload.subject}


# What each stage files, so a stage-level action knows what to act on.
STAGE_KIND: dict[str, str] = {
    "notes": "notes", "material": "material", "diagram": "diagram",
    "media": "photo_prompt", "simulation": "simulation",
    "activity": "activity", "questions": "question",
}


class StageActionRequest(BaseModel):
    """One action, on one stage, for a grade or one subject of it."""

    grade: str
    stage: str
    subject: str = ""
    # run — generate it. review — send every version for a layer-2 read.
    # approval — run the approving layer's work. regenerate — write the next
    # version from what the reviews found.
    action: str = "run"
    layer: int = 2
    provider: str = ""
    model: str = ""
    custom_instructions: str = ""


@router.post("/act")
def act_on_stage(
    payload: StageActionRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Do the thing this stage needs next, without leaving the board.

    Every one of these already existed, on a different screen, asking for the
    same grade and subject again. The board is the screen that knows what a
    stage is short of; it should be the screen that asks for it.
    """
    from ..routes import curriculum as curriculum_routes

    if payload.stage not in stage_policy.STAGES:
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{payload.stage}' is not a pipeline stage. The stages are: "
            f"{', '.join(stage_policy.STAGES)}.",
        )

    kind = STAGE_KIND.get(payload.stage)
    if payload.action == "run":
        result = curriculum_routes.factory_queue_work(
            curriculum_routes.QueueWorkRequest(
                grade=payload.grade, subject=payload.subject,
                kinds=[payload.stage],
                custom_instructions=payload.custom_instructions,
            ),
            auth,
        )
    elif payload.action in ("review", "approval"):
        if not kind:
            raise_api_error(
                "VALIDATION_FAILED",
                f"{payload.stage} does not file versions, so there is nothing "
                f"to review. It is checked by what comes after it.",
            )
        result = curriculum_routes.factory_queue_review(
            curriculum_routes.QueueReviewRequest(
                grade=payload.grade, subject=payload.subject,
                kinds=[kind], work=payload.action, layer=payload.layer,
                provider=payload.provider, model=payload.model,
            ),
            auth,
        )
    elif payload.action == "regenerate":
        if not kind:
            raise_api_error(
                "VALIDATION_FAILED",
                f"{payload.stage} files no versions, so there is nothing to "
                f"regenerate from.",
            )
        result = curriculum_routes.factory_queue_regenerate(
            curriculum_routes.QueueRegenerateRequest(
                grade=payload.grade, subject=payload.subject),
            auth,
        )
    else:
        raise_api_error(
            "VALIDATION_FAILED",
            f"'{payload.action}' is not something a stage can be asked for. "
            f"Use run, review, approval or regenerate.",
        )

    logger.info("Board ran %s on %s for %s/%s.", payload.action, payload.stage,
                payload.grade, payload.subject or "every subject")
    return {**result, "stage": payload.stage, "action": payload.action}


@router.get("/{grade}/units")
def stage_units(
    grade: str,
    stage: str = Query(..., min_length=1),
    subject: str = Query(""),
    limit: int = Query(100, ge=1, le=500),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """The individual versions at this stage, and what each still needs.

    A stage that says "5 of 7 not reviewed" and cannot say WHICH five leaves a
    person to go and find them, which is the work the board was supposed to
    remove.
    """
    from ..infra.db import fetch_all
    from ..services import review_layers

    kind = STAGE_KIND.get(stage)
    if not kind:
        return {"grade": grade, "stage": stage, "kind": "", "units": [],
                "note": f"{stage} does not file versions of its own."}

    where = ["a.kind = :kind",
             "(LOWER(a.grade) = LOWER(:grade) OR LOWER(a.grade) = LOWER(:alt))"]
    params: dict[str, Any] = {
        "kind": kind, "grade": grade, "alt": grade.replace("grade-", ""),
        "limit": limit,
    }
    if subject:
        where.append("LOWER(a.subject) = LOWER(:subject)")
        params["subject"] = subject

    rows = fetch_all(
        f"""
        SELECT DISTINCT ON (a.artifact_key)
               a.artifact_id, a.artifact_key, a.version, a.status,
               a.subject, a.strand_name, a.sub_strand_name, a.created_at
        FROM artifacts a
        WHERE {' AND '.join(where)}
        ORDER BY a.artifact_key, a.version DESC
        LIMIT :limit
        """,
        params,
    ) or []

    units = []
    for row in rows:
        artifact_id = str(row["artifact_id"])
        try:
            approval = review_layers.approval_state(artifact_id)
            reviews = review_layers.reviews_for(artifact_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read the state of %s: %s", artifact_id, exc)
            approval, reviews = {}, []
        latest = reviews[0] if reviews else {}
        units.append({
            **{k: (str(v) if k == "created_at" else v) for k, v in row.items()},
            "layers_run": sorted({int(r["layer"]) for r in reviews}),
            "verdict": str(latest.get("verdict") or ""),
            "confidence": int(latest.get("overall_confidence") or 0),
            "can_approve": bool(approval.get("can_approve")),
            "requires_override": bool(approval.get("requires_override")),
            "blockers": approval.get("blockers") or [],
            "warnings": approval.get("warnings") or [],
        })
    return {"grade": grade, "stage": stage, "kind": kind, "subject": subject,
            "units": units}


class BulkApproveRequest(BaseModel):
    """Sign for several versions at once."""

    artifact_ids: list[str]
    # Coverage counts approved work as taught-ready, so this is a signature
    # under a claim about a grade — not a checkbox.
    reviewed_by_me: bool = False
    note: str = ""
    override_reason: str = ""


@router.post("/approve")
def approve_units(
    payload: BulkApproveRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Approve what is ready, and say precisely why the rest is not.

    Bulk, because approving a grade one artifact at a time across two screens
    is how approval gets skipped. Still a signature: the same gate runs per
    artifact, and a version that cannot be approved is REPORTED rather than
    quietly left out — a bulk action that silently does less than it says is
    worse than one that refuses.
    """
    from ..routes.artifacts import LabelRequest, apply_label

    if not payload.reviewed_by_me:
        raise_api_error(
            "VALIDATION_FAILED",
            "Approval needs a person to say they have read these versions. "
            "The review layers narrow what reaches you; they do not replace "
            "you, and coverage counts approved work as taught-ready.",
        )

    approved, refused = [], []
    for artifact_id in [a.strip() for a in payload.artifact_ids if a.strip()]:
        try:
            apply_label(
                artifact_id,
                LabelRequest(label="approved", reviewed_by_me=True,
                             note=payload.note,
                             override_reason=payload.override_reason),
                auth,
            )
            approved.append(artifact_id)
        except Exception as exc:  # noqa: BLE001
            refused.append({
                "artifact_id": artifact_id,
                "reason": str(getattr(exc, "message", None) or exc)[:300],
            })
    logger.info("Board approved %d version(s); %d refused.",
                len(approved), len(refused))
    return {"approved": approved, "refused": refused,
            "counts": {"approved": len(approved), "refused": len(refused)}}


@router.get("/{grade}/logs")
def stage_logs(
    grade: str,
    stage: str = Query(..., min_length=1),
    subject: str = Query(""),
    limit: int = Query(40, ge=1, le=200),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """What this stage's jobs did, newest first, with the step log each wrote.

    A stage that says "2 failed" and cannot say what failed is a red light with
    no wiring behind it. The worker already writes its steps to the job row as
    it works; this is that, per stage.
    """
    from ..infra.db import fetch_all

    where = ["(LOWER(grade) = LOWER(:grade) OR LOWER(grade) = LOWER(:alt))",
             "kind = :stage"]
    params: dict[str, Any] = {
        "grade": grade, "alt": grade.replace("grade-", ""),
        "stage": stage, "limit": limit,
    }
    if subject:
        where.append("LOWER(subject) = LOWER(:subject)")
        params["subject"] = subject

    rows = fetch_all(
        f"""
        SELECT job_id, kind, subject, strand, sub_strand, status, attempts,
               error, created_at, started_at, finished_at,
               llm_calls, total_tokens, cost_usd,
               result->'progress' AS progress
        FROM jobs
        WHERE {' AND '.join(where)}
        ORDER BY COALESCE(finished_at, started_at, created_at) DESC
        LIMIT :limit
        """,
        params,
    ) or []
    return {
        "grade": grade, "stage": stage, "subject": subject,
        "runs": [dict(r) for r in rows],
        "counts": {
            status: sum(1 for r in rows if r.get("status") == status)
            for status in ("queued", "running", "done", "failed", "cancelled")
        },
    }


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
