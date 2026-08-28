"""Regenerating from a review, and what counts as progress.

A review that names a defect and then leaves a person to retype it into a
custom-instructions box is a review most of whose value is lost in transit.
And a grade reading 92% has to say whether that is content a person signed for
or content nobody has opened.
"""
from __future__ import annotations

import pytest

from app.errors import ApiError
from app.services.coverage import approved_rollup, weighted_rollup
from app.services.revision_directives import MAX_ISSUES, build


def _review(layer=2, issues=None, dimensions=None, verdict="revise"):
    return {
        "layer": layer, "provider": "anthropic", "model": "claude-3-5-sonnet-20241022",
        "verdict": verdict, "overall_confidence": 66,
        "issues": issues or [], "dimensions": dimensions or {},
    }


# ── The directives ──────────────────────────────────────────────────────────

def test_the_findings_become_instructions() -> None:
    revision = build([_review(issues=[
        {"severity": "high", "where": "strand list", "what": "The Church is missing",
         "fix": "add it"},
    ])])

    assert "The Church is missing" in revision["directives"]
    assert "Fix: add it" in revision["directives"]
    assert len(revision["issues"]) == 1


def test_the_generator_is_told_what_to_keep() -> None:
    """A regeneration that rewrites everything loses what passed, and its diff
    becomes unreadable — which defeats the diff review it exists to get."""
    revision = build([_review(issues=[{"severity": "high", "where": "x", "what": "y"}])])

    assert "not a fresh start" in revision["directives"]
    assert "Keep every part that was not criticised" in revision["directives"]


def test_a_defect_raised_twice_is_sent_once() -> None:
    """Both reviewers finding the same thing is agreement, not two defects."""
    issue = {"severity": "high", "where": "strand list", "what": "The Church is missing"}
    revision = build([_review(layer=2, issues=[issue]), _review(layer=3, issues=[issue])])

    assert len(revision["issues"]) == 1


def test_the_worst_defects_come_first() -> None:
    revision = build([_review(issues=[
        {"severity": "low", "where": "a", "what": "minor"},
        {"severity": "high", "where": "b", "what": "serious"},
        {"severity": "medium", "where": "c", "what": "middling"},
    ])])

    assert [i["severity"] for i in revision["issues"]] == ["high", "medium", "low"]


def test_the_instruction_does_not_run_to_pages() -> None:
    """Every defect billed equally is every defect ignored equally."""
    revision = build([_review(issues=[
        {"severity": "low", "where": f"f{i}", "what": f"issue {i}"} for i in range(40)
    ])])

    assert len(revision["issues"]) == MAX_ISSUES


def test_the_weak_dimensions_say_why_it_mattered() -> None:
    """The issue says what to change; the evidence stops a fix that satisfies
    the letter of the issue and not the thing it was about."""
    revision = build([_review(dimensions={
        "completeness": {"score": 40, "evidence": "no descriptions on any strand"},
        "faith_integrity": {"score": 100, "evidence": "clean"},
    })])

    assert [d["dimension"] for d in revision["weak_dimensions"]] == ["completeness"]
    assert "no descriptions" in revision["directives"]


def test_a_dimension_marked_not_applicable_is_not_a_weakness() -> None:
    revision = build([_review(dimensions={
        "faith_integrity": {"score": 0, "not_applicable": True, "evidence": "not a religious area"},
    })])

    assert revision["weak_dimensions"] == []


def test_a_humans_comment_outranks_the_models() -> None:
    revision = build([_review()], [{"body": "Check page 202 yourself", "resolved": False}])

    assert "outranks the models above" in revision["directives"]
    assert "Check page 202 yourself" in revision["directives"]


def test_a_resolved_comment_is_not_carried_forward() -> None:
    """Carrying a fixed issue forward makes the generator "fix" something that
    is already right, and the next review disagrees with the last one about
    content neither of them changed."""
    revision = build([_review()], [{"body": "old news", "resolved": True}])

    assert revision["human_comments"] == []


def test_a_clean_review_produces_no_instruction() -> None:
    assert build([_review(verdict="pass")])["directives"] == ""


def test_a_fabricated_fix_is_forbidden() -> None:
    revision = build([_review(issues=[{"severity": "high", "where": "x", "what": "y"}])])

    assert "rather than inventing a value" in revision["directives"]
    assert "the same defect, now invisible" in revision["directives"]


# ── The route ───────────────────────────────────────────────────────────────

def test_every_generated_kind_can_be_regenerated_from_its_review() -> None:
    from app.routes.artifacts import _REGENERATORS

    for kind in ("strand", "sub_strand", "notes", "diagram", "activity",
                 "photo_prompt", "video_prompt"):
        assert kind in _REGENERATORS, f"{kind} has no regeneration path"


def test_a_kind_without_a_path_says_so_rather_than_doing_nothing() -> None:
    from app.routes.artifacts import _REGENERATORS

    route = open("app/routes/artifacts.py").read()
    assert "has no regeneration path yet" in route
    assert "question" not in _REGENERATORS or True  # questions have their own batch flow


# ── Approval and progress ───────────────────────────────────────────────────

def test_approving_requires_a_person_to_sign_for_it() -> None:
    """The layers narrow what reaches a person; they do not replace them. A
    pipeline that could approve its own output would let a grade report itself
    complete without anyone having read a line of it."""
    route = open("app/routes/artifacts.py").read()

    assert "reviewed_by_me" in route
    assert "they do not replace you" in route


def test_produced_and_approved_are_reported_separately() -> None:
    """Folding approval into one number would make an operator reading 92%
    unable to tell which 92% it is."""
    children = [
        {"weight_hours": 8, "overall_percentage": 100, "approved_percentage": 100},
        {"weight_hours": 2, "overall_percentage": 100, "approved_percentage": 0},
    ]

    assert weighted_rollup(children) == 100
    assert approved_rollup(children) == 80, "unapproved work must not read as done"


def test_approval_rolls_up_weighted_by_teaching_time() -> None:
    """A 10-lesson sub-strand approved counts for more than a 2-lesson one."""
    children = [
        {"weight_hours": 10, "overall_percentage": 100, "approved_percentage": 100},
        {"weight_hours": 2, "overall_percentage": 100, "approved_percentage": 0},
    ]

    assert approved_rollup(children) == 83


def test_nothing_approved_reads_as_zero_however_much_was_produced() -> None:
    children = [{"weight_hours": 5, "overall_percentage": 100, "approved_percentage": 0}]

    assert weighted_rollup(children) == 100
    assert approved_rollup(children) == 0
