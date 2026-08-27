"""Raw source text must never save as curriculum content.

A chunk the model could not parse comes back as the chunk itself. One saved as
a sixth CRE strand, "4.0 CHRISTIAN VALUES", holding a single sub-strand whose
`values` list was two hundred lines of pages 214-221 — page markers, line
addresses, table headings. Its real content had already been extracted
correctly by another chunk, so this was pure duplication.
"""
from __future__ import annotations

import pytest

from app.services import substrand_hygiene as hygiene


def test_line_addresses_are_the_giveaway() -> None:
    """The chunk renderer prefixes every line with page:line. Getting those
    back means the answer is the question."""
    reason = hygiene.inspect("Christian Values", {
        "sub_strand_name": "Love for God",
        "values": ["214:34  Communication: Learners develop communication skills"],
    })
    assert "page:line addresses" in reason


def test_page_markers_are_the_giveaway_too() -> None:
    reason = hygiene.inspect("The Church", {
        "sub_strand_name": "A House of God",
        "learning_experiences": ["[PAGE 218]", "take a nature walk"],
    })
    assert "page markers" in reason


def test_quoting_the_tables_own_headings_is_refused() -> None:
    reason = hygiene.inspect("The Church", {
        "sub_strand_name": "Church Activities",
        "slos": ["By the end of the sub-strand, the learner should be able to:"],
    })
    assert "table headings" in reason


def test_a_sub_strand_that_repeats_its_strand_is_refused() -> None:
    """A parse that fails at table level names the block it could not read."""
    reason = hygiene.inspect("4.0 CHRISTIAN VALUES",
                             {"sub_strand_name": "4.0 CHRISTIAN VALUES"})
    assert "repeats the strand name" in reason


def test_real_content_passes_untouched() -> None:
    assert hygiene.inspect("The Church", {
        "sub_strand_name": "A House of God",
        "allocated_time": "7 lessons",
        "slos": ["state one difference between the church and other buildings"],
        "learning_experiences": ["take a nature walk in the school neighbourhood"],
        "values": ["Unity", "Patriotism"],
        "source_pages": [218, 219],
    }) == ""


def test_scripture_references_are_not_line_addresses() -> None:
    """"Matthew 22:39 B" and "1Samuel 17:41-49" are content, not debris."""
    assert hygiene.inspect("Christian Values", {
        "sub_strand_name": "Love for Neighbour",
        "learning_experiences": [
            "listen to a pre-recorded verse from Matthew 22:39B",
            "repeat saying 'Matthew 22:39 B' aloud",
            "listen to the story of David and Goliath; 1Samuel 17:41-49",
        ],
    }) == ""


@pytest.mark.parametrize("written,expected", [
    ("4.0 CHRISTIAN VALUES", "christian values"),
    ("4.0 Christian Values", "christian values"),
    ("Christian Values", "christian values"),
    ("STRAND 5.0: THE CHURCH", "the church"),
    ("1.0 Pre-Number Activities", "pre number activities"),
])
def test_numbering_is_not_identity(written, expected) -> None:
    assert hygiene.strand_key(written) == expected


def test_duplicate_strands_under_different_numbering_collapse() -> None:
    kept, refused = hygiene.clean_strands([
        {"strand_name": "Christian Values", "description": "Love, sharing, respect."},
        {"strand_name": "4.0 CHRISTIAN VALUES", "strand_id": "4.0"},
        {"strand_name": "The Church"},
    ])

    assert [k["strand_name"] for k in kept] == ["Christian Values", "The Church"]
    assert len(refused) == 1
    assert "duplicates 'Christian Values'" in refused[0]["reason"]
    # The fuller record survives, and picks up what the duplicate carried.
    assert kept[0]["strand_id"] == "4.0"
    assert kept[0]["description"] == "Love, sharing, respect."


def test_a_batch_reports_what_it_dropped() -> None:
    kept, refused = hygiene.clean("Christian Values", [
        {"sub_strand_name": "Love for God", "allocated_time": "7 lessons"},
        {"sub_strand_name": "Christian Values", "values": ["215:12  (9 lessons)"]},
        {"sub_strand_name": "Love for God"},
    ])

    assert [k["sub_strand_name"] for k in kept] == ["Love for God"]
    assert len(refused) == 2
    assert any("duplicates" in r["reason"] for r in refused)


def test_numbering_is_stripped_from_display_names() -> None:
    """The design numbers some entries and not others; the id column carries it."""
    assert hygiene.strip_numbering("4.1 Love for God") == "Love for God"
    assert hygiene.strip_numbering("A House of God") == "A House of God"
    assert hygiene.strip_numbering("2.2 David and Goliath") == "David and Goliath"
