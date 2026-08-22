from __future__ import annotations

import logging
from typing import Any, Callable

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random_exponential,
)

from ..errors import ApiError

logger = logging.getLogger("cbc-retry")


def is_retryable_api_error(exception: BaseException) -> bool:
    if isinstance(exception, ApiError):
        return exception.retryable
    # System/Network/Timeout exceptions are typically retryable
    return isinstance(exception, (ConnectionError, TimeoutError, OSError))


# Langfuse retry: 3 attempts, 500ms, 1500ms, 3500ms
def retry_langfuse(func: Callable[..., Any]) -> Callable[..., Any]:
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=3.5),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, Exception)),
        reraise=True,
    )(func)


# LLM retry: 3 attempts, exponential backoff with jitter
def retry_llm(func: Callable[..., Any]) -> Callable[..., Any]:
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(min=1, max=7),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, Exception)),
        reraise=True,
    )(func)


# Storage/MinIO retry: 3 attempts, 1s interval
def retry_storage(func: Callable[..., Any]) -> Callable[..., Any]:
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1.0, min=1.0, max=3.0),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, Exception)),
        reraise=True,
    )(func)
