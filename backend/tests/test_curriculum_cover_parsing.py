"""Subject and grade read off a KICD cover page.

The cover names the learning area on its own line. Getting this wrong is silent:
a design filed under the wrong grade or as "General Curriculum" still generates
questions, they are just for the wrong cohort or unattributable.
"""
from __future__ import annotations

import pytest

from app.services.curriculum_extractor import (
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
