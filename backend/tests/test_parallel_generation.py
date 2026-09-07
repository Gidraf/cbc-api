"""Running several sub-strands at once, without running one twice.

The queue was sequential on purpose: "ten at once is how a run fails halfway
with no way to tell which half". That reasoning is about jobs that interfere.
Two sub-strands do not: a grade has hundreds, each spends its time waiting on a
provider rather than on this machine, and doing them one at a time is why a
grade takes an afternoon.

Two jobs for the SAME sub-strand are the case that must never overlap. The
stations are a chain — material is written from the notes, diagrams drawn
against them — so a material job starting while its own notes job is still
running writes from whatever was filed last time, or from nothing.
"""
from __future__ import annotations

import inspect
import os

import pytest
from sqlalchemy import text

from app.services import job_queue


def _claim_sql() -> str:
    return (
        """
        UPDATE jobs SET status = 'running'
        WHERE job_id = (
            SELECT job_id FROM jobs WHERE status = 'queued' AND %s LIMIT 1
        ) RETURNING *
        """ % job_queue._FREE_SCOPE
    )


def test_a_job_is_not_claimable_while_its_own_substrand_is_running() -> None:
    sql = _claim_sql()

    assert "NOT EXISTS" in sql
    for column in ("grade", "subject", "sub_strand"):
        assert f"busy.{column}" in sql and f"jobs.{column}" in sql
    # Its own row must not block it.
    assert "busy.job_id <> jobs.job_id" in sql


def test_the_scope_match_is_case_insensitive_and_null_safe() -> None:
    """A job filed with grade "Grade-9" and another with "grade-9" are the same
    sub-strand, and a NULL sub-strand must not silently match everything."""
    sql = _claim_sql()

    assert sql.count("LOWER(COALESCE(") == 6, "both sides of all three columns"


def test_the_claim_is_still_atomic() -> None:
    """`FOR UPDATE SKIP LOCKED` is what lets several workers claim at once
    without two of them taking the same row."""
    source = inspect.getsource(job_queue._claim)

    assert "FOR UPDATE SKIP LOCKED" in source
    assert "ORDER BY created_at ASC" in source, "oldest first, still"


def test_the_claim_sql_binds_no_parameters() -> None:
    """The scope clause is composed, so a parameter that went missing would
    fail at run time rather than in a test."""
    assert sorted(text(_claim_sql())._bindparams) == []


def test_the_busy_check_binds_only_the_job_id() -> None:
    sql = ("SELECT 1 AS busy FROM jobs WHERE job_id = :job_id AND NOT (%s)"
           % job_queue._FREE_SCOPE)

    assert sorted(text(sql)._bindparams) == ["job_id"]


# ── the Celery path, which is handed an id and cannot skip ──────────────────


def test_celery_waits_rather_than_running_beside_itself() -> None:
    """It never sees the queue, so it cannot skip past a blocked job the way
    the poller does. With concurrency above one it would otherwise start the
    material for a sub-strand whose notes are still being written."""
    source = inspect.getsource(job_queue.run_job_by_id)

    assert "scope_is_busy(job_id)" in source
    assert "WAITING" in source
    # And it must not consume an attempt: it never ran.
    assert source.index("scope_is_busy") < source.index("_claim_by_id")


def test_a_waiting_job_comes_back_rather_than_being_lost() -> None:
    from app import tasks

    source = inspect.getsource(tasks.run_job)

    assert "job_queue.WAITING" in source
    assert "countdown=15" in source, "shorter than a retry: it waits on a station"


def test_waiting_is_neither_a_failure_nor_a_run() -> None:
    assert job_queue.WAITING not in (job_queue.FAILED, job_queue.DONE,
                                     job_queue.RUNNING, job_queue.QUEUED)


# ── how many ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_env():
    was = os.environ.get("JOB_WORKERS")
    yield
    if was is None:
        os.environ.pop("JOB_WORKERS", None)
    else:
        os.environ["JOB_WORKERS"] = was


def test_it_stays_at_one_unless_asked() -> None:
    os.environ.pop("JOB_WORKERS", None)
    assert job_queue.worker_count() == 1


def test_it_can_be_raised() -> None:
    os.environ["JOB_WORKERS"] = "6"
    assert job_queue.worker_count() == 6


def test_it_is_capped_because_the_limit_is_the_provider_not_the_machine() -> None:
    """These threads wait on an API. The ceiling is the rate limit and the
    wallet, not the core count."""
    os.environ["JOB_WORKERS"] = "500"
    assert job_queue.worker_count() == 12


def test_nonsense_falls_back_to_one_rather_than_crashing_the_worker() -> None:
    os.environ["JOB_WORKERS"] = "lots"
    assert job_queue.worker_count() == 1


def test_starting_twice_does_not_double_the_workers() -> None:
    source = inspect.getsource(job_queue.start_worker)

    assert "alive = [w for w in _workers if w.is_alive()]" in source
    assert "return False" in source


# ── retrying only what could possibly work ──────────────────────────────────


def test_a_permanent_failure_is_not_retried() -> None:
    """`is_retryable_api_error` existed and nothing used it: every decorator
    asked tenacity to retry bare `Exception`, so a wrong model name, an
    exhausted quota and a refused prompt each burned three attempts and two
    backoffs before failing exactly as they were always going to.

    At one worker that is a slow failure. At eight it is eight workers spending
    money to reach the same answer, and a rate limit hit by the retries of
    calls that were never going to succeed."""
    from app.errors import ApiError, raise_api_error
    from app.services.retry import retry_llm

    for code in ("LLM_INVALID_MODEL", "LLM_CREDIT_EXHAUSTED",
                 "MODEL_CREDENTIAL_MISSING", "LLM_CONTENT_FILTER"):
        calls = {"n": 0}

        @retry_llm
        def _call():
            calls["n"] += 1
            raise_api_error(code, "no")

        with pytest.raises(ApiError):
            _call()
        assert calls["n"] == 1, f"{code} was retried"


def test_a_transient_failure_is_still_retried() -> None:
    from app.errors import ApiError, raise_api_error
    from app.services.retry import retry_llm

    for code in ("LLM_RATE_LIMITED", "LLM_PROVIDER_TIMEOUT",
                 "LLM_PROVIDER_ERROR", "MODEL_ENDPOINT_UNAVAILABLE"):
        calls = {"n": 0}

        @retry_llm
        def _call():
            calls["n"] += 1
            raise_api_error(code, "later")

        with pytest.raises(ApiError):
            _call()
        assert calls["n"] == 3, f"{code} gave up too early"


def test_httpx_transport_errors_are_retried() -> None:
    """httpx's connect and read timeouts inherit from NONE of the builtin
    network errors, so a policy checking only those would have stopped
    retrying every real network failure in this codebase while claiming to
    retry transient ones."""
    import httpx

    from app.services.retry import is_retryable_api_error

    for error in (httpx.ConnectError("x"), httpx.ReadTimeout("x"),
                  httpx.ConnectTimeout("x"), httpx.RemoteProtocolError("x")):
        assert is_retryable_api_error(error), type(error).__name__


def test_a_plain_bug_is_not_retried() -> None:
    """Retrying a KeyError three times wastes money and hides the bug."""
    from app.services.retry import is_retryable_api_error

    assert not is_retryable_api_error(KeyError("typo"))
    assert not is_retryable_api_error(ValueError("bug"))


def test_every_decorator_reads_the_same_policy() -> None:
    import inspect

    from app.services import retry as module

    source = inspect.getsource(module)

    assert source.count("retry=retry_if_exception(is_retryable_api_error)") == 3
    assert "retry_if_exception_type" not in source
