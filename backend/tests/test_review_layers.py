"""Three layers, scored per dimension, with approval gated on independence.

A single "90%" says nothing about WHAT was 90%. Content can be beautifully
written and misaligned with the design, or exactly aligned and pitched at the
wrong age — both used to score in the eighties.
"""
from __future__ import annotations

import json

import pytest

from app.services import review_layers as review
from app.services import review_vendors as vendors


def _dims(**scores):
    return {name: {"score": value, "evidence": f"because of {name}"}
            for name, value in scores.items()}


def _full(score=90):
    return _dims(**{name: score for name in review.DIMENSIONS})


def test_the_dimensions_are_weighted_and_sum_to_one() -> None:
    assert round(sum(d["weight"] for d in review.DIMENSIONS.values()), 6) == 1.0
    assert "curriculum_alignment" in review.DIMENSIONS
    assert "faith_integrity" in review.DIMENSIONS


def test_an_unreported_dimension_scores_zero_and_says_so() -> None:
    """Defaulting it to a pass is how an unreviewed dimension becomes an
    approved one."""
    scored = review.score_dimensions(_dims(curriculum_alignment=95))

    assert scored["completeness"].score == 0
    assert scored["completeness"].issues == ["not assessed"]
    assert "did not report" in scored["completeness"].evidence


def test_the_overall_is_derived_not_taken_from_the_model() -> None:
    """A model asked for both its dimensions and an overall produces an overall
    that flatters its dimensions."""
    scored = review.score_dimensions(_full(80))
    assert review.overall_from(scored) == 80

    # Even when the model insists otherwise, only the dimensions count.
    verdict = review.from_response(
        {"dimensions": _full(80), "overall_confidence": 99},
        type("A", (), {"artifact_id": "a", "artifact_key": "k"})(),
        2, "anthropic", "claude-3-5-sonnet-20241022",
    )
    assert verdict.overall_confidence == 80


def test_a_not_applicable_dimension_is_excluded_rather_than_scored() -> None:
    """Faith integrity does not apply to Mathematical Activities, and giving it
    a free 100 would inflate every non-religious area."""
    raw = _full(60)
    raw["faith_integrity"] = {"not_applicable": True, "evidence": "not a religious area"}
    scored = review.score_dimensions(raw)

    assert scored["faith_integrity"].not_applicable
    assert review.overall_from(scored) == 60, "the excluded dimension must not move it"


def test_one_weak_dimension_blocks_a_pass_however_high_the_average() -> None:
    """Exactly aligned and pitched at the wrong age is not a pass."""
    scored = review.score_dimensions(
        _dims(curriculum_alignment=100, guideline_adherence=100, factual_correctness=100,
              level_appropriateness=45, faith_integrity=100, completeness=100)
    )
    overall = review.overall_from(scored)

    assert overall >= review.APPROVAL_FLOOR
    assert review.decide(scored, overall) == "revise"


def test_a_bad_dimension_is_a_rejection() -> None:
    scored = review.score_dimensions(_full(30))
    assert review.decide(scored, review.overall_from(scored)) == "reject"


def test_a_strong_review_passes() -> None:
    scored = review.score_dimensions(_full(92))
    assert review.decide(scored, review.overall_from(scored)) == "pass"


def test_the_weakest_dimension_is_named() -> None:
    verdict = review.from_response(
        {"dimensions": _dims(curriculum_alignment=95, guideline_adherence=90,
                             factual_correctness=88, level_appropriateness=40,
                             faith_integrity=100, completeness=85)},
        type("A", (), {"artifact_id": "a", "artifact_key": "k"})(),
        2, "gemini", "gemini-1.5-pro",
    )
    assert verdict.weakest() == "level_appropriateness"


def test_a_regeneration_is_reviewed_as_a_diff() -> None:
    """Re-reading the whole thing invites a different score for unchanged
    content, which makes review look unstable when it is the reading that moved."""
    artifact = type("A", (), {
        "kind": "notes", "grade": "grade-pp1", "subject": "CRE",
        "strand_name": "The Bible", "sub_strand_name": "A Holy Book",
        "version": 4, "content": {"title": "x"},
    })()
    messages = review.build_messages(
        artifact, 2,
        diff_summary={"previous_version": 3, "current_version": 4,
                      "counts": {"added": 1, "removed": 0, "changed": 2}},
    )
    body = messages[1]["content"]

    assert "THIS IS A REGENERATION" in body
    assert "Review WHAT CHANGED" in body
    assert "improvement, a regression" in body


def test_a_first_generation_is_reviewed_whole() -> None:
    artifact = type("A", (), {
        "kind": "notes", "grade": "grade-pp1", "subject": "CRE",
        "strand_name": "", "sub_strand_name": "", "version": 1, "content": {},
    })()
    body = review.build_messages(artifact, 2)[1]["content"]

    assert "THIS IS A REGENERATION" not in body
    assert "THE ARTIFACT UNDER REVIEW" in body


def test_the_prompt_forbids_the_model_reporting_its_own_overall() -> None:
    artifact = type("A", (), {"kind": "notes", "grade": "", "subject": "",
                              "strand_name": "", "sub_strand_name": "",
                              "version": 1, "content": {}})()
    system = review.build_messages(artifact, 2)[0]["content"]

    assert "Do not report an overall figure" in system
    assert "Score each dimension 0-100 SEPARATELY" in system


def test_only_layer_three_can_approve() -> None:
    assert review.LAYERS[1]["can_approve"] is False
    assert review.LAYERS[2]["can_approve"] is False
    assert review.LAYERS[3]["can_approve"] is True


# ── Independence ────────────────────────────────────────────────────────────

def _reviews(*rows):
    return list(rows)


def test_approval_needs_layers_two_and_three(monkeypatch) -> None:
    monkeypatch.setattr(review, "reviews_for", lambda _id: _reviews(
        {"layer": 1, "verdict": "pass", "overall_confidence": 90,
         "provider": "openai", "model": "gpt-4o-mini"},
    ))
    state = review.approval_state("a")

    assert not state["can_approve"]
    assert any("layer 2" in b for b in state["blockers"])
    assert any("layer 3" in b for b in state["blockers"])


def test_one_vendor_reviewing_itself_is_not_a_second_opinion(monkeypatch) -> None:
    """Two models from one vendor share training data and failure modes, so
    that pairing is one opinion asked twice."""
    monkeypatch.setattr(review, "reviews_for", lambda _id: _reviews(
        {"layer": 1, "verdict": "pass", "overall_confidence": 90,
         "provider": "openai", "model": "gpt-4o-mini"},
        {"layer": 2, "verdict": "pass", "overall_confidence": 91,
         "provider": "openai", "model": "gpt-4o"},
        {"layer": 3, "verdict": "pass", "overall_confidence": 90,
         "provider": "openai", "model": "gpt-4o"},
    ))
    state = review.approval_state("a")

    assert not state["can_approve"]
    assert any("same vendor" in b for b in state["blockers"])


def test_a_genuine_second_opinion_can_approve(monkeypatch) -> None:
    monkeypatch.setattr(review, "reviews_for", lambda _id: _reviews(
        {"layer": 1, "verdict": "pass", "overall_confidence": 88,
         "provider": "openai", "model": "gpt-4o-mini"},
        {"layer": 2, "verdict": "pass", "overall_confidence": 91,
         "provider": "anthropic", "model": "claude-3-5-sonnet-20241022"},
        {"layer": 3, "verdict": "pass", "overall_confidence": 90,
         "provider": "gemini", "model": "gemini-1.5-pro"},
    ))
    state = review.approval_state("a")

    assert state["can_approve"], state["blockers"]
    assert state["vendors"] == ["anthropic", "openai"]


def test_a_rejection_at_any_layer_blocks_approval(monkeypatch) -> None:
    monkeypatch.setattr(review, "reviews_for", lambda _id: _reviews(
        {"layer": 1, "verdict": "pass", "overall_confidence": 88,
         "provider": "openai", "model": "gpt-4o-mini"},
        {"layer": 2, "verdict": "reject", "overall_confidence": 30,
         "provider": "anthropic", "model": "claude-3-5-sonnet-20241022"},
        {"layer": 3, "verdict": "pass", "overall_confidence": 90,
         "provider": "gemini", "model": "gemini-1.5-pro"},
    ))
    assert not review.approval_state("a")["can_approve"]


def test_an_approver_that_only_says_revise_does_not_approve(monkeypatch) -> None:
    monkeypatch.setattr(review, "reviews_for", lambda _id: _reviews(
        {"layer": 1, "verdict": "pass", "overall_confidence": 88,
         "provider": "openai", "model": "gpt-4o-mini"},
        {"layer": 2, "verdict": "pass", "overall_confidence": 85,
         "provider": "anthropic", "model": "claude-3-5-sonnet-20241022"},
        {"layer": 3, "verdict": "revise", "overall_confidence": 72,
         "provider": "gemini", "model": "gemini-1.5-pro"},
    ))
    state = review.approval_state("a")

    assert not state["can_approve"]
    assert any("approver did not pass" in b for b in state["blockers"])


# ── Vendors ─────────────────────────────────────────────────────────────────

def test_all_four_vendors_are_offered() -> None:
    assert sorted(vendors.REVIEW_MODELS) == ["anthropic", "gemini", "ollama", "openai"]


def test_a_vendor_is_never_suggested_to_review_itself() -> None:
    assert "openai" not in vendors.independent_of("openai")
    assert set(vendors.independent_of("openai")) == {"anthropic", "gemini", "ollama"}


def test_an_unknown_vendor_is_not_accepted() -> None:
    assert not vendors.is_known("some-startup")


# ── The screen ──────────────────────────────────────────────────────────────

def test_the_approval_screen_is_routed_and_navigable() -> None:
    """The layers existed and nothing in the console reached them."""
    main = open("../frontend-web/src/main.tsx").read()
    shell = open("../frontend-web/src/app/AppShell.tsx").read()

    assert 'path="approvals"' in main
    assert "Approvals" in main
    assert 'to: "/approvals"' in shell


def test_the_screen_shows_dimensions_rather_than_one_number() -> None:
    view = open("../frontend-web/src/views/VersionReview.tsx").read()

    assert "Confidence by dimension" in view
    assert "Evidence" in view
    assert "weakest" in view


def test_approve_is_disabled_with_its_blockers_shown() -> None:
    """A disabled button with no reason is indistinguishable from a broken one."""
    view = open("../frontend-web/src/views/VersionReview.tsx").read()

    assert "canApprove" in view
    assert "blockers.join" in view
    assert "Not approvable yet" in view


def test_the_review_panel_is_shared_rather_than_duplicated() -> None:
    """The standalone screen and the factory must show the same thing. Two
    copies drift, and the one you are not looking at is the one that rots."""
    approvals = open("../frontend-web/src/views/Approvals.tsx").read()
    factory = open("../frontend-web/src/views/ContentFactory.tsx").read()

    assert "VersionReview" in approvals
    assert "VersionReview" in factory
    # The scores themselves are defined once.
    assert "Confidence by dimension" not in approvals


def test_the_panel_is_tabbed() -> None:
    """Versions, the diff, the reviews and the labels are a click apart, not a
    navigation apart: moving between screens made the operator hold the
    previous screen in their head."""
    view = open("../frontend-web/src/views/VersionReview.tsx").read()

    assert "Tabs" in view
    for tab in ("Current version", "Versions", "Review", "Changes", "Comments"):
        assert f'label: "{tab}"' in view, f"the {tab} tab is missing"


def test_the_factory_links_through_to_the_versions_it_filed() -> None:
    view = open("../frontend-web/src/views/CurriculumStructure.tsx").read()

    assert "/approvals?grade=" in view
    assert "Review and approve them" in view


def test_the_console_is_served_built_not_from_a_dev_server() -> None:
    """A dev server transforms every module on request, so a file the module
    graph asks for and cannot find becomes a full-screen error overlay on top of
    the running console. An operator saw an ENOENT for a path that does not
    exist in this repo, covering their curriculum."""
    dockerfile = open("../frontend-web/Dockerfile").read()
    # The comment explains what it replaced, so read the instructions only.
    instructions = "\n".join(
        line for line in dockerfile.split("\n") if not line.strip().startswith("#")
    )

    assert "npm run dev" not in instructions
    assert "npm run build" in instructions
    assert "vite" in instructions and "preview" in instructions
    assert "npm ci" in instructions, "the lockfile pins what was tested"


def test_the_dev_server_cannot_read_outside_the_project() -> None:
    config = open("../frontend-web/vite.config.ts").read()

    assert "strict: true" in config
    assert "allow: [root]" in config


def test_the_api_proxy_survives_the_switch_to_a_built_bundle() -> None:
    """An API that is only reachable in dev works on a laptop and 502s in
    production."""
    config = open("../frontend-web/vite.config.ts").read()

    assert "preview:" in config
    assert config.count("proxy") >= 3, "the same proxy must serve dev and preview"


def test_the_review_panel_is_reachable_from_the_factory_itself() -> None:
    """The decisions belong where the work is. Sending an operator to another
    screen to see what changed and back to decide made them hold the previous
    screen in their head."""
    factory = open("../frontend-web/src/views/ContentFactory.tsx").read()
    structure = open("../frontend-web/src/views/CurriculumStructure.tsx").read()

    assert "StationVersions" in factory
    assert "Versions, review and approval" in factory
    assert "SubStrandVersions" in structure


def test_the_panel_does_not_rebuild_the_servers_identity_rule() -> None:
    """A client-side copy of artifact_key reports "no versions yet" for content
    that exists the moment the two drift."""
    factory = open("../frontend-web/src/views/ContentFactory.tsx").read()
    panel = open("../frontend-web/src/views/VersionReview.tsx").read()

    assert "artifactKeyFor" not in factory, "the key rule was rebuilt on the client"
    assert "useArtifacts(" in factory, "artifacts must be found by asking the server"
    assert "artifact.data?.artifact_key" in panel, (
        "the panel must take the key from the artifact the server returned"
    )


def test_every_station_that_offers_review_actually_files_versions() -> None:
    """A station mapped to a kind it never files shows an empty panel forever."""
    import re

    factory = open("../frontend-web/src/views/ContentFactory.tsx").read()
    routes = open("app/routes/curriculum.py").read()

    block = factory[factory.index("STATION_ARTIFACT_KIND"):]
    block = block[: block.index("};")]
    offered = set(re.findall(r'^\s*(\w+):\s*"(\w+)"', block, re.M))

    filed = set(re.findall(r'_record_artifact\(\s*"(\w+)"', routes))
    for _station, kind in offered:
        assert kind in filed, f"the console offers review of '{kind}', which nothing files"


# ── The console has to be able to reach the stations ────────────────────────

def test_the_factory_does_not_depend_on_coverage_to_offer_a_substrand() -> None:
    """Coverage measures what has been PRODUCED. Using it as the list of what
    exists meant a grade whose coverage came back empty had no selectable
    sub-strand — so no stations rendered, and notes and media were unreachable
    while the sub-strands sat in the database."""
    view = open("../frontend-web/src/views/ContentFactory.tsx").read()

    assert "useSavedSubstrands" in view
    assert "emptyReport" in view, "a zeroed report must let the stations render"
    assert "{progress.data && !substrand && (" not in view, (
        "the sub-strand picker is still gated on the coverage report"
    )


def test_every_station_is_reachable_including_media_and_simulations() -> None:
    view = open("../frontend-web/src/views/ContentFactory.tsx").read()

    for station in ("notes", "visuals", "media", "simulations", "practicals", "questions"):
        assert f'id: "{station}"' in view, f"the {station} station is missing"


def test_a_label_can_be_taken_off_a_version() -> None:
    """A label pinned to the wrong version is worse than no label: `approved`
    means a person signed for THAT version."""
    queries = open("../frontend-web/src/lib/queries.ts").read()
    panel = open("../frontend-web/src/views/VersionReview.tsx").read()

    assert "unlabel: useMutation" in queries
    assert 'method: "DELETE"' in queries
    assert "actions.unlabel.mutate" in panel
    assert "Click to take" in panel


def test_planned_media_is_shown_as_a_picture_not_a_row() -> None:
    """A media brief is a wall of text describing an image, and reading it as
    text is the one way you cannot tell whether it will produce the right
    picture."""
    view = open("../frontend-web/src/views/MediaLibrary.tsx").read()

    assert "function Placeholder" in view
    assert "aspectRatio" in view, "a planned asset must occupy the shape it will have"
    assert 'role="img"' in view
    assert "<img" in view and "<video" in view


def test_the_media_library_is_routed_and_navigable() -> None:
    main = open("../frontend-web/src/main.tsx").read()
    shell = open("../frontend-web/src/app/AppShell.tsx").read()

    assert 'path="media"' in main
    assert 'to: "/media"' in shell


def test_a_station_coverage_does_not_measure_cannot_crash_the_screen() -> None:
    """Stations and coverage dimensions are not the same list and never will be:
    a station is added the moment its generator exists, and weighting it in
    coverage is a separate decision. Reading the dimension directly meant adding
    the simulations station took the whole screen down with "Cannot read
    properties of undefined (reading 'percentage')"."""
    view = open("../frontend-web/src/views/ContentFactory.tsx").read()

    assert "function dimensionFor" in view
    assert "(selected.report as any)[station.id]" not in view
    assert "(selected.report as any)[station.requires]" not in view
    assert "(selected.report as any)[k]" not in view, (
        "the summary grid still indexes the report directly"
    )
    assert "unmeasured" in view, "an unmeasured station must say so, not read 0%"
