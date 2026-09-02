"""The real Grade 9 Agriculture design, as the PDF reader hands it over.

Two failures met in one document, both invisible from the console: the grade
was unreadable so the design went to Grade 7, and the sub-strand table is a
four-column layout flattened into single lines so nothing was read from it —
which produced an empty design that looked exactly like one never run.
"""
from __future__ import annotations

from app.services.curriculum_extractor import (
    _cover_text, _grade_from_text, curriculum_extractor,
)

# Verbatim, including the page banners the reader inserts and the "Displaying
# …Grade9 1.8.2024 -Proofread.pdf" line above the real cover.
COVER = """================================================================================
📄 PAGE 1 OF 36
================================================================================

Page 1 of 36
Page
/
36
Displaying Agriculture Grade9 1.8.2024 -Proofread.pdf. Page 1
KENYA INSTITUTE OF CURRICULUM DEVELOPMENT
A Skilled and Ethical Society
JUNIOR SCHOOL CURRICULUM DESIGN
AGRICULTURE
GRADE 9
Page 1 of 36 Page 4 of 36
"""

SUMMARY = """SUMMARY OF STRANDS AND SUB-STRANDS
Strands Sub-Strands Suggested Number of Lessons
1.0 Conservation of Resources 1.1 Conserving Animal Feed: Hay 12
1.2 Conserving Leftover Food 11
1.3 Integrated Farming 12
2.0 Food Production Processes 2.1 Organic Gardening 14
2.2 Storage of Crop Produce 10
2.3 Cooking: Using Flour Mixtures 14
3.0 Hygiene Practises 3.1 Cleaning Waste Disposal Facilities 9
3.2 Disinfecting Clothing and Household Articles 12
4.0 Production Techniques 4.1 Grafting in Plants 13
4.2 Homemade Sun Dryer 13
Total Number of Lessons 120
Note: The suggested number of lessons per sub-strand may vary depending on the context of learning.

STRAND 1.0: CONSERVATION OF RESOURCES
Strand Sub-Strand Specific Learning
Outcomes
Suggested Learning Experiences Suggested Key
Inquiry Question(s)
1.0 Conservation
of Resources
1.1 Conserving
Animal Feed:
Hay
(12 lessons)
By the end of the sub- strand the learner should
be able to:
a) describe methods of
conserving forage in
coping with drought,
b) conserve forage to
cope with drought.
Learners are guided to:
• use digital and print resources to
search for information.
How can hay
conservation
contribute to coping
with drought?
"""


def test_the_grade_is_read_from_this_cover() -> None:
    """The cover says "GRADE 9" thirteen lines down, under a page banner and a
    "Displaying …Grade9…" line — and "Grade9" has no space in it."""
    assert "GRADE 9" in _cover_text(COVER)
    assert _grade_from_text(COVER, {"grade": "grade-9"}) == ("grade-9", "Junior School")

    # And with no dataset to fall back on, the cover alone still settles it.
    assert _grade_from_text(COVER, {})[0] == "grade-9"


def test_the_whole_spine_is_read_from_the_summary_table() -> None:
    """The detail pages yield nothing — a sub-strand arrives as "1.1
    Conserving" / "Animal Feed:" / "Hay" / "(12 lessons)" on four lines. The
    design's own summary still holds all ten in one clean list."""
    subs = curriculum_extractor._extract_substrands(
        SUMMARY, "Agriculture", "grade-9", "Junior School")

    assert len(subs) == 10, [s.sub_strand_name for s in subs]

    by_name = {s.sub_strand_name: s for s in subs}
    assert "Conserving Animal Feed: Hay" in by_name
    assert "Disinfecting Clothing and Household Articles" in by_name, "not truncated"

    hay = by_name["Conserving Animal Feed: Hay"]
    assert hay.strand_name == "Conservation of Resources"
    assert hay.strand_id == "1.0"
    assert hay.sub_strand_id == "1.1"
    assert hay.allocated_hours == "12 lessons"

    # The strand carries forward down its rows, so 1.2 and 1.3 are not orphans.
    assert by_name["Integrated Farming"].strand_name == "Conservation of Resources"
    assert by_name["Homemade Sun Dryer"].strand_name == "Production Techniques"

    # Every lesson count in the design's own total.
    assert sum(int(s.allocated_hours.split()[0]) for s in subs) == 120


def test_the_total_row_is_not_read_as_a_sub_strand() -> None:
    """"Total Number of Lessons 120" and the note beneath it sit in the same
    table and must not become an eleventh sub-strand."""
    subs = curriculum_extractor._substrands_from_summary(
        SUMMARY, "Agriculture", "grade-9", "Junior School")
    names = " ".join(s.sub_strand_name.lower() for s in subs)
    assert "total" not in names
    assert "note" not in names


def test_a_strand_heading_may_be_punctuated() -> None:
    """"STRAND 1.0: CONSERVATION OF RESOURCES" — requiring whitespace straight
    after the number matched none of the Grade 9 designs."""
    import inspect
    import re

    from app.services.curriculum_extractor import CurriculumExtractorService

    source = inspect.getsource(CurriculumExtractorService._extract_substrands)
    found = re.search(r'strand_pattern = r"([^"]+)"', source)
    assert found, "the strand heading pattern moved"
    assert re.search(found.group(1), "\nSTRAND 1.0: CONSERVATION OF RESOURCES", re.IGNORECASE)
    assert re.search(found.group(1), "\nSTRAND 1.0 CREATION", re.IGNORECASE), "still matches the unpunctuated form"
