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
