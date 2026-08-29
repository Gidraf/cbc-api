"""Generation runs in its own process, survives the tab, and reviews itself.

The work used to happen on the HTTP request that asked for it. A refresh, a
navigation, a proxy timeout or a deploy threw away a run that was minutes in
and already paid for, leaving nothing behind that said what had been running.
"""
from __future__ import annotations

import pathlib
from types import SimpleNamespace

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend-web"


def _read(path: str) -> str:
    return (BACKEND / path).read_text()


def _front(path: str) -> str:
    return (FRONTEND / path).read_text()


# ── Celery ──────────────────────────────────────────────────────────────────


def test_the_task_is_registered_and_named():
    from app.celery_app import celery_app
    from app import tasks  # noqa: F401

    assert "cbc.run_job" in celery_app.tasks


def test_work_is_acknowledged_only_after_it_finishes():
    """Acknowledging on receipt loses the job when a worker is killed
    mid-generation: the row says 'running' for ever and nothing retries it."""
    from app.celery_app import celery_app

    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True


def test_the_worker_does_not_prefetch():
    """Reserved jobs a busy worker will not start for minutes make the queue
    look stuck and starve a second worker if one is added."""
    from app.celery_app import celery_app

    assert celery_app.conf.worker_prefetch_multiplier == 1


def test_a_wedged_generation_cannot_hold_a_worker_for_ever():
    from app.celery_app import celery_app

    assert celery_app.conf.task_time_limit > 0
    assert celery_app.conf.task_soft_time_limit < celery_app.conf.task_time_limit


def test_the_compose_worker_runs_one_job_at_a_time_by_default():
    compose = (BACKEND.parent / "docker-compose.yml").read_text()

    assert "celery -A app.celery_app worker" in compose
    assert "--concurrency=${CELERY_CONCURRENCY:-1}" in compose
    # Its own Redis database, so the generation broker is not flushed along
    # with the older pipeline queue.
    assert "redis://redis:6379/1" in compose


def test_celery_is_a_declared_dependency():
    assert "celery==" in _read("requirements.txt")


def test_the_task_imports_the_routes_so_handlers_exist():
    """A worker that imports the queue but not the routes has an empty registry
    and fails every job with 'no handler registered' — which reads like a code
    bug and is a wiring one."""
    source = _read("app/tasks.py")
    assert "from .routes import curriculum" in source


def test_a_requeued_job_is_dispatched_again():
    """Under the in-process worker the poll loop picked a requeued job back up.
    A Celery task that returns is simply finished."""
    source = _read("app/tasks.py")
    assert "run_job.apply_async" in source
    assert "job_queue.QUEUED" in source


# ── the queue prefers Celery and degrades honestly ──────────────────────────


def test_enqueue_dispatches_rather_than_hoping_a_thread_is_alive():
    source = _read("app/services/job_queue.py")
    enqueue = source[source.index("def enqueue("):]
    enqueue = enqueue[: enqueue.index("\ndef dispatch")]
    assert "dispatch(job_id)" in enqueue


def test_a_missing_broker_falls_back_rather_than_swallowing_the_work():
    """Queueing into a broker nobody listens to is the worst outcome: the
    console says 'queued' and means 'lost'."""
    source = _read("app/services/job_queue.py")
    dispatch = source[source.index("def dispatch("):]
    dispatch = dispatch[: dispatch.index("\ndef _claim")]

    assert "broker_available()" in dispatch
    assert "start_worker()" in dispatch
    assert 'return "in_process"' in dispatch


def test_the_api_does_not_start_a_thread_when_celery_is_up():
    """It dies with the API process and multiplies if the API is scaled."""
    source = _read("app/main.py")
    startup = source[source.index("def startup()"):]
    startup = startup[: startup.index("_bootstrap_default_stage_bindings")]

    assert "recover_stalled()" in startup
    assert "if broker_available():" in startup
    assert "no in-process worker started" in startup


def test_a_redelivered_job_cannot_run_twice():
    source = _read("app/services/job_queue.py")
    claim = source[source.index("def _claim_by_id("):]
    claim = claim[: claim.index("\ndef run_job_by_id")]
    assert "AND status = 'queued'" in claim


def test_abandoned_work_is_recovered_rather_than_left_running_for_ever():
    source = _read("app/services/job_queue.py")
    recover = source[source.index("def recover_stalled("):]
    recover = recover[: recover.index("\ndef _loop")]

    assert "status = 'running'" in recover
    assert "dispatch(job_id)" in recover
    # One that has burned its attempts is failed, not retried a third time.
    assert ">= MAX_ATTEMPTS" in recover


def test_both_paths_execute_through_one_function():
    """Two copies of this would drift, and the one that drifted would be the
    one nobody watches."""
    source = _read("app/services/job_queue.py")
    assert source.count("def _execute(") == 1
    assert "return _execute(job)" in source


# ── every station is queueable ──────────────────────────────────────────────


def test_every_production_station_can_run_in_the_background():
    from app.routes import curriculum  # noqa: F401
    from app.services import job_queue

    kinds = set(job_queue.known_kinds())
    assert {"notes", "diagram", "media", "simulation", "activity",
            "questions", "substrands"} <= kinds


def test_the_console_queues_stations_rather_than_holding_the_request():
    view = _front("src/views/ContentFactory.tsx")
    assert '"/api/v1/curriculum/factory/queue"' in view
    # The job id lives in the URL, which is what makes a refresh harmless.
    assert 'setParam({ job: jobId, station: station.id })' in view


def test_a_station_result_is_stored_so_the_page_can_reopen_onto_it():
    source = _read("app/routes/curriculum.py")
    assert "MAX_QUEUED_RESULT_BYTES" in source
    fn = source[source.index("def _queued_result("):]
    fn = fn[: fn.index("\ndef _run_queued_questions")]
    # Whole result when it fits, summary plus an honest note when it does not.
    assert "return {**result, **summary}" in fn
    assert '"truncated": True' in fn


# ── review cycles ───────────────────────────────────────────────────────────


def _result(score: int, passed: bool, version: int, actions=None):
    return {
        "artifact": {"artifact_id": "art_1", "version": version},
        "quality_gate": {
            "passed": passed,
            "overall_score": score,
            "summary_message": f"scored {score}",
            "next_actions": actions if actions is not None else ["Improve source grounding"],
            "reviewer": {"feedback": [{"aspect": "source_grounding"}], "risk_flags": []},
        },
    }


def test_a_passing_generation_does_not_pay_for_a_second_cycle():
    from app.services import review_cycle

    calls: list[str] = []

    def produce(instructions: str):
        calls.append(instructions)
        return _result(92, True, 1)

    _, report = review_cycle.run(produce, label="notes")

    assert len(calls) == 1
    assert report.stopped_because == "approved"
    assert report.final_passed


def test_a_failing_generation_is_sent_back_with_the_reviewers_own_words():
    from app.services import review_cycle

    seen: list[str] = []
    scores = iter([76, 91])

    def produce(instructions: str):
        seen.append(instructions)
        score = next(scores)
        return _result(score, score >= 85, len(seen))

    _, report = review_cycle.run(produce, label="notes")

    assert len(seen) == 2
    assert "Improve source grounding" in seen[1]
    assert "KEEP WHAT ALREADY PASSED" in seen[1]
    assert report.final_passed
    assert [c.score for c in report.cycles] == [76, 91]
    # Every cycle filed a version, so the progression is on the record.
    assert [c.version for c in report.cycles] == [1, 2]


def test_a_cycle_that_does_not_improve_stops_the_loop():
    """A model that did not get better with the findings in front of it will
    not get better on the third reading of the same findings."""
    from app.services import review_cycle

    calls = []

    def produce(instructions: str):
        calls.append(instructions)
        return _result(76, False, len(calls))

    _, report = review_cycle.run(produce, label="notes")

    assert len(calls) == 2, "the third pass costs the same as the one that just failed to help"
    assert report.stopped_because == "no_improvement"


def test_the_loop_is_bounded_even_while_it_keeps_improving():
    from app.services import review_cycle

    calls = []
    scores = iter([50, 60, 70, 80, 90])

    def produce(instructions: str):
        calls.append(instructions)
        return _result(next(scores), False, len(calls))

    _, report = review_cycle.run(produce, label="notes")

    assert len(calls) == review_cycle.MAX_CYCLES
    assert report.stopped_because == "max_cycles"


def test_a_gate_that_names_nothing_to_fix_does_not_loop():
    from app.services import review_cycle

    calls = []

    def produce(instructions: str):
        calls.append(instructions)
        return _result(60, False, len(calls), actions=[])

    _, report = review_cycle.run(produce, label="notes")

    assert len(calls) == 1
    assert report.stopped_because == "no_actionable_findings"


def test_the_operator_is_told_when_the_latest_version_is_not_the_best():
    """The version a reader opens by default is the latest, and here that is
    not always the one to use."""
    from app.services import review_cycle

    scores = iter([70, 88, 74])

    def produce(instructions: str):
        score = next(scores)
        return _result(score, False, 1)

    # Improvement then regression: cycle 2 is the one to keep.
    _, report = review_cycle.run(produce, label="notes", max_cycles=3)

    assert report.best_cycle == 2
    assert not report.latest_is_best
    assert "pick cycle 2" in report.to_dict()["note"]


def test_the_cycle_does_not_approve_its_own_output():
    """An automatic loop that also approved would be a review with no
    independent party in it."""
    source = _read("app/services/review_cycle.py")
    assert "approve" not in source.split('"""')[2].lower() or "does NOT" in source
    assert "a human still approves one" in source


def test_the_stations_run_their_cycles_inside_the_worker():
    source = _read("app/routes/curriculum.py")
    assert source.count("review_cycle.run(") == 2  # stations, and questions
    runner = source[source.index("def _run_queued("):]
    runner = runner[: runner.index("\n# A station's output")]
    assert 'out["review_cycles"] = cycles.to_dict()' in runner


# ── the reviewers and the approver run in the worker too ────────────────────


def test_review_and_approval_are_queueable_kinds():
    """They are model calls like the generators and take as long — they were
    the half of the pipeline still run by hand, one artifact at a time."""
    from app.routes import curriculum  # noqa: F401
    from app.services import job_queue

    kinds = set(job_queue.known_kinds())
    assert "review" in kinds and "approval" in kinds


def test_the_queued_approver_does_not_approve():
    """Coverage counts approved work, so a pipeline that approved its own
    output would let a grade report itself taught-ready with nobody having read
    a line of it."""
    source = _read("app/routes/curriculum.py")
    handler = source[source.index("def _run_queued_approval"):]
    handler = handler[: handler.index("\ndef _register_queue_handlers")]

    assert '"requires_human": True' in handler
    assert "It does NOT approve" in handler
    # It runs the layers and reports what still blocks a person's sign-off.
    assert "approval_state" in handler
    assert "apply_label" not in handler and "status = 'approved'" not in handler


def test_the_approver_runs_the_layers_that_are_missing_in_order():
    """Layer 3 cannot judge what layer 2 has not seen."""
    source = _read("app/routes/curriculum.py")
    handler = source[source.index("def _run_queued_approval"):]
    assert "for layer in (2, 3):" in handler[:3000]


def test_two_versions_of_one_sub_strand_are_not_deduplicated():
    """Keyed only on the sub-strand, the review of version 2 collapsed into the
    review of version 1 and the new version was never looked at."""
    source = _read("app/services/job_queue.py")
    enqueue = source[source.index("def enqueue("):]
    enqueue = enqueue[: enqueue.index("\ndef dispatch")]

    assert "payload->>'artifact_id'" in enqueue
    assert "payload->>'layer'" in enqueue


# ── the console can say how much is waiting and where ───────────────────────


def test_the_queue_reports_position_and_per_kind_progress():
    source = _read("app/services/job_queue.py")
    status = source[source.index("def status("):]

    assert "ROW_NUMBER() OVER (ORDER BY created_at ASC)" in status
    assert '"counts_by_kind"' in status
    assert '"queue_depth"' in status
    # Where the work runs, so "queued" is never ambiguous about whether
    # anything is listening.
    assert '"runs_on"' in status


def test_the_panel_shows_where_work_runs_and_how_deep_the_line_is():
    panel = _front("src/views/QueuePanel.tsx")
    assert "background worker" in panel
    assert "in-process fallback" in panel
    assert "waiting" in panel
    assert "In line" in panel


def test_the_panel_can_queue_review_and_the_approvers_work():
    panel = _front("src/views/QueuePanel.tsx")
    assert 'work: "review"' in panel
    assert 'work: "approval"' in panel
    assert "Approval itself stays yours" in panel


def test_the_question_bank_uses_the_same_engine():
    """Question generation was held open on the request that asked for it, so a
    refresh threw away a batch already paid for."""
    view = _front("src/views/QuestionBank.tsx")
    assert "<QueuePanel" in view
    assert 'defaultKinds={["questions"]}' in view


def test_the_worker_actually_registers_the_task_it_will_be_handed():
    """`autodiscover_tasks` runs while celery_app is still executing, so
    importing app.tasks — which imports celery_app — is a cycle that Celery
    swallows. The worker then boots cleanly, prints an empty [tasks] list, and
    fails every job with "unregistered task"."""
    source = _read("app/celery_app.py")

    assert 'include=["app.tasks"]' in source
    assert "celery_app.autodiscover_tasks(" not in source
