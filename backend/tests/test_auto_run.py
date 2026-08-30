"""Unattended generation, with a floor it stops at.

Set it going, come back, download everything. The danger is that unattended
generation which keeps going while quality collapses produces a grade of
unusable content, at full price, and the operator finds out at the end.
"""
from __future__ import annotations

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

    assert "What runs unattended" in panel
    assert "Untick a stage to keep it for yourself" in panel
    assert "You will run these yourself" in panel
    assert "steps: autoSteps" in panel


def test_learning_areas_can_be_chosen_one_at_a_time():
    panel = " ".join((FRONTEND / "src/views/AutoRunPanel.tsx").read_text().split())

    assert "Which learning areas" in panel
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
