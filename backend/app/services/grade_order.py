"""Canonical CBC grade ordering.

Grade slugs are stored as text (``grade-1``, ``grade-10``, ``grade-pp1``, ``grade-dte``),
so ``ORDER BY grade`` sorts them lexicographically and yields grade-1, grade-10,
grade-11, grade-12, grade-2. Every listing that shows grades to a user or to the
exam builder must order by :func:`grade_ordinal` instead.
"""
from __future__ import annotations

import re

# Basic Education progression, lowest to highest. DTE (Diploma in Teacher
# Education) sits above basic education and sorts last.
GRADE_SEQUENCE: list[tuple[str, str, str]] = [
    ("grade-pp1", "PP1", "Pre-Primary"),
    ("grade-pp2", "PP2", "Pre-Primary"),
    ("grade-1", "Grade 1", "Lower Primary"),
    ("grade-2", "Grade 2", "Lower Primary"),
    ("grade-3", "Grade 3", "Lower Primary"),
    ("grade-4", "Grade 4", "Upper Primary"),
    ("grade-5", "Grade 5", "Upper Primary"),
    ("grade-6", "Grade 6", "Upper Primary"),
    ("grade-7", "Grade 7", "Junior School"),
    ("grade-8", "Grade 8", "Junior School"),
    ("grade-9", "Grade 9", "Junior School"),
    ("grade-10", "Grade 10", "Senior School"),
    ("grade-11", "Grade 11", "Senior School"),
    ("grade-12", "Grade 12", "Senior School"),
    ("grade-dte", "Diploma in Teacher Education", "Tertiary"),
]

_ORDINAL: dict[str, int] = {slug: idx + 1 for idx, (slug, _, _) in enumerate(GRADE_SEQUENCE)}
_LABEL: dict[str, str] = {slug: label for slug, label, _ in GRADE_SEQUENCE}
_LEVEL: dict[str, str] = {slug: level for slug, _, level in GRADE_SEQUENCE}

UNKNOWN_ORDINAL = 999


def normalize_grade(grade: str | None) -> str:
    """Coerce any inbound grade spelling to a canonical ``grade-x`` slug."""
    if not grade:
        return ""

    raw = str(grade).strip().lower().replace("_", "-").replace(" ", "-")
    raw = re.sub(r"-+", "-", raw).strip("-")

    if raw.startswith("grade-"):
        raw = raw[len("grade-") :]
    elif raw.startswith("grade"):
        raw = raw[len("grade") :].strip("-")

    if raw in {"dte", "diploma", "teacher-education"}:
        return "grade-dte"
    if raw in {"pp1", "pp2"}:
        return f"grade-{raw}"
    if raw.isdigit():
        return f"grade-{int(raw)}"

    return f"grade-{raw}" if raw else ""


def grade_ordinal(grade: str | None) -> int:
    """Position in the CBC progression, lowest grade first.

    Unrecognised grades sort last rather than raising, so a malformed row never
    breaks a listing.
    """
    return _ORDINAL.get(normalize_grade(grade), UNKNOWN_ORDINAL)


def grade_label(grade: str | None) -> str:
    slug = normalize_grade(grade)
    return _LABEL.get(slug, slug.replace("grade-", "Grade ").replace("-", " ").title() if slug else "Unknown")


def grade_level(grade: str | None) -> str:
    """The BECF level band a grade belongs to (Lower Primary, Junior School, …)."""
    return _LEVEL.get(normalize_grade(grade), "")


def sort_grades(grades: list[str]) -> list[str]:
    """Sort grade slugs lowest to highest, de-duplicating on the way."""
    seen: set[str] = set()
    unique: list[str] = []
    for g in grades:
        slug = normalize_grade(g)
        if slug and slug not in seen:
            seen.add(slug)
            unique.append(slug)
    return sorted(unique, key=lambda g: (grade_ordinal(g), g))


def sort_rows_by_grade(rows: list[dict], key: str = "grade") -> list[dict]:
    """Sort dicts carrying a grade field, lowest grade first."""
    return sorted(rows, key=lambda r: (grade_ordinal(r.get(key)), str(r.get(key) or "")))


def describe(grade: str | None) -> dict[str, object]:
    """The full display record for a grade — what list endpoints should return."""
    slug = normalize_grade(grade)
    return {
        "slug": slug,
        "label": grade_label(slug),
        "level": grade_level(slug),
        "ordinal": grade_ordinal(slug),
    }
