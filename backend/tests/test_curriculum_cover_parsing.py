"""Subject and grade read off a KICD cover page.

The cover names the learning area on its own line. Getting this wrong is silent:
a design filed under the wrong grade or as "General Curriculum" still generates
questions, they are just for the wrong cohort or unattributable.
"""
from __future__ import annotations

import pytest

from app.services.curriculum_extractor import (
    _looks_like_a_heading,
    subject_from_filename,
    _grade_from_text,
    _looks_like_subject,
    _subject_from_cover,
)


def cover(level_banner: str, subject: str, grade_banner: str) -> str:
    return (
        "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\n"
        "A skilled and Ethical Society\n"
        f"{level_banner}\n{subject}\n{grade_banner}\n"
    )


@pytest.mark.parametrize("subject,grade_banner,want_subject,want_grade,want_level", [
    ("FRENCH", "GRADE 4", "French", "grade-4", "Upper Primary"),
    ("MATHEMATICS", "GRADE 6", "Mathematics", "grade-6", "Upper Primary"),
    ("CHEMISTRY", "GRADE 10", "Chemistry", "grade-10", "Senior School"),
    ("PHYSICS", "GRADE 12", "Physics", "grade-12", "Senior School"),
    ("INTEGRATED SCIENCE", "GRADE 8", "Integrated Science", "grade-8", "Junior School"),
    ("ENGLISH ACTIVITIES", "GRADE 3", "English Activities", "grade-3", "Lower Primary"),
])
def test_cover_yields_subject_and_grade(subject, grade_banner, want_subject, want_grade, want_level):
    text = cover("SENIOR SCHOOL CURRICULUM DESIGN", subject, grade_banner)
    assert _subject_from_cover(text).title() == want_subject
    assert _grade_from_text(text, {}) == (want_grade, want_level)


def test_grade_10_is_not_read_as_grade_1():
    """The old matcher tested for substrings, so 'GRADE 10' answered to 'GRADE 1'."""
    text = cover("SENIOR SCHOOL CURRICULUM DESIGN", "BIOLOGY", "GRADE 10")
    grade, level = _grade_from_text(text, {})
    assert grade == "grade-10"
    assert level == "Senior School"


def test_grade_5_and_6_stay_distinct():
    """They used to collapse into grade-4 together."""
    five = _grade_from_text(cover("PRIMARY SCHOOL EDUCATION CURRICULUM DESIGN", "SCIENCE", "GRADE 5"), {})
    six = _grade_from_text(cover("PRIMARY SCHOOL EDUCATION CURRICULUM DESIGN", "SCIENCE", "GRADE 6"), {})
    assert five[0] == "grade-5"
    assert six[0] == "grade-6"


def test_level_banner_is_not_mistaken_for_the_subject():
    text = cover("PRIMARY SCHOOL EDUCATION CURRICULUM DESIGN", "FRENCH", "GRADE 4")
    assert _subject_from_cover(text).title() == "French"


def test_diploma_cover_names_subject_before_the_words():
    text = (
        "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\n"
        "DIPLOMA IN TEACHER EDUCATION\n"
        "PRE-PRIMARY AND PRIMARY\n"
        "AGRICULTURE\n"
        "CURRICULUM DESIGN\n"
    )
    assert _subject_from_cover(text).title() == "Agriculture"
    assert _grade_from_text(text, {})[0] == "grade-dte"


def test_pathway_label_is_never_accepted_as_a_subject():
    """'Pure Sciences #2' is a group and an index, not a learning area."""
    assert not _looks_like_subject("Pure Sciences #2")
    assert not _looks_like_subject("Technical Studies #7")
    assert _looks_like_subject("Pure Sciences")


def test_grade_falls_back_to_the_declared_catalogue_grade():
    text = "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\nCURRICULUM DESIGN\nCHEMISTRY\n"
    assert _grade_from_text(text, {"grade": "Grade 11"}) == ("grade-11", "Senior School")


def test_missing_grade_everywhere_reports_nothing_rather_than_guessing():
    assert _grade_from_text("CURRICULUM DESIGN\nCHEMISTRY\n", {}) == ("", "")


# ── A level name must never become a subject ─────────────────────────────────
# Sub-strands key on (grade, subject, strand, sub_strand), so two designs that
# resolve to the same subject overwrite each other. Accepting "Diploma in
# Teacher Education" as a learning area collapsed all 30 DTE designs into one.

@pytest.mark.parametrize("level_name", [
    "Diploma in Teacher Education",
    "Pre-Primary and Primary",
    "Senior School",
    "Junior School",
    "Lower Primary",
    "Upper Primary",
    "Basic Education",
    "General Curriculum",
    "Primary School Education",
])
def test_level_names_are_rejected_as_subjects(level_name):
    assert not _looks_like_subject(level_name)


@pytest.mark.parametrize("subject", [
    "Agriculture", "Chemistry", "English", "Kiswahili", "Art & Craft",
    "Kenyan Sign Language", "ICT Integration in Education", "Home Science",
    "Christian Religious Education", "Pre-Technical Studies",
])
def test_real_learning_areas_are_still_accepted(subject):
    assert _looks_like_subject(subject)


def test_diploma_cover_resolves_to_the_learning_area_not_the_programme():
    text = (
        "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\n"
        "DIPLOMA IN TEACHER EDUCATION\n"
        "PRE-PRIMARY AND PRIMARY\n"
        "AGRICULTURE\n"
        "CURRICULUM DESIGN\n"
    )
    assert _subject_from_cover(text).title() == "Agriculture"


def test_two_diploma_designs_do_not_collapse_into_one_subject():
    """The failure mode from the logs: every DTE design becoming one subject."""
    def cover(area):
        return (
            "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\n"
            "DIPLOMA IN TEACHER EDUCATION\nPRE-PRIMARY AND PRIMARY\n"
            f"{area}\nCURRICULUM DESIGN\n"
        )

    subjects = {_subject_from_cover(cover(a)).title() for a in ("AGRICULTURE", "MUSIC", "HOME SCIENCE")}
    assert subjects == {"Agriculture", "Music", "Home Science"}


# ── The grade comes from the cover, never from the body ──────────────────────
# A design's body mentions other grades constantly ("as introduced in Grade 1"),
# so searching the whole document filed a Pre-Primary design under Grade 1.

def test_pre_primary_is_not_claimed_by_a_grade_mentioned_in_the_body():
    text = (
        "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\n"
        "PRE-PRIMARY 1\nCURRICULUM DESIGN\nLANGUAGE ACTIVITIES\n"
        + "\n" * 5
        + "This builds on competencies acquired before Grade 1 and prepares the "
          "learner for Grade 1 and Grade 2 work.\n"
    )
    assert _grade_from_text(text, {}) == ("grade-pp1", "Pre-Primary")


def test_pre_primary_2_is_distinguished_from_pre_primary_1():
    text = "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\nPRE-PRIMARY 2\nCURRICULUM DESIGN\n"
    assert _grade_from_text(text, {})[0] == "grade-pp2"


def test_a_grade_mentioned_far_into_the_body_does_not_override_the_cover():
    text = (
        "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\n"
        "PRIMARY SCHOOL EDUCATION CURRICULUM DESIGN\nMATHEMATICS\nGRADE 4\n"
        + "\n".join("Learners revisit Grade 9 content." for _ in range(200))
    )
    assert _grade_from_text(text, {})[0] == "grade-4"


@pytest.mark.parametrize("spelling", [
    "Pre - Primary 1", "Pre-Primary 1", "Pre Primary 2", "PRE - PRIMARY",
])
def test_spaced_hyphen_spellings_are_still_rejected_as_subjects(spelling):
    """'Pre - Primary 1' slipped past the level filter and became a subject."""
    assert not _looks_like_subject(spelling)


# ── Subjects must be learning areas, never prose lifted from the body ────────
# Ingests produced 'Self-Awareness As Learners Talk About Their N' and
# 'Of The Basic Education Curriculum.' because any line after any occurrence of
# "curriculum design" was accepted.

@pytest.mark.parametrize("fragment", [
    "Self-Awareness As Learners Talk About Their N",
    "Of The Basic Education Curriculum.",
    "the learner should be able to identify",
    "This design builds on competencies acquired earlier,",
])
def test_prose_is_not_mistaken_for_a_heading(fragment):
    assert not _looks_like_a_heading(fragment)


@pytest.mark.parametrize("heading", [
    "MATHEMATICS", "LANGUAGE ACTIVITIES", "Christian Religious Education",
    "Art & Craft", "CRE",
])
def test_real_headings_are_accepted(heading):
    assert _looks_like_a_heading(heading)


@pytest.mark.parametrize("filename,expected", [
    ("Grade 1-3 CRE - Revised.pdf", "CRE"),
    ("Grade 1-3 English Activities - Revised Sept.pdf", "English Activities"),
    ("Grade 1-3 Mathematics - Revised.pdf", "Mathematics"),
    ("Chemistry Grade 12 - March 2026.pdf", "Chemistry"),
    ("DTE SOCIAL STUDIES.pdf", "SOCIAL STUDIES"),
])
def test_subject_is_read_from_the_filename(filename, expected):
    assert subject_from_filename(filename) == expected


def test_a_known_learning_area_on_the_cover_wins_over_any_heuristic():
    """The catalogue is the strongest signal: no guessing needed."""
    text = (
        "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\n"
        "Self-awareness as learners talk about their needs\n"
        "PRIMARY SCHOOL EDUCATION CURRICULUM DESIGN\n"
        "MATHEMATICS\nGRADE 4\n"
    )
    assert _subject_from_cover(text) == "Mathematics"


def test_a_body_sentence_mentioning_curriculum_design_is_not_a_subject():
    text = (
        "KENYA INSTITUTE OF CURRICULUM DEVELOPMENT\n"
        "PRE-PRIMARY 1\n"
        "This forms part of the basic education curriculum design framework.\n"
        "Of The Basic Education Curriculum.\n"
    )
    assert _subject_from_cover(text) != "Of The Basic Education Curriculum."
