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
from .services.auth import AuthContext, authenticate_login, create_access_token, get_auth_context, require_roles
from .services.browser_agent import browse_page
from .services.pipeline import PipelineService
from .services.provider_router import ProviderRouter
from .services.validation import validate_grade_dataset
from .services.workflow import WorkflowService
from .state import StageBinding, runtime_state

app = FastAPI(title="CBC API Runtime", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
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

    if runtime_state.decrypt_api_key(Provider.GEMINI.value):
        provider = Provider.GEMINI.value
        model = "gemini-2.5-flash"
    else:
        provider = Provider.OLLAMA.value
        model = "llama3.1"

    for stage in STAGE_NAMES:
        runtime_state.stage_bindings[stage] = StageBinding(
            pipeline_stage=stage,
            provider=provider,
            model=model,
            base_url=None,
        )


@app.on_event("startup")
def startup() -> None:
    run_migrations()
    runtime_state.sync_users_from_env()
    runtime_state.load_from_db()
    try:
        object_storage.ensure_bucket()
    except Exception as exc:  # noqa: BLE001
        # Keep API booting in degraded mode when external MinIO is temporarily unavailable.
        logger.warning("MinIO bootstrap skipped at startup: %s", exc)
    _bootstrap_default_stage_bindings()
    for provider in runtime_state.provider_credentials:
        runtime_state.persist_provider(provider)
    for stage in runtime_state.stage_bindings:
        runtime_state.persist_stage_binding(stage)


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
    if payload.provider not in runtime_state.provider_credentials:
        raise_api_error("UNSUPPORTED_MODEL_PROVIDER", f"Unsupported provider: {payload.provider}")

    updated = []
    for stage in sorted(STAGE_NAMES):
        runtime_state.stage_bindings[stage] = StageBinding(
            pipeline_stage=stage,
            provider=payload.provider,
            model=payload.model,
            base_url=payload.base_url,
        )
        runtime_state.persist_stage_binding(stage)
        updated.append(stage)

    return {
        "provider": payload.provider,
        "model": payload.model,
        "base_url": payload.base_url,
        "stages_updated": updated,
    }


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
    _dataset_slug = validate_grade_dataset(payload.curriculum.grade)
    _ = _dataset_slug
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


@app.post("/pipeline/generate")
def generate(payload: GenerateRequest, _: AuthContext = Depends(require_roles("admin", "operator"))) -> GenerateResponse:
    start = time.time()
    _dataset_slug = validate_grade_dataset(payload.curriculum.grade)

    result = pipeline_service.run(payload)
    runtime_state.save_pipeline_run(result.run_id, payload.model_dump(), result.model_dump())
    latency_ms = int((time.time() - start) * 1000)

    aggregate_provenance = {
        "pipeline_stage_count": len(result.stage_runs),
        "stage_provenance": [stage.provenance.model_dump() for stage in result.stage_runs],
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
