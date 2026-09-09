"""The pages of a design a sub-strand actually needs, and nothing else.

The notes prompt carried the whole 69-page Grade 9 Mathematics design — the
foreword, the ISBN, the table of contents, and every other strand — for a
sub-strand that occupies four pages. Which the system already knew:

    "source_pages": [12, 13, 14, 20]

Ninety thousand of the prompt's 124,000 characters were pages the model must
not write about, sent to a model whose reasoning degrades under exactly that
load.
"""
from __future__ import annotations

from app.services import design_scope


def _document(pages: int = 8, **marked: str) -> str:
    out = []
    for n in range(1, pages + 1):
        body = f"Content of page {n}."
        if str(n) in marked:
            body += " " + marked[str(n)]
        out.append(f"Page {n} of {pages}\n{body}")
    return "\n".join(out)


def test_only_the_sub_strand_s_own_pages_are_kept() -> None:
    trim = design_scope.for_sub_strand(_document(), [4, 5], "Integers")

    assert trim.kept == [4, 5]
    assert trim.dropped == 6 and trim.total == 8
    assert "Content of page 4" in trim.text
    assert "Content of page 7" not in trim.text


def test_the_front_matter_a_guide_quotes_is_kept_too() -> None:
    """The prompt quotes the essence statement and the outcomes, and a
    citation has to resolve against something."""
    doc = _document(essence := None) if False else _document(
        **{"3": "ESSENCE STATEMENT", "6": "LESSON ALLOCATION"})

    trim = design_scope.for_sub_strand(doc, [4], "Integers")

    assert 3 in trim.kept and 6 in trim.kept


def test_the_document_s_own_furniture_is_dropped() -> None:
    doc = _document(**{"2": "FOREWORD", "3": "TABLE OF CONTENTS"})

    trim = design_scope.for_sub_strand(doc, [5], "Integers")

    assert 2 not in trim.kept and 3 not in trim.kept


def test_what_was_dropped_is_said_rather_than_hidden() -> None:
    trim = design_scope.for_sub_strand(_document(), [4], "Integers")

    assert "pages 4 of 8" in trim.text
    assert "not shown, so nothing here belongs to them" in trim.text


def test_pages_that_are_not_recorded_send_the_whole_design() -> None:
    """A design nobody has indexed is not improved by guessing which quarter
    of it matters."""
    doc = _document()

    trim = design_scope.for_sub_strand(doc, [], "Integers")

    assert trim.text == doc and not trim.trimmed
    assert "not recorded" in trim.reason


def test_a_document_with_no_page_markers_is_sent_whole() -> None:
    """Unpaged text parses as one page, which then matches nothing — either
    way the whole thing is sent, which is the behaviour that matters."""
    text = "Just some text with no pages."

    trim = design_scope.for_sub_strand(text, [4])

    assert trim.text == text and not trim.trimmed
    assert trim.reason


def test_a_trim_that_would_empty_the_design_does_not_happen() -> None:
    """A trim that sends nothing is worse than one that does not happen."""
    trim = design_scope.for_sub_strand(_document(), [99], "Integers")

    assert not trim.trimmed
    assert "no page matched" in trim.reason


def test_the_route_reads_the_pages_it_selects() -> None:
    """The trim is a no-op unless `source_pages` is in the query. It was not."""
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_notes)
    before_from = source.split("FROM curriculum_substrands")[0]

    assert "source_pages" in before_from
    assert "design_scope.for_sub_strand(" in source


def test_the_authoring_stations_do_not_default_to_a_small_model() -> None:
    """Every stage defaulted to gpt-4o-mini, including the one asked to hold
    35,000 tokens of curriculum design and write six lessons of Grade 9
    mathematics."""
    from app.services.stages import needs_reasoning

    for stage in ("notes_generation", "material_generation",
                  "question_generation", "diagram_generation"):
        assert needs_reasoning(stage), stage

    # And reading a table out of a document does not need one.
    for stage in ("ingest_extraction", "structure_generation"):
        assert not needs_reasoning(stage), stage
