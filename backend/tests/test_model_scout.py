"""The weekly model scout: read prices, try cheaper models, recommend, never switch alone."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from app.services import model_scout as ms, model_trial, price_book

PAGE_ROW = ('<astro-island uid="x" props="{&quot;tier&quot;:[0,&quot;standard&quot;],'
            '&quot;rows&quot;:[1,[{rows}]]}"></astro-island>')


def _page(rows: list[tuple], tier: str = "standard") -> str:
    cells = ",".join(
        "[1,[[0,&quot;%s&quot;],[0,%s],[0,%s],[0,%s],[0,%s]]]" % r for r in rows)
    return PAGE_ROW.replace("{rows}", cells).replace("standard", tier)


# ── the price page ──────────────────────────────────────────────────────────

def test_the_standard_table_is_read_and_the_context_note_dropped() -> None:
    page = _page([("gpt-6-sol", 2, 0.2, 2.5, 10), ("gpt-6-luna", 0.1, 0.01, 0.125, 0.5),
                  ("gpt-5.4 (<272K context length)", 2.5, 0.25, "null", 15)])
    page += _page([("gpt-6-sol", 1, 0.1, 1.25, 5)], tier="batch")
    prices = {p.model: p for p in price_book.parse_openai(page)}

    assert set(prices) == {"gpt-6-sol", "gpt-6-luna", "gpt-5.4"}
    assert prices["gpt-6-sol"].output == 10, "the batch table is not the standard one"
    assert prices["gpt-5.4"].cache_write is None


def test_a_read_that_looks_wrong_is_not_believed() -> None:
    few = price_book.parse_openai(_page([("gpt-6-sol", 2, 0.2, 2.5, 10)]))
    assert price_book.check(few, {}), "one row is a page that did not render"

    rows = [("gpt-6-sol", 2, 0.2, 2.5, 200), ("a", 1, 0, 0, 1), ("b", 1, 0, 0, 1)]
    jump = price_book.check(price_book.parse_openai(_page(rows)), {"gpt-6-sol": {"output": 10}})
    assert any("in one read" in p for p in jump)


# ── what to try ─────────────────────────────────────────────────────────────

def _prices(**kw):
    old = datetime.now(timezone.utc) - timedelta(days=90)
    base = {"gpt-6-sol": (2, 10), "gpt-6-luna": (0.1, 0.5), "gpt-6-astra": (10, 50),
            "gpt-5.6-terra": (2, 12), "gpt-5.5-pro": (30, 180)}
    base.update(kw)
    return {m: {"input": i, "output": o, "first_seen": old} for m, (i, o) in base.items()}


def test_only_station_models_are_tried() -> None:
    assert ms.usable("gpt-6-luna") and ms.usable("gpt-5.6-terra")
    for name in ("gpt-5.5-pro", "gpt-5.3-codex", "gpt-image-1.5", "gpt-realtime-2", "gpt-4o"):
        assert not ms.usable(name), name


def test_cheaper_models_are_tried_cheapest_first_writer_first() -> None:
    todo = ms.candidates(_prices(), {"writer": "gpt-6-sol", "reader": "gpt-6-luna"}, set())

    assert [(c["tier"], c["model"]) for c in todo] == [("writer", "gpt-6-luna")]
    assert "cheaper" in todo[0]["why"]


def test_a_model_tried_recently_waits() -> None:
    todo = ms.candidates(_prices(), {"writer": "gpt-6-sol", "reader": "gpt-6-luna"},
                         {("writer", "gpt-6-luna")})
    assert todo == []


def test_a_new_model_a_little_dearer_is_still_worth_a_look() -> None:
    prices = _prices()
    prices["gpt-7-sol"] = {"input": 2.5, "output": 12,
                           "first_seen": datetime.now(timezone.utc) - timedelta(days=2)}
    todo = ms.candidates(prices, {"writer": "gpt-6-sol", "reader": "gpt-6-luna"}, {("writer", "gpt-6-luna")})

    assert [c["model"] for c in todo] == ["gpt-7-sol"]
    assert "new this week" in todo[0]["why"]


# ── deciding ────────────────────────────────────────────────────────────────

def _o(passed=True, score=80, accepted=4, cost=0.02, error=""):
    return ms.Outcome(tier="writer", model="m", role="x", passed=passed, score=score,
                      requested=4, accepted=accepted, cost_usd=cost, error=error)


def test_cheaper_and_as_good_is_recommended() -> None:
    base = ms.summarise([_o() for _ in range(5)])
    cand = ms.summarise([_o(cost=0.004) for _ in range(4)] + [_o(passed=False, cost=0.004)])

    decided, reasons = ms.verdict(cand, base)
    assert decided == "recommended", reasons
    assert any("less" in r for r in reasons)


def test_cheap_per_token_but_not_per_kept_question_is_not() -> None:
    base = ms.summarise([_o() for _ in range(5)])
    cand = ms.summarise([_o(accepted=1, cost=0.018) for _ in range(5)])

    decided, reasons = ms.verdict(cand, base)
    assert decided == "not_recommended"


def test_a_model_that_breaks_the_station_is_not_recommended() -> None:
    base = ms.summarise([_o() for _ in range(5)])
    cand = ms.summarise([_o(cost=0.001, error="SCHEMA_VALIDATION_FAILED") for _ in range(2)]
                        + [_o(cost=0.001) for _ in range(3)])

    decided, reasons = ms.verdict(cand, base)
    assert decided == "not_recommended"
    assert any("failed outright" in r for r in reasons)


def test_worse_work_is_not_recommended_however_cheap() -> None:
    base = ms.summarise([_o() for _ in range(5)])
    cand = ms.summarise([_o(passed=False, score=55, cost=0.001) for _ in range(5)])

    assert ms.verdict(cand, base)[0] == "not_recommended"


# ── trials keep nothing, and never judge themselves ─────────────────────────

def test_a_trial_swaps_only_its_tier_and_never_the_judge() -> None:
    with model_trial.trial("writer", "gpt-6-luna"):
        assert model_trial.model_for("question_generation", "openai") == "gpt-6-luna"
        assert model_trial.model_for("profile_generation", "openai") is None, "a reader stage"
        assert model_trial.model_for("reviewer_panel", "openai") is None, "the judge"
        assert model_trial.model_for("question_generation", "anthropic") is None
    assert model_trial.model_for("question_generation", "openai") is None


def test_the_baseline_runs_dry_on_the_models_in_use() -> None:
    with model_trial.dry_run():
        assert model_trial.active() is not None
        assert model_trial.model_for("question_generation", "openai") is None


def test_the_questions_station_keeps_nothing_during_a_trial() -> None:
    import inspect

    from app.routes import questions

    source = inspect.getsource(questions.factory_generate_questions_batch)
    assert "if normalized_questions and trial is None:" in source
    assert source.count("if trial is None:") >= 2
    assert "model_trial.active() is not None" in inspect.getsource(questions._draw_question_figures)


def test_it_runs_weekly_and_only_admins_see_it() -> None:
    import inspect

    from app.celery_app import celery_app
    from app.routes import model_scout as routes

    assert "weekly-model-scout" in celery_app.conf.beat_schedule
    assert 'require_roles("admin")' in inspect.getsource(routes)
