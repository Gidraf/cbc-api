"""Research that answers a curriculum question from the open web is not research.

`AUTHORITATIVE_DOMAINS` reads like a scope and is not one: it moves a
credibility score from 0.85 to 0.95 and keeps every result either way. A
dossier for a Grade 9 sub-strand was assembled from general-web pages and a
Wikipedia summary, none of which knows what the KICD design says.
"""
from __future__ import annotations

from app.services import web_research


def test_a_lookalike_domain_is_outside_the_scope() -> None:
    assert web_research.within_scope("www.kicd.ac.ke")
    assert web_research.within_scope("KNEC.AC.KE")
    assert not web_research.within_scope("kicd.ac.ke.example.com")
    assert not web_research.within_scope("en.wikipedia.org")


def test_the_searches_themselves_look_in_the_right_place() -> None:
    agent = web_research.WebResearchAgent()
    queries = agent._generate_search_queries(
        "Mathematics", "Numbers", "Integers", "grade-9", "notes", "",
        scope=web_research.CURRICULUM_DOMAINS)

    assert queries, "a scoped run still searches"
    assert all(q.startswith("(site:kicd.ac.ke OR") for q in queries)


def test_results_from_outside_the_scope_are_discarded_not_downranked() -> None:
    import unittest.mock as mock

    agent = web_research.WebResearchAgent()
    hits = [
        {"title": "t", "url": "https://en.wikipedia.org/wiki/Integer",
         "domain": "en.wikipedia.org", "snippet": "s", "credibility": 0.85},
        {"title": "t", "url": "https://kicd.ac.ke/designs/g9-maths",
         "domain": "kicd.ac.ke", "snippet": "s", "credibility": 0.95},
    ]
    with mock.patch.object(agent, "_execute_search", return_value=hits):
        dossier = agent.research_topic("Mathematics", "Numbers", "Integers",
                                       grade="grade-9")

    assert [c.source_domain for c in dossier.citations] == ["kicd.ac.ke"]
    assert any("discarded" in line for line in dossier.deliberation_trace)


def test_nothing_at_all_is_reported_rather_than_hidden() -> None:
    """Scoped and open both dry: say so, do not pretend the dossier is full."""
    import unittest.mock as mock

    agent = web_research.WebResearchAgent()
    with mock.patch.object(agent, "_execute_search", return_value=[]):
        dossier = agent.research_topic("Mathematics", "Numbers", "Integers",
                                       grade="grade-9")

    assert not dossier.citations
    assert any("scoped or open" in line for line in dossier.deliberation_trace)


def test_a_scope_that_finds_nothing_widens_instead_of_starving() -> None:
    """An empty `dossier_formatted_context` reaches the model as silence.

    kicd.ac.ke publishes the designs as documents, not a page per sub-strand,
    so a scoped search legitimately finds nothing — and the station that
    defaulted to scope handed every generation an empty research block without
    anything saying why.
    """
    import unittest.mock as mock

    agent = web_research.WebResearchAgent()
    outside = [{"title": "t", "url": "https://en.wikipedia.org/wiki/Integer",
                "domain": "en.wikipedia.org", "snippet": "s",
                "credibility": 0.95}]

    calls: list[bool] = []

    def search(query: str, *, allow_fallback: bool = True):
        calls.append(allow_fallback)
        # Scoped pass (no fallback) finds nothing; the widened pass finds this.
        return outside if allow_fallback else []

    with mock.patch.object(agent, "_execute_search", side_effect=search):
        dossier = agent.research_topic("Mathematics", "Numbers", "Integers",
                                       grade="grade-9")

    assert [c.source_domain for c in dossier.citations] == ["en.wikipedia.org"]
    assert True in calls, "it must actually widen, not just report widening"
    assert any("Widening beyond" in line for line in dossier.deliberation_trace)
    assert any("NONE of them is the design" in line
               for line in dossier.deliberation_trace)


def test_a_widened_source_cannot_outrank_the_design() -> None:
    import unittest.mock as mock

    agent = web_research.WebResearchAgent()
    outside = [{"title": "t", "url": "https://example.com/integers",
                "domain": "example.com", "snippet": "s", "credibility": 0.95}]

    def search(query: str, *, allow_fallback: bool = True):
        return outside if allow_fallback else []

    with mock.patch.object(agent, "_execute_search", side_effect=search):
        dossier = agent.research_topic("Mathematics", "Numbers", "Integers",
                                       grade="grade-9")

    assert dossier.citations
    assert all(c.credibility_score <= web_research.OUTSIDE_SCOPE_CEILING
               for c in dossier.citations)


def test_scoped_research_does_not_fall_back_to_an_encyclopaedia() -> None:
    import unittest.mock as mock

    agent = web_research.WebResearchAgent()
    with mock.patch.object(agent, "_search_wikipedia_urllib") as fallback:
        with mock.patch("app.services.web_research.HAS_HTTPX", False):
            assert agent._execute_search("q", allow_fallback=False) == []
    fallback.assert_not_called()
