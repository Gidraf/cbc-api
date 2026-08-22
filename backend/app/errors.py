from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ApiError(Exception):
    code: str
    message: str
    status_code: int
    retryable: bool = False


ERRORS = {
    "UNAUTHORIZED_ACCESS": (401, False),
    "DATASET_ITEM_NOT_FOUND": (404, False),
    "UNSUPPORTED_MODEL_PROVIDER": (400, False),
    "MODEL_NOT_CONFIGURED_FOR_STAGE": (400, False),
    "MODEL_CREDENTIAL_MISSING": (401, False),
    "MODEL_ENDPOINT_UNAVAILABLE": (503, True),
    "INVALID_GRADE_DATASET": (400, False),
    "QUALITY_GATE_REJECTED": (422, False),
    "INSUFFICIENT_WRITTEN_RESPONSE_ITEMS": (422, False),
    "SCHEMA_VALIDATION_FAILED": (422, False),
}


def raise_api_error(code: str, message: str) -> None:
    status, retryable = ERRORS.get(code, (500, False))
    raise ApiError(code=code, message=message, status_code=status, retryable=retryable)
