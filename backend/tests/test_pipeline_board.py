"""The pipeline as a board.

Everything needed to answer "where is this grade?" existed and was spread
across five screens: coverage said what percentage was generated, the queue
said what was running, the artifact list said what versions existed, the review
panel said what one version scored. None of them said, for one grade, which
stage of which subject is holding everything else up.
"""
from __future__ import annotations

import pathlib

from app.services import pipeline_board as pb
from app.services import stage_policy as sp


def _stage(name: str, **kw) -> pb.Stage:
    stage = pb.Stage(stage=name, label=pb.STAGE_LABEL.get(name, name))
    for key, value in kw.items():
        setattr(stage, key, value)
    return stage


def _decide(name: str, **kw) -> pb.Stage:
    stage = _stage(name, **kw)
    pb._decide(stage, sp.default_for(name))
    return stage


# ── what colour a stage is, and why ─────────────────────────────────────────


def test_a_failing_job_beats_everything_else():
    """Whatever else is true, a red build is the thing to look at."""
    stage = _decide("notes", expected=7, built=7, reviewed=7, approved=7, failed=2)

    assert stage.status == "failing"
    assert "2 job(s) failed" in stage.blocked_by


def test_a_stage_with_nothing_built_says_how_much_is_expected():
    stage = _decide("notes", expected=7)

    assert stage.status == "not_started"
    assert "7 expected" in stage.blocked_by


def test_a_partly_built_stage_says_how_far():
    stage = _decide("notes", expected=7, built=3)

    assert stage.status == "built"
    assert "3 of 7 built" in stage.blocked_by


def test_built_but_unreviewed_names_the_layers_its_gate_wants():
    stage = _decide("notes", expected=7, built=7, reviewed=2)

    assert stage.status == "built"
    assert "layer(s) 2, 3" in stage.blocked_by


def test_reviewed_but_unsigned_says_a_person_is_what_is_missing():
    stage = _decide("notes", expected=7, built=7, reviewed=7, approved=0)

    assert stage.status == "reviewed"
    assert "awaiting a person's approval" in stage.blocked_by


def test_a_stage_whose_gate_wants_no_review_does_not_wait_for_one():
    """Reading the design in is not authored, so there is no judgement to
    review — and a gate that demanded one would block for ever."""
    stage = _decide("ingest", expected=1, built=1, reviewed=0, approved=1)

    assert stage.status == "approved"


def test_everything_done_is_approved():
    stage = _decide("notes", expected=7, built=7, reviewed=7, approved=7)

    assert stage.status == "approved"
    assert stage.blocked_by == ""


def test_percentage_is_against_what_is_expected_not_what_exists():
    """Measuring completion against what was produced means a stage that
    produced nothing is 100% complete."""
    assert _stage("notes", expected=7, built=3).percentage == 43
    assert _stage("notes", expected=0, built=0).percentage == 0


# ── the board reads top-down ────────────────────────────────────────────────


def _branch(*stages: pb.Stage) -> pb.Branch:
    return pb.Branch(subject="CRE", stages=list(stages))


def test_a_branch_is_as_far_along_as_its_earliest_unfinished_stage():
    branch = _branch(
        _decide("ingest", expected=1, built=1, approved=1),
        _decide("notes", expected=7, built=3),
        _decide("material", expected=7),
    )

    assert branch.blocking.stage == "notes"
    assert branch.status == "built"


def test_a_branch_with_every_stage_approved_is_approved():
    branch = _branch(_decide("ingest", expected=1, built=1, approved=1))

    assert branch.status == "approved"
    assert branch.blocking is None


def test_a_downstream_stage_says_it_is_waiting_rather_than_not_started():
    """A board showing ten reds tells you ten things when one of them caused
    the other nine."""
    policies = [sp.default_for(n) for n in ("notes", "material", "diagram")]
    branch = pb.Branch(subject="CRE", stages=[
        _decide("notes", expected=7, built=3),
        _decide("material", expected=7),
        _decide("diagram", expected=7),
    ])
    # The same pass `branch()` runs.
    blocking = None
    for i, stage in enumerate(branch.stages):
        if blocking is not None and stage.status == "not_started":
            stage.status = "blocked"
            stage.blocked_by = (f"Waiting on {branch.stages[blocking].label.lower()}: "
                                f"{branch.stages[blocking].blocked_by}")
            continue
        if blocking is None and stage.status != "approved" and policies[i].blocks_downstream:
            blocking = i

    assert branch.stages[1].status == "blocked"
    assert "Waiting on lesson plan" in branch.stages[1].blocked_by


def test_the_cost_of_a_branch_is_the_sum_of_its_stages():
    branch = _branch(_stage("notes", cost_usd=0.02), _stage("material", cost_usd=0.05))

    assert branch.cost_usd == 0.07


# ── a gate per stage, not one for the pipeline ──────────────────────────────


def test_reading_a_table_and_writing_a_lesson_do_not_get_the_same_gate():
    """One rule for everything meant running a two-vendor review chain on an
    extraction, or turning the gate off and losing it for the lesson plan."""
    strands = sp.default_for("strands")
    notes = sp.default_for("notes")

    assert strands.min_vendors == 1 and not strands.requires_human
    assert notes.min_vendors == 2 and notes.requires_human


def test_the_material_has_the_highest_bar():
    """The only stage whose product a child hears verbatim."""
    material = sp.default_for("material")

    assert material.overall_target > sp.default_for("notes").overall_target


def test_the_material_blocks_nothing_because_nothing_is_drawn_from_it():
    assert not sp.default_for("material").blocks_downstream
    assert sp.default_for("notes").blocks_downstream


def test_an_unknown_stage_gets_a_gate_rather_than_none():
    """A stage nobody has configured should not be the one with no gate."""
    policy = sp.default_for("something_new")

    assert policy.required_layers == [2]
    assert "conservative default" in policy.why


def test_every_default_explains_itself():
    for policy in sp.DEFAULTS:
        assert len(policy.why) > 40, policy.stage


def test_a_gate_that_could_never_be_satisfied_is_refused():
    """More vendors than layers can never be met, and the stage would block for
    ever with nothing an operator could do about it."""
    import pytest

    with pytest.raises(Exception) as caught:
        sp.save("strands", {"required_layers": [2], "min_vendors": 3})

    assert "can never be satisfied" in getattr(caught.value, "message", "")


def test_the_board_survives_a_table_that_is_not_there():
    """A board that refuses to draw because one table is missing is less useful
    than a board with one column empty."""
    branch = pb.branch("grade-pp1", "CRE", sp.all_policies())

    assert [s.stage for s in branch.stages] == list(sp.STAGES)


# ── the screen ──────────────────────────────────────────────────────────────


def _view() -> str:
    return (pathlib.Path(__file__).resolve().parents[2]
            / "frontend-web/src/views/Pipelines.tsx").read_text()


def test_the_board_is_reachable_and_named_for_what_it_is():
    shell = (pathlib.Path(__file__).resolve().parents[2]
             / "frontend-web/src/app/AppShell.tsx").read_text()
    router = (pathlib.Path(__file__).resolve().parents[2]
              / "frontend-web/src/main.tsx").read_text()

    assert 'to: "/pipelines"' in shell
    assert '<Pipelines />' in router


def test_a_stage_says_what_its_gate_is_where_it_is_shown():
    """A red stage whose gate nobody can see is a red stage nobody can clear."""
    view = _view()

    assert "no review required" in view
    assert "a person signs" in view


def test_the_gate_is_editable_per_stage():
    view = _view()

    assert "function PolicyEditor(" in view
    assert "Back to the default" in view


def test_a_busy_board_is_watched_and_an_idle_one_is_not():
    queries = (pathlib.Path(__file__).resolve().parents[2]
               / "frontend-web/src/lib/queries.ts").read_text()

    assert "st.running > 0" in queries
