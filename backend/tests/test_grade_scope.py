"""A grade's scope, derived from its own design, small enough to inject.

PP1's scope was written by hand — letter sounds only, nothing beyond 10. Doing
the other fourteen that way does not scale, and summarising a 296-page design in
one call is the context-length failure this system already hit. So it is read in
page-aligned chunks and reconciled.

The result goes into EVERY authoring prompt, so a summary that runs to pages
re-creates the problem it was built to solve.
"""
from __future__ import annotations

from app.services.document_chunking import Chunk
from app.services.document_index import Line, Page
from app.services.grade_scope import (
    MAX_CHARS, MAX_FACT_CHARS, MAX_FACTS, GradeScope, compact, derive_scope,
)
from app.services.level_register import register_for_grade


def _chunk(index: int, first: int, last: int) -> Chunk:
    pages = [Page(number=n, lines=[Line(page=n, line=1, text="x")]) for n in range(first, last + 1)]
    return Chunk(index=index, pages=pages, text="x" * 100)


def test_a_fact_that_bounds_nothing_is_dropped() -> None:
    """"Learners will enjoy the activities" stops no generator overreaching,
    and it costs space in every prompt for the rest of the system's life."""
    facts = compact([
        {"statement": "Learners will enjoy the activities.", "source_pages": ["4"]},
        {"statement": "The learning area develops critical thinking.", "source_pages": ["5"]},
        {"statement": "Rote counting goes to 10; number symbols only to 9.", "source_pages": ["96"]},
        {"statement": "One lesson is 30 minutes.", "source_pages": ["9"]},
    ])
    kept = [f.statement for f in facts]

    # Bounding facts come first, whatever order they arrived in.
    assert kept[0].startswith("Rote counting")
    assert "One lesson is 30 minutes." in kept
    assert kept.index("Rote counting goes to 10; number symbols only to 9.") < len(kept)
    bounding = kept[:2]
    assert all("enjoy" not in b and "critical thinking" not in b for b in bounding)


def test_the_summary_stays_small_enough_to_sit_in_every_prompt() -> None:
    facts = compact([
        {"statement": f"Strand {i} covers only up to {i * 5} items.", "source_pages": [str(i)]}
        for i in range(1, 40)
    ])

    assert len(facts) <= MAX_FACTS
    assert sum(len(f.statement) for f in facts) <= MAX_CHARS


def test_an_overlong_fact_is_truncated_not_dropped() -> None:
    facts = compact([{"statement": "Learners count up to " + "9" * 500, "source_pages": ["1"]}])

    assert len(facts) == 1
    assert len(facts[0].statement) <= MAX_FACT_CHARS
    assert facts[0].statement.endswith("…")


def test_the_same_fact_from_two_chunks_is_kept_once() -> None:
    facts = compact([
        {"statement": "One lesson is 30 minutes.", "source_pages": ["9"]},
        {"statement": "one lesson is 30 minutes", "source_pages": ["9"]},
        {"statement": "One  lesson  is  30  minutes.", "source_pages": ["11"]},
    ])
    assert len(facts) == 1


def test_every_fact_carries_the_pages_it_was_read_from() -> None:
    scope = GradeScope(
        grade="grade-4", subject="Mathematics",
        facts=compact([{"statement": "Numbers go up to 1000 only.", "source_pages": ["24", "25"]}]),
    )
    assert scope.notes == ["Numbers go up to 1000 only. [24, 25]"]


def test_a_design_is_read_in_chunks_and_reconciled() -> None:
    """The whole point: a 296-page design cannot be summarised in one call."""
    seen: list[str] = []

    def generate(chunk):
        seen.append(chunk.page_range)
        if chunk.index == 0:
            return [{"statement": "One lesson is 30 minutes.", "source_pages": ["9"]}]
        return [{"statement": "Counting stops at 10.", "source_pages": ["96"]}]

    document = "\n".join(
        f"PAGE {n} OF 400\n" + "\n".join(f"line {i} of page {n} " + "y" * 200 for i in range(30))
        for n in range(1, 401)
    )
    scope = derive_scope("grade-pp1", "Mathematical Activities", document, generate,
                         context_window_tokens=20_000, overhead_tokens=4_000)

    assert len(seen) > 1, "a long design must be split, not sent whole"
    statements = [f.statement for f in scope.facts]
    assert "One lesson is 30 minutes." in statements
    assert "Counting stops at 10." in statements
    assert scope.trace["chunks"]["chunk_count"] == len(seen)


def test_one_failing_chunk_does_not_lose_the_others() -> None:
    def generate(chunk):
        if chunk.index == 1:
            raise RuntimeError("model refused")
        return [{"statement": f"Chunk {chunk.index} limits things to {chunk.index}.",
                 "source_pages": [str(chunk.first_page)]}]

    document = "\n".join(
        f"PAGE {n} OF 300\n" + "\n".join("z" * 200 for _ in range(30)) for n in range(1, 301)
    )
    scope = derive_scope("grade-7", "Mathematics", document, generate,
                         context_window_tokens=20_000, overhead_tokens=4_000)

    assert scope.facts, "a single bad chunk must not empty the summary"
    assert scope.trace["chunks_failed"] == 1
    assert scope.trace["chunks_succeeded"] >= 1


def test_no_document_yields_no_scope_rather_than_an_invented_one() -> None:
    def generate(chunk):  # pragma: no cover - must never run
        raise AssertionError("should not be called without a document")

    scope = derive_scope("grade-5", "Mathematics", "", generate)

    assert scope.facts == []
    assert scope.trace == {"skipped": "no source document"}


def test_derived_scope_replaces_the_read_the_design_placeholder() -> None:
    """The moment a grade's design is read, that grade becomes as sharp as PP1."""
    before = register_for_grade("grade-5").grade_notes
    assert before == [
        "The specific content for this grade must be read from its own KICD "
        "design document. Do not carry over another grade's scope."
    ]

    after = register_for_grade("grade-5", notes=["Numbers to 1000 only. [24]"]).grade_notes
    assert after == ["Numbers to 1000 only. [24]"]

    block = register_for_grade("grade-5", notes=["Numbers to 1000 only. [24]"]).format_for_prompt()
    assert "WHAT GRADE 5 ACTUALLY COVERS" in block
    assert "Numbers to 1000 only. [24]" in block


def test_empty_or_blank_derived_notes_fall_back_rather_than_emptying_the_block() -> None:
    for notes in ([], ["", "   "], None):
        got = register_for_grade("grade-pp1", notes=notes).grade_notes
        assert "letter SOUNDS only" in " ".join(got), notes


def test_malformed_facts_are_skipped_not_crashed_on() -> None:
    facts = compact([
        None, "a bare string", 42,
        {"statement": ""}, {"no_statement": "x"},
        {"statement": "Counting stops at 10.", "source_pages": None},
    ])
    assert [f.statement for f in facts] == ["Counting stops at 10."]
    assert facts[0].source_pages == []
