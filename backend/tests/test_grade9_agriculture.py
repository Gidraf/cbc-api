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


# ── a level is DECLARED, not mentioned ──────────────────────────────────────

FOREWORD = """================================================================================
📄 PAGE 1 OF 73
================================================================================

Page 1 of 73
Displaying Social Studies Grade 9 - Revised.pdf. Page 1
KENYA INSTITUTE OF CURRICULUM DEVELOPMENT
A Skilled and Ethical Society
JUNIOR SCHOOL CURRICULUM DESIGN
SOCIAL STUDIES
GRADE 9
Page 3 of 73
FOREWORD
The Government of Kenya is committed to ensuring that policy objectives for Education meet the
Ministry of Education (MoE) has successfully and progressively rolled out the implementation of
the Competency Based Curriculum (CBC) at Pre-Primary, Primary and Junior School levels.
"""


def test_a_mention_of_pre_primary_in_prose_is_not_a_declaration() -> None:
    """Every KICD Grade 9 design carries that foreword sentence, the cover
    window is sixty lines and reaches page 3, and the pre-primary test ran
    before the numeric one — so a Social Studies GRADE 9 design was filed under
    grade-pp1. Written, stored, and invisible under the grade it was ingested
    for.
    """
    assert _grade_from_text(FOREWORD, {"grade": "grade-9"}) == ("grade-9", "Junior School")
    # And with no dataset to fall back on, the cover alone still settles it.
    assert _grade_from_text(FOREWORD, {})[0] == "grade-9"


def test_a_real_pre_primary_cover_still_reads_as_pre_primary() -> None:
    """The fix must not cost the case it was guarding."""
    assert _grade_from_text(
        "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\nPRE-PRIMARY 1\nCRE ACTIVITIES\n", {},
    ) == ("grade-pp1", "Pre-Primary")
    assert _grade_from_text("PRE-PRIMARY 2\nLANGUAGE ACTIVITIES\n", {})[0] == "grade-pp2"
    assert _grade_from_text("PP1\nMATHEMATICAL ACTIVITIES\n", {})[0] == "grade-pp1"
    assert _grade_from_text("DIPLOMA IN TEACHER EDUCATION\nMATHEMATICS\n", {})[0] == "grade-dte"


def test_only_a_heading_can_declare_a_grade() -> None:
    """A heading is short. Prose is not."""
    from app.services.curriculum_extractor import _DECLARATION_CHARS, _level_in

    assert _level_in("GRADE 9")[1:] == ("grade-9", "Junior School")
    assert _level_in("PRE-PRIMARY 1")[1] == "grade-pp1"

    prose = ("the Competency Based Curriculum (CBC) at Pre-Primary, Primary and "
             "Junior School levels.")
    assert len(prose) > _DECLARATION_CHARS, "prose must be excluded by length"
    # The line itself still parses; it is the LENGTH that keeps it out.
    assert _level_in(prose)[1] == "grade-pp1"
    assert _grade_from_text(f"SOCIAL STUDIES\nGRADE 9\n{prose}\n", {})[0] == "grade-9"


def test_a_design_under_another_grade_is_not_reported_as_absent() -> None:
    """"It claims design X, which is not in the database" was wrong and sent
    the diagnosis the wrong way: the design existed, filed under the grade its
    cover was misread as."""
    import inspect
    from pathlib import Path

    from app.routes import admin_langfuse

    source = inspect.getsource(admin_langfuse.get_item_text)
    assert "WHERE design_id = ANY(:ids)" in source, "looked up globally"
    assert '"filed_under_another_grade"' in source
    assert "d not in stored and d not in elsewhere" in source

    screen = " ".join(
        (Path(__file__).resolve().parents[2] / "frontend-web/src/views/ItemText.tsx")
        .read_text().split()
    )
    assert "The design was written — under" in screen
    assert "which is in no grade at all" in screen


def test_the_most_specific_declaration_wins_not_the_first_one() -> None:
    """A PP2 design prints "PRE - PRIMARY SCHOOL CURRICULUM DESIGN" above
    "PRE - PRIMARY 2", so taking the first line found reads it as PP1. The
    level word alone is the weakest thing on any cover — it is on the PP1 and
    the PP2 ones both."""
    pp2 = ("KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\n"
           "PRE - PRIMARY SCHOOL CURRICULUM DESIGN\nPRE - PRIMARY 2\n")
    assert _grade_from_text(pp2, {})[0] == "grade-pp2"

    # A cover with only the level word still resolves, at the weakest rank.
    assert _grade_from_text("PRE-PRIMARY CURRICULUM DESIGN\nCRE ACTIVITIES\n", {})[0] == "grade-pp1"


# ── every level on the ladder, told apart ───────────────────────────────────

_FOREWORD = (
    "The Ministry of Education has rolled out the implementation of the "
    "Competency Based Curriculum (CBC) at Pre-Primary, Primary and Junior "
    "School levels."
)

# Every grade KICD publishes for, with the foreword sentence that broke this
# appended to each — because it is on every one of these documents.
_COVERS = {
    "grade-pp1": "PRE - PRIMARY SCHOOL CURRICULUM DESIGN\nPRE - PRIMARY 1\nCRE ACTIVITIES\n",
    "grade-pp2": "PRE - PRIMARY SCHOOL CURRICULUM DESIGN\nPRE - PRIMARY 2\nLANGUAGE ACTIVITIES\n",
    "grade-1": "LOWER PRIMARY CURRICULUM DESIGN\nGRADE 1\nMATHEMATICAL ACTIVITIES\n",
    "grade-2": "LOWER PRIMARY CURRICULUM DESIGN\nGRADE 2\nENGLISH ACTIVITIES\n",
    "grade-3": "GRADE 3 CURRICULUM DESIGN\nKISWAHILI\n",
    "grade-4": "UPPER PRIMARY CURRICULUM DESIGN\nGRADE 4\nSCIENCE AND TECHNOLOGY\n",
    "grade-5": "GRADE 5 CURRICULUM DESIGN\nAGRICULTURE\n",
    "grade-6": "GRADE 6 CURRICULUM DESIGN\nSOCIAL STUDIES\n",
    "grade-7": "JUNIOR SCHOOL CURRICULUM DESIGN\nGRADE 7\nINTEGRATED SCIENCE\n",
    "grade-8": "JUNIOR SCHOOL CURRICULUM DESIGN\nGRADE 8\nPRE-TECHNICAL STUDIES\n",
    "grade-9": "JUNIOR SCHOOL CURRICULUM DESIGN\nSOCIAL STUDIES\nGRADE 9\n",
    "grade-10": "SENIOR SCHOOL CURRICULUM DESIGN\nGRADE 10\nBIOLOGY\n",
    "grade-11": "SENIOR SCHOOL CURRICULUM DESIGN\nGRADE 11\nCHEMISTRY\n",
    "grade-12": "SENIOR SCHOOL CURRICULUM DESIGN\nGRADE 12\nPHYSICS\n",
    "grade-dte": "DIPLOMA IN TEACHER EDUCATION\nCURRICULUM DESIGN\nMATHEMATICS\n",
}


def test_every_grade_on_the_ladder_is_told_apart() -> None:
    """Each with the foreword sentence appended, because it is on every one of
    these documents and it is what sent Grade 9 to PP1."""
    from app.services.grade_order import GRADE_SEQUENCE

    assert set(_COVERS) == {slug for slug, _, _ in GRADE_SEQUENCE}, "a grade is untested"

    for want, cover in _COVERS.items():
        assert _grade_from_text(cover + _FOREWORD, {})[0] == want, want


def test_the_dataset_never_has_to_correct_the_cover() -> None:
    """With the cover read correctly, the declared grade agrees rather than
    overriding — which is how a misread cover stayed invisible."""
    for want, cover in _COVERS.items():
        assert _grade_from_text(cover + _FOREWORD, {"grade": want})[0] == want, want


def test_the_diploma_is_not_mistaken_for_pre_primary() -> None:
    """Its covers do not always print the phrase whole: "DIPLOMA CURRICULUM
    DESIGN" above "PRE-PRIMARY AND PRIMARY TEACHER EDUCATION" put the level
    word on one line and the diploma on another.

    "PRE-PRIMARY AND PRIMARY" is itself the tell — a pre-primary design says
    "PRE-PRIMARY" without "AND PRIMARY" after it.
    """
    for cover in (
        "DIPLOMA IN TEACHER EDUCATION (PRE-PRIMARY AND PRIMARY)\nMATHEMATICS\n",
        "PRE-PRIMARY AND PRIMARY TEACHER EDUCATION\nDIPLOMA CURRICULUM DESIGN\n",
        "DIPLOMA CURRICULUM DESIGN\nENGLISH\n",
    ):
        assert _grade_from_text(cover, {})[0] == "grade-dte", cover

    # And the guard must not swallow the pre-primary designs it sits next to.
    assert _grade_from_text("PRE - PRIMARY SCHOOL CURRICULUM DESIGN\nPRE - PRIMARY 1\n", {})[0] == "grade-pp1"
    assert _grade_from_text("PRE-PRIMARY CURRICULUM DESIGN\nCRE ACTIVITIES\n", {})[0] == "grade-pp1"


def test_a_two_digit_grade_is_not_read_as_one_digit() -> None:
    """10, 11 and 12 must not be mistaken for 1 and 2 — the reason the grade
    was read as a number in the first place."""
    for number in (10, 11, 12):
        assert _grade_from_text(f"GRADE {number} CURRICULUM DESIGN\n", {})[0] == f"grade-{number}"
