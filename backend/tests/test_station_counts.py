"""How many a station produces, set where the work is started.

Every station had its own hardcoded default and no way to change it from the
console, so "generate 50 questions for this strand" meant editing the request
by hand. Worse, `min_visuals` was a field on the visuals request that reached
no prompt at all: setting it did nothing, and the station planned whatever it
felt like.
"""
from __future__ import annotations

from app.services.langfuse_seed import SEED_PROMPT_BLOCKS

import inspect
from pathlib import Path

from app.routes import curriculum

FRONTEND = Path(__file__).resolve().parents[2] / "frontend-web"


def test_the_queue_carries_a_count_per_station() -> None:
    assert "counts" in curriculum.QueueWorkRequest.model_fields

    queued = inspect.getsource(curriculum.factory_queue_work)
    assert 'payload.counts.get(kind)' in queued
    assert '"count": int(payload.counts[kind])' in queued


def test_one_count_reaches_whichever_field_a_station_calls_it() -> None:
    """The number typed on the board reached the questions station and no
    other, because each had invented a different name for it."""
    runner = inspect.getsource(curriculum._run_queued)

    assert '"min_visuals", "min_activities", "batch_count", "count"' in runner
    assert "if field_name in allowed" in runner


def test_the_questions_station_reads_the_same_count() -> None:
    runner = inspect.getsource(curriculum._run_queued_questions)

    assert 'payload.get("count") or payload.get("batch_count")' in runner


def test_the_visual_count_reaches_the_prompt_not_only_the_template() -> None:
    """A template variable the Langfuse prompt does not reference silently
    does nothing, which is what `min_visuals` did for its whole life."""
    # The instruction text moved into the prompt store; the route
    # renders it. Checking both is checking that the rule exists AND
    # still reaches the station that needs it.
    source = (inspect.getsource(curriculum.factory_plan_visuals)
              + SEED_PROMPT_BLOCKS["substrand-notes-context"])

    assert "PRODUCE AT LEAST" in source
    assert "min_visuals" in source
    assert "spread across its lessons" in source, "not piled onto one"


def test_practicals_got_the_same_control() -> None:
    assert "min_activities" in curriculum.FactoryPlanActivitiesRequest.model_fields

    # The instruction text moved into the prompt store; the route
    # renders it. Checking both is checking that the rule exists AND
    # still reaches the station that needs it.
    source = (inspect.getsource(curriculum.factory_plan_activities)
              + SEED_PROMPT_BLOCKS["notes-plan-context"])
    assert "PRODUCE AT LEAST" in source
    assert "min_activities" in source


def test_a_count_of_zero_or_nonsense_falls_back_rather_than_asking_for_none() -> None:
    for source in (inspect.getsource(curriculum.factory_plan_visuals),
                   inspect.getsource(curriculum.factory_plan_activities)):
        assert "max(1, int(getattr(payload" in source


def test_the_console_offers_it_only_where_a_number_means_something() -> None:
    """Notes are one per allocated hour, not a quantity to choose."""
    factory = " ".join((FRONTEND / "src/views/ContentFactory.tsx").read_text().split())

    assert 'How many per sub-strand' in factory
    assert '["visuals", "practicals", "questions"].includes(station.id)' in factory
    assert '"notes"' not in factory.split("How many per sub-strand")[0][-260:]
    # Blank keeps whatever the station already did.
    assert "Blank uses this station's own default" in factory
    assert "counts[kind] ? { counts: { [kind]: counts[kind] } } : {}" in factory
