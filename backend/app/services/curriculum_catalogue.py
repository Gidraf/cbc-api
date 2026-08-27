"""What KICD publishes for each grade, so gaps are visible before ingest.

The console used to list only the grades that happened to be in the database,
behind a hard-coded fallback of six. A grade with nothing ingested was therefore
indistinguishable from a grade that does not exist, and Grades 1-3, 5, 6 and
10-12 never appeared at all.

Listing the published set instead makes "Grade 11 has 0 of 38 designs" a visible
state rather than a silent absence.

Source: the KICD curriculum-designs pages, read through the site's WordPress
REST API on 2026-08-26. Subject names are exactly as KICD prints them.
"""
from __future__ import annotations

from .grade_order import GRADE_SEQUENCE

# Grades 1-3 share one combined Lower Primary design, so the same seven
# learning areas are expected for each of them.
_LOWER_PRIMARY = [
    "CRE", "English Activities", "Environmental Activities", "HRE", "IRE",
    "Kiswahili", "Mathematics",
]

_UPPER_PRIMARY = [
    "Arabic", "CRE", "Creative Arts", "English", "French", "German", "HRE",
    "IRE", "Indigenous Language", "Kiswahili", "Mandarin", "Mathematics",
    "Science and Technology", "Social Studies",
]

_JUNIOR_SCHOOL = [
    "Agriculture", "Arabic", "CRE", "Creative Arts", "English", "French",
    "German", "HRE", "IRE", "Indigenous Language", "Integrated Science",
    "Kiswahili", "Mandarin", "Mathematics", "Pre-Technical Studies",
    "Social Studies",
]

# Senior school is published by pathway, not by learning area: each heading
# carries several unlabelled designs. The real subject is only on each PDF's
# cover, so it is resolved at ingest — see curriculum_extractor.
_SENIOR_PATHWAYS = [
    "Applied Sciences", "Arts & Sports", "Foreign Languages", "Humanities",
    "Languages", "Pure Sciences", "Religious Education", "Technical Studies",
]

_DTE = [
    "Agriculture", "Arabic", "Art & Craft", "Child Development",
    "Christian Religious Education", "Curriculum Studies", "Education Assessment",
    "Educational Resources", "English", "French", "German",
    "Hindu Religious Education",
    "Historical & Comparative Foundations of Education", "Home Science",
    "ICT Integration in Education", "Inclusive Education", "Indigenous Language",
    "Islamic Religious Education", "Kenyan Sign Language", "Kiswahili",
    "Leadership and Management", "Mandarin", "Mathematics", "Microteaching",
    "Music", "Philosophical and Sociological Foundations of Education",
    "Physical Education", "Research Skills", "Science & Technology",
    "Social Studies",
]

# Pre-Primary is published as a SINGLE PDF containing every learning area — the
# PP1 design's own table of contents lists these seven. Filing them all under
# one subject called "Pre-Primary 1" (which is a level, not a learning area)
# made every area overwrite the last, so a request for Language Activities was
# answered with Christian Religious Education. See design_sections.
_PRE_PRIMARY = [
    "Christian Religious Education", "Creative Activities",
    "Environmental Activities", "Hindu Religious Education",
    "Islamic Religious Education", "Language Activities",
    "Mathematical Activities",
]

EXPECTED_SUBJECTS: dict[str, list[str]] = {
    "grade-pp1": list(_PRE_PRIMARY),
    "grade-pp2": list(_PRE_PRIMARY),
    "grade-1": list(_LOWER_PRIMARY),
    "grade-2": list(_LOWER_PRIMARY),
    "grade-3": list(_LOWER_PRIMARY),
    "grade-4": list(_UPPER_PRIMARY),
    "grade-5": list(_UPPER_PRIMARY),
    "grade-6": list(_UPPER_PRIMARY),
    "grade-7": list(_JUNIOR_SCHOOL),
    "grade-8": list(_JUNIOR_SCHOOL),
    "grade-9": list(_JUNIOR_SCHOOL),
    "grade-10": list(_SENIOR_PATHWAYS),
    "grade-11": list(_SENIOR_PATHWAYS),
    "grade-12": list(_SENIOR_PATHWAYS),
    "grade-dte": list(_DTE),
}

# Published design count — the number of PDFs KICD publishes, which is not the
# number of learning areas. Pre-Primary publishes one document holding seven
# areas; senior school publishes more documents than it has pathway headings.
EXPECTED_DESIGN_COUNT: dict[str, int] = {
    "grade-pp1": 1, "grade-pp2": 1,
    "grade-1": 7, "grade-2": 7, "grade-3": 7,
    "grade-4": 14, "grade-5": 14, "grade-6": 14,
    "grade-7": 16, "grade-8": 16, "grade-9": 16,
    "grade-10": 38, "grade-11": 38, "grade-12": 38,
    "grade-dte": 30,
}

# Senior-school subject names are not published; they come off each PDF's cover.
GRADES_WITH_PATHWAY_LABELS = frozenset({"grade-10", "grade-11", "grade-12"})

# Grades whose single published document holds several learning areas, and so
# must be split at ingest rather than filed as one design.
GRADES_WITH_COMBINED_DESIGN = frozenset({"grade-pp1", "grade-pp2"})


def has_combined_design(grade_slug: str) -> bool:
    """True when one published PDF for this grade holds several learning areas."""
    return grade_slug in GRADES_WITH_COMBINED_DESIGN


def expected_subjects(grade_slug: str) -> list[str]:
    return list(EXPECTED_SUBJECTS.get(grade_slug, []))


def expected_design_count(grade_slug: str) -> int:
    return EXPECTED_DESIGN_COUNT.get(grade_slug, 0)


def all_grade_slugs() -> list[str]:
    """Every grade KICD publishes for, in progression order."""
    return [slug for slug, _label, _level in GRADE_SEQUENCE]
