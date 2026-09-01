"""The pipeline board: grades as projects, subjects as branches, stages as steps.

Everything needed to answer "where is this grade?" existed and was spread
across five screens. This is one place to look, and one place to change what a
stage has to pass before its output moves on.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
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


# What each stage files, so a stage-level action knows what to act on. The
# board's copy is the only copy: two of these drift the first time a station is
# added, and the half that is missed silently refuses every action on it.
STAGE_KIND = pipeline_board.STAGE_KIND


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


@router.get("/{grade}/requirements")
def stage_requirements(
    grade: str,
    subject: str = Query(..., min_length=1),
    station: str = Query("", description="Only what this station owes"),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """What the lesson plans ask for, per lesson, in their own words.

    The plan already names its assets — "visual aids for gestures", "observe
    pictures of Adam and Eve". Nothing was reading them: each asset station was
    given the sub-strand's title and outcomes and asked to plan from scratch,
    so an asset the plan asked for was never guaranteed to exist and one it
    never mentioned could be produced and approved.
    """
    from ..services import artifact_registry, asset_requirements

    plans = artifact_registry.search(grade, subject, "notes", limit=200)
    wanted = asset_requirements.Requirements()
    for row in plans:
        try:
            plan = artifact_registry.get(str(row["artifact_id"])).content or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read plan %s: %s", row.get("artifact_id"), exc)
            continue
        found = asset_requirements.read(plan)
        for item in found.items:
            item.module_title = f"{row.get('sub_strand_name') or ''} — {item.module_title}".strip(" —")
            wanted.items.append(item)

    if station:
        wanted.items = [i for i in wanted.items if i.station == station]
    return {"grade": grade, "subject": subject, "station": station,
            "plans_read": len(plans), **wanted.to_dict()}


@router.get("/fragments")
def list_fragments(
    subject: str = Query("", description="Only what applies to this subject"),
    grade: str = Query(""),
    station: str = Query(""),
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict[str, Any]:
    """The domain prompts, and where each one applies.

    Education is wide. A prompt that must serve every subject is a prompt
    nobody improves: change the paragraph about balancing equations and you
    have edited the prompt that writes a PP1 singing lesson, so the person who
    knows chemistry will not touch it — and it stays wrong.

    Each of these is separate, small, and its own Langfuse prompt.
    """
    from ..services import prompt_fragments

    catalogue = prompt_fragments.catalogue()
    if subject or grade or station:
        applies = {f.name for f in prompt_fragments.for_context(subject, station, grade)}
        for entry in catalogue:
            entry["applies_here"] = entry["name"] in applies
    return {"fragments": catalogue,
            "filtered_for": {"subject": subject, "grade": grade, "station": station}}


class FragmentEditRequest(BaseModel):
    """A fragment improved in the console."""

    body: str


@router.put("/fragments/{name}")
def edit_fragment(
    name: str,
    payload: FragmentEditRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Improve one domain prompt, without touching any of the others.

    Written to Langfuse under the fragment's own name, so it can be edited
    there too and so the change is versioned where every other prompt change
    is. The built-in text stays in the code as the default, which is what makes
    a fresh deployment work with no prompt store at all.
    """
    from ..services import prompt_fragments
    from ..services.prompt_sync import push_one

    fragment = next((f for f in prompt_fragments.FRAGMENTS if f.name == name), None)
    if fragment is None:
        raise_api_error(
            "VALIDATION_FAILED",
            f"There is no '{name}' fragment. The fragments are: "
            f"{', '.join(f.name for f in prompt_fragments.FRAGMENTS)}.",
        )
    if not payload.body.strip():
        raise_api_error(
            "VALIDATION_FAILED",
            "An empty fragment would silently remove this subject's domain "
            "rules from every station that uses it. To stop using it, narrow "
            "the subjects it applies to instead.",
        )

    try:
        push_one(fragment.langfuse_name, payload.body)
    except Exception as exc:  # noqa: BLE001
        raise_api_error(
            "MODEL_ENDPOINT_UNAVAILABLE",
            f"Could not save the fragment to Langfuse ({exc}). The built-in "
            f"text is still in use, so nothing has changed.",
        )
    logger.info("Fragment %s edited by %s.", name, getattr(auth, "subject", "?"))
    return {"fragment": fragment.to_dict(), "saved": True}


@router.get("/prompts/export")
def export_prompts(
    _: AuthContext = Depends(require_roles("admin", "operator", "developer")),
) -> Response:
    """Every prompt, as a folder of Markdown files.

    Prompts are the part of this system that most needs editing and is worst
    served by editing it one textarea at a time. The interesting work — making
    the chemistry fragment agree with the notation block, making every
    authoring prompt use the same register language — is work across the whole
    set at once, and a console that only ever shows one is a console in which
    that work does not get done.

    The text is what is CURRENTLY SERVING, not the built-in defaults. Exporting
    the defaults would hand back a bundle that silently reverts every edit
    already made in Langfuse the moment it is uploaded again.
    """
    from ..services import prompt_bundle

    files = prompt_bundle.collect()
    blob = prompt_bundle.write_zip(files)
    logger.info("Exported %d prompt(s) as a bundle.", len(files))
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"content-disposition": 'attachment; filename="cbc-prompts.zip"'},
    )


@router.post("/prompts/import")
async def import_prompts(
    file: UploadFile = File(..., description="The edited bundle, zipped"),
    confirm: str = Form("", description="The word APPLY, once the plan has been read"),
    allow_new: bool = Form(False),
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Bring an edited bundle back.

    Two steps, always: without `confirm` this reports what WOULD change and
    writes nothing. Prompts are the behaviour of every generator in the system,
    and an upload that turns out to have been the wrong folder is not something
    to discover from the output a week later.

    Three things it will not do, each learned from a way this kind of tool goes
    wrong:

    *   It never DELETES. A prompt missing from the bundle is reported and left
        exactly as it is, because half a bundle is a normal accident and a
        wiped prompt store is not a recoverable one.
    *   It never PROMOTES a prompt that fails validation. An edit that renamed
        {{ level_register }} still looks fine and fails days later as output
        that quietly lost its register — so the text is saved, and production
        keeps serving the version that works.
    *   It never invents a prompt from a name it does not recognise unless
        asked, because that is nearly always a typo in a folder name, and
        accepting it creates an orphan while the real prompt serves old text.
    """
    from ..services import prompt_bundle

    blob = await file.read()
    try:
        incoming = prompt_bundle.read_zip(blob)
    except ValueError as exc:
        raise_api_error("VALIDATION_FAILED", str(exc))

    result = prompt_bundle.apply_bundle(
        incoming, allow_new=allow_new, confirm=confirm.strip().upper()
    )
    logger.info(
        "Prompt bundle from %s: %s",
        getattr(auth, "subject", "?"),
        "applied" if result.get("applied") else "planned only",
    )
    return result


class ResetStageRequest(BaseModel):
    """Throw away one stage's output, or a grade's, so it can be built again."""

    grade: str
    stage: str = ""
    subject: str = ""
    # The exact word, because a boolean is too easy to send by accident from a
    # form or a retried request.
    confirm: str = ""


@router.post("/reset")
def reset(
    payload: ResetStageRequest,
    auth: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict[str, Any]:
    """Reset one stage, or everything a grade has produced.

    A stage-level reset because that is the unit an operator works in. Clearing
    a whole grade to re-run the diagrams costs the lesson plans that were fine,
    and clearing nothing means living with the first attempt.

    Without a stage this clears the grade — every stage, every subject unless
    one is named — through the same path the factory reset uses, so a grade
    cleared here is cleared the same way and leaves nothing behind.
    """
    from ..routes import curriculum as curriculum_routes
    from ..services import factory_reset, pipeline_board

    if payload.stage:
        result = pipeline_board.reset_stage(
            payload.grade, payload.subject, payload.stage,
            confirm=payload.confirm)
        if not result.get("supported"):
            raise_api_error("VALIDATION_FAILED", result["reason"])
        return result

    # No stage named: the whole grade. Routed through the factory reset rather
    # than reimplemented, because that one knows about the tables a stage reset
    # has no business in — designs, sub-strands, ingest status.
    report = curriculum_routes.factory_reset(
        curriculum_routes.FactoryResetRequest(
            grade=payload.grade, subject=payload.subject,
            confirm=(factory_reset.CONFIRMATION
                     if payload.confirm.strip().upper() == "DELETE"
                     else payload.confirm),
        ),
        auth,
    )
    return {"stage": "", "supported": True, **report}


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
