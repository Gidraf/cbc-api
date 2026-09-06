"""How much of a grade's curriculum has actually been produced, in one place.

Coverage was computed inside the coverage ROUTE, so the pipeline board — where
an operator actually stands while working — had a weaker idea of progress: it
counted sub-strands touched, not curriculum met. A stage tile read "3 of 3"
beside a Coverage screen reading 34%, and neither number explained the other.
"""
from __future__ import annotations

import inspect

import pytest

from app.services import production_coverage as pc

BLUEPRINTS = [
    {"subject": "Mathematics", "strand_name": "Numbers", "sub_strand_name": "Integers",
     "allocated_hours": 8, "required_diagrams": ["number line", "operations"],
     "experiments": [], "slos": ["slo-1", "slo-2"]},
    {"subject": "Mathematics", "strand_name": "Numbers", "sub_strand_name": "Indices",
     "allocated_hours": 4, "required_diagrams": [], "experiments": [], "slos": []},
]


@pytest.fixture
def filed(monkeypatch):
    from app.services import scope_key, substrand_bundle

    monkeypatch.setattr(pc, "_blueprints", lambda g, s: list(BLUEPRINTS))
    monkeypatch.setattr(substrand_bundle, "index_for_grade", lambda g, s="": {
        scope_key.key("Mathematics", "Integers"): {
            "notes": {"modules": [{}, {}, {}]},
            "diagrams": [{}, {}],
            "activities": [],
            "questions": [{}] * 5,
        }})


def test_it_measures_against_the_design_not_against_what_was_produced() -> None:
    """Measuring completion against what exists means a stage that produced
    nothing is 100% complete."""
    d = pc.Dimension(generated=12, required=20)

    assert d.remaining == 8
    assert d.percentage == 60
    assert "12 of 20 produced, 8 remaining" in d.to_dict()["says"]


def test_a_complete_dimension_says_so() -> None:
    assert "complete" in pc.Dimension(generated=5, required=5).to_dict()["says"]


def test_producing_more_than_required_is_not_over_a_hundred() -> None:
    assert pc.Dimension(generated=40, required=20).percentage == 100
    assert pc.Dimension(generated=40, required=20).remaining == 0


def test_an_estimated_target_says_that_it_is_estimated() -> None:
    """A sub-strand whose design gave no figure is measured against a fallback,
    and a number derived from a guess must say so."""
    says = pc.Dimension(generated=0, required=3, estimated=True).to_dict()["says"]

    assert "target estimated" in says
    assert "gave no figure" in says


def test_the_overall_is_weighted_by_what_each_dimension_requires() -> None:
    """Averaging the percentages would let a sub-strand needing one diagram
    count as much as one needing twelve."""
    report = pc.Report(dimensions={"notes": pc.Dimension(8, 10),
                                   "visuals": pc.Dimension(2, 20)})

    assert report.percentage == 33, "averaging would say 85"


def test_a_grade_with_no_design_measures_nothing_rather_than_a_hundred(monkeypatch) -> None:
    monkeypatch.setattr(pc, "_blueprints", lambda g, s: [])
    report = pc.report("grade-9", "Mathematics")

    assert report.substrands == 0
    assert report.percentage == 0


def test_it_counts_what_is_filed_per_dimension(filed) -> None:
    report = pc.report("grade-9", "Mathematics")

    assert report.substrands == 2
    assert report.measured == 1, "only Integers has anything filed"
    assert report.dimensions["notes"].generated == 3
    assert report.dimensions["visuals"].generated == 2
    assert report.dimensions["questions"].generated == 5


def test_the_requirement_totals_across_every_substrand(filed) -> None:
    """Integers asks for 8 hours and 2 diagrams; Indices asks for 4 hours and
    has no diagram list, so its visual target is estimated."""
    report = pc.report("grade-9", "Mathematics")

    assert report.dimensions["notes"].required == 12
    assert report.dimensions["visuals"].estimated is True, "Indices gave no figure"


def test_a_stage_is_mapped_to_the_dimension_it_owes(filed) -> None:
    report = pc.report("grade-9", "Mathematics")

    assert report.for_stage("diagram") is report.dimensions["visuals"]
    assert report.for_stage("questions") is report.dimensions["questions"]
    # `material`, `media` and `simulation` have no blueprint requirement — the
    # design says how many diagrams a sub-strand needs, not how many
    # recordings — so they get no invented target.
    assert report.for_stage("material") is None
    assert report.for_stage("media") is None


def test_work_matching_no_substrand_is_reported(monkeypatch) -> None:
    from app.services import scope_key, substrand_bundle

    monkeypatch.setattr(pc, "_blueprints", lambda g, s: [BLUEPRINTS[0]])
    monkeypatch.setattr(substrand_bundle, "index_for_grade", lambda g, s="": {
        scope_key.key("Mathematics", "Integers"): {},
        scope_key.key("Mathematics", "Something Else"): {}})

    said = " ".join(pc.report("grade-9", "Mathematics").unmatched)
    assert "something else" in said


# ── where it is shown ───────────────────────────────────────────────────────


def test_every_board_stage_carries_what_the_curriculum_still_wants() -> None:
    """"3 of 3 sub-strands" and "12 of 84 diagrams" are both true and only one
    of them is progress."""
    from app.services import pipeline_board

    source = inspect.getsource(pipeline_board.branch)
    assert "production_coverage.report(" in source
    assert "produced.for_stage(name)" in source
    # Measured once for the branch, not seven times.
    assert source.count("production_coverage.report(") == 1


def test_the_funnel_shows_the_grade_not_only_the_day() -> None:
    """500 questions written is a good day and still 3% of a curriculum."""
    from pathlib import Path

    from app.routes import questions

    assert "production_coverage.report(" in inspect.getsource(
        questions.question_throughput_board)

    frontend = Path(__file__).resolve().parents[2] / "frontend-web"
    panel = " ".join((frontend / "src/ui/QuestionPipeline.tsx").read_text().split())
    assert "Curriculum produced" in panel
    assert "left</span>" in panel, "what remains, beside what is done"
    assert "title={d.says}" in panel, "the full sentence on hover"


def test_the_stage_tile_shows_what_is_left() -> None:
    from pathlib import Path

    frontend = Path(__file__).resolve().parents[2] / "frontend-web"
    tiles = " ".join((frontend / "src/views/Pipelines.tsx").read_text().split())

    assert "stage.coverage.remaining" in tiles
    assert "title={stage.coverage.says}" in tiles
    assert "stage.coverage.percentage" in tiles, "the bar means the curriculum"


def test_each_substrand_carries_its_own_numbers(filed) -> None:
    """The sub-strand chooser had a second computation of its own and read 0%
    for the one sub-strand the coverage panel on the same screen showed as the
    only one with anything filed. Two numbers about the same thing, on the same
    page, disagreeing."""
    rows = {r.name: r for r in pc.report("grade-9", "Mathematics").per_substrand}

    assert set(rows) == {"Integers", "Indices"}
    assert rows["Integers"].filed is True
    assert rows["Integers"].percentage > 0, "it has notes, diagrams and questions"
    assert rows["Indices"].filed is False
    assert rows["Indices"].percentage == 0


def test_a_substrand_row_is_weighted_the_same_way_the_grade_is() -> None:
    row = pc.SubStrand(dimensions={"notes": pc.Dimension(8, 10),
                                   "visuals": pc.Dimension(2, 20)})

    assert row.percentage == 33, "averaging would say 85, as it does for a grade"


def test_the_rows_travel_on_the_report(filed) -> None:
    out = pc.report("grade-9", "Mathematics").to_dict()

    assert len(out["substrand_rows"]) == 2
    assert out["substrand_rows"][0]["dimensions"]["notes"]["says"]
