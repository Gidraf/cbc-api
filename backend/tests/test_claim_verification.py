"""Verification must confirm or say it could not — never assert either falsely."""
from __future__ import annotations

import pytest

from app.services import claim_verification as cv


class Citation:
    def __init__(self, url, title="", snippet="", credibility_score=0.9):
        self.url, self.title, self.snippet = url, title, snippet
        self.credibility_score = credibility_score


class Dossier:
    def __init__(self, citations):
        self.citations = citations


# ── Choosing what is worth checking ─────────────────────────────────────────

def test_claims_with_quantities_and_authorities_are_picked():
    text = (
        "Learners should feel encouraged and supported throughout the lesson. "
        "Maize yields in Trans Nzoia average 25 kg per hectare under the KALRO trial protocol. "
        "The teacher may wish to consider grouping the class."
    )
    claims = cv.extract_claims(text)
    assert len(claims) == 1
    assert "KALRO" in claims[0]


def test_pedagogical_prose_asserts_nothing_and_is_not_checked():
    text = "The teacher should encourage learners to think critically and work together in groups."
    assert cv.extract_claims(text) == []


def test_claims_are_found_inside_nested_generated_content():
    content = {"hour_modules": [{"full_lecture_notes":
        "Soil pH between 5.5 and 7.0 supports nutrient uptake, per KALRO guidance from 2019."}]}
    assert any("KALRO" in c for c in cv.extract_claims(content))


# ── Verdicts ────────────────────────────────────────────────────────────────

def test_a_claim_found_on_the_opened_page_is_supported_with_its_source(monkeypatch):
    monkeypatch.setattr(
        cv, "_read_page",
        lambda url: "KALRO trials show maize yields in Trans Nzoia average 25 kg per hectare under protocol.",
    )
    verdict = cv.verify_claim(
        "Maize yields in Trans Nzoia average 25 kg per hectare under the KALRO trial protocol.",
        [Citation("https://kalro.org/trial", title="KALRO trials")],
    )
    assert verdict.status == cv.SUPPORTED
    assert verdict.source_url == "https://kalro.org/trial"
    assert verdict.excerpt, "a supported claim must carry the excerpt it rests on"
    assert verdict.matched_terms


def test_a_claim_absent_from_the_page_is_unverified_not_supported(monkeypatch):
    monkeypatch.setattr(cv, "_read_page", lambda url: "This page is about marine fisheries in Lamu.")
    verdict = cv.verify_claim(
        "Maize yields in Trans Nzoia average 25 kg per hectare under the KALRO trial protocol.",
        [Citation("https://example.org/fish")],
    )
    assert verdict.status == cv.UNVERIFIED
    assert verdict.confidence < 0.34


def test_the_page_is_opened_rather_than_the_snippet_trusted(monkeypatch):
    """Search snippets are 350 characters and cannot confirm anything."""
    opened: list[str] = []
    monkeypatch.setattr(cv, "_read_page", lambda url: opened.append(url) or "irrelevant text")
    cv.verify_claim("KICD allocates 40 hours to this strand in 2024.", [Citation("https://kicd.ac.ke/x")])
    assert opened == ["https://kicd.ac.ke/x"]


def test_more_credible_sources_are_consulted_first(monkeypatch):
    order: list[str] = []
    monkeypatch.setattr(cv, "_read_page", lambda url: order.append(url) or "")
    cv.verify_claim(
        "KICD allocates 40 hours to this strand in 2024.",
        [Citation("https://blog.example/a", credibility_score=0.2),
         Citation("https://kicd.ac.ke/b", credibility_score=0.95)],
    )
    assert order[0] == "https://kicd.ac.ke/b"


# ── Whole-artefact verification ─────────────────────────────────────────────

def test_no_sources_reports_unverified_rather_than_passing():
    result = cv.verify_content(
        {"notes": "KICD allocates 40 hours to this strand in 2024."}, Dossier([])
    )
    assert result["supported"] == 0
    assert result["unverified"] == result["claims_checked"] >= 1
    assert "no sources" in result["summary"].lower()


def test_nothing_checkable_is_reported_honestly():
    result = cv.verify_content({"notes": "Encourage learners to collaborate."}, Dossier([Citation("https://x")]))
    assert result["claims_checked"] == 0
    assert "no checkable" in result["summary"].lower()


def test_supported_claims_expose_the_urls_a_reviewer_can_follow(monkeypatch):
    monkeypatch.setattr(
        cv, "_read_page",
        lambda url: "KICD allocates 40 hours to this strand in the 2024 revised design.",
    )
    result = cv.verify_content(
        {"notes": "KICD allocates 40 hours to this strand in 2024."},
        Dossier([Citation("https://kicd.ac.ke/design", title="KICD design")]),
    )
    assert result["supported"] == 1
    assert result["sources"] == ["https://kicd.ac.ke/design"]
    assert result["verdicts"][0]["excerpt"]


def test_a_page_that_will_not_open_does_not_become_support(monkeypatch):
    monkeypatch.setattr(cv, "_read_page", lambda url: "")
    result = cv.verify_content(
        {"notes": "KICD allocates 40 hours to this strand in 2024."},
        Dossier([Citation("https://kicd.ac.ke/design")]),
    )
    assert result["supported"] == 0


# ── The audit must not claim verification it did not perform ────────────────

def _dossier():
    from app.services.web_research import ResearchDossier
    return ResearchDossier(
        topic="t", subject="Agriculture", grade="grade-dte", search_queries=[],
        citations=[], empirical_data_points=[], academic_insights=[],
        kenyan_case_studies=[], deliberation_trace=[], safety_guidelines=[],
        formatted_context="",
    )


def _check(report, name):
    return next(c for c in report.audit_checks if c["name"] == name)


def test_accuracy_is_reported_unverified_when_nothing_was_checked():
    """It used to always PASS with 'Verified against KALRO/KICD benchmarks'."""
    from app.services.web_research import web_research_agent

    report = web_research_agent.perform_quality_audit(
        {"notes": "word " * 400}, "notes", _dossier()
    )
    assert _check(report, "Scientific & Technical Accuracy")["status"] == "UNVERIFIED"


def test_safety_warns_when_the_content_never_mentions_safety():
    """Both branches used to PASS, so safety passed regardless of content."""
    from app.services.web_research import web_research_agent

    report = web_research_agent.perform_quality_audit(
        {"notes": "Kenya curriculum learners work in groups. " * 40}, "notes", _dossier()
    )
    assert _check(report, "Safety & Hazard Protocols")["status"] == "WARN"


def test_safety_passes_only_when_precautions_are_present():
    from app.services.web_research import web_research_agent

    report = web_research_agent.perform_quality_audit(
        {"notes": "Kenya curriculum learners work in groups. " * 40 + "Observe safety precautions for this hazard."},
        "notes", _dossier(),
    )
    assert _check(report, "Safety & Hazard Protocols")["status"] == "PASS"


def test_assessment_alignment_is_checked_rather_than_asserted():
    from app.services.web_research import web_research_agent

    without = web_research_agent.perform_quality_audit(
        {"notes": "Kenya curriculum learners work in groups. " * 40}, "notes", _dossier()
    )
    assert _check(without, "Criterion Assessment Alignment")["status"] == "WARN"

    with_rubric = web_research_agent.perform_quality_audit(
        {"notes": "Kenya curriculum learners work in groups. " * 40 + "Use the rubric: exceeding expectation, and the slo."},
        "notes", _dossier(),
    )
    assert _check(with_rubric, "Criterion Assessment Alignment")["status"] == "PASS"


def test_verified_audit_reports_the_sources_it_used(monkeypatch):
    from app.services import claim_verification as cvmod
    from app.services.web_research import ResearchCitation, web_research_agent

    monkeypatch.setattr(
        cvmod, "_read_page",
        lambda url: "KICD allocates 40 hours to this strand in the 2024 revised design.",
    )
    dossier = _dossier()
    dossier.citations = [ResearchCitation(
        title="KICD", url="https://kicd.ac.ke/d", source_domain="kicd.ac.ke",
        snippet="", key_facts=[], credibility_score=0.95,
    )]

    report = web_research_agent.perform_quality_audit(
        {"notes": "Kenya curriculum learners work in groups. " * 40
                  + "KICD allocates 40 hours to this strand in 2024."},
        "notes", dossier, verify=True,
    )
    check = _check(report, "Scientific & Technical Accuracy")
    assert check["status"] == "PASS"
    assert "https://kicd.ac.ke/d" in check["sources"]
