"""Coverage has to count everything the factory produces.

Photographs and videos were produced and counted by nothing, so a sub-strand
with a full media plan scored the same as one with none. And "produced" was
being read as "done": every artifact could be an unreviewed draft and the
sub-strand still read 100%.
"""
from __future__ import annotations

from app.services.coverage import WEIGHTS, compute_substrand_coverage


def _node(**over):
    node = {"allocated_hours": "7 lessons", "slos": [{"id": "a"}, {"id": "b"}]}
    node.update(over)
    return node


def test_the_weights_still_sum_to_one() -> None:
    assert round(sum(WEIGHTS.values()), 6) == 1.0


def test_media_is_a_scored_dimension() -> None:
    assert "media" in WEIGHTS
    dims = compute_substrand_coverage(_node(), {})["dimensions"]
    assert "media" in dims


def test_a_planned_photo_is_not_a_produced_one() -> None:
    """Planning a photograph is authoring a prompt; the asset does not exist
    until somebody produces it."""
    report = compute_substrand_coverage(_node(), {
        "media": [{"status": "planned"}, {"status": "planned"}],
    })
    media = report["dimensions"]["media"]

    assert media["planned"] == 2
    assert media["generated"] == 0
    assert media["percentage"] == 0


def test_produced_media_scores() -> None:
    report = compute_substrand_coverage(_node(), {
        "media": [{"status": "produced"}, {"status": "produced"}],
    })
    assert report["dimensions"]["media"]["percentage"] == 100


def test_the_design_decides_how_much_media_is_needed() -> None:
    report = compute_substrand_coverage(
        _node(required_media=["a", "b", "c", "d"]),
        {"media": [{"status": "produced"}] * 2},
    )
    media = report["dimensions"]["media"]

    assert media["required"] == 4
    assert media["percentage"] == 50
    assert media["estimated"] is False


def test_a_missing_media_requirement_is_flagged_as_estimated() -> None:
    report = compute_substrand_coverage(_node(), {})
    assert report["dimensions"]["media"]["estimated"] is True


def test_approval_is_a_scored_dimension() -> None:
    """Produced is not the same as fit to teach."""
    assert "approved" in WEIGHTS
    report = compute_substrand_coverage(_node(), {
        "approved": {"total": 10, "approved": 4},
    })
    approved = report["dimensions"]["approved"]

    assert approved["percentage"] == 40
    assert approved["remaining"] == 6


def test_approval_is_never_estimated() -> None:
    """A guessed approval is the one number that must never be guessed."""
    report = compute_substrand_coverage(_node(), {})
    assert report["dimensions"]["approved"]["estimated"] is False
    assert report["dimensions"]["approved"]["percentage"] == 0


def test_everything_produced_but_nothing_approved_is_not_complete() -> None:
    generated = {
        "notes": {"hour_modules": [{}] * 7},
        "diagrams": [{}] * 14,
        "activities": [{}] * 7,
        "questions": [{"curriculum": {"slo_id": "a"}}, {"curriculum": {"slo_id": "b"}}] * 6,
        "media": [{"status": "produced"}] * 2,
        "approved": {"total": 12, "approved": 0},
    }
    report = compute_substrand_coverage(_node(), generated)

    assert report["dimensions"]["approved"]["percentage"] == 0
    assert not report["production_ready"], "unreviewed drafts are not production ready"
    assert report["overall_percentage"] < 100


def test_the_progress_report_feeds_media_and_approvals_in() -> None:
    """Coverage can only score what the report hands it."""
    source = open("app/routes/admin_langfuse.py").read()

    assert "FROM substrand_media" in source
    assert "label = 'approved'" in source
    assert 'generated["media"]' in source
    assert 'generated["approved"]' in source
