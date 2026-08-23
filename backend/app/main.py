from __future__ import annotations

import logging
import time

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .config import OFFICIAL_BASE_URLS, Provider
from .errors import ApiError, raise_api_error
from .infra.db import run_migrations
from .infra.queue import job_queue
from .infra.storage import object_storage
from .models import (
    AdminConfigView,
    GenerateRequest,
    GenerateResponse,
    ProviderConfigInput,
    ProviderConfigView,
    StageBindingInput,
    StageBindingView,
)
from .routes.admin_langfuse import router as admin_langfuse_router
from .routes.auth import router as auth_router
from .routes.curriculum import router as curriculum_router
from .routes.questions import router as questions_router
from .routes.targets import router as targets_router
from .services.auth import AuthContext, authenticate_login, create_access_token, get_auth_context, require_roles
from .services.browser_agent import browse_page
from .services.metrics import metrics_service
from .services.pipeline import PipelineService
from .services.provider_router import ProviderRouter
from .services.validation import validate_grade_dataset
from .services.workflow import WorkflowService
from .state import StageBinding, runtime_state

app = FastAPI(title="CBC API Platform", version="2.1.0", description="Contract-First Educational Content Production System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Modular Feature Routers
app.include_router(auth_router)
app.include_router(admin_langfuse_router)
app.include_router(curriculum_router)
app.include_router(questions_router)
app.include_router(targets_router)

router = ProviderRouter(runtime_state)
pipeline_service = PipelineService(router)
workflow_service = WorkflowService(runtime_state)
logger = logging.getLogger("cbc-api")

STAGE_NAMES = {
    "notes_generation",
    "diagram_generation",
    "activity_generation",
    "question_generation",
    "reviewer_panel",
    "regeneration",
}


def _apply_bootstrap_bindings(provider: str, model: str, base_url: str | None) -> dict:
    if provider not in runtime_state.provider_credentials:
        raise_api_error("UNSUPPORTED_MODEL_PROVIDER", f"Unsupported provider: {provider}")

    updated = []
    for stage in sorted(STAGE_NAMES):
        runtime_state.stage_bindings[stage] = StageBinding(
            pipeline_stage=stage,
            provider=provider,
            model=model,
            base_url=base_url,
        )
        runtime_state.persist_stage_binding(stage)
        updated.append(stage)

    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "stages_updated": updated,
    }


class BrowseRequest(BaseModel):
    url: str


class BulkStageBindingRequest(BaseModel):
    provider: str
    model: str
    base_url: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class ReviewDecisionRequest(BaseModel):
    decision: str


class HumanReviewDecisionRequest(BaseModel):
    decision: str


def _bootstrap_default_stage_bindings() -> None:
    if runtime_state.stage_bindings:
        return

    provider = Provider.OPENAI.value
    model = "gpt-4o-mini"

    for stage in STAGE_NAMES:
        runtime_state.stage_bindings[stage] = StageBinding(
            pipeline_stage=stage,
            provider=provider,
            model=model,
            base_url=None,
        )


@app.on_event("startup")
def startup() -> None:
    try:
        run_migrations()
        runtime_state.sync_users_from_env()
        runtime_state.load_from_db()
    except Exception as exc:
        logger.error("Database initialization warning during startup: %s", exc)

    try:
        object_storage.ensure_bucket()
    except Exception as exc:  # noqa: BLE001
        logger.warning("MinIO bootstrap skipped at startup: %s", exc)

    try:
        _bootstrap_default_stage_bindings()
        for provider in runtime_state.provider_credentials:
            runtime_state.persist_provider(provider)
        for stage in runtime_state.stage_bindings:
            runtime_state.persist_stage_binding(stage)
    except Exception as exc:
        logger.warning("Default bindings initialization warning: %s", exc)


@app.exception_handler(ApiError)
async def api_error_handler(_, exc: ApiError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "failed",
            "errors": [
                {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                }
            ],
        },
    )


@app.get("/health")
def health() -> dict:
    redis_ok = False
    minio_ok = False

    try:
        redis_ok = job_queue.ping()
    except Exception:  # noqa: BLE001
        redis_ok = False

    try:
        object_storage.ensure_bucket()
        minio_ok = True
    except Exception:  # noqa: BLE001
        minio_ok = False

    return {
        "status": "ok" if redis_ok and minio_ok else "degraded",
        "checks": {
            "redis": redis_ok,
            "minio": minio_ok,
        },
    }


@app.get("/api/v1/metrics")
def get_metrics(_: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer"))) -> dict:
    return metrics_service.get_system_metrics()


# Direct /auth/login backward compatibility
@app.post("/auth/login")
def login(payload: LoginRequest) -> dict:
    context = authenticate_login(payload.username, payload.password)
    token = create_access_token(context.subject, context.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": context.role,
        "subject": context.subject,
    }


@app.get("/auth/me")
def me(context: AuthContext = Depends(get_auth_context)) -> dict:
    return {
        "subject": context.subject,
        "role": context.role,
        "auth_type": context.auth_type,
    }


@app.put("/admin/providers/{provider}/config")
def configure_provider(
    provider: str,
    payload: ProviderConfigInput,
    _: AuthContext = Depends(require_roles("admin")),
) -> dict:
    if provider not in runtime_state.provider_credentials:
        raise_api_error("UNSUPPORTED_MODEL_PROVIDER", f"Unsupported provider: {provider}")

    conf = runtime_state.provider_credentials[provider]

    if provider in {Provider.OPENAI.value, Provider.ANTHROPIC.value, Provider.GEMINI.value}:
        conf.base_url = payload.base_url or OFFICIAL_BASE_URLS[Provider(provider)]
    else:
        conf.base_url = payload.base_url or conf.base_url or "http://localhost:11434"
        conf.ollama_models = payload.ollama_models

    if payload.api_key:
        credential_ref_id = runtime_state.save_api_key(provider, payload.api_key)
    else:
        credential_ref_id = conf.credential_ref_id

    runtime_state.persist_provider(provider)

    return {
        "provider": provider,
        "base_url": conf.base_url,
        "has_api_key": bool(conf.encrypted_api_key),
        "credential_ref_id": credential_ref_id,
        "ollama_models": conf.ollama_models,
    }


@app.post("/admin/pipeline-bindings/{stage}")
def set_stage_binding(
    stage: str,
    payload: StageBindingInput,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict:
    if stage == "bootstrap":
        return _apply_bootstrap_bindings(payload.provider, payload.model, payload.base_url)

    if stage not in STAGE_NAMES:
        raise_api_error("MODEL_NOT_CONFIGURED_FOR_STAGE", f"Unsupported stage: {stage}")

    runtime_state.stage_bindings[stage] = StageBinding(
        pipeline_stage=stage,
        provider=payload.provider,
        model=payload.model,
        base_url=payload.base_url,
    )
    runtime_state.persist_stage_binding(stage)

    return {
        "pipeline_stage": stage,
        "provider": payload.provider,
        "model": payload.model,
        "base_url": payload.base_url,
    }


@app.post("/admin/pipeline-bindings/bootstrap")
def bootstrap_stage_bindings(
    payload: BulkStageBindingRequest,
    _: AuthContext = Depends(require_roles("admin", "operator")),
) -> dict:
    return _apply_bootstrap_bindings(payload.provider, payload.model, payload.base_url)


@app.get("/admin/config")
def get_admin_config(_: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer"))) -> AdminConfigView:
    provider_views = []
    for provider, conf in runtime_state.provider_credentials.items():
        provider_views.append(
            ProviderConfigView(
                provider=provider,
                base_url=conf.base_url,
                has_api_key=bool(conf.encrypted_api_key),
                ollama_models=conf.ollama_models,
            )
        )

    binding_views = []
    for stage, binding in runtime_state.stage_bindings.items():
        binding_views.append(
            StageBindingView(
                pipeline_stage=stage,
                provider=binding.provider,
                model=binding.model,
                base_url=binding.base_url,
            )
        )

    return AdminConfigView(providers=provider_views, stage_bindings=binding_views)


@app.post("/pipeline/enqueue")
def enqueue_generate(payload: GenerateRequest, _: AuthContext = Depends(require_roles("admin", "operator"))) -> dict:
    validate_grade_dataset(payload.curriculum.grade)
    job_id = job_queue.enqueue_generation(payload)
    return {
        "job_id": job_id,
        "status": "queued",
        "request_id": payload.request_id,
        "trace_id": payload.trace_id,
    }


@app.get("/pipeline/jobs/{job_id}")
def get_job(job_id: str, _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer"))) -> dict:
    return job_queue.get_job(job_id)


@app.get("/pipeline/runs")
def list_runs(_: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer"))) -> dict:
    items = []
    for run_id, entry in runtime_state.run_registry.items():
        items.append(
            {
                "run_id": run_id,
                "request_id": entry.get("request_id"),
                "trace_id": entry.get("trace_id"),
                "workflow_state": entry.get("workflow_state"),
                "updated_at": entry.get("updated_at"),
            }
        )

    items.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    return {"items": items}


@app.post("/pipeline/generate")
def generate(payload: GenerateRequest, _: AuthContext = Depends(require_roles("admin", "operator"))) -> GenerateResponse:
    start = time.time()
    validate_grade_dataset(payload.curriculum.grade)

    result = pipeline_service.run(payload)
    runtime_state.save_pipeline_run(result.run_id, payload.model_dump(), result.model_dump())
    latency_ms = int((time.time() - start) * 1000)

    aggregate_provenance = {
        "pipeline_stage_count": len(result.stage_runs),
        "stage_provenance": [stage.provenance.model_dump() for stage in result.stage_runs],
        "cost_summary": result.cost_summary,
    }

    return GenerateResponse(
        request_id=payload.request_id,
        trace_id=payload.trace_id,
        status="success",
        agent="GenerationPipeline",
        latency_ms=latency_ms,
        result=result.model_dump(),
        errors=[],
        provenance=aggregate_provenance,
    )


@app.post("/agents/browse")
async def browse(payload: BrowseRequest, _: AuthContext = Depends(require_roles("admin", "operator", "developer"))) -> dict:
    return await browse_page(payload.url)


@app.get("/review/queue")
def review_queue(_: AuthContext = Depends(require_roles("admin", "reviewer"))) -> dict:
    return {"items": workflow_service.review_queue()}


@app.post("/review/{run_id}/decision")
def review_decision(
    run_id: str,
    payload: ReviewDecisionRequest,
    _: AuthContext = Depends(require_roles("admin", "reviewer")),
) -> dict:
    result = workflow_service.review_decision(run_id, payload.decision)
    return {"run_id": result.run_id, "state": result.state, "updated_at": result.updated_at}


@app.get("/human-review/queue")
def human_review_queue(_: AuthContext = Depends(require_roles("admin", "reviewer"))) -> dict:
    return {"items": workflow_service.human_review_queue()}


@app.post("/human-review/{run_id}/decision")
def human_review_decision(
    run_id: str,
    payload: HumanReviewDecisionRequest,
    _: AuthContext = Depends(require_roles("admin", "reviewer")),
) -> dict:
    result = workflow_service.human_review_decision(run_id, payload.decision)
    return {"run_id": result.run_id, "state": result.state, "updated_at": result.updated_at}


@app.get("/production/ready")
def production_ready(_: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer"))) -> dict:
    return {"items": workflow_service.production_ready()}


@app.get("/api/v1/bundles")
def list_bundles(
    status: str | None = None,
    limit: int = 50,
    _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer")),
) -> dict:
    from .infra.db import fetch_all

    cond = ["1=1"]
    params: dict[str, Any] = {"limit": limit}
    if status:
        cond.append("status = :status")
        params["status"] = status

    rows = fetch_all(
        f"SELECT * FROM substrand_resources WHERE {' AND '.join(cond)} ORDER BY updated_at DESC LIMIT :limit",
        params,
    )
    return {"bundles": rows, "count": len(rows)}


@app.post("/api/v1/bundles/{bundle_id}/human-decision")
def bundle_human_decision(
    bundle_id: str,
    payload: dict[str, Any],
    auth_ctx: AuthContext = Depends(require_roles("admin", "reviewer")),
) -> dict:
    from .infra.db import execute

    decision = payload.get("decision", "approve")  # 'approve' -> 'published', 'reject' -> 'rejected', 'revision' -> 'needs_safety_revision'
    notes = payload.get("notes", "")

    new_status = "published" if decision == "approve" else ("needs_safety_revision" if decision == "revision" else "rejected")

    execute(
        """
        UPDATE substrand_resources
        SET status = :status,
            review_audit = jsonb_set(
                COALESCE(review_audit, '{}'::jsonb),
                '{human_approval}',
                CAST(:audit AS jsonb)
            ),
            updated_at = NOW()
        WHERE bundle_id = :bid
        """,
        {
            "status": new_status,
            "audit": to_json({
                "decision": decision,
                "reviewed_by": auth_ctx.actor_id,
                "notes": notes,
                "timestamp": now_iso(),
            }),
            "bid": bundle_id,
        },
    )
    return {"bundle_id": bundle_id, "status": new_status, "decision": decision}


# ── Cost Analytics Endpoints ─────────────────────────────────────────────────

@app.get("/api/v1/costs/summary")
def get_cost_summary(_: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer"))) -> dict:
    from .infra.db import fetch_all, fetch_one

    totals = fetch_one(
        """
        SELECT
            COALESCE(SUM(total_tokens), 0) as total_tokens,
            COALESCE(SUM(total_cost_usd), 0) as total_cost_usd,
            COUNT(DISTINCT run_id) as total_runs
        FROM generation_costs
        """
    ) or {}

    by_provider = fetch_all(
        """
        SELECT provider, SUM(total_tokens) as tokens, SUM(total_cost_usd) as cost_usd, COUNT(*) as calls
        FROM generation_costs
        GROUP BY provider ORDER BY cost_usd DESC
        """
    ) or []

    by_stage = fetch_all(
        """
        SELECT pipeline_stage, AVG(total_tokens) as avg_tokens, SUM(total_cost_usd) as total_cost, COUNT(*) as calls
        FROM generation_costs
        GROUP BY pipeline_stage ORDER BY total_cost DESC
        """
    ) or []

    recent = fetch_all(
        """
        SELECT run_id, SUM(total_tokens) as tokens, SUM(total_cost_usd) as cost_usd
        FROM generation_costs
        GROUP BY run_id ORDER BY MAX(created_at) DESC LIMIT 20
        """
    ) or []

    total_runs = totals.get("total_runs", 0)
    total_cost = float(totals.get("total_cost_usd", 0))

    return {
        "total_tokens": totals.get("total_tokens", 0),
        "total_cost_usd": round(total_cost, 4),
        "total_runs": total_runs,
        "avg_cost_per_run": round(total_cost / total_runs, 6) if total_runs > 0 else 0.0,
        "by_provider": by_provider,
        "by_stage": by_stage,
        "recent_runs": recent,
    }


@app.get("/api/v1/costs/run/{run_id}")
def get_run_costs(run_id: str, _: AuthContext = Depends(require_roles("admin", "operator", "reviewer", "developer"))) -> dict:
    from .infra.db import fetch_all

    stages = fetch_all(
        """
        SELECT pipeline_stage, provider, model, prompt_tokens, completion_tokens,
               total_tokens, input_cost_usd, output_cost_usd, total_cost_usd, created_at
        FROM generation_costs
        WHERE run_id = :run_id ORDER BY created_at ASC
        """,
        {"run_id": run_id},
    ) or []

    total_tokens = sum(s.get("total_tokens", 0) for s in stages)
    total_cost = sum(float(s.get("total_cost_usd", 0)) for s in stages)

    return {
        "run_id": run_id,
        "stages": stages,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 6),
    }
