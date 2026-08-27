"""Reading a design in pieces, then reconciling what each piece produced."""
from __future__ import annotations

import pytest

from app.services import document_chunking as dc
from app.services import map_reduce as mr


def document(pages: int, lines_per_page: int = 40, width: int = 90) -> str:
    out = []
    for p in range(1, pages + 1):
        out.append("=" * 80)
        out.append(f"PAGE {p} OF {pages}")
        out.append("=" * 80)
        out.append("")
        for l in range(lines_per_page):
            out.append(f"Page {p} line {l} " + "x" * width)
    return "\n".join(out)


# ── Chunking ────────────────────────────────────────────────────────────────

def test_a_document_that_fits_is_one_chunk():
    chunks = dc.chunk_document(document(3), context_window_tokens=128_000)
    assert len(chunks) == 1
    assert chunks[0].page_range == "1-3"


def test_a_large_document_is_split_to_fit_the_window():
    """170k tokens in one call is what the provider rejected outright."""
    chunks = dc.chunk_document(document(120), context_window_tokens=16_000, overhead_tokens=4_000)
    assert len(chunks) > 1
    budget = dc.budget_chars(16_000, 4_000)
    assert all(len(c.text) <= budget for c in chunks)


def test_chunks_never_split_a_page():
    """A page split down the middle would break every citation into it."""
    chunks = dc.chunk_document(document(40), context_window_tokens=16_000, overhead_tokens=4_000)
    seen: list[int] = []
    for c in chunks:
        seen.extend(p.number for p in c.pages)
    assert seen == sorted(seen)
    assert len(seen) == len(set(seen)), "a page must appear in exactly one chunk"


def test_every_chunk_reports_the_pages_it_holds():
    chunks = dc.chunk_document(document(40), context_window_tokens=16_000, overhead_tokens=4_000)
    assert all(c.page_range for c in chunks)
    assert chunks[0].first_page == 1


def test_lines_carry_their_address_so_the_model_can_cite_them():
    chunk = dc.chunk_document(document(2))[0]
    assert "1:1  Page 1 line 0" in chunk.text
    assert "[PAGE 2]" in chunk.text


def test_a_page_bigger_than_the_budget_is_kept_whole_not_truncated():
    huge = document(1, lines_per_page=400, width=200)
    chunks = dc.chunk_document(huge, context_window_tokens=6_000, overhead_tokens=4_000)
    assert len(chunks) == 1, "splitting it would invalidate its citations"
    assert len(chunks[0].pages) == 1


# ── Reconciliation ──────────────────────────────────────────────────────────

def make_chunk(index: int, first: int, last: int) -> dc.Chunk:
    from app.services.document_index import Page
    return dc.Chunk(index=index, pages=[Page(number=n) for n in range(first, last + 1)], text="")


def test_a_strand_seen_in_two_chunks_is_kept_once_with_both_page_ranges():
    a, b = make_chunk(0, 1, 18), make_chunk(1, 19, 36)
    items, summary = mr.reconcile([
        (a, [{"strand_name": "1.0 Listening and Speaking", "description": "Short"}]),
        (b, [{"strand_name": "Listening and Speaking", "description": "A much fuller description of the strand"}]),
    ])
    assert len(items) == 1
    assert summary["duplicates_merged"] == 1
    assert items[0]["source_pages"] == ["1-18", "19-36"]
    assert items[0]["description"].startswith("A much fuller")


def test_numbering_differences_do_not_create_duplicates():
    a, b = make_chunk(0, 1, 5), make_chunk(1, 6, 10)
    items, _ = mr.reconcile([
        (a, [{"strand_name": "2.0 Pre-Reading"}]),
        (b, [{"strand_name": "Pre Reading"}]),
    ])
    assert len(items) == 1


def test_distinct_strands_are_all_kept_in_reading_order():
    a, b = make_chunk(0, 1, 5), make_chunk(1, 6, 10)
    items, summary = mr.reconcile([
        (a, [{"strand_name": "Listening"}, {"strand_name": "Speaking"}]),
        (b, [{"strand_name": "Pre-Writing"}]),
    ])
    assert [i["strand_name"] for i in items] == ["Listening", "Speaking", "Pre-Writing"]
    assert summary["items_after"] == 3


def test_lists_are_unioned_rather_than_overwritten():
    a, b = make_chunk(0, 1, 5), make_chunk(1, 6, 10)
    items, _ = mr.reconcile([
        (a, [{"name": "Cells", "slos": ["describe the cell"]}]),
        (b, [{"name": "Cells", "slos": ["compare plant and animal cells"]}]),
    ])
    assert items[0]["slos"] == ["describe the cell", "compare plant and animal cells"]


def test_items_with_no_identifiable_name_are_kept_and_counted():
    a = make_chunk(0, 1, 5)
    items, summary = mr.reconcile([(a, [{"description": "no name field"}, {"description": "another"}])])
    assert len(items) == 2
    assert summary["items_without_identity"] == 2


# ── The pipeline end to end ─────────────────────────────────────────────────

def test_every_chunk_is_generated_from_and_traced():
    seen: list[str] = []

    def generate(chunk):
        seen.append(chunk.page_range)
        return [{"strand_name": f"Strand from page {chunk.first_page}"}]

    result = mr.map_reduce_over_document(
        document(40), generate, context_window_tokens=16_000, overhead_tokens=4_000
    )
    body = result.to_dict()
    assert len(seen) == body["trace"]["chunks"]["chunk_count"] > 1
    assert body["trace"]["chunks_failed"] == 0
    assert all(s["status"] == "ok" for s in body["trace"]["steps"])
    assert all("duration_ms" in s for s in body["trace"]["steps"])


def test_one_failing_chunk_does_not_discard_the_others():
    def generate(chunk):
        if chunk.index == 1:
            raise RuntimeError("provider rejected the request")
        return [{"strand_name": f"Strand {chunk.index}"}]

    result = mr.map_reduce_over_document(
        document(60), generate, context_window_tokens=16_000, overhead_tokens=4_000
    )
    body = result.to_dict()
    assert body["trace"]["chunks_failed"] == 1
    assert body["items"], "the chunks that succeeded must still produce output"
    failed = next(s for s in body["trace"]["steps"] if s["status"] == "failed")
    assert "provider rejected" in failed["error"]
    assert failed["pages"], "the trace must name the pages that failed"


def test_the_trace_says_which_pages_each_call_saw():
    result = mr.map_reduce_over_document(
        document(40), lambda c: [], context_window_tokens=16_000, overhead_tokens=4_000
    )
    steps = result.to_dict()["trace"]["steps"]
    assert all("-" in s["pages"] or s["pages"].isdigit() for s in steps)
