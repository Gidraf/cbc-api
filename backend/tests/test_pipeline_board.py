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


# ── every grade, not only the started ones ──────────────────────────────────


def test_the_board_lists_every_grade_in_the_curriculum():
    """Listing only what has been started answers "what have I done" and hides
    the question actually being asked. A grade with nothing in it is the most
    actionable row on the board: it is the one to start next."""
    from app.services.grade_order import GRADE_SEQUENCE

    rows = pb.projects()

    assert len(rows) == len(GRADE_SEQUENCE)
    assert [r["grade"] for r in rows] == [g for g, _, _ in GRADE_SEQUENCE]


def test_the_grades_are_in_curriculum_order_not_alphabetical():
    rows = [r["grade"] for r in pb.projects()]

    assert rows.index("grade-pp1") < rows.index("grade-2")
    assert rows.index("grade-2") < rows.index("grade-12")


def test_a_grade_says_whether_its_design_has_been_read_in():
    for row in pb.projects():
        assert "ingested" in row
        assert "level" in row


def test_a_grade_is_compared_case_insensitively_on_both_sides():
    """The rows are written "grade-pp1"; a caller sending "PP1" derives
    "grade-PP1", which is not equal to it in Postgres — and the board then
    reported a grade with seven ingested designs as having no sub-strands at
    all. Fixed once on the sub-strands endpoint and reintroduced here."""
    import pathlib

    source = (pathlib.Path(__file__).resolve().parents[1]
              / "app/services/pipeline_board.py").read_text()

    assert "a.grade = :grade OR a.grade = :alt_grade" not in source
    assert "LOWER(a.grade) = LOWER(:grade)" in source
    assert source.count("grade = :grade OR grade = :alt") == 0


# ── starting work from the board, and watching it ───────────────────────────


def test_a_stage_can_be_started_from_the_board():
    """Starting work meant leaving the board, finding the factory, choosing the
    same grade and subject again, and pressing a station."""
    import inspect

    from app.routes import pipelines

    source = inspect.getsource(pipelines.run_stage)
    assert "_queue_stage" in source
    assert "is not a pipeline stage" in source


def test_a_stage_reports_what_its_jobs_did():
    """A stage that says "2 failed" and cannot say what failed is a red light
    with no wiring behind it."""
    import inspect

    from app.routes import pipelines

    source = inspect.getsource(pipelines.stage_logs)
    assert "result->'progress'" in source
    assert "ORDER BY COALESCE(finished_at, started_at, created_at) DESC" in source


def test_the_log_is_scoped_to_the_stage_and_grade_asked_for():
    import inspect

    from app.routes import pipelines

    source = inspect.getsource(pipelines.stage_logs)
    assert "kind = :stage" in source
    assert "LOWER(grade) = LOWER(:grade)" in source


def _view() -> str:
    import pathlib

    return (pathlib.Path(__file__).resolve().parents[2]
            / "frontend-web/src/views/Pipelines.tsx").read_text()


def test_the_board_can_run_a_stage_and_then_follow_it():
    view = _view()

    assert "function StageLog(" in view
    assert 'act.mutate({ grade, stage: stage.stage, subject: branch.subject, action: "run" })' in view


def test_a_run_in_flight_is_polled_and_an_idle_one_is_not():
    queries = (__import__("pathlib").Path(__file__).resolve().parents[2]
               / "frontend-web/src/lib/queries.ts").read_text()

    assert 'queryKey: ["stage-logs"' in queries
    assert "busy > 0 ? 2000 : false" in queries


def test_a_grade_that_has_not_been_ingested_is_pointed_at_the_next_step():
    """A dead row is worse than no row: it says something is wrong and nothing
    about what to do."""
    assert "Import the design" in _view()
    assert "not ingested" in _view()


# ── an unattended run is a pipeline run ─────────────────────────────────────


def test_the_auto_run_reports_itself_in_pipeline_stages():
    """A percentage answers "how far" and nothing about WHERE — and an operator
    watching a grade run overnight is asking which stage is slow, not what
    fraction is done."""
    from app.routes.curriculum import _auto_run_stages

    stages = _auto_run_stages([
        {"stage": "notes", "total": 7, "queued": 2, "running": 1, "done": 4,
         "failed": 0, "cost": 0.12},
    ])
    notes = next(s for s in stages if s["stage"] == "notes")

    assert notes["label"] == "Lesson plan"
    assert notes["status"] == "running"
    assert notes["percentage"] == 57


def test_a_stage_the_run_has_not_reached_is_listed_with_zeros():
    """The shape of the whole pipeline is what says how far there is still to
    go, and a board that grows as work arrives cannot be read at a glance."""
    from app.routes.curriculum import _auto_run_stages
    from app.services import stage_policy

    stages = _auto_run_stages([{"stage": "notes", "total": 7, "done": 7}])

    assert [s["stage"] for s in stages] == list(stage_policy.STAGES)
    assert next(s for s in stages if s["stage"] == "questions")["status"] \
        == "not_reached"


def test_a_failing_stage_is_reported_as_failing_however_much_is_done():
    from app.routes.curriculum import _auto_run_stages

    stages = _auto_run_stages([
        {"stage": "notes", "total": 7, "done": 6, "failed": 1}])

    assert next(s for s in stages if s["stage"] == "notes")["status"] == "failing"


def test_the_running_job_carries_the_steps_it_is_writing():
    """Without them "running · 94s" reads the same whether it is thinking or
    wedged, which is the whole question an operator has at 94s."""
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_auto_run_activity)
    assert "result->'progress' AS progress" in source
    assert "by_subject" in source


def _auto_view() -> str:
    import pathlib

    return (pathlib.Path(__file__).resolve().parents[2]
            / "frontend-web/src/views/AutoRunActivity.tsx").read_text()


def test_the_auto_run_shows_the_stage_strip_not_only_a_bar():
    view = _auto_view()

    assert "Stages" in view
    assert "STAGE_TONE" in view
    assert "not_reached" in view


def test_the_auto_run_narrates_the_job_on_the_bench():
    assert "job.progress?.steps" in _auto_view()


def test_the_auto_run_lives_on_the_board():
    """It IS a pipeline run, so it belongs where a person looks for one rather
    than in a panel of its own with its own words for the same stages."""
    import pathlib

    board = (pathlib.Path(__file__).resolve().parents[2]
             / "frontend-web/src/views/Pipelines.tsx").read_text()

    assert "<AutoRunPanel grade={grade} />" in board
    assert "<AutoRunActivity grade={grade} running />" in board


# ── every action, where the stage is ────────────────────────────────────────


def test_a_stage_can_be_run_reviewed_approved_or_regenerated_from_the_board():
    """Each of these already existed, on a different screen, asking for the
    same grade and subject again. The board is the screen that knows what a
    stage is short of."""
    import inspect

    from app.routes import pipelines

    source = inspect.getsource(pipelines.act_on_stage)
    for action in ("run", "review", "approval", "regenerate"):
        assert f'"{action}"' in source, action
    assert "_queue_stage" in source
    assert "factory_queue_review" in source
    assert "factory_queue_regenerate" in source


def test_an_action_a_stage_cannot_take_says_why():
    import inspect

    from app.routes import pipelines

    source = inspect.getsource(pipelines.act_on_stage)
    assert "does not file versions, so there is nothing" in source
    assert "is not something a stage can be asked for" in source


def test_a_stage_says_which_versions_still_need_something():
    """A stage that says "5 of 7 not reviewed" and cannot say WHICH five leaves
    a person to go and find them, which is the work the board was supposed to
    remove."""
    import inspect

    from app.routes import pipelines

    source = inspect.getsource(pipelines.stage_units)
    assert "DISTINCT ON (a.artifact_key)" in source, "one row per thing, latest version"
    assert "approval_state" in source
    assert "can_approve" in source


def test_a_stage_with_no_versions_of_its_own_says_so_rather_than_looking_empty():
    from app.routes import pipelines

    assert "ingest" not in pipelines.STAGE_KIND
    assert "strands" not in pipelines.STAGE_KIND


# ── approving in bulk is still a signature ──────────────────────────────────


def test_bulk_approval_still_needs_a_person_to_say_they_read_it():
    import inspect

    from app.routes import pipelines

    source = inspect.getsource(pipelines.approve_units)
    assert "reviewed_by_me" in source
    assert "they do not replace" in source


def test_a_version_that_cannot_be_approved_is_reported_not_skipped():
    """A bulk action that silently does less than it says is worse than one
    that refuses."""
    import inspect

    from app.routes import pipelines

    source = inspect.getsource(pipelines.approve_units)
    assert "refused.append(" in source
    assert '"counts": {"approved"' in source


def test_bulk_approval_runs_the_same_gate_per_artifact():
    """Not a second, looser path to the same label."""
    import inspect

    from app.routes import pipelines

    assert "apply_label(" in inspect.getsource(pipelines.approve_units)


def _view() -> str:
    import pathlib

    return (pathlib.Path(__file__).resolve().parents[2]
            / "frontend-web/src/views/Pipelines.tsx").read_text()


def test_the_board_offers_every_action_on_the_stage_panel():
    view = _view()

    for label in ("Run", "Review", "Send to the approver",
                  "Regenerate from findings", "Versions & approve"):
        assert f">{label}<" in view or f"{label}" in view, label


def test_review_is_offered_only_once_there_is_something_to_review():
    """An action that cannot work is worse than one that is not offered: it
    reads as broken."""
    view = _view()

    assert "disabled={act.isPending || !stage.built}" in view
    assert "disabled={act.isPending || !stage.reviewed}" in view


def test_the_unit_list_says_what_each_version_still_needs():
    view = _view()

    assert "ready to sign" in view
    assert "approvable over an objection" in view
    assert "u.blockers[0]" in view


def test_refusals_are_shown_after_a_bulk_approval():
    assert "refused:" in _view()


# ── the journey starts at the dataset ───────────────────────────────────────


def test_the_first_stage_answers_whether_the_design_arrived():
    """`ingest` went green the moment a design row existed, which says nothing
    about the dataset it came from — whether anything is waiting, whether an
    item failed, or whether the grade has simply never been imported. A grade
    with nothing in it read as "not started" either way, and "no design" and
    "never imported" are different problems with different next actions."""
    state = pb.dataset_state("grade-pp1")

    assert set(state) >= {"state", "note", "designs", "items", "by_status"}


def test_a_grade_nobody_has_imported_says_where_to_start():
    state = pb.dataset_state("grade-pp1")

    assert state["state"] == "not_imported"
    assert "starts at the Langfuse dataset" in state["note"]


def test_a_failed_dataset_item_is_a_hole_in_every_stage_after_it():
    stage = _stage("ingest")
    stage.dataset = {"state": "failing", "note": "1 item(s) failed to read.",
                     "designs": 0, "items": 3, "by_status": {"failed": 1}}
    pb._decide(stage, sp.default_for("ingest"))

    assert stage.status == "failing"
    assert "failed to read" in stage.blocked_by


def test_the_dataset_state_beats_the_row_count_on_the_first_stage():
    """A design row existing is not the same as the dataset being read."""
    stage = _stage("ingest", built=1, approved=1)
    stage.dataset = {"state": "not_imported", "note": "Nothing has been imported.",
                     "designs": 0, "items": 0, "by_status": {}}
    pb._decide(stage, sp.default_for("ingest"))

    assert stage.status == "not_started"


# ── resetting a stage rather than a grade ───────────────────────────────────


def test_a_stage_can_be_thrown_away_on_its_own():
    """Clearing a whole grade to re-run the diagrams costs the lesson plans
    that were fine, and clearing nothing means living with the first attempt."""
    assert set(pb.RESET_KINDS) == {
        "notes", "material", "diagram", "media", "simulation", "activity",
        "questions"}


def test_a_stage_that_files_nothing_says_so_rather_than_deleting_a_grade():
    """Clearing the design a grade was built from is a very large action to
    put behind a very small button."""
    result = pb.reset_stage("grade-pp1", "CRE", "ingest")

    assert not result["supported"]
    assert "not a stage" in result["reason"]


def test_a_reset_is_a_dry_run_until_the_word_is_typed():
    """Two steps, always: the first says what would go, the second does it."""
    import inspect

    source = inspect.getsource(pb.reset_stage)

    assert 'confirm.strip().upper() != "DELETE"' in source
    assert '"dry_run": True' in source
    assert "everything else stays" in source, \
        "it should say what survives a stage reset"


def test_queued_work_goes_with_the_stage_it_would_rebuild():
    """A job left behind runs and rebuilds what was just deleted, which reads
    as the reset silently undoing itself."""
    import inspect

    source = inspect.getsource(pb.reset_stage)
    assert "DELETE FROM jobs" in source
    assert "silently undoing itself" in source


def test_reviews_and_labels_go_before_the_versions_they_point_at():
    import inspect

    source = inspect.getsource(pb.reset_stage)
    reviews = source.index("artifact_reviews")
    versions = source.index("DELETE FROM artifacts a")

    assert reviews < versions


def test_clearing_a_whole_grade_goes_through_the_factory_reset():
    """Reimplementing it would miss the tables a stage reset has no business
    in — designs, sub-strands, ingest status."""
    import inspect

    from app.routes import pipelines

    source = inspect.getsource(pipelines.reset)
    assert "curriculum_routes.factory_reset(" in source
    assert "factory_reset.CONFIRMATION" in source


def _view() -> str:
    import pathlib

    return (pathlib.Path(__file__).resolve().parents[2]
            / "frontend-web/src/views/Pipelines.tsx").read_text()


def test_the_console_shows_what_would_go_before_it_goes():
    """A reset that clears more than the operator pictured is the one they find
    out about a week later."""
    view = _view()

    assert "function ResetButton(" in view
    assert 'confirm: "DELETE"' in view
    assert "Counting…" in view


def test_reset_is_offered_at_the_stage_the_subject_and_the_grade():
    view = _view()

    assert 'label={`Reset ${stage.label.toLowerCase()}`}' in view
    assert 'label="Reset this subject"' in view
    assert 'label="Reset"' in view


def test_a_grade_with_nothing_in_it_is_pointed_at_the_dataset():
    view = _view()

    assert "Import the design" in view
    assert "Import from Langfuse" in view


def test_the_board_does_not_offer_actions_that_can_only_fail() -> None:
    """"ingest does not file versions, so there is nothing to review."

    That message is correct, and an operator should never have been able to
    reach it. Review, Send to the approver and Regenerate all act on filed
    versions; `ingest`, `strands` and `substrands` write curriculum rows and
    file none. The buttons were shown on every stage and enabled as soon as the
    stage had built anything, so pressing Review on a grade whose design had
    just been read failed every time.
    """
    from app.services import pipeline_board

    for stage in ("ingest", "strands", "substrands"):
        assert pipeline_board.Stage(stage=stage).files_versions is False
    for stage in ("notes", "material", "diagram", "media", "simulation",
                  "activity", "questions"):
        assert pipeline_board.Stage(stage=stage).files_versions is True

    # And the board tells the console, rather than the console guessing.
    assert "files_versions" in pipeline_board.Stage(stage="notes").to_dict()


def test_what_a_stage_files_is_recorded_in_exactly_one_place() -> None:
    """Two copies drift the first time a station is added, and the half that is
    missed silently refuses every action on it."""
    from app.routes import pipelines as routes
    from app.services import pipeline_board

    assert routes.STAGE_KIND is pipeline_board.STAGE_KIND

    source = open("app/routes/pipelines.py").read()
    assert 'STAGE_KIND: dict[str, str] = {' not in source, "the routes must not redeclare it"


def test_the_console_hides_those_actions_rather_than_greying_them_out() -> None:
    """A greyed-out Review reads as "not yet", which is a different and wrong
    answer — the stage will never have anything to review."""
    board = " ".join(
        open("../frontend-web/src/views/Pipelines.tsx").read().split()
    )

    assert "{stage.files_versions ? (" in board
    assert "Files no versions of its own" in board
    assert "it is checked by what comes after it" in board


def test_a_structure_stage_is_queued_through_the_mechanism_that_can_run_it() -> None:
    """There are two queues, and the board only ever used one.

    `queue-work` fans a station out across sub-strands that already exist.
    `ingest`, `strands` and `substrands` have no sub-strands to fan out across
    — they are what CREATES them — and run through the pipeline queue instead.
    Sending them to `queue-work` gave "Cannot queue strands. Known: activity,
    diagram, material, media, notes, questions, simulation.", which meant the
    board could not build the first three stages of its own chain and no grade
    could be started from it at all.
    """
    import inspect

    from app.routes import pipelines

    source = inspect.getsource(pipelines._queue_stage)
    assert "factory_queue_pipeline" in source, "structure stages"
    assert "factory_queue_work" in source, "the stations"
    assert "STAGE_KIND" in source, "one rule decides which, and it is the board's"

    # And the stages that need the pipeline queue are exactly the ones that
    # file no versions, so there is one fact here rather than two lists.
    from app.services import pipeline_board

    for stage in ("ingest", "strands", "substrands"):
        assert not pipeline_board.STAGE_KIND.get(stage)
    for stage in ("notes", "material", "diagram", "questions"):
        assert pipeline_board.STAGE_KIND.get(stage)


def test_the_dataset_panel_is_not_shown_where_there_is_no_dataset() -> None:
    """An empty dict is falsy in Python and TRUTHY in JavaScript, so "Dataset:
    item(s) imported, design(s) read in" — with no numbers in it — appeared
    under every stage."""
    from app.services import pipeline_board

    assert pipeline_board.Stage(stage="strands").to_dict()["dataset"] is None
    assert pipeline_board.Stage(
        stage="ingest", dataset={"state": "done"}
    ).to_dict()["dataset"] == {"state": "done"}

    board = open("../frontend-web/src/views/Pipelines.tsx").read()
    assert "{stage.dataset?.state && (" in board
