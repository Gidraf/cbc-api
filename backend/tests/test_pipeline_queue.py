"""The whole chain, unattended: design in, questions out.

The chain used to be a person. Ingest, wait, read the result, click strands,
wait, click each strand's sub-strands, wait, click notes for each sub-strand,
wait — an afternoon of pressing buttons and watching, per learning area. That
is the only reason the work was ever done one item at a time.
"""
from __future__ import annotations

import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend-web"


def _read(path: str) -> str:
    return (BACKEND / path).read_text()


def _front(path: str) -> str:
    return (FRONTEND / path).read_text()


def test_every_stage_from_the_dataset_to_the_questions_is_queueable():
    from app.routes import curriculum  # noqa: F401
    from app.services import job_queue

    kinds = set(job_queue.known_kinds())
    assert {
        "ingest", "strands", "substrands", "notes", "diagram", "media",
        "simulation", "activity", "questions", "review", "approval",
        "regenerate", "pipeline",
    } <= kinds


def test_the_steps_are_in_dependency_order():
    """A run that did notes before sub-strands would generate nothing and
    report success."""
    from app.routes.curriculum import PIPELINE_STEPS

    order = list(PIPELINE_STEPS)
    assert order.index("ingest") < order.index("strands")
    assert order.index("strands") < order.index("substrands")
    assert order.index("substrands") < order.index("notes")
    for grounded in ("diagram", "media", "simulation", "activity", "questions"):
        assert order.index("notes") < order.index(grounded), grounded


def test_a_step_is_expanded_across_the_right_unit():
    """Getting this wrong either runs the notes once for a whole grade or
    ingests the design ninety times."""
    from app.routes.curriculum import _STEP_SCOPE

    assert _STEP_SCOPE["ingest"] == "subject"
    assert _STEP_SCOPE["strands"] == "subject"
    assert _STEP_SCOPE["substrands"] == "strand"
    for per_substrand in ("notes", "diagram", "media", "simulation", "activity", "questions"):
        assert _STEP_SCOPE[per_substrand] == "sub_strand"


def test_a_stage_advances_only_once_however_wide_it_fanned_out():
    """Without the barrier each of twelve sub-strand jobs would queue the next
    stage as it landed — twelve times, and the stage after that a hundred and
    forty-four."""
    source = _read("app/routes/curriculum.py")
    advance = source[source.index("def _advance_pipeline"):]
    advance = advance[: advance.index("\ndef _register_queue_handlers")]

    assert "status IN ('queued', 'running')" in advance
    assert "job_id <> :job_id" in advance
    assert "return \"\"" in advance


def test_the_next_stage_is_expanded_from_what_the_last_one_saved():
    """Expanded at queue time, a station step would have to guess sub-strands
    the sub-strand step has not produced yet."""
    source = _read("app/routes/curriculum.py")
    expand = source[source.index("def _expand_step"):]
    expand = expand[: expand.index("\ndef _run_queued_pipeline")]

    assert "_stored_strands" in expand and "_stored_substrands" in expand


def test_a_pipeline_step_cannot_be_swallowed_as_a_duplicate_of_itself():
    """A pipeline queues its next step while the current one is still
    'running' — it is the running job that queues it. Keyed without the step
    index, every stage after the first was dropped as a duplicate and the run
    stopped dead one stage in, looking finished."""
    source = _read("app/services/job_queue.py")
    enqueue = source[source.index("def enqueue("):]
    enqueue = enqueue[: enqueue.index("\ndef dispatch")]

    assert "payload->>'index'" in enqueue
    assert ":step_index" in enqueue


def test_the_pipeline_delegates_to_the_same_handlers_the_buttons_use():
    """Two implementations would drift, and the one that drifted would be the
    one nobody watches."""
    from app.routes import curriculum

    assert curriculum._PIPELINE_HANDLERS["notes"] is curriculum._run_queued
    assert curriculum._PIPELINE_HANDLERS["substrands"] is curriculum._run_queued_substrands
    assert curriculum._PIPELINE_HANDLERS["questions"] is curriculum._run_queued_questions
    assert set(curriculum._PIPELINE_HANDLERS) == set(curriculum.PIPELINE_STEPS)


def test_steps_are_reordered_rather_than_run_as_listed():
    source = _read("app/routes/curriculum.py")
    route = source[source.index("def factory_queue_pipeline"):]
    route = route[: route.index("\n@router.post")]

    assert "steps = [s for s in PIPELINE_STEPS if s in set(steps)]" in route
    # And starting somewhere with nothing to run against is refused rather than
    # queued into silence.
    assert "MISSING_PARENT_CONTEXT" in route


def test_strand_generation_saves_rather_than_returning_a_screenful():
    """A strand list nobody saved is a run whose entire output dies with the
    tab."""
    source = _read("app/routes/curriculum.py")
    handler = source[source.index("def _run_queued_strands"):]
    handler = handler[: handler.index("\ndef _run_queued_regeneration")]

    assert "factory_save_strands(" in handler
    assert '"saved_count"' in handler


def test_regeneration_needs_findings_to_regenerate_from():
    """Regenerating without them is another roll of the same dice at the same
    price."""
    source = _read("app/routes/curriculum.py")
    route = source[source.index("def factory_queue_regenerate"):]
    route = route[: route.index("\n@router.post")]

    assert "JOIN artifact_reviews" in route
    assert "r.verdict IN ('revise', 'reject')" in route


def test_reviews_are_stored_and_read_back_rather_than_returned_once():
    source = _read("app/services/review_layers.py")
    assert "FROM artifact_reviews WHERE artifact_id" in source


def test_the_console_can_start_a_run_and_see_which_step_it_is_on():
    panel = _front("src/views/QueuePanel.tsx")
    assert "Queue the full run" in panel
    assert "Queue regeneration from findings" in panel
    assert "STEP_LABEL[job.step]" in panel

    source = _read("app/services/job_queue.py")
    # Without this every stage of a full run reads as "pipeline".
    assert "payload->'steps'->>COALESCE((payload->>'index')::int, 0)" in source
