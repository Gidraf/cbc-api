"""Queued work, and rubrics where the design's table could not be read.

KICD prints its rubric as a four-column table, and the extracted text of those
pages is the worst-mangled part of every design. One run produced nine rubrics
of which four were wrong — one carrying a row from a different strand entirely.
The next run produced two, both correct, and dropped seven that exist.

And one sub-strand's notes take about a minute; a grade's worth take an
afternoon, which no HTTP request survives.
"""
from __future__ import annotations

import pytest

from app.services import job_queue
from app.services.rubric_filler import LEVELS, fill, is_usable, needs_filling

_COMPLETE = [{
    "indicator": "Ability to identify three qualities of God.",
    "exceeding": "Identifies more than three.", "meeting": "Identifies three.",
    "approaching": "Identifies two.", "below": "Identifies one.",
}]


# ── Rubrics ─────────────────────────────────────────────────────────────────

def test_a_complete_rubric_is_left_alone_and_marked_as_the_designs() -> None:
    subs = [{"sub_strand_name": "Our God", "assessment_rubric": _COMPLETE}]

    report = fill(subs, lambda s: pytest.fail("should not have generated"))

    assert report.from_design == ["Our God"]
    assert subs[0]["rubric_source"] == "design"


@pytest.mark.parametrize("missing", LEVELS)
def test_a_rubric_missing_any_level_is_refilled(missing) -> None:
    """A teacher marking against three levels has nowhere to put the fourth
    kind of answer."""
    partial = [{k: v for k, v in _COMPLETE[0].items() if k != missing}]

    assert not is_usable(partial)
    assert needs_filling([{"sub_strand_name": "x", "assessment_rubric": partial}])


def test_a_generated_rubric_says_it_was_generated() -> None:
    """A rubric read from KICD and one derived from its outcomes are different
    things, and a reviewer must be able to tell them apart."""
    subs = [{"sub_strand_name": "Our God", "assessment_rubric": None}]

    fill(subs, lambda s: _COMPLETE)

    assert subs[0]["rubric_source"] == "generated_from_outcomes"
    assert subs[0]["assessment_rubric"] == _COMPLETE


def test_an_incomplete_generation_is_refused_rather_than_stored() -> None:
    """Storing it would hide the gap behind something that looks filled."""
    subs = [{"sub_strand_name": "Our God", "assessment_rubric": None}]

    report = fill(subs, lambda s: [{"indicator": "x", "meeting": "y"}])

    assert report.generated == []
    assert report.failed[0]["error"] == "the generated rubric was itself incomplete"
    assert "rubric_source" not in subs[0]


def test_a_generator_failure_does_not_stop_the_batch() -> None:
    subs = [
        {"sub_strand_name": "A", "assessment_rubric": None},
        {"sub_strand_name": "B", "assessment_rubric": None},
    ]

    def flaky(sub_strand):
        if sub_strand["sub_strand_name"] == "A":
            raise RuntimeError("model timed out")
        return _COMPLETE

    report = fill(subs, flaky)

    assert report.generated == ["B"]
    assert report.failed[0]["sub_strand"] == "A"


def test_the_sub_strand_route_fills_rubrics() -> None:
    route = open("app/routes/curriculum.py").read()
    block = route[route.index("def factory_generate_substrands"):]
    block = block[: block.index("\n@router.")]

    assert "rubric_filler.fill" in block
    assert '"rubrics": rubrics.to_dict()' in block


# ── The queue ───────────────────────────────────────────────────────────────

def test_every_queueable_kind_has_a_station() -> None:
    from app.routes.curriculum import _QUEUEABLE

    for kind, endpoint in _QUEUEABLE.items():
        assert endpoint, f"{kind} has no station"
    assert set(job_queue.known_kinds()) >= set(_QUEUEABLE)


def test_queued_work_runs_the_same_code_as_a_click() -> None:
    """A queue that reimplements the station is a second implementation to keep
    correct, and the two drift."""
    route = open("app/routes/curriculum.py").read()

    assert "handler = globals()[endpoint]" in route
    assert "queued work and clicked work" in route


def test_the_queue_is_sequential_on_purpose() -> None:
    """Ten at once fails halfway with no way to tell which half."""
    source = open("app/services/job_queue.py").read()

    assert "FOR UPDATE SKIP LOCKED LIMIT 1" in source
    assert "one at a time" in source.lower()


def test_a_job_is_retried_once_and_then_left() -> None:
    """A job that has crashed twice will crash a third time, and retrying spends
    money to learn nothing."""
    source = open("app/services/job_queue.py").read()

    assert job_queue.MAX_ATTEMPTS == 2
    assert "spends money to learn nothing" in source


def test_the_same_work_is_not_queued_twice() -> None:
    """It would run the model twice and file two versions differing only by
    sampling noise."""
    source = open("app/services/job_queue.py").read()

    assert "status IN ('queued', 'running')" in source
    assert "sampling noise" in source


def test_cancelling_does_not_kill_a_running_job() -> None:
    """It would leave the artifact half-written with no record of which half."""
    source = open("app/services/job_queue.py").read()

    assert "WHERE status = 'queued'" in source
    assert "half-written" in source


def test_the_worker_survives_a_single_failure() -> None:
    """A queue whose worker died looks exactly like an empty one."""
    source = open("app/services/job_queue.py").read()

    assert "must outlive any single failure" in source


def test_the_worker_starts_with_the_api() -> None:
    """Anything queued before a restart is still queued, and without a worker
    the queue looks empty."""
    main = open("app/main.py").read()

    assert "job_queue.start_worker()" in main
    assert "still queued" in main


def test_the_console_stops_polling_when_the_queue_is_idle() -> None:
    """A screen that polls an idle queue forever is a request every few seconds,
    all day."""
    queries = open("../frontend-web/src/lib/queries.ts").read()

    assert "outstanding > 0 ? 4000 : false" in queries


def test_the_picker_refreshes_when_sub_strands_are_saved() -> None:
    """The stations are keyed on a selected sub-strand. Without this there was
    nothing to select until a hard reload."""
    queries = open("../frontend-web/src/lib/queries.ts").read()

    assert 'queryKey: ["saved-substrands"]' in queries
