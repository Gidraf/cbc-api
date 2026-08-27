"""Page-and-line addressing, tested against the real extractor output shape."""
from __future__ import annotations

import pytest

from app.services import document_index as di

# Exactly what the browser extractor writes, including the doubled marker.
CAPTURED = """================================================================================
📄 PAGE 1 OF 76
================================================================================

Page 1 of 76
KENYA INSTITUTE OF CURRICULUM DEVELOPMENT
PRE-PRIMARY 1
LANGUAGE ACTIVITIES

================================================================================
📄 PAGE 2 OF 76
================================================================================

Page 2 of 76
First Published 2017
Revised 2024
ISBN: 978-9914-43-996-0

================================================================================
📄 PAGE 12 OF 76
================================================================================

Page 12 of 76
STRAND 1.0 LISTENING AND SPEAKING
1.1 Greetings and Farewell (4 lessons)
By the end of the sub strand the learner should be able to:
a) respond to greetings appropriately,
b) use polite language in greeting adults.
"""


@pytest.fixture
def pages():
    return di.parse_pages(CAPTURED)


def test_pages_come_from_the_document_not_arbitrary_chunking(pages):
    assert [p.number for p in pages] == [1, 2, 12]


def test_separators_and_markers_do_not_consume_line_numbers(pages):
    """A reference would drift by the number of rules above it."""
    first = pages[0].lines
    assert first[0].text == "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT"
    assert first[0].line == 1
    assert not any("PAGE 1 OF 76" in l.text for l in first)
    assert not any(set(l.text) == {"="} for l in first)


def test_line_numbers_restart_on_each_page(pages):
    assert all(p.lines[0].line == 1 for p in pages)


def test_a_line_has_a_readable_address(pages):
    page12 = next(p for p in pages if p.number == 12)
    strand = next(l for l in page12.lines if l.text.startswith("STRAND 1.0"))
    assert strand.ref == "12:1"


def test_a_page_reports_its_topic(pages):
    assert "LISTENING AND SPEAKING" in next(p for p in pages if p.number == 12).heading


def test_a_document_with_no_markers_is_still_addressable():
    pages = di.parse_pages("First line here.\nSecond line here.\n\nThird line here.")
    assert len(pages) == 1
    assert [l.line for l in pages[0].lines] == [1, 2, 3]


def test_the_extractors_repeated_page_marker_does_not_split_a_page():
    doubled = "📄 PAGE 5 OF 9\nPage 5 of 9\nReal content line.\nAnother line."
    pages = di.parse_pages(doubled)
    assert [p.number for p in pages] == [5]
    assert [l.text for l in pages[0].lines] == ["Real content line.", "Another line."]


# ── Citing and resolving ────────────────────────────────────────────────────

def test_a_quote_resolves_to_its_exact_address(pages):
    found = di.find_reference(pages, "respond to greetings appropriately")
    assert found["page"] == 12
    assert found["match"] == "exact"
    assert found["ref"] == "12:4"


def test_a_paraphrase_is_traced_but_marked_as_not_verbatim(pages):
    found = di.find_reference(pages, "learner should respond appropriately to greetings")
    assert found is not None
    assert found["match"] == "partial"
    assert found["score"] < 1.0


def test_an_invented_quote_resolves_to_nothing(pages):
    assert di.find_reference(pages, "photosynthesis in mangrove ecosystems of Lamu county") is None


def test_a_reference_reads_back_the_lines_it_names(pages):
    lines = di.resolve_reference(pages, "12:4")
    assert len(lines) == 1
    assert "respond to greetings" in lines[0].text


def test_a_reference_can_span_a_range(pages):
    lines = di.resolve_reference(pages, "12:4-5")
    assert [l.line for l in lines] == [4, 5]


def test_a_reference_may_carry_its_document_code(pages):
    assert di.parse_reference("GRADE-PP1-LANGUAGE 12:4") == ("GRADE-PP1-LANGUAGE", 12, 4, 4)
    assert di.parse_reference("not a reference") is None


def test_document_codes_are_stable_and_readable():
    assert di.document_code("grade-4", "Science and Technology") == "GRADE-4-SCIENCE-AND-TECHNOLOGY"


def test_search_returns_every_hit_with_its_address(pages):
    hits = di.search(pages, "greeting")
    assert len(hits) >= 2
    assert all("ref" in h for h in hits)


def test_the_index_summarises_without_shipping_the_whole_document(pages):
    index = di.build_index(CAPTURED, "grade-pp1", "Pre-Primary 1")
    assert index["page_count"] == 3
    assert index["line_count"] > 8
    assert index["code"] == "GRADE-PP1-PRE-PRIMARY-1"
    assert "lines" not in index["pages"][0]


def test_a_rendered_page_re_parses_as_the_page_it_came_from() -> None:
    """Rendering and parsing must be inverses.

    A learning area is split out of a combined design as rendered text, then
    read again by the next stage. When the re-read did not recognise its own
    "[PAGE n]" markers, a 90-page section became one page numbered 1: every
    citation pointed at page 1, and chunking could not split it, because a
    single page is never split — which is the context-length failure again.
    """
    from app.services.document_chunking import _page_text
    from app.services.document_index import parse_pages

    original = parse_pages(
        "PAGE 202 OF 296\nSummary of Strands\n1.0 Creation\n\n"
        "PAGE 203 OF 296\nThe Bible is a Holy Book\n"
    )
    rendered = "\n\n".join(_page_text(p) for p in original)

    reparsed = parse_pages(rendered)

    assert [p.number for p in reparsed] == [202, 203]
    assert [l.text for l in reparsed[0].lines] == [l.text for l in original[0].lines]
    # Idempotent: a third pass must not stack another address onto each line.
    assert "\n\n".join(_page_text(p) for p in reparsed) == rendered


def test_a_line_starting_with_a_scripture_reference_keeps_it() -> None:
    """The address strip is not allowed to eat content that merely looks like one."""
    from app.services.document_index import parse_pages

    pages = parse_pages("PAGE 7 OF 40\n3:16  For God so loved the world\n")

    assert pages[0].lines[0].text == "3:16  For God so loved the world"
