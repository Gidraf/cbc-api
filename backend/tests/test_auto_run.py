"""Unattended generation, with a floor it stops at.

Set it going, come back, download everything. The danger is that unattended
generation which keeps going while quality collapses produces a grade of
unusable content, at full price, and the operator finds out at the end.
"""
from __future__ import annotations

import re

import pathlib

from app.services import auto_run, quality_score

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend-web"


def _run(scores, floor=95.0, window=5, confidence=0.9):
    run = auto_run.AutoRun(floor=floor, window=window)
    halted_at = None
    for index, value in enumerate(scores, start=1):
        run.items.append({
            "label": f"item {index}", "score": value, "confidence": confidence,
            "weakest": "lesson_coverage",
            "counted": confidence >= auto_run.MIN_CONFIDENCE,
        })
        if (halted_at is None and len(run.judged) >= run.window
                and run.recent_median < run.floor):
            halted_at = index
    return run, halted_at


# ── the score ───────────────────────────────────────────────────────────────


def test_the_score_is_built_from_checks_that_actually_ran():
    """Every accuracy figure so far has been a person reading output against
    the design. That is the right way to judge a curriculum and the wrong way
    to gate a machine: it does not exist until somebody does it."""
    healthy = quality_score.score({
        "grounded": True, "source_material_length": 31689,
        "lesson_coverage": {"modules_required": 7, "modules_found": 7,
                            "percentage": 100, "thin_modules": [], "unit": "lessons"},
        "citations": {"total": 7, "verified": 7, "percentage": 100},
        "review_cycles": {"cycles_run": 2, "best_score": 91, "final_passed": True},
    }, "notes")

    assert healthy.score > 95
    assert healthy.weakest == "gate"


def test_the_thin_run_scores_far_below_the_floor():
    """Seven modules between 498 and 798 characters against a 1,500 floor."""
    thin = quality_score.score({
        "grounded": True, "source_material_length": 31689,
        "lesson_coverage": {"modules_required": 7, "modules_found": 7,
                            "percentage": 0,
                            "thin_modules": [{"module": n} for n in range(1, 8)],
                            "unit": "lessons"},
        "citations": {"total": 7, "verified": 7, "percentage": 100},
        "review_cycles": {"cycles_run": 3, "best_score": 76, "final_passed": False},
    }, "notes")

    assert thin.score < 70
    assert thin.weakest == "lesson_coverage"


def test_an_unmeasured_signal_is_excluded_not_scored_zero():
    """Scoring it zero punishes a station for having no citations to check;
    scoring it full lets an unchecked item pass as a verified one."""
    partial = quality_score.score({"grounded": True, "source_material_length": 100}, "strands")

    assert partial.score == 100.0, "measured on grounding alone, and grounded"
    assert partial.confidence < 0.5, "but almost nothing was checked"


def test_confidence_reports_how_much_of_the_scheme_applied():
    full = quality_score.score({
        "grounded": True, "source_material_length": 1,
        "lesson_coverage": {"modules_required": 7, "modules_found": 7, "percentage": 100},
        "citations": {"total": 3, "verified": 3, "percentage": 100},
        "sub_strands": [{"assessment_rubrics": [{"rubric_source": "design"}]}],
        "quality_gate": {"overall_score": 90, "passed": True},
        "fabrication": {"checked_chars": 4000, "score": 100.0, "findings": []},
        "repetition": {"checked": True, "score": 100.0, "findings": []},
        "integrity": {"checked": True, "score": 100.0, "findings": []},
    }, "notes")
    assert full.confidence == 1.0


# ── the halt ────────────────────────────────────────────────────────────────


def test_one_bad_item_does_not_stop_a_grade():
    """A mean halts on a single outlier: four items at 97 and one at 55
    averages 89, and a whole grade stops for one sub-strand that could simply
    be regenerated."""
    run, halted_at = _run([97, 98, 55, 97, 99, 98, 97])

    assert halted_at is None
    assert run.recent_average < 95, "the mean would have halted it"
    assert run.recent_median >= 95, "the median is what decides"


def test_a_real_collapse_stops_it_within_a_few_items():
    run, halted_at = _run([97, 98, 96, 97, 99, 60, 58, 61, 59, 57])

    assert halted_at is not None
    assert halted_at <= 8, "a few sub-strands, not a grade"


def test_a_slow_degrade_is_caught_even_while_the_lifetime_average_looks_fine():
    """A run that starts well and degrades has a lifetime average that stays
    healthy long after the output stops being usable."""
    run, halted_at = _run([99, 99, 99, 99, 99, 92, 88, 84, 80, 78])

    assert halted_at is not None
    assert run.average > 85, "the lifetime average never fell through the floor"


def test_a_healthy_run_is_never_halted():
    _, halted_at = _run([97, 98, 96, 97, 99, 98, 97, 96, 99, 97])
    assert halted_at is None


def test_it_will_not_decide_before_the_window_is_full():
    """Halting on the first two items is halting on the variance of two items."""
    _, halted_at = _run([10, 10])
    assert halted_at is None


def test_items_judged_on_too_little_evidence_do_not_vote():
    """An item scored on one signal out of five is not a pass, and a run that
    halted on three of them would be halting on noise."""
    run, halted_at = _run([10, 10, 10, 10, 10, 10], confidence=0.2)

    assert halted_at is None
    assert run.judged == []
    assert len(run.items) == 6, "still recorded, just not voted on"


def test_the_halt_names_the_item_and_what_let_it_down():
    """"Quality dropped" is not actionable. "Our God at 55, lesson coverage"
    is."""
    run = auto_run.AutoRun(floor=95.0, window=3)
    for label, value in (("notes: Our God", 40), ("notes: A Holy Book", 42),
                         ("notes: The Wise Men", 38)):
        run.items.append({"label": label, "score": value, "confidence": 0.9,
                          "weakest": "lesson_coverage", "counted": True})
    assert run.recent_median < run.floor

    body = run.to_dict()
    assert body["weakest_items"][0]["label"] == "notes: The Wise Men"


# ── wiring ──────────────────────────────────────────────────────────────────


def test_a_halted_run_cancels_what_it_had_not_started():
    """Otherwise the queue keeps producing exactly the content the halt
    decided was not worth producing."""
    source = (BACKEND / "app/routes/curriculum.py").read_text()
    runner = source[source.index("def _run_queued_pipeline"):]
    runner = runner[: runner.index("\ndef _advance_pipeline")]

    assert "auto_run.record(" in runner
    assert "job_queue.cancel(batch_id=" in runner
    # And it does NOT advance to the next stage after halting.
    assert runner.index("halted is not None") < runner.index("advanced = _advance_pipeline")


def test_every_scored_item_is_recorded_even_when_it_does_not_halt():
    source = (BACKEND / "app/services/auto_run.py").read_text()
    fn = source[source.index("def record("):]
    assert "run.items.append(" in fn
    assert "UPDATE auto_runs SET items" in fn


def test_the_panel_says_what_the_score_is_not():
    """A floor of 95 means nothing if the operator thinks it means the accuracy
    a person reading against the design would give."""
    # JSX wraps prose across lines, so compare on normalised whitespace.
    panel = " ".join((FRONTEND / "src/views/AutoRunPanel.tsx").read_text().split())

    assert "not the same number as a person reading" in panel
    assert "cannot tell whether a rubric measures the right thing" in panel
    assert "nothing measurable is wrong" in panel


def test_the_migration_exists_and_is_ordered():
    import re

    source = (BACKEND / "app/infra/db.py").read_text()
    assert '"024_auto_runs"' in source
    names = re.findall(r'^\s+"(\d{3}_[a-z0-9_]+)",', source, re.M)
    assert names == sorted(names)


# ── choosing what is automatic and what stays yours ─────────────────────────


def test_stages_can_be_left_out_of_the_run():
    """All-or-nothing forces a choice between doing everything by hand and
    trusting everything to the machine. The expensive or judgement-heavy stages
    are often the ones worth watching."""
    panel = " ".join((FRONTEND / "src/views/AutoRunPanel.tsx").read_text().split())

    assert "The chain" in panel
    assert "Click one to hold it back and run it yourself" in panel
    assert "Held back for you" in panel
    assert "steps: autoSteps" in panel
    # And it does not pretend it can carry on past one: the chain depends on
    # itself, so a held-back stage is where the run ends.
    assert "does not skip past a held-back stage" in panel


def test_learning_areas_can_be_chosen_one_at_a_time():
    panel = " ".join((FRONTEND / "src/views/AutoRunPanel.tsx").read_text().split())

    assert "Learning areas" in panel
    assert "subjects: autoSubjects" in panel
    # And it says why you would start with one.
    assert "read the weakest-items table before turning the rest loose" in panel


def test_review_cycles_are_set_per_run_because_they_are_the_cost():
    """Three passes over a grade is three times the bill, and that should not
    need a deploy to change."""
    panel = " ".join((FRONTEND / "src/views/AutoRunPanel.tsx").read_text().split())
    assert "Review cycles per item" in panel
    assert "review_cycles: cycles" in panel

    source = (BACKEND / "app/routes/curriculum.py").read_text()
    assert 'max_cycles=int(payload.get("review_cycles") or review_cycle.MAX_CYCLES)' in source
    assert '"review_cycles": max(1, payload.review_cycles)' in source


def test_an_empty_subject_selection_still_means_everything():
    """Ticking nothing is how the operator says "all of it", and refusing to
    start would be a worse answer than doing what they meant."""
    source = (BACKEND / "app/routes/curriculum.py").read_text()
    route = source[source.index("def factory_auto_run("):]
    route = route[: route.index("@router.get")]
    assert "if not subjects:" in route
    assert "SELECT DISTINCT subject FROM curriculum_designs" in route


# ── seeing what it is doing, and what it costs ──────────────────────────────


def test_every_model_call_is_metered_in_one_place():
    """Threading a meter through fourteen route handlers guarantees the one
    that gets missed is the one that spends the most."""
    source = (BACKEND / "app/services/llm_client.py").read_text()
    generate = source[source.index("    def generate("):]
    generate = generate[: generate.index("    def _classify_http_error")]

    assert "from .run_meter import add as _meter" in generate
    assert "_meter(usage, config.model, config.provider)" in generate


def test_the_meter_turns_tokens_into_money():
    from app.services import run_meter
    from app.services.cost_tracker import TokenUsage

    run_meter.start("job_x")
    run_meter.add(TokenUsage(prompt_tokens=50_000, completion_tokens=4_000),
                  "gpt-4o", "openai")
    meter = run_meter.stop()

    assert meter.calls == 1
    assert meter.total_tokens == 54_000
    assert meter.cost_usd > 0, "a priced model must produce a cost"


def test_a_call_outside_a_job_is_not_an_error():
    """A plain HTTP request is not part of a run; metering it would be wrong
    and raising would break it."""
    from app.services import run_meter
    from app.services.cost_tracker import TokenUsage

    run_meter.stop()
    run_meter.add(TokenUsage(prompt_tokens=10, completion_tokens=1), "gpt-4o", "openai")
    assert run_meter.current() is None


def test_the_meter_never_fails_a_generation():
    """Losing a cost figure is the lesser harm by a wide margin."""
    from app.services import run_meter

    run_meter.start("job_x")
    run_meter.add(object(), "no-such-model", "no-such-provider")  # nonsense on purpose
    assert run_meter.stop() is not None


def test_a_failed_job_still_records_what_it_spent():
    """Recording only successes makes the bill look smaller than the
    statement."""
    source = (BACKEND / "app/services/job_queue.py").read_text()
    execute = source[source.index("def _execute("):]
    execute = execute[: execute.index("\ndef _loop")]

    failure = execute[execute.index("except Exception"):execute.index("return {\"job_id\": job_id, \"status\": status")]
    assert "cost_usd = cost_usd + :cost" in failure


def test_the_activity_view_answers_the_three_real_questions():
    """What is it doing, is it any good, and what has it cost."""
    source = (BACKEND / "app/routes/curriculum.py").read_text()
    route = source[source.index("def factory_auto_run_activity"):]
    route = route[: route.index("\n@router.post")]

    assert '"now_running"' in route
    assert '"recent"' in route and "'quality'->>'score'" in route
    assert '"spend"' in route and '"cost_usd"' in route
    # The projection is labelled an estimate rather than sold as a quote.
    assert "an estimate" in route


def test_the_projection_is_not_presented_as_a_quote():
    view = " ".join((FRONTEND / "src/views/AutoRunActivity.tsx").read_text().split())
    assert "an estimate, not a quote" in view


def test_the_cost_columns_have_a_migration():
    source = (BACKEND / "app/infra/db.py").read_text()
    assert '"025_job_cost"' in source
    assert "ADD COLUMN IF NOT EXISTS cost_usd" in source

    names = re.findall(r'^\s+"(\d{3}_[a-z0-9_]+)",', source, re.M)
    assert names == sorted(names)


def test_auto_mode_plans_against_the_board_not_beside_it() -> None:
    """The stage picker was a wall of identical buttons in no particular order.

    You chose which stages to run unattended with no idea which of them were
    already done, already failing, or waiting on something upstream — and then
    read the answer on a different screen. The picker is now the board's own
    stage row: same tiles, same words, same counts, in dependency order.
    """
    panel = open("../frontend-web/src/views/AutoRunPanel.tsx").read()
    board = open("../frontend-web/src/views/Pipelines.tsx").read()
    shared = open("../frontend-web/src/views/pipelineVocabulary.ts").read()

    # One vocabulary, imported by both — not two copies that drift apart the
    # first time a stage is renamed on one screen.
    assert 'from "./pipelineVocabulary"' in panel
    assert 'from "./pipelineVocabulary"' in board
    for screen in (panel, board):
        assert "const TONE" not in screen, "the tones belong in the shared module"
        assert "const WORDS" not in screen
    assert "approved" in shared and "waiting upstream" in shared

    # The panel reads real state, so a tile can say what the stage is actually
    # doing rather than only whether it is ticked.
    assert "usePipeline" in panel
    assert "rollupStages" in panel

    # The chain is a chain: one scrolling row in PIPELINE_STEPS order, never
    # wrapped. Wrapping put Questions underneath Read the design.
    assert "overflowX" in panel and "flexWrap" not in panel.split("The chain")[1][:2000]
    assert "PIPELINE_STEPS.map" in panel


def test_auto_mode_refuses_to_quietly_run_a_grade_with_no_design() -> None:
    """A run over a grade whose dataset was never imported produces nothing and
    says so only at the end."""
    panel = open("../frontend-web/src/views/AutoRunPanel.tsx").read()

    assert "nothingImported" in panel
    assert "no design to read" in panel
    assert "/datasets?grade=" in panel


def test_auto_mode_does_not_show_a_score_before_anything_is_scored() -> None:
    """"median 0 of the last 5 - mean 0 across 0 scored item(s)" was shown
    before a run had ever started, and a red zero reads as a failure."""
    panel = open("../frontend-web/src/views/AutoRunPanel.tsx").read()

    assert "items_counted ?? 0) > 0" in panel, "gate on what was counted, not on what was attempted"
    assert "run && scored" in panel


def test_the_rollup_reports_the_stage_that_still_needs_work() -> None:
    """A grade rolled up across seven learning areas has seven answers per
    stage. Reporting the best of them is how a stage reads 'approved' while two
    subjects in it have not started."""
    shared = open("../frontend-web/src/views/pipelineVocabulary.ts").read()

    ranks = shared.split("const RANK = [")[1].split("]")[0]
    order = [w.strip().strip('",') for w in ranks.replace("\n", " ").split() if w.strip(' ",')]
    assert order.index("failing") < order.index("not_started") < order.index("approved")
