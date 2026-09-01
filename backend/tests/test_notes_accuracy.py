"""Accuracy defects that applied to every subject and every grade.

The notes came back good and the panels around them were wrong: the inspector
said "No design attached" for a fully grounded run, the gate said source
grounding was not measurable while 31,689 characters of design sat in the
prompt, six of fourteen correct citations were reported as unsupported because
KICD prints in narrow columns, and the research dossier handed the generator
four invented statistics under a heading reading "VERIFIED".
"""
from __future__ import annotations

import pytest

from app.services.citation_check import reconcile_pages, verify
from app.services.web_research import web_research_agent as agent

_RULE = "=" * 80
_DESIGN = (
    f"{_RULE}\nPAGE 203 OF 296\n{_RULE}\n\n"
    "The learner is guided to:\n"
    "• say the name of God in their mother tongue or\n"
    "language of catchment area,\n"
    "• use gestures to describe God; Mungu ni mkuu na\n"
    "wa ajabu sana,\n"
)


# ── The dossier must not invent evidence ────────────────────────────────────

def test_unretrieved_figures_are_never_called_verified() -> None:
    """"85% of children who demonstrate understanding of Christian values [KICD
    Annual Report 2022]" came from a generated teaching profile, with zero
    sources retrieved, under a heading saying VERIFIED."""
    block = agent._build_formatted_context(
        "Christian Religious Education", "Our God", [],
        [{"metric": "Children understanding Christian values", "value": "85%",
          "source": "KICD Annual Report 2022"}],
        [], [], [],
    )

    assert "VERIFIED EMPIRICAL DATA" not in block
    assert "UNVERIFIED" in block
    assert "DO NOT USE IN THE CONTENT" in block
    assert "never cite them" in block


def test_figures_from_real_sources_are_not_disclaimed() -> None:
    from app.services.web_research import ResearchCitation

    block = agent._build_formatted_context(
        "Agriculture", "Soil fertility",
        [ResearchCitation(title="KALRO soils", url="https://kalro.org/x",
                          source_domain="kalro.org", snippet="pH 5.2")],
        [{"metric": "Mean topsoil pH", "value": "5.2", "source": "KALRO 2023"}],
        [], [], [],
    )

    assert "FIGURES FROM THE RETRIEVED SOURCES" in block
    assert "UNVERIFIED" not in block


def test_no_sources_says_so_rather_than_naming_institutions() -> None:
    """It used to print "Authoritative KICD Curriculum Standards & KALRO
    Scientific Publications" when nothing at all had been retrieved."""
    block = agent._build_formatted_context("Mathematical Activities", "Numbers",
                                           [], [], [], [], [])

    assert "NONE. No source was retrieved" in block


@pytest.mark.parametrize("subject,strand,expected", [
    ("Christian Religious Education", "Creation", False),
    ("Language Activities", "Reading", False),
    ("Agriculture", "Crop production", True),
])
def test_agriculture_is_only_researched_for_agricultural_subjects(subject, strand, expected) -> None:
    """A Pre-Primary CRE sub-strand searched KALRO for "Our God agricultural
    scientific principles data"."""
    queries = " ".join(
        agent._generate_search_queries(subject, strand, "Our God", "grade-pp1", "notes", "")
    )

    assert ("KALRO" in queries) is expected


def test_laboratory_protocols_are_not_sought_for_singing_songs() -> None:
    queries = " ".join(
        agent._generate_search_queries(
            "Christian Religious Education", "Creation", "Our God", "grade-pp1", "notes", ""
        )
    )

    assert "laboratory experiment apparatus" not in queries


# ── Citations that wrap ─────────────────────────────────────────────────────

def test_a_quote_wrapping_onto_the_next_line_verifies() -> None:
    """KICD prints in narrow columns: 203:2 holds "say the name of God in their
    mother tongue or" and the rest is on 203:3."""
    report = verify(
        {"citations": [{"claim": "a", "ref": "203:2",
                        "quote": "say the name of God in their mother tongue or "
                                 "language of catchment area"}]},
        _DESIGN,
    )

    assert report.verified == 1
    assert "the line wraps" in report.citations[0].reason
    assert report.citations[0].found_at == "203:2-3"


def test_the_wrap_stops_at_the_next_bullet() -> None:
    """A run that swallowed the following bullet would verify a quote against
    text it did not come from."""
    report = verify(
        {"citations": [{"ref": "203:2", "quote": "use gestures to describe God"}]},
        _DESIGN,
    )

    assert report.verified == 0, "the next bullet must not be read as continuation"


def test_a_genuinely_wrong_address_still_fails() -> None:
    report = verify(
        {"citations": [{"ref": "203:2", "quote": "the wise men brought gold and myrrh"}]},
        _DESIGN,
    )

    assert report.verified == 0
    assert "is unsupported" in report.citations[0].reason


def test_a_citation_is_counted_once_not_once_per_mirror() -> None:
    """Notes carry `modules` and a mirrored `hour_modules`, so every citation
    was found twice and fourteen were reported where there are seven."""
    citation = {"ref": "203:4", "quote": "use gestures to describe God"}
    report = verify(
        {"modules": [{"citations": [citation]}],
         "hour_modules": [{"citations": [citation]}]},
        _DESIGN,
    )

    assert report.to_dict()["total"] == 1


# ── Pages must add up ───────────────────────────────────────────────────────

def test_a_strands_pages_and_its_sub_strands_pages_reconcile() -> None:
    report = reconcile_pages("Creation", [202, 203, 204, 205],
                             {"Our God": [202, 203], "God Our Creator": [204, 205]})

    assert report.reconciles
    assert report.uncovered == []


def test_a_page_no_sub_strand_claims_is_named() -> None:
    """Either a sub-strand is missing, or one is citing the wrong pages."""
    report = reconcile_pages("Creation", [202, 203, 204, 205],
                             {"Our God": [202, 203], "God Our Creator": [205]})

    assert not report.reconciles
    assert report.uncovered == [204]


def test_a_sub_strand_citing_outside_its_strand_is_named() -> None:
    report = reconcile_pages("Creation", [202, 203],
                             {"Our God": [202], "God Our Creator": [203, 999]})

    assert [o["page"] for o in report.outside] == [999]


def test_two_sub_strands_claiming_one_page_is_named() -> None:
    report = reconcile_pages("Creation", [202, 203],
                             {"Our God": [202, 203], "God Our Creator": [203]})

    assert [o["page"] for o in report.overlapping] == [203]


# ── The panels must report what actually happened ───────────────────────────

def test_the_inspector_is_shown_the_resolved_design() -> None:
    """It said "No design attached" for a run whose log read "stored design
    (31689 chars)" — it was shown the request field the caller left empty."""
    route = open("app/routes/curriculum.py").read()
    notes = route[route.index("def factory_generate_notes"):]
    notes = notes[: notes.index("\n@router.")]

    assert "source_material=source_text" in notes
    assert "source_material=payload.source_material_text" not in notes


def test_the_quality_gate_is_given_the_design_to_score_grounding_against() -> None:
    route = open("app/routes/curriculum.py").read()
    notes = route[route.index("def factory_generate_notes"):]
    notes = notes[: notes.index("\n@router.")]

    assert '"raw_source": source_text' in notes


def test_the_inspector_can_generate_without_closing() -> None:
    inspector = open("../frontend-web/src/views/PromptInspector.tsx").read()
    factory = open("../frontend-web/src/views/ContentFactory.tsx").read()

    assert "onGenerate" in inspector
    assert "Generate the notes" in factory


# ── padding that no similarity check can see ────────────────────────────────


def _lesson(n, title, slo, ref, experiences):
    return {
        "title": f"Lesson {n}: {title}", "module_number": n,
        "slos_covered": [slo], "citations": [{"ref": ref, "quote": slo}],
        "learning_experiences_used": experiences,
        "exposition_segments": [{"topic": f"Topic {n}", "body": f"body {n} " * 40}],
    }


_PRAYER_AND_SONG = ["say a short prayer to God in groups", "sing songs about God in groups"]


def _seven_lessons_three_outcomes() -> dict:
    """A real guide: PP1 CRE 'Our God', seven funded lessons, three outcomes.

    Lessons 4-7 all teach "appreciate God as a loving heavenly father" from
    203:24, and all four have the learners do the same two things.
    """
    return {"modules": [
        _lesson(1, "Describing God", "identify three qualities of God", "203:23",
                ["say the name of God in their mother tongue"]),
        _lesson(2, "More Qualities", "identify three qualities of God", "203:34",
                ["in turns, say what they know about God"]),
        _lesson(3, "Short Prayers", "practice saying short prayers", "203:21",
                ["sing songs about God in groups"]),
        _lesson(4, "God's Love", "appreciate God as a loving heavenly father", "203:24", _PRAYER_AND_SONG),
        _lesson(5, "God's Provision", "appreciate God as a loving heavenly father", "203:24", _PRAYER_AND_SONG),
        _lesson(6, "Love in Action", "appreciate God as a loving heavenly father", "203:24", _PRAYER_AND_SONG),
        _lesson(7, "Celebrating", "appreciate God as a loving heavenly father", "203:24", _PRAYER_AND_SONG),
    ]}


def test_four_lessons_on_one_outcome_is_reported_as_padding() -> None:
    """The prose differs, so no similarity check charged them, and a guide
    four-sevenths of which was one outcome taught four times scored 100."""
    from app.services import redundancy_check

    report = redundancy_check.inspect(_seven_lessons_three_outcomes())
    group = next(g for g in report["same_outcome_same_source"]
                 if g["ref"] == "203:24")

    assert len(group["lessons"]) == 4
    assert group["same_experiences"] is True, "the guide's own account of what they do"
    assert report["clean"] is False
    assert report["score"] < 70


def test_two_lessons_on_one_outcome_is_depth_not_padding() -> None:
    """An outcome can honestly need two lessons, and often does. Charging that
    would teach an operator to ignore the finding."""
    from app.services import redundancy_check

    notes = {"modules": [
        _lesson(1, "Introducing", "appreciate God", "203:24", ["say the name of God"]),
        _lesson(2, "Practising", "appreciate God", "203:24", ["sing songs about God in groups"]),
    ]}
    group = redundancy_check.inspect(notes)["same_outcome_same_source"][0]

    assert group["same_experiences"] is False
    assert redundancy_check._is_padding(group) is False


def test_the_loop_now_has_lessons_to_rewrite() -> None:
    """This is why it stalled at 77%.

    The finding was reported to the reviewer every time and scored 60 on
    curriculum alignment, but remediation collected rewrite targets only from
    near-duplicates and parallel shapes — so there was nothing to rewrite, the
    regeneration came back identical, and the loop stopped for good.
    """
    from app.services import notes_remediation

    score, findings, targets = notes_remediation._inspect(
        _seven_lessons_three_outcomes(), []
    )

    # Keep lesson 4 — it is the honest one. Rewrite the padding.
    assert targets == [5, 6, 7]
    assert any("all teach" in f for f in findings)
    # And the instruction says what to do, not just what is wrong.
    directive = next(f for f in findings if "all teach" in f)
    assert "Keep the first" in directive
    assert "no lesson has used yet" in directive
