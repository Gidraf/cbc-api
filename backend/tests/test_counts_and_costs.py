"""The questions studio, the board and the bill must agree with each other.

Three disagreements, each a real screen:

- the studio said "no guide" beside a sub-strand the Content Factory showed a
  guide for — one compared names with LOWER(), the other with `scope_key`;
- the day's "generated" count was taken before the save, under the model's
  positional labels, so forty runs of "Q1".."Q15" counted fifteen questions;
- "spend to date" read only the legacy pipeline's table, and Claude models
  were priced at $0.
"""
from __future__ import annotations

import inspect

from app.services import artifact_registry, cost_tracker, question_throughput as th, run_meter, scope_key


# ── guides ──────────────────────────────────────────────────────────────────

def test_the_guide_search_matches_names_the_way_the_board_does(monkeypatch) -> None:
    seen: dict = {}

    def fetch_all(sql, params=None):
        seen["sql"], seen["params"] = sql, params
        return []

    monkeypatch.setattr("app.infra.db.fetch_all", fetch_all)
    artifact_registry.search(grade="9", subject="Mathematics ", sub_strand="Whole  Numbers", kind="notes")

    assert seen["params"]["sub_strand"] == "whole numbers"
    assert seen["params"]["subject"] == "mathematics"
    assert scope_key.sql("a.sub_strand_name") in seen["sql"]
    assert "LOWER(a.sub_strand_name) = LOWER(:sub_strand)" not in seen["sql"]


# ── counts ──────────────────────────────────────────────────────────────────

def test_generated_is_recorded_after_the_save_under_the_banks_ids() -> None:
    from app.routes import questions

    source = inspect.getsource(questions.factory_generate_questions_batch)
    save = source.index("save_batch_questions(")
    generated = source.index("question_throughput.GENERATED")
    assert generated > save, "counted before the save, under positional labels"
    assert "question_throughput.GENERATED, normalized_questions" not in source


def test_items_that_never_reached_the_bank_each_count_once() -> None:
    assert th.unsaved_id("Q1") != th.unsaved_id("Q1")
    assert th.unsaved_id("Q1").endswith(":Q1")


def test_a_day_says_what_a_question_cost() -> None:
    day = th.DayProgress(done={th.GENERATED: 40}, target=th.Target(), generated_cost_usd=2.0)

    assert day.cost_per_question == 0.05
    assert day.to_dict()["generated_cost_usd"] == 2.0
    assert th.DayProgress(target=th.Target()).cost_per_question == 0.0


def test_every_count_compares_the_grade_however_it_is_spelt() -> None:
    for fn in (th._counts_today, th._waiting, th.history, th.get_target):
        source = inspect.getsource(fn)
        assert "_grade_clause(" in source, fn.__name__
        assert "LOWER(grade) = LOWER(:grade)" not in source, fn.__name__


def test_a_day_is_a_nairobi_day() -> None:
    start = th._day_start(__import__("datetime").date(2026, 9, 24))
    assert start.utcoffset().total_seconds() == 3 * 3600


# ── the meter ───────────────────────────────────────────────────────────────

class _Usage:
    prompt_tokens = 1_000_000
    completion_tokens = 0
    total_tokens = 1_000_000
    cached_tokens = 0


def test_a_step_is_priced_on_its_own_and_still_counts_for_its_job(monkeypatch) -> None:
    monkeypatch.setattr(run_meter, "_file_direct", lambda *a: None)
    job = run_meter.start("job-1")
    try:
        step = run_meter.begin()
        run_meter.add(_Usage(), "claude-sonnet-5", "anthropic")
        run_meter.end(step)
        run_meter.add(_Usage(), "claude-sonnet-5", "anthropic")
    finally:
        run_meter.stop()

    assert step.cost_usd == 2.0
    assert job.cost_usd == 4.0 and job.calls == 2


def test_a_call_outside_any_job_is_filed_once(monkeypatch) -> None:
    filed: list = []
    monkeypatch.setattr(run_meter, "_file_direct", lambda *a: filed.append(a))
    run_meter.stop()

    run_meter.add(_Usage(), "claude-sonnet-5", "anthropic")          # plain request
    with run_meter.measure():                                         # studio step
        run_meter.add(_Usage(), "claude-sonnet-5", "anthropic")
    with run_meter.measure(accounted=True):                           # legacy pipeline
        run_meter.add(_Usage(), "claude-sonnet-5", "anthropic")
    run_meter.start("job-2")                                          # queued job
    run_meter.add(_Usage(), "claude-sonnet-5", "anthropic")
    run_meter.stop()

    assert len(filed) == 2


def test_a_retried_job_keeps_the_cost_of_every_attempt() -> None:
    from app.services import job_queue

    source = inspect.getsource(job_queue)
    assert "cost_usd = :cost" not in source
    assert source.count("cost_usd = cost_usd + :cost") == 2


# ── prices ──────────────────────────────────────────────────────────────────

def _cost(model: str, provider: str) -> float:
    usage = cost_tracker.TokenUsage(prompt_tokens=1_000_000, completion_tokens=1_000_000,
                                    total_tokens=2_000_000)
    return cost_tracker.calculate_cost(model, provider, usage).total_cost_usd


def test_current_claude_models_are_not_free() -> None:
    assert _cost("claude-sonnet-5", "anthropic") == 12.0
    assert _cost("claude-haiku-4-5", "anthropic") == 6.0
    assert _cost("claude-opus-5-5", "anthropic") == 24.0
    assert _cost("claude-opus-5", "anthropic") == 30.0


def test_a_local_model_is_free_whatever_it_is_called() -> None:
    assert _cost("gpt-4o", "ollama") == 0.0
    assert _cost("qwen3:32b", "ollama") == 0.0


def test_a_vague_name_is_not_priced_as_whatever_came_first() -> None:
    assert _cost("gpt", "openai") == 0.0


def test_cached_prompt_tokens_are_billed_at_the_cache_rate() -> None:
    usage = cost_tracker.TokenUsage(prompt_tokens=1_000_000, completion_tokens=0,
                                    total_tokens=1_000_000, cached_tokens=1_000_000)
    assert cost_tracker.calculate_cost("claude-sonnet-5", "anthropic", usage).total_cost_usd == 0.2
