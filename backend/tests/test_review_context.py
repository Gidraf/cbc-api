"""What the reviewer is shown, and what it is fair to score it on.

Two defects met here. The design lookup was written for sub-strands and used
for every kind, so a strand artifact — which has no sub_strand_name — matched
no row, got an empty comparison, and the miss was logged at DEBUG and
swallowed: strand reviews scored curriculum_alignment against nothing and
reported a number for it.

And the dimensions were read as though every artifact should contain
everything. A strand list came back at 40 on completeness and 50 on guideline
adherence for lacking sub-strands, outcomes, core competencies, values and
PCIs — none of which a strand list carries. It was marked down for not being a
different artifact.
"""
from __future__ import annotations

import json

import pytest

from app.services import review_context
from app.services.artifact_registry import Artifact
from app.services.review_layers import KIND_SCOPE, MAX_ARTIFACT_CHARS, build_messages


def _artifact(kind, **kwargs):
    return Artifact(
        artifact_id="a1", kind=kind, grade="grade-pp1",
        subject="Christian Religious Education", strand_name="The Bible",
        content=kwargs.pop("content", {"x": 1}), **kwargs,
    )


# ── The rubric fits the artifact ────────────────────────────────────────────

def test_a_strand_list_is_not_marked_down_for_lacking_sub_strands() -> None:
    system = build_messages(_artifact("strand", sub_strand_name=""), 2)[0]["content"]

    assert "WHAT A 'strand' ARTIFACT IS" in system
    assert "their absence here is correct" in system
    assert "not being something it was never meant to be" in system


def test_the_completeness_bar_is_the_kinds_own_contents() -> None:
    for kind in ("strand", "sub_strand", "notes", "photo_prompt", "question"):
        system = build_messages(_artifact(kind, sub_strand_name="A Holy Book"), 2)[0]["content"]
        assert KIND_SCOPE[kind]["holds"][:40] in system, f"{kind} has no completeness bar"


def test_a_photo_prompt_is_not_expected_to_be_programmable() -> None:
    """A diagram is SVG and editable; a photograph is neither."""
    system = build_messages(_artifact("photo_prompt", sub_strand_name="A Holy Book"), 2)[0]["content"]

    assert "not the photo" in system
    assert "neither generated as code" in system


def test_an_activity_without_hazards_is_not_a_defect() -> None:
    system = build_messages(_artifact("experiment", sub_strand_name="A Holy Book"), 2)[0]["content"]

    assert "invented hazards" in system


# ── Grounding per kind ──────────────────────────────────────────────────────

def test_a_strand_artifact_is_grounded_in_the_designs_strand_summary(monkeypatch) -> None:
    """It used the sub-strand lookup, matched nothing, and said nothing."""
    monkeypatch.setattr("app.infra.db.fetch_one", lambda *a, **k: None)
    monkeypatch.setattr("app.infra.db.fetch_all", lambda *a, **k: [])

    grounding = review_context.for_artifact(_artifact("strand", sub_strand_name=""))

    assert grounding.found, "the published catalogue alone is enough to judge against"
    assert "Creation" in grounding.text
    assert "90 lessons" in grounding.text


def test_a_missing_grounding_says_why(monkeypatch) -> None:
    monkeypatch.setattr("app.infra.db.fetch_one", lambda *a, **k: None)

    grounding = review_context.for_artifact(
        _artifact("notes", sub_strand_name="Nowhere In The Design")
    )

    assert not grounding.found
    assert "Nowhere In The Design" in grounding.missing_reason
    assert "before reviewing content derived from it" in grounding.missing_reason


def test_an_ungrounded_review_is_told_not_to_score_alignment() -> None:
    """Scoring it anyway means scoring against the model's own recollection of a
    Kenyan curriculum, which is the failure this review exists to catch."""
    user = build_messages(
        _artifact("strand", sub_strand_name=""), 2,
        design_extract="", missing_design="Nothing is stored for it.",
    )[1]["content"]

    assert "NO DESIGN WAS AVAILABLE" in user
    assert "not_applicable" in user
    assert "Nothing is stored for it." in user


# ── Descendants as context, not as the thing under review ───────────────────

def test_the_strands_own_sub_strands_are_shown_for_context() -> None:
    """Five names alone give a reviewer nothing to judge completeness against."""
    user = build_messages(
        _artifact("strand", sub_strand_name=""), 2,
        design_extract="the design",
        descendants="The Bible:\n  2.1 A Holy Book — 7 lessons, 3 outcome(s)",
    )[1]["content"]

    assert "FOR CONTEXT" in user
    assert "A Holy Book" in user
    assert "This is NOT under review" in user
    assert "do not mark the artifact down for content that lives here" in user


# ── Truncation is stated, not silent ────────────────────────────────────────

def test_a_truncated_artifact_says_so() -> None:
    """Judged silently, a cut-off artifact scores well on completeness because
    nothing told the reviewer the tail was missing."""
    huge = {"modules": ["word " * 200 for _ in range(200)]}
    assert len(json.dumps(huge)) > MAX_ARTIFACT_CHARS

    user = build_messages(_artifact("notes", content=huge, sub_strand_name="A Holy Book"), 2)[1]["content"]

    assert "TRUNCATED" in user
    assert "Do NOT score `completeness`" in user


def test_an_artifact_that_fits_says_nothing_about_truncation() -> None:
    user = build_messages(_artifact("notes", sub_strand_name="A Holy Book"), 2)[1]["content"]

    assert "TRUNCATED" not in user


# ── The route reports what it sent ──────────────────────────────────────────

def test_the_route_returns_what_the_reviewer_was_shown() -> None:
    """A 94% from a reviewer that was never given the design is not a 94% about
    the curriculum, and the only way to tell them apart is the inputs."""
    route = open("app/routes/artifacts.py").read()

    assert '"inputs": {' in route
    assert '"grounding": grounding.to_dict()' in route
    assert '"truncated"' in route
    assert '"messages": messages' in route


def test_a_grounding_miss_is_warned_not_swallowed() -> None:
    route = open("app/routes/artifacts.py").read()

    assert "logger.debug(\"No design extract" not in route
    assert "has no design to judge against" in route
