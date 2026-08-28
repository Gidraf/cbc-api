"""A strand whose sub-strands cannot be read has no sub-strands.

The parser used to fabricate one when its sub-strand pattern matched nothing:
a single record named after the strand, carrying the strand's entire body. Every
outcome of every real sub-strand ended up shredded into one list.

That produced "1.0 CREATION / 1.0 CREATION" with 54 fragments in Hindu Religious
Education, and "1.0 GREETINGS AND FAREWELL / 1.0 GREETINGS AND FAREWELL" with 17
in Language Activities — where those are themes, not strands, and the design runs
six of them across three real strands.

Storing a placeholder puts something in the database that looks like content and
is not, and everything downstream measures it as if it were. Leaving the strand
empty is what routes the operator to the generators, which read these layouts.
"""
from __future__ import annotations

from app.services.curriculum_extractor import curriculum_extractor as extractor

# A column-wrapped design: the sub-strand cell is split across lines, so no
# "1.1 Greetings" token exists for the pattern to match.
_WRAPPED = """
STRAND 1.0 GREETINGS AND FAREWELL
1.1
Greetings
and Farewell
(3 lessons)
By the end of the sub-strand the learner should be able to:
a) use greetings in
the language of the catchment area,
b) use farewell words
appropriately,
c) give reasons why
we greet people.
The learner is guided to:
- greet one another in pairs
- role-play meeting a visitor
"""

# A design the parser genuinely can read.
_READABLE = """
STRAND 1.0 CREATION
Sub Strand 1.1 Our God (7 lessons)
By the end of the sub-strand, the learner should be able to:
a) identify three qualities of God,
b) practice saying short prayers,
c) appreciate God as a loving heavenly father.
The learner is guided to:
- say the name of God in their mother tongue
- sing songs about God in groups
"""


def test_an_unreadable_strand_yields_no_sub_strand() -> None:
    found = extractor._extract_substrands(
        _WRAPPED, "Language Activities", "grade-pp1", "Pre-Primary"
    )

    assert found == [], "a placeholder was stored for a strand nothing could be read from"


def test_it_does_not_name_a_sub_strand_after_its_strand() -> None:
    """This is the shape every one of these defects took."""
    found = extractor._extract_substrands(
        _WRAPPED, "Language Activities", "grade-pp1", "Pre-Primary"
    )

    assert not any(
        s.strand_name.strip().lower() == s.sub_strand_name.strip().lower() for s in found
    )


def test_the_unreadable_section_is_named_rather_than_silently_dropped() -> None:
    """An unreadable design and a readable one produced the same count, and
    nothing said which was which."""
    extractor._extract_substrands(_WRAPPED, "Language Activities", "grade-pp1", "Pre-Primary")

    unparsed = getattr(extractor, "_last_unparsed", [])
    assert unparsed
    assert any("GREETINGS AND FAREWELL" in name for name in unparsed)


def test_a_readable_design_still_parses() -> None:
    """The guard must not cost the layouts that already worked."""
    found = extractor._extract_substrands(
        _READABLE, "Christian Religious Education", "grade-pp1", "Pre-Primary"
    )

    assert len(found) == 1
    assert "Our God" in found[0].sub_strand_name
    assert found[0].strand_name != found[0].sub_strand_name
    assert found[0].allocated_hours


def test_the_failure_list_does_not_leak_between_designs() -> None:
    """One design's failures reported against the next is a false alarm that
    trains the operator to ignore the real ones."""
    extractor._extract_substrands(_WRAPPED, "Language Activities", "grade-pp1", "Pre-Primary")
    extractor._extract_substrands(_READABLE, "Christian Religious Education",
                                  "grade-pp1", "Pre-Primary")

    assert getattr(extractor, "_last_unparsed", []) == []


def test_the_ingest_result_says_what_to_do_next() -> None:
    source = open("app/services/curriculum_extractor.py").read()

    assert '"unparsed_sections": unparsed' in source
    assert "/factory/generate-substrands" in source
    assert "reads the design with a model" in source


def test_sub_strand_is_not_matched_as_a_strand() -> None:
    """"Sub Strand 1.1 Our God" contains "Strand 1.1 Our God". The strand
    pattern matched it, splitting the design at every sub-strand heading and
    leaving the real sub-strands inside sections that were themselves
    sub-strands. A strand heading starts a line."""
    import re

    from app.services import curriculum_extractor as module

    source = open(module.__file__).read()
    pattern = re.search(r'strand_pattern = r"([^"]+)"', source).group(1)

    text = "STRAND 1.0 CREATION\nSub Strand 1.1 Our God (7 lessons)\n"
    matches = re.findall(pattern, text, re.IGNORECASE)

    assert len(matches) == 1, f"matched {len(matches)} strands, expected 1"
    assert "CREATION" in matches[0][0]
