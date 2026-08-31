"""A review that finds four real defects and changes nothing is a comment.

Layer 2 came back "pass at 83%" with four specific, correct, actionable
findings — two lessons that were the same lesson, a PCI never addressed, a
nature walk that does not fit the time, an abstraction a four-year-old cannot
hold. Every part needed to act on them existed. All of them waited for a
button, and "pass" made pressing it look unnecessary.
"""
from __future__ import annotations

import pathlib

from app.services import artifact_refinement as ar

# The verdict from the run that prompted this.
AT_83 = {
    "overall_confidence": 83,
    "verdict": "pass",
    "dimensions": {
        "completeness": {"name": "completeness", "score": 95},
        "faith_integrity": {"name": "faith_integrity", "score": 100},
        "factual_correctness": {"name": "factual_correctness", "score": 90},
        "guideline_adherence": {"name": "guideline_adherence", "score": 80},
        "curriculum_alignment": {"name": "curriculum_alignment", "score": 70},
        "level_appropriateness": {"name": "level_appropriateness", "score": 85},
    },
    "issues": [
        {"severity": "medium", "where": "curriculum_alignment",
         "what": "Repetition of content in lessons 3 and 4.",
         "fix": "Consolidate them."},
        {"severity": "low", "where": "guideline_adherence",
         "what": "Self-esteem is not addressed.", "fix": "Add it."},
    ],
}


def _verdict(overall: int, weakest: int = 95, issues: list | None = None) -> dict:
    return {
        "overall_confidence": overall, "verdict": "pass",
        "dimensions": {
            "completeness": {"name": "completeness", "score": 95},
            "curriculum_alignment": {"name": "curriculum_alignment",
                                     "score": weakest},
        },
        "issues": issues if issues is not None else [],
    }


# ── "not broken" and "finished" are different bars ──────────────────────────


def test_a_pass_at_83_with_open_findings_is_not_finished():
    """`decide()` passes at 80 overall with no dimension under 70 — the right
    bar for a gate, the wrong one for stopping work."""
    assert AT_83["verdict"] == "pass"
    assert not ar.meets_target(AT_83)


def test_an_average_that_clears_while_one_dimension_is_poor_is_not_finished():
    assert not ar.meets_target(_verdict(95, weakest=60))


def test_every_dimension_clearing_is_not_enough_while_a_finding_stands():
    """A HIGH finding beside a 94 is a 94 with something seriously wrong in it."""
    assert not ar.meets_target(_verdict(94, weakest=90, issues=[
        {"severity": "high", "what": "A fabricated citation."}]))


def test_a_low_severity_finding_does_not_hold_it_open_for_ever():
    """Otherwise nothing is ever finished, and the loop spends money proving
    it."""
    assert ar.meets_target(_verdict(94, weakest=90, issues=[
        {"severity": "low", "what": "Consider adding follow-up activities."}]))


def test_a_review_that_reported_no_dimensions_does_not_pass_by_saying_nothing():
    assert not ar.meets_target({"overall_confidence": 99, "dimensions": {}})


def test_the_target_is_configurable_because_it_is_a_judgement():
    assert ar.meets_target(_verdict(85, weakest=80),
                           overall_target=80, dimension_target=75)
    assert not ar.meets_target(_verdict(85, weakest=80))


def test_the_weakest_dimension_is_named_with_its_score():
    assert ar.weakest_of(AT_83) == ("curriculum_alignment", 70)


def test_a_not_applicable_dimension_is_not_the_weakest():
    verdict = _verdict(90, weakest=90)
    verdict["dimensions"]["faith_integrity"] = {
        "name": "faith_integrity", "score": 0, "not_applicable": True}

    assert ar.weakest_of(verdict)[1] == 90


def test_what_is_short_is_said_in_the_words_an_operator_would_use():
    reason = ar._why(AT_83, overall_target=90, dimension_target=85)

    assert "83/100 against a target of 90" in reason
    assert "curriculum alignment at 70 against 85" in reason
    assert "Repetition of content in lessons 3 and 4" in reason


# ── the loop ────────────────────────────────────────────────────────────────


def _looper(verdicts: list[dict]):
    """A reviewer that returns each verdict in turn, and a regenerator that
    files a new id each time."""
    seen: list[str] = []
    made: list[str] = []

    def review(artifact_id: str) -> dict:
        seen.append(artifact_id)
        return verdicts[min(len(seen), len(verdicts)) - 1]

    def regenerate(artifact_id: str) -> str:
        made.append(artifact_id)
        return f"art_v{len(made) + 1}"

    return review, regenerate, seen, made


def test_it_stops_the_moment_the_target_is_met():
    review, regenerate, seen, made = _looper([_verdict(94, weakest=90)])
    report = ar.run("art_v1", review=review, regenerate=regenerate)

    assert report.met_target
    assert report.stopped_because == "met_target"
    assert made == [], "it regenerated something that was already good"


def test_it_regenerates_from_the_findings_and_reviews_again():
    review, regenerate, seen, made = _looper([
        AT_83, _verdict(88, weakest=88), _verdict(93, weakest=90)])
    report = ar.run("art_v1", review=review, regenerate=regenerate)

    assert report.met_target
    assert len(report.cycles) == 3
    assert made == ["art_v1", "art_v2"]
    assert seen == ["art_v1", "art_v2", "art_v3"]


def test_a_cycle_that_does_not_help_ends_the_loop():
    """It read the findings and did not act on them. Reading them a third time
    costs the same as the pass that just failed to help."""
    review, regenerate, seen, made = _looper([AT_83, _verdict(84, weakest=70)])
    report = ar.run("art_v1", review=review, regenerate=regenerate)

    assert report.stopped_because == "no_improvement"
    assert not report.met_target


def test_it_is_bounded():
    review, regenerate, seen, made = _looper([
        _verdict(70, weakest=60), _verdict(80, weakest=60),
        _verdict(89, weakest=60), _verdict(95, weakest=60)])
    report = ar.run("art_v1", review=review, regenerate=regenerate,
                    max_cycles=2)

    assert len(report.cycles) == 2
    assert report.stopped_because == "max_cycles"


def test_the_best_version_is_reported_not_the_last():
    """A cycle that made it worse should not be the version an operator is sent
    to."""
    review, regenerate, seen, made = _looper([
        _verdict(70, weakest=60), _verdict(88, weakest=60),
        _verdict(72, weakest=60)])
    report = ar.run("art_v1", review=review, regenerate=regenerate)

    assert report.best_overall == 88
    assert report.best_artifact_id == "art_v2"


def test_a_review_that_throws_does_not_lose_what_came_before():
    def review(artifact_id: str) -> dict:
        raise RuntimeError("provider timed out")

    report = ar.run("art_v1", review=review, regenerate=lambda a: "x")

    assert report.stopped_because == "review_failed"
    assert report.cycles[0].error.startswith("RuntimeError")


def test_a_regeneration_that_files_nothing_stops_rather_than_looping():
    review, _, _, _ = _looper([AT_83])
    report = ar.run("art_v1", review=review, regenerate=lambda a: "")

    assert report.stopped_because == "no_new_version"


def test_what_still_stands_is_reported():
    review, regenerate, _, _ = _looper([AT_83, AT_83])
    report = ar.run("art_v1", review=review, regenerate=regenerate)

    assert not report.met_target
    assert report.outstanding
    assert report.outstanding[0]["severity"] == "medium"


def test_every_cycle_is_narrated():
    steps: list[tuple[str, str, str]] = []
    review, regenerate, _, _ = _looper([AT_83, _verdict(93, weakest=90)])
    ar.run("art_v1", review=review, regenerate=regenerate,
           step=lambda *a: steps.append(a))

    names = [s[0] for s in steps]
    assert "Review 1" in names
    assert "Regenerate 1" in names
    assert "Refinement finished" in names


# ── wiring ──────────────────────────────────────────────────────────────────


def test_the_route_refuses_a_kind_it_cannot_regenerate():
    import inspect

    from app.routes import artifacts

    source = inspect.getsource(artifacts.refine_artifact)
    assert "has no regeneration path" in source
    assert "artifact_refinement.run(" in source


def _panel() -> str:
    return (pathlib.Path(__file__).resolve().parents[2]
            / "frontend-web/src/views/VersionReview.tsx").read_text()


def test_the_console_offers_the_loop_rather_than_only_one_review():
    assert "Review and refine" in _panel()
    assert "actions.refine.mutate({ provider, model })" in _panel()


def test_the_console_says_why_it_stopped_short():
    panel = _panel()

    assert "stopped short" in panel
    assert "Stopped because" in panel


# ── editing a draft by hand ─────────────────────────────────────────────────


def test_a_draft_can_be_edited_and_filed_as_the_next_version():
    """Everything could be generated, reviewed and regenerated, and none of it
    could be FIXED. An operator who could see exactly what was wrong with one
    paragraph had to write a custom instruction, spend a generation, and hope
    the model changed that paragraph and nothing else."""
    panel = _panel()

    assert "function EditDraft(" in panel
    assert "Save as the next version" in panel


def test_the_editor_says_the_signed_version_is_left_alone():
    assert "this one is left" in _panel()


def test_bad_json_is_caught_before_it_is_sent():
    """A misplaced comma should cost a moment, not a round trip and a stack
    trace."""
    assert "That is not valid JSON." in _panel()


def test_the_edit_uses_the_route_that_already_existed():
    """`PUT /artifacts/{id}` already filed a hand edit as the next version. A
    second endpoint doing the same thing is a second thing to keep correct."""
    import inspect

    from app.routes import artifacts

    assert inspect.getsource(artifacts.edit_artifact).count("def edit_artifact") == 1
    assert "update_content" in inspect.getsource(artifacts.edit_artifact)


# ── drawing from a plan nobody has signed ───────────────────────────────────


def test_a_downstream_station_can_ask_whether_the_plan_is_approved():
    """A diagram planned from a plan that then changes is a perfectly good
    picture of the wrong lesson, and nothing downstream notices."""
    from app.services import stage_guard

    assert "diagram" in stage_guard.DOWNSTREAM_OF_PLAN
    assert "simulation" in stage_guard.DOWNSTREAM_OF_PLAN
    assert stage_guard.require_approved_plan(
        "notes", "grade-pp1", "CRE", "Our God") == {"required": False}


# ── clearing a grade has to clear the drafts too ────────────────────────────


def test_clearing_a_grade_removes_the_queued_work_and_its_drafts():
    """A "start again" left every unaccepted sub-strand draft in place and a
    queue still holding jobs for content that no longer exists — which then
    ran, and regenerated it."""
    from app.services.factory_reset import DERIVED

    jobs = next((t for t in DERIVED if t.table == "jobs"), None)

    assert jobs is not None, "queued work and drafts survive a grade reset"
    assert jobs.where("grade-pp1", "")[0]


def test_a_grade_reset_no_longer_orphans_reviews_labels_and_comments():
    """These carry no grade of their own, so a grade-scoped reset SKIPPED them
    — deleting the artifacts and leaving their reviews and labels behind,
    pointing at rows that no longer exist."""
    from app.services.factory_reset import DERIVED

    for table in ("artifact_comments", "artifact_reviews", "artifact_labels"):
        target = next(t for t in DERIVED if t.table == table)
        clause, params = target.where("grade-pp1", "")

        assert clause.startswith("artifact_id IN (SELECT"), table
        assert params["grade"] == "grade-pp1"


def test_a_cleared_grade_can_be_ingested_again():
    """Left behind, `dataset_ingest_status` reported the grade as already
    ingested and the design never came back."""
    from app.services.factory_reset import DERIVED

    target = next(t for t in DERIVED if t.table == "dataset_ingest_status")

    assert target.where("grade-pp1", "")[0]


def test_spend_history_is_not_deleted_to_clear_content():
    """Telemetry is not content, and losing what a grade cost to learn it was
    wrong is not a reset."""
    from app.services.factory_reset import DERIVED

    for table in ("generation_costs", "pipeline_runs"):
        target = next(t for t in DERIVED if t.table == table)
        assert not target.where("grade-pp1", "")[0], table
