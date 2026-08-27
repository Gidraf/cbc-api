from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ApiError(Exception):
    code: str
    message: str
    status_code: int
    retryable: bool = False
    # Machine-readable specifics for errors where "what failed" is a list rather
    # than a sentence — which learning areas are missing, which pages were
    # rejected. A caller catching this should not have to parse the message.
    detail: dict | None = None


ERRORS = {
    # Authentication & Authorization
    "UNAUTHORIZED_ACCESS": (401, False),
    "FORBIDDEN": (403, False),
    # Datasets & Context
    "DATASET_ITEM_NOT_FOUND": (404, False),
    "INVALID_GRADE_DATASET": (400, False),
    "MISSING_CONTEXT_LAYER": (400, False),
    # Model & Routing
    "UNSUPPORTED_MODEL_PROVIDER": (400, False),
    "MODEL_NOT_CONFIGURED_FOR_STAGE": (400, False),
    "MODEL_CREDENTIAL_MISSING": (401, False),
    "MODEL_ENDPOINT_UNAVAILABLE": (503, True),
    "LLM_PROVIDER_TIMEOUT": (504, True),
    "LLM_PROVIDER_ERROR": (502, True),
    "LLM_CREDIT_EXHAUSTED": (402, False),
    "LLM_RATE_LIMITED": (429, True),
    "LLM_INVALID_MODEL": (400, False),
    "LLM_CONTENT_FILTER": (400, False),
    # Langfuse
    "LANGFUSE_UNAVAILABLE": (503, True),
    "PROMPT_NOT_FOUND": (404, False),
    "PROMPT_COMPILE_ERROR": (400, False),
    "LANGFUSE_DATASET_NOT_FOUND": (404, False),
    "LANGFUSE_CONTEXT_ASSEMBLY_FAILED": (500, False),
    # Assets & Storage
    "DIAGRAM_GENERATION_FAILED": (502, True),
    "STORAGE_UPLOAD_FAILED": (502, True),
    # Quality & Policy Gates
    "QUALITY_GATE_REJECTED": (422, False),
    "CRITICAL_RISK_FLAG": (422, False),
    "INSUFFICIENT_WRITTEN_RESPONSE_ITEMS": (422, False),
    "SCHEMA_VALIDATION_FAILED": (422, False),
    "REGENERATION_LIMIT_EXCEEDED": (422, False),
    # A diagram with no part safe to blank cannot carry an occlusion question.
    # That is a content problem the operator can fix, not a server fault.
    "UNPROCESSABLE_DIAGRAM": (422, False),
    # A stage was asked to generate without an ancestor it depends on. The
    # remedy is to produce the missing parent, so this is the caller's to fix.
    "MISSING_PARENT_CONTEXT": (422, False),
    # Some of a design's learning areas were ingested and some were not. The
    # work that succeeded is kept — raising instead of persisting would throw
    # away four good learning areas to report three bad ones — but the caller
    # must not be told this succeeded. 422: the document is the thing to fix.
    "PARTIAL_INGEST": (422, False),
    # The work is already done. A conflict, not a failure: the caller can retry
    # with force to replace what the previous run produced.
    "ALREADY_INGESTED": (409, False),
    "HUMAN_REVIEW_REQUIRED": (409, False),
    "APPROVER_VERIFICATION_REQUIRED": (412, False),
    # Idempotency & Concurrency
    "IDEMPOTENCY_CONFLICT": (409, False),
    "NOT_FOUND": (404, False),
}


def raise_api_error(code: str, message: str, detail: dict | None = None) -> None:
    status, retryable = ERRORS.get(code, (500, False))
    raise ApiError(
        code=code, message=message, status_code=status,
        retryable=retryable, detail=detail,
    )
