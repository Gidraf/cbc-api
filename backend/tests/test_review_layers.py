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
    # Every vendor that reviewed, not only layers 1 and 2. Reporting a subset
    # is how the gate came to check a pair it did not require.
    assert state["vendors"] == ["anthropic", "gemini", "openai"]


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


def test_an_approver_that_says_revise_is_a_warning_a_person_may_overrule(monkeypatch) -> None:
    """`decide()` returns "revise" whenever ANY single dimension falls below
    70, and this pipeline has measured one model scoring the same unchanged
    artifact 40, 70, 95 and 100 on factual_correctness. Treating that as an
    absolute veto meant a guide a person had read and judged fit could not be
    approved, with no way to say so and no way forward."""
    monkeypatch.setattr(review, "reviews_for", lambda _id: _reviews(
        {"layer": 2, "verdict": "pass", "overall_confidence": 85,
         "provider": "anthropic", "model": "claude-3-5-sonnet-20241022"},
        {"layer": 3, "verdict": "revise", "overall_confidence": 72,
         "provider": "gemini", "model": "gemini-2.0-flash"},
    ))
    state = review.approval_state("a")

    assert state["can_approve"], state["blockers"]
    assert state["requires_override"]
    assert any("asked for revision" in w for w in state["warnings"])


def test_a_rejection_is_not_something_a_person_can_sign_past(monkeypatch) -> None:
    monkeypatch.setattr(review, "reviews_for", lambda _id: _reviews(
        {"layer": 2, "verdict": "pass", "overall_confidence": 85,
         "provider": "anthropic", "model": "claude-3-5-sonnet-20241022"},
        {"layer": 3, "verdict": "reject", "overall_confidence": 40,
         "provider": "gemini", "model": "gemini-2.0-flash"},
    ))
    state = review.approval_state("a")

    assert not state["can_approve"]
    assert not state["requires_override"]


def test_a_blocker_names_the_dimension_that_held_it_back(monkeypatch) -> None:
    """"the approver did not pass it" named nothing and pointed nowhere. A
    blocker a person cannot act on is the same defect as a review finding
    nobody can act on."""
    monkeypatch.setattr(review, "reviews_for", lambda _id: _reviews(
        {"layer": 2, "verdict": "pass", "overall_confidence": 85,
         "provider": "anthropic", "model": "claude-3-5-sonnet-20241022"},
        {"layer": 3, "verdict": "revise", "overall_confidence": 72,
         "provider": "gemini", "model": "gemini-2.0-flash",
         "dimensions": {
             "factual_correctness": {"name": "factual_correctness", "score": 55,
                                     "issues": ["Citation 203:26 is wrong"]},
             "completeness": {"name": "completeness", "score": 90, "issues": []},
         }},
    ))
    warning = review.approval_state("a")["warnings"][0]

    assert "factual correctness scored 55" in warning
    assert "against a floor of 70" in warning
    assert "Citation 203:26 is wrong" in warning


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


def test_no_client_route_is_swallowed_by_an_api_proxy_prefix() -> None:
    """A proxy key is matched by PREFIX, so `/pipeline` also caught `/pipelines`.

    The board's own page then answered {"detail": "Not Found"} from the API on a
    refresh while working perfectly when reached from the sidebar, because only
    the refresh is a server request. This has now happened three times —
    /questions, /review, /pipelines — so it is asserted rather than remembered.
    """
    import re

    config = open("../frontend-web/vite.config.ts").read()
    main = open("../frontend-web/src/main.tsx").read()

    prefixes = re.search(r"const API_PREFIXES = \[(.*?)\]", config, re.S)
    assert prefixes, "the proxied prefixes must stay in one readable list"
    proxied = re.findall(r'"(/[^"]+)"', prefixes.group(1))
    assert "/api" in proxied

    routes = [f"/{p}" for p in re.findall(r'path="([a-z-]+)"', main)]
    assert "/pipelines" in routes, "the board's route is the one this regressed on"

    # The keys must be anchored at a path boundary, so a route added later is
    # safe without anyone re-reading this test.
    assert '`^${path}(?:[/?]|$)`' in config, "proxy keys must be anchored regexes"

    # Match the way the running proxy matches, not the way the list reads.
    for route in routes:
        for prefix in proxied:
            key = re.compile(f"^{re.escape(prefix)}(?:[/?]|$)")
            assert not key.match(route), (
                f"the client route {route} is swallowed by the proxied prefix "
                f"{prefix}; the page will answer with API JSON on a refresh"
            )


def test_the_api_base_url_is_an_origin_not_a_mount_point() -> None:
    """This API serves /api/v1/... but ALSO /admin, /generate, /pipeline and
    /health at the root.

    A base of "/api" turned /admin/pipeline-bindings into
    /api/admin/pipeline-bindings — a 404 the console showed as an empty
    Model-per-station screen with no error at all, because a 404 on a list
    endpoint looks exactly like an empty list. It also made every diagram and
    exam render URL /api/api/v1/...
    """
    api = open("../frontend-web/src/api.ts").read()
    compose = open("../docker-compose.yml").read()

    # Empty by default: same origin, and the proxy already routes each prefix.
    assert "VITE_API_BASE_URL: ${VITE_API_BASE_URL:-}" in compose
    assert "ORIGIN, not a mount point" in compose

    # And only an absolute base is ever prepended, so setting it to a path
    # again cannot resurrect the bug.
    assert "export function apiUrl" in api
    assert 'if (!/^https?:\\/\\//i.test(API_BASE_URL)) return cleanPath;' in api

    # Nothing builds an API URL by hand any more; that is how the two render
    # URLs drifted into /api/api/v1 without anyone noticing.
    for screen in ("src/views/DiagramLibrary.tsx", "src/views/ExamBuilder.tsx"):
        source = open(f"../frontend-web/{screen}").read()
        assert "${API_BASE_URL}" not in source
        assert "apiUrl(" in source


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


def test_the_structure_builder_survives_the_first_save() -> None:
    """It was gated on "no sub-strands yet", so saving the first strand's
    sub-strands made it vanish — and with it the only way to generate the other
    four. A learning area is built strand by strand, so the builder has to
    survive its own first success."""
    view = open("../frontend-web/src/views/ContentFactory.tsx").read()

    # Comments wrap, so compare on normalised whitespace.
    flat = " ".join(view.split())

    assert "{!substrand && !saved.isLoading && allSubstrands.length === 0 && (" not in view
    # Rendered whenever the picker is showing — not only when nothing is
    # saved, and not only once a subject is chosen.
    assert "{!substrand && !saved.isLoading && ( <details" in flat
    # Still rendered when there IS work, just collapsed.
    assert "Build more of the structure" in view


def test_the_operator_is_told_how_many_strands_are_left() -> None:
    """Otherwise they have to remember which of five they have done, and the
    thing that would have told them was what disappeared."""
    view = open("../frontend-web/src/views/ContentFactory.tsx").read()

    flat = " ".join(view.split())

    assert "strandsRemaining" in flat
    assert "no sub-strands yet" in flat
    assert "every strand has sub-strands" in flat


def test_saving_sub_strands_refreshes_the_remaining_count() -> None:
    queries = open("../frontend-web/src/lib/queries.ts").read()
    start = queries.index("saveSubstrands: useMutation")
    # To the end of this mutation's onSuccess, not the first "})," which closes
    # the mutationFn's own argument.
    block = queries[start: queries.index('["saved-substrands"]', start) + 40]

    assert "keys.structure(grade, subject)" in block


def test_running_only_the_two_layers_the_gate_asks_for_can_approve(monkeypatch) -> None:
    """The gate requires layers 2 and 3. It then checked the vendors of layers
    1 and 2 — so an operator who ran exactly what was asked was blocked by a
    rule about a layer 1 that had never run, told "layers 1 and 2 used the same
    vendor" about a comparison with nothing on one side, and had no way to
    clear it. Approval was unreachable."""
    monkeypatch.setattr(review, "reviews_for", lambda _id: _reviews(
        {"layer": 2, "verdict": "pass", "overall_confidence": 91,
         "provider": "openai", "model": "gpt-4o"},
        {"layer": 3, "verdict": "pass", "overall_confidence": 90,
         "provider": "anthropic", "model": "claude-3-5-sonnet-20241022"},
    ))
    state = review.approval_state("a")

    assert state["can_approve"], state["blockers"]


def test_the_approver_may_not_share_a_vendor_with_the_review_it_approves(monkeypatch) -> None:
    monkeypatch.setattr(review, "reviews_for", lambda _id: _reviews(
        {"layer": 2, "verdict": "pass", "overall_confidence": 91,
         "provider": "openai", "model": "gpt-4o"},
        {"layer": 3, "verdict": "pass", "overall_confidence": 90,
         "provider": "openai", "model": "gpt-4o-mini"},
    ))
    state = review.approval_state("a")

    assert not state["can_approve"]
    assert any("Re-run layer 3 with a different vendor" in b
               for b in state["blockers"])


def test_a_layer_1_that_never_ran_is_not_a_blocker(monkeypatch) -> None:
    """It is not in the gate's list of required layers, so its absence must
    not be reported as a fault the operator has to fix."""
    monkeypatch.setattr(review, "reviews_for", lambda _id: _reviews(
        {"layer": 2, "verdict": "pass", "overall_confidence": 91,
         "provider": "openai", "model": "gpt-4o"},
        {"layer": 3, "verdict": "pass", "overall_confidence": 90,
         "provider": "gemini", "model": "gemini-2.0-flash"},
    ))
    state = review.approval_state("a")

    assert not any("layer 1" in b for b in state["blockers"])


# ── what reaches the next layer ─────────────────────────────────────────────


def _route_source() -> str:
    import inspect

    from app.routes import artifacts

    return inspect.getsource(artifacts.review_artifact)


def test_only_the_latest_review_of_each_layer_reaches_the_next_one():
    """A layer-2 review run four times gave factual_correctness 95, 40, 100 and
    70 on identical content, and all four were pasted into the layer-3 prompt
    from one vendor, contradicting each other. That is not four opinions; it is
    one model's instability."""
    source = _route_source()

    assert "if layer in superseded:" in source
    assert "prior.append(row)" in source


def test_a_layer_that_disagreed_with_itself_is_reported_as_one_line():
    """Instability is a signal. Three more full reviews are not."""
    source = _route_source()

    assert "HOW STEADY THE EARLIER LAYERS WERE" in source
    assert "a spread of" in source
    assert "confidence as low" in source


def test_an_unparseable_response_is_not_recorded_as_a_rejection():
    """Every dimension zero, a low overall, and a verdict of "reject" that
    looked exactly like a judgement. A reviewer that did not answer has not
    rejected anything, and recording it blocks approval for a reason nobody can
    act on."""
    source = _route_source()

    assert 'if not (content.get("dimensions") or {}):' in source
    assert "returned no scored dimensions" in source
    # And it says how big the prompt was, because that is the usual cause.
    assert "characters; if the artifact is large" in source


def test_approving_over_an_objection_needs_a_reason_and_records_it():
    """An override nobody can find later is not a decision, it is a hole."""
    import inspect

    from app.routes import artifacts

    source = inspect.getsource(artifacts.apply_label)

    assert 'state.get("requires_override") and not payload.override_reason.strip()' in source
    assert "Approved over the approver's objection" in source
    assert 'dimension="approval"' in source


def test_the_console_offers_the_override_rather_than_a_dead_button():
    """"the approver did not pass it" disabled the button and gave a person no
    way forward — on content they had read and judged fit."""
    import pathlib

    panel = (pathlib.Path(__file__).resolve().parents[2]
             / "frontend-web/src/views/VersionReview.tsx").read_text()

    assert "Approvable, over an objection" in panel
    assert "requiresOverride && !override.trim()" in panel, \
        "the reason must be required before the button works"
    assert "override_reason: override" in panel


# ── what the reviewer is given, and what it is told not to say ──────────────


def test_layer_two_reviews_without_seeing_anyone_else_s_verdict():
    """A reviewer shown someone else's scores anchors to them, which is how
    three runs of one model produced three different numbers and every later
    layer inherited whichever it happened to be shown. Layer 3 adjudicates, so
    it does see them."""
    import inspect

    from app.routes import artifacts

    source = inspect.getsource(artifacts.review_artifact)
    assert "if payload.layer >= 3 else []" in source


def test_the_reviewer_is_shown_the_designs_own_scripture_rather_than_asked_to_recall_it():
    """It scored faith_integrity 100 on a PP1 guide teaching the Prodigal Son —
    a parable the PP1 design does not carry. Nothing was wrong with its
    reasoning; it had no list to check against."""
    design = """[PAGE 205]
205:22  c) tell the story of Adam and Eve,
[PAGE 209]
209:29  1Samuel 17:41-49,
[PAGE 206]
206:37  watch or listen to the Bible story in; Mark 10:13-16.
"""
    block = review.design_inventory(design)

    assert "EVERY SCRIPTURE REFERENCE THIS DESIGN NAMES" in block
    assert "1Samuel 17:41" in block and "Mark 10:13" in block
    assert "came from outside the design" in block
    assert "curriculum_alignment" in block


def test_a_design_with_no_named_scripture_produces_no_block():
    """A Mathematics design names none, and an empty inventory would read as
    'the design permits nothing'."""
    assert review.design_inventory("[PAGE 1]\n1:1  Count to ten.\n") == ""
    assert review.design_inventory("") == ""


def test_the_inventory_reaches_the_reviewer():
    artifact = type("A", (), {"kind": "notes", "grade": "grade-pp1",
                              "subject": "CRE", "strand_name": "",
                              "sub_strand_name": "", "version": 1,
                              "content": {}})()
    user = review.build_messages(
        artifact, 2, design_inventory="=== EVERY SCRIPTURE REFERENCE ==="
    )[1]["content"]

    assert "=== EVERY SCRIPTURE REFERENCE ===" in user


def test_a_reviewer_can_read_the_guide_it_is_approving():
    """The version tab showed an outline and a JSON dump — enough to check a
    field is present, not enough to notice that a lesson teaches a parable the
    design does not carry."""
    import pathlib

    panel = (pathlib.Path(__file__).resolve().parents[2]
             / "frontend-web/src/views/VersionReview.tsx").read_text()

    assert 'data.kind === "notes" && (' in panel
    assert "<NotesReader" in panel
