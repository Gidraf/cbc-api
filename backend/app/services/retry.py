from __future__ import annotations

import logging
from typing import Any, Callable

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    wait_random_exponential,
)

from ..errors import ApiError

logger = logging.getLogger("cbc-retry")


def is_retryable_api_error(exception: BaseException) -> bool:
    """Whether trying the same call again could possibly work.

    This function existed and nothing used it: every decorator below asked
    tenacity to retry on bare `Exception`, so a wrong model name, an exhausted
    quota, a missing credential and a refused prompt each burned three attempts
    and two backoffs before failing exactly as they were always going to.

    At one worker that is a slow failure. At eight it is eight workers spending
    money to arrive at the same answer, and a rate limit hit by the retries of
    calls that were never going to succeed.

    The taxonomy in `errors.py` already says which is which — a 429 or a 502 is
    worth another go, a 400 or a 402 is not — so the decision is read from
    there rather than guessed at here.
    """
    if isinstance(exception, ApiError):
        if not exception.retryable:
            logger.info("Not retrying %s: %s", exception.code,
                        "the same call will fail the same way")
        return exception.retryable
    # A dropped connection or a timeout says nothing about the request, only
    # about the moment it was made.
    #
    # `httpx.TransportError` is listed explicitly: httpx's connect and read
    # timeouts inherit from NONE of the builtins above, so a policy that
    # checked only those would have stopped retrying every real network
    # failure in this codebase while claiming to retry transient ones.
    import httpx

    return isinstance(exception, (ConnectionError, TimeoutError, OSError,
                                  httpx.TransportError))


# Langfuse retry: 3 attempts, 500ms, 1500ms, 3500ms
def retry_langfuse(func: Callable[..., Any]) -> Callable[..., Any]:
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=3.5),
        retry=retry_if_exception(is_retryable_api_error),
        reraise=True,
    )(func)


# LLM retry: 3 attempts, exponential backoff with jitter
def retry_llm(func: Callable[..., Any]) -> Callable[..., Any]:
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(min=1, max=7),
        retry=retry_if_exception(is_retryable_api_error),
        reraise=True,
    )(func)


# Storage/MinIO retry: 3 attempts, 1s interval
def retry_storage(func: Callable[..., Any]) -> Callable[..., Any]:
    return retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1.0, min=1.0, max=3.0),
        retry=retry_if_exception(is_retryable_api_error),
        reraise=True,
    )(func)
