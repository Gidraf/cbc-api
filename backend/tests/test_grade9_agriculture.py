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


# ── Social Studies Grade 9: the summary table wraps ─────────────────────────

SOCIAL_STUDIES = """SUMMARY OF STRANDS AND SUB-STRANDS
Strand Sub-Strand Suggested Number
of Lessons
1.0 Social Studies and Career
Development
1.1 Pathway Choices 4
1.2 Pre-career Support Systems 4
2.0 Community Service-Learning 2.1 Community Service-Learning Project 8
3.0 People and Relationships 3.1 Socio-economic practices of early humans 6
3.2 Indigenous knowledge systems in African Societies 8
3.3 Poverty Reduction 6
3.4 Population Structure 8
3.5 Peaceful Conflict Resolution 8
3.6 Healthy Relationships 4
4.0 Natural and Historic Built
Environments
4.1 Topographical maps 8
4.2 Internal Land Forming Processes 8
4.3 Multipurpose River Projects in Africa 8
4.4 Management and Conservation of the Environment 6
4.5 World Heritage Sites in Africa 6
Page 13 of 73 Page 15 of 73
Page 14 of 73
xiv
5.0 Political Developments and
Governance
5.1 The Constitution of Kenya 8
5.2 Civic Engagement in Governance 6
5.3 Kenya's Bill of Rights 8
5.4 Cultural Globalisation 6
Total Number of Lessons 120
Note: The suggested number of lessons per sub-strand may be less or more depending on the context
"""


def _read(text: str):
    return curriculum_extractor._substrands_from_summary(
        text, "Social Studies", "grade-9", "Junior School")


def test_a_strand_whose_name_wraps_is_still_read() -> None:
    """"1.0 Social Studies and Career" / "Development" — the name lands on two
    lines, and reading only whole rows lost strands 1.0, 4.0 and 5.0."""
    subs = _read(SOCIAL_STUDIES)

    assert len(subs) == 18, [s.sub_strand_id for s in subs]
    by_id = {s.sub_strand_id: s for s in subs}
    assert by_id["1.1"].sub_strand_name == "Pathway Choices"
    assert by_id["1.1"].strand_name == "Social Studies and Career Development"
    assert by_id["4.1"].strand_name == "Natural and Historic Built Environments"
    assert by_id["5.4"].strand_name == "Political Developments and Governance"

    # The design's own total.
    assert sum(int(s.allocated_hours.split()[0]) for s in subs) == 120


def test_a_sub_strand_is_filed_by_its_own_number_not_by_the_last_strand_seen() -> None:
    """With 4.0 and 5.0 unread, 4.1 through 5.4 were all filed under "People
    and Relationships" — the last strand that HAD been read.

    Silently wrong is worse than missing: a sub-strand under the wrong strand
    is generated, reviewed and printed without anybody seeing it.
    """
    for sub in _read(SOCIAL_STUDIES):
        assert sub.strand_id == f"{sub.sub_strand_id.split('.')[0]}.0", sub.sub_strand_id
        assert sub.strand_name, f"{sub.sub_strand_id} has no strand"

    people = [s for s in _read(SOCIAL_STUDIES)
              if s.strand_name == "People and Relationships"]
    assert {s.sub_strand_id for s in people} == {"3.1", "3.2", "3.3", "3.4", "3.5", "3.6"}


def test_the_page_furniture_between_the_two_halves_is_not_a_strand() -> None:
    """The table spans two pages, so "Page 13 of 73 Page 15 of 73", "xiv" and
    the closing note sit inside it."""
    names = {s.sub_strand_name.lower() for s in _read(SOCIAL_STUDIES)}
    assert not any("page" in n or "total" in n or "note" in n for n in names)


def test_the_agriculture_design_still_reads_the_same() -> None:
    """Its strands are on one line each; the change for wrapped names must not
    cost the unwrapped case."""
    subs = curriculum_extractor._substrands_from_summary(
        SUMMARY, "Agriculture", "grade-9", "Junior School")

    assert len(subs) == 10
    assert sum(int(s.allocated_hours.split()[0]) for s in subs) == 120
    by_id = {s.sub_strand_id: s for s in subs}
    assert by_id["1.1"].strand_name == "Conservation of Resources"
    assert by_id["4.2"].sub_strand_name == "Homemade Sun Dryer"
