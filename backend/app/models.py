from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .config import ALLOWED_PROVIDERS, ALLOWED_STAGES


class Actor(BaseModel):
    type: Literal["system", "admin", "api"]
    id: str


class Curriculum(BaseModel):
    level: str
    grade: str
    subject: str
    subject_code: str
    pathway: str | None = None
    track: str | None = None
    strand: str
    sub_strand: str
    slo_id: str


class Controls(BaseModel):
    idempotency_key: str
    deadline_ms: int = Field(default=120000, ge=1000, le=300000)
    max_regen_attempts: int = Field(default=2, ge=0, le=5)
    environment: Literal["dev", "staging", "prod"] = "prod"


class GenerateRequest(BaseModel):
    request_id: str
    trace_id: str
    tenant_id: str
    actor: Actor
    curriculum: Curriculum
    controls: Controls


class ProviderConfigInput(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    ollama_models: list[str] = Field(default_factory=list)


class StageBindingInput(BaseModel):
    provider: str
    model: str
    base_url: str | None = None

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        if value not in ALLOWED_PROVIDERS:
            raise ValueError("unsupported provider")
        return value


class ProviderConfigView(BaseModel):
    provider: str
    base_url: str | None = None
    has_api_key: bool = False
    ollama_models: list[str] = Field(default_factory=list)


class StageBindingView(BaseModel):
    pipeline_stage: str
    provider: str
    model: str
    base_url: str | None = None


class AdminConfigView(BaseModel):
    providers: list[ProviderConfigView]
    stage_bindings: list[StageBindingView]


class ErrorItem(BaseModel):
    code: str
    message: str
    retryable: bool = False


class Provenance(BaseModel):
    langfuse_prompt_name: str
    langfuse_prompt_version: str
    langfuse_prompt_label: str
    prompt_hash_sha256: str
    model_provider: str
    model_name: str
    model_revision: str
    temperature: float
    top_p: float
    pipeline_stage: str
    resolved_model_provider: str
    resolved_model_name: str
    resolved_base_url: str
    credential_ref_id: str
    created_at: str


class GenerateResponse(BaseModel):
    request_id: str
    trace_id: str
    status: Literal["success", "failed", "partial"]
    agent: str
    latency_ms: int
    result: dict
    errors: list[ErrorItem]
    provenance: dict


class StageRunResult(BaseModel):
    pipeline_stage: str
    output: dict
    provenance: Provenance


class PipelineResult(BaseModel):
    run_id: str
    stage_runs: list[StageRunResult]
    published_bundle: dict


class StageBindingPath(BaseModel):
    stage: str

    @field_validator("stage")
    @classmethod
    def validate_stage(cls, value: str) -> str:
        if value not in ALLOWED_STAGES:
            raise ValueError("unsupported stage")
        return value


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
