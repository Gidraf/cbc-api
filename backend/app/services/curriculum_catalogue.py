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

from typing import Any

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

# Pre-Primary is counted two different ways, and both are correct.
#
# The LESSON ALLOCATION table (PP1 p.9) lists FIVE activity areas per week:
# Language 5, Mathematical 5, Creative 6, Environmental 5, Religious 3, plus one
# Pastoral Instruction Programme lesson — 25 in total. That is the timetable.
#
# The TABLE OF CONTENTS (p.6) lists SEVEN curriculum designs, because the single
# "Religious Activities" slot is filled by one of three separate designs with
# entirely different strands: Christian, Hindu or Islamic RE. A learner takes one.
#
# Content generation must use the seven. Collapsing them into one "Religious
# Activities" bucket is precisely the faith-mixing this system exists to prevent:
# there is no set of strands common to CRE, HRE and IRE to generate from.
#
# The PP1 design's own table of contents lists these seven. Filing them all under
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

# Weekly lessons per timetable slot (PP1 p.9). The religious slot is filled by
# whichever of CRE/HRE/IRE the learner takes, which is why five slots carry
# seven designs.
PRE_PRIMARY_WEEKLY_LESSONS: dict[str, int] = {
    "Language Activities": 5,
    "Mathematical Activities": 5,
    "Creative Activities": 6,
    "Environmental Activities": 5,
    "Religious Activities": 3,
    "Pastoral Instruction Programme": 1,
}

# One per learner, never more.
PRE_PRIMARY_RELIGIOUS_AREAS = (
    "Christian Religious Education",
    "Hindu Religious Education",
    "Islamic Religious Education",
)


def has_combined_design(grade_slug: str) -> bool:
    """True when one published PDF for this grade holds several learning areas."""
    return grade_slug in GRADES_WITH_COMBINED_DESIGN

# ── What each Pre-Primary learning area should contain ───────────────────────
# Read off the PP1 design's own "Summary of Strands and Sub Strands" tables.
# Ingest is otherwise unverifiable: a split that produced one learning area with
# every sub-strand looks the same in the console as a correct one, and the only
# way to notice was to read a generated paper and find Hindu RE in a Language
# question. These counts turn that into a number.
#
# Every entry cites the page of the design's own "Summary of Strands and
# Sub-Strands" table it was read from, so the claim is checkable rather than
# asserted. Secondary sources disagree with this table — some describe the
# pre-2024 design, some describe Grade 1's — and the document wins.
#
# Note the shapes differ. Language Activities is the only area with a genuine
# theme axis (6 themes x 3 strands -> 36 sub-strands). Creative and
# Environmental Activities use their themes AS strands. The three religious
# education areas have no themes at all.
PRE_PRIMARY_STRUCTURE: dict[str, dict[str, Any]] = {
    "Language Activities": {
        # PP1 design, "Summary of Strands and Sub-Strands", page(s) [16, 17].
        "source_pages": [16, 17],
        "strands": ["Listening and Speaking", "Reading", "Writing"],
        "themes": [
            "1.0 Greetings and Farewell", "2.0 Myself", "3.0 My Family",
            "4.0 My Home", "5.0 My Neighbourhood", "6.0 My School",
        ],
        "sub_strand_count": 36,
        "lessons": 150,
    },
    "Mathematical Activities": {
        # PP1 design, "Summary of Strands and Sub-Strands", page(s) [106].
        "source_pages": [106],
        "strands": ["1.0 Pre-Number Activities", "2.0 Numbers", "3.0 Measurement", "4.0 Geometry"],
        "themes": [],
        "sub_strand_count": 17,
        "lessons": 150,
    },
    "Creative Activities": {
        # PP1 design, "Summary of Strands and Sub-Strands", page(s) [148].
        "source_pages": [148],
        "strands": ["1.0 Myself", "2.0 My Family", "3.0 My Home", "4.0 My School"],
        "themes": [],
        "sub_strand_count": 9,
        "lessons": 180,
    },
    "Environmental Activities": {
        # PP1 design, "Summary of Strands and Sub-Strands", page(s) [176].
        "source_pages": [176],
        "strands": [
            "1.0 Myself", "2.0 My Family", "3.0 My Home",
            "4.0 My Neighbourhood", "5.0 My School",
        ],
        "themes": [],
        "sub_strand_count": 14,
        "lessons": 154,
    },
    "Christian Religious Education": {
        # PP1 design, "Summary of Strands and Sub-Strands", page(s) [202].
        "source_pages": [202],
        "strands": [
            "1.0 Creation", "2.0 The Bible", "3.0 The Life of Jesus Christ",
            "4.0 Christian Values", "5.0 The Church",
        ],
        "themes": [],
        "sub_strand_count": 12,
        "lessons": 90,
    },
    "Hindu Religious Education": {
        # PP1 design, "Summary of Strands and Sub-Strands", page(s) [224].
        "source_pages": [224],
        "strands": [
            "1.0 Creation", "2.0 Manifestations of Paramatma", "3.0 Scriptures",
            "4.0 Worship", "5.0 Sadachaar", "6.0 Yoga",
        ],
        "themes": [],
        "sub_strand_count": 16,
        "lessons": 90,
    },
    "Islamic Religious Education": {
        # PP1 design, "Summary of Strands and Sub-Strands", page(s) [253].
        "source_pages": [253],
        "strands": [
            "1.0 Qur'an", "2.0 Pillars of Iman", "3.0 Devotional Acts",
            "4.0 Akhlaq (Moral Teachings)", "5.0 Siirah", "6.0 Islamic Festivals",
        ],
        "themes": [],
        "sub_strand_count": 14,
        "lessons": 90,
    },
}


def expected_structure(grade_slug: str, subject: str) -> dict[str, Any]:
    """The strands and sub-strand count a learning area should have, if known."""
    if grade_slug in GRADES_WITH_COMBINED_DESIGN:
        return dict(PRE_PRIMARY_STRUCTURE.get(subject, {}))
    return {}


def uses_theme_axis(grade_slug: str, subject: str) -> bool:
    """True only where the design really runs themes across strands."""
    return bool(expected_structure(grade_slug, subject).get("themes"))



def expected_subjects(grade_slug: str) -> list[str]:
    return list(EXPECTED_SUBJECTS.get(grade_slug, []))


def expected_design_count(grade_slug: str) -> int:
    return EXPECTED_DESIGN_COUNT.get(grade_slug, 0)


def all_grade_slugs() -> list[str]:
    """Every grade KICD publishes for, in progression order."""
    return [slug for slug, _label, _level in GRADE_SEQUENCE]
