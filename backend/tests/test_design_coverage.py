"""Which parts of a KICD design the generated questions actually cover.

`production_coverage` counts what was made. A count cannot say WHICH outcome
has no question against it — a sub-strand can read 100% produced with three of
its five outcomes never assessed, because ten questions on outcome one look
exactly like ten questions spread across five.

This names what is missing.
"""
from __future__ import annotations

import pytest

from app.services import design_coverage as dc

DESIGN = {
    "strand_name": "Numbers", "sub_strand_name": "Integers",
    "allocated_hours": "6 lessons",
    "slos": [
        {"slo_id": "g9-mat-01", "slo": "perform combined operations on integers"},
        {"slo_id": "g9-mat-02", "slo": "apply integers to real life situations"},
    ],
    "key_inquiry_questions": ["How do we use negative numbers in daily life?"],
    "core_competencies": ["Critical thinking and problem solving"],
    "values": ["Responsibility"],
    "learning_experiences": ["Learners work out combined operations in groups"],
    "required_diagrams": ["A number line showing negative and positive integers"],
    "experiments": [],
}


def _cover(questions):
    return dc.for_sub_strand(DESIGN, questions, "grade-9", "Mathematics")


# ── naming the gap, not counting the output ─────────────────────────────────


def test_an_outcome_with_no_question_is_named() -> None:
    cover = _cover([{"question_id": "q1",
                     "stem": "Evaluate the combined operations shown.",
                     "curriculum_link": {"slo_id": "g9-mat-01"}}])
    outcomes = next(d for d in cover.dimensions if d.name == "outcomes")

    assert outcomes.covered == 1 and len(outcomes.elements) == 2
    assert [g.ref for g in outcomes.gaps] == ["g9-mat-02"]
    assert "real life" in outcomes.gaps[0].text


def test_a_recorded_outcome_link_beats_word_overlap() -> None:
    """The question schema carries an slo_id. A recorded link is worth more
    than any amount of word matching, and it is checked first."""
    cover = _cover([{"question_id": "q1", "stem": "Work it out.",
                     "curriculum_link": {"slo_id": "g9-mat-02"}}])
    outcomes = next(d for d in cover.dimensions if d.name == "outcomes")

    assert [e.ref for e in outcomes.elements if e.covered] == ["g9-mat-02"]


def test_ten_questions_on_one_outcome_do_not_cover_five() -> None:
    """The failure this exists to catch."""
    cover = _cover([{"question_id": f"q{i}",
                     "stem": "Evaluate the combined operations shown.",
                     "curriculum_link": {"slo_id": "g9-mat-01"}}
                    for i in range(10)])
    outcomes = next(d for d in cover.dimensions if d.name == "outcomes")

    assert cover.questions == 10
    assert outcomes.percent == 50.0


# ── a dimension the design is silent about is not a gap ─────────────────────


def test_a_dimension_the_design_never_states_is_not_scored_as_missing() -> None:
    """Reporting it as a gap would send somebody to write content the
    curriculum never asked for, and the way to raise the score would be to
    invent an experiment."""
    cover = _cover([])
    experiments = next(d for d in cover.dimensions if d.name == "experiments")

    assert not experiments.stated
    assert experiments.to_dict()["status"] == dc.NOT_STATED
    assert experiments.gaps == []
    assert "nothing to cover" in experiments.note


def test_the_total_is_weighted_over_what_the_design_states() -> None:
    cover = _cover([])

    assert all(d.stated for d in cover.stated)
    assert "experiments" not in [d.name for d in cover.stated]


def test_a_design_that_states_nothing_still_carries_its_grade_s_demand() -> None:
    """The demand floor comes from the GRADE, not from the design text, so a
    sub-strand nobody has extracted yet still has a bar to clear. Every other
    dimension is silent because the design said nothing to be silent about."""
    empty = dc.for_sub_strand({"sub_strand_name": "x"}, [], "grade-9", "Maths")

    assert empty.percent == 0.0
    assert [d.name for d in empty.stated] == ["demand"]
    assert {g.kind for d in empty.dimensions for g in d.gaps} == {"rung"}


# ── demand is a dimension of its own ────────────────────────────────────────


def test_an_outcome_can_be_covered_and_the_demand_still_unmet() -> None:
    """A real and common combination: the outcome is assessed by a question
    that asks the learner to name something, and the rubric it is marked
    against asks them to compare."""
    cover = _cover([
        {"question_id": "q1",
         "stem": "Name the combined operations used on these integers.",
         "curriculum_link": {"slo_id": "g9-mat-01"}},
        {"question_id": "q2",
         "stem": "List the ways integers apply to real life situations.",
         "curriculum_link": {"slo_id": "g9-mat-02"}},
    ])
    outcomes = next(d for d in cover.dimensions if d.name == "outcomes")
    demand = next(d for d in cover.dimensions if d.name == "demand")

    assert outcomes.percent == 100.0
    assert demand.gaps, "every question is a recall question"
    assert any("analyse" in g.text for g in demand.gaps)


def test_the_demand_dimension_says_where_its_floor_came_from() -> None:
    demand = next(d for d in _cover([]).dimensions if d.name == "demand")

    assert "band floor" in demand.note or "profile" in demand.note


def test_the_youngest_have_no_demand_dimension_to_fail() -> None:
    cover = dc.for_sub_strand(DESIGN, [], "grade-pp1", "Mathematical Activities")
    demand = next(d for d in cover.dimensions if d.name == "demand")

    assert not demand.stated


# ── the view a person uses to decide what to generate next ──────────────────


def test_the_report_ranks_the_weakest_aspect_across_a_scope() -> None:
    report = dc.Report(grade="grade-9", subject="Mathematics")
    report.sub_strands = [_cover([]), _cover([
        {"question_id": "q1", "stem": "Compare how integers apply to real life "
                                      "situations and to combined operations."}])]

    by_dimension = report.by_dimension()
    names = [d["name"] for d in by_dimension]

    assert names[0] != "experiments", "a not_stated dimension sorts last"
    assert by_dimension[-1]["status"] == dc.NOT_STATED
    assert {d["name"] for d in by_dimension} == set(dc.WEIGHTS)


def test_the_report_says_which_sub_strands_to_work_on() -> None:
    report = dc.Report(grade="grade-9", subject="Mathematics")
    report.sub_strands = [_cover([])]

    worst = report.worst()

    assert worst and worst[0]["sub_strand"] == "Integers"
    assert worst[0]["gaps"] > 0
    assert worst[0]["worst_dimension"]


def test_every_weight_belongs_to_a_dimension_that_is_built() -> None:
    """A weight for a dimension nothing produces silently rescales the total."""
    built = {d.name for d in _cover([]).dimensions}

    assert built == set(dc.WEIGHTS)
    assert abs(sum(dc.WEIGHTS.values()) - 1.0) < 1e-9


def test_reading_a_scope_without_a_database_returns_nothing_rather_than_raising() -> None:
    report = dc.for_scope("grade-9", "Mathematics")

    assert report.sub_strands == [] and report.percent == 0.0
