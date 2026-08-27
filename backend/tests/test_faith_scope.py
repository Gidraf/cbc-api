"""Christian, Hindu and Islamic Religious Education must not share a prompt.

KICD publishes all three inside one Pre-Primary document. Ingested together they
shared a subject, so an Islamic sub-strand sat beside "1.0 Creation" and
"6.0 Yoga" in the same prompt. For most learning areas that is a correctness
bug; here it is also a matter of respect. A child sitting an IRE paper must not
be asked about the Bible.

The designs share a framework and differ entirely in content, so the isolation
is on content, not on the BECF competencies, values or rubrics.
"""
from __future__ import annotations

import pytest

from app.services.curriculum_catalogue import all_grade_slugs, expected_subjects
from app.services.faith_scope import (
    cross_faith_terms, is_religious_area, prompt_block, scope_for,
)


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [
        # Pre-Primary and DTE print the full name.
        ("Christian Religious Education", "Christian Religious Education"),
        ("Hindu Religious Education", "Hindu Religious Education"),
        ("Islamic Religious Education", "Islamic Religious Education"),
        # Grades 1-9 catalogue them as abbreviations. Matching exact strings
        # recognised only Pre-Primary and silently skipped every other grade.
        ("CRE", "Christian Religious Education"),
        ("HRE", "Hindu Religious Education"),
        ("IRE", "Islamic Religious Education"),
        ("C.R.E", "Christian Religious Education"),
        ("cre", "Christian Religious Education"),
        # Whatever a cover happens to print.
        ("Christian Religious Activities", "Christian Religious Education"),
        ("ISLAMIC RELIGIOUS EDUCATION ACTIVITIES", "Islamic Religious Education"),
        ("Hindu Religious Education (Sanatan)", "Hindu Religious Education"),
    ],
)
def test_a_faith_area_is_recognised_however_it_is_spelled(spelling: str, expected: str) -> None:
    scope = scope_for(spelling)
    assert scope is not None, f"{spelling!r} was not recognised"
    assert scope.subject == expected


def test_isolation_applies_at_every_grade_not_just_pre_primary() -> None:
    """Three areas x twelve grades that publish them, all resolved."""
    resolved = [
        (grade, subject)
        for grade in all_grade_slugs()
        for subject in expected_subjects(grade)
        if is_religious_area(subject)
    ]
    grades = {g for g, _ in resolved}

    assert len(resolved) == 36
    for grade in ("grade-pp1", "grade-1", "grade-4", "grade-7", "grade-dte"):
        assert grade in grades, f"{grade} has religious areas but none were scoped"


@pytest.mark.parametrize(
    "subject",
    ["Language Activities", "Mathematics", "Kiswahili", "Integrated Science",
     "Social Studies", "Creative Arts", "Pre-Technical Studies", "Agriculture"],
)
def test_ordinary_learning_areas_get_no_faith_block(subject: str) -> None:
    """The block must appear only where it applies, or it becomes noise."""
    assert scope_for(subject) is None
    assert prompt_block(subject) == ""


def test_the_block_names_what_is_in_scope_and_what_is_forbidden() -> None:
    block = prompt_block("IRE")

    assert "Islamic Religious Education" in block
    assert "The Holy Qur'an" in block
    assert "Allah (S.W.T.)" in block
    # The other two are named explicitly, not left to inference.
    assert "Christian Religious Education" in block
    assert "Hindu Religious Education" in block
    assert "must NOT draw on any other faith" in block
    # The shared framework is preserved; only content is isolated.
    assert "The framework is common; the content is not." in block


def test_hindu_religious_education_covers_four_faiths_by_design() -> None:
    """KICD scopes HRE across Hinduism/Sanatan, Jain, Buddhist and Sikh
    (PP1 p.213). Treating those as contamination would break the real design."""
    scope = scope_for("HRE")

    assert scope is not None
    assert set(scope.faiths) == {"Hinduism/Sanatan", "Jain", "Buddhist", "Sikh"}
    for scripture in ("Ramayan", "Kalpasutra", "Dhammapada", "Sri Guru Granth Sahib Ji"):
        assert any(scripture in s for s in scope.scriptures), scripture

    content = ("Learners identify Trimurti, recite Namo Jinanam, and listen to a story "
               "about Lord Buddha and Sri Guru Nanak Dev Ji.")
    assert cross_faith_terms(content, "HRE") == []
    assert "that is the design's own intent" in prompt_block("HRE")


def test_content_from_another_faith_is_detected_after_generation() -> None:
    """A prompt instruction is a request; this is the check."""
    bible_in_ire = "Learners retell the story of David and Goliath from the Bible."
    assert set(cross_faith_terms(bible_in_ire, "IRE")) >= {"bible", "david and goliath"}

    quran_in_cre = "Learners recite the shahadah and say Bismillah before the activity."
    assert set(cross_faith_terms(quran_in_cre, "CRE")) >= {"shahadah", "bismillah"}

    yoga_in_cre = "Learners practise simple yoga asanas and identify Trimurti."
    assert "trimurti" in cross_faith_terms(yoga_in_cre, "CRE")


def test_a_faith_area_writing_its_own_content_is_not_flagged() -> None:
    clean = {
        "IRE": "Learners recite the shahadah and practise the dua before entering the toilet.",
        "CRE": "Learners retell the story of David and Goliath and colour a picture of the Church.",
        "HRE": "Learners recite Om Namah Shivaay and name the parts of the body used in yoga.",
    }
    for subject, text in clean.items():
        assert cross_faith_terms(text, subject) == [], f"{subject} flagged its own content"


def test_non_religious_content_is_never_flagged() -> None:
    assert cross_faith_terms("Learners chant rhymes on letter sounds a to e.", "Language Activities") == []
    assert cross_faith_terms("anything at all", None) == []
    assert cross_faith_terms("", "IRE") == []


def test_partial_words_do_not_trigger_a_false_positive() -> None:
    """"dua" inside "graduation", "eid" inside "weighed"."""
    assert cross_faith_terms("The learner attends a graduation ceremony.", "CRE") == []
    assert cross_faith_terms("The object is weighed on a balance.", "CRE") == []
