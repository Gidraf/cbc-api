"""One way to compare a grade in SQL.

The same grade is written four ways across this system — "PP1", "pp1",
"grade-pp1", "Grade-PP1" — because it arrives from a Langfuse dataset name, a
URL path, a design's cover page and an operator's typing, and nothing forced
them to agree. Every query then invented its own comparison:

    grade = :grade
    grade = :grade OR grade = :alt_grade
    LOWER(a.grade) = LOWER(:grade)
    REPLACE(LOWER(a.grade), 'grade-', '') = ...

The first two are exact and case-sensitive. They worked for the grade that
happened to be ingested with the same spelling the code passed, and silently
matched nothing for the next one — which is how a fully ingested Grade 9
reported every subject as missing while PP1 was fine.

`clause()` is the only comparison. It normalises BOTH sides, so it does not
matter which spelling reached the database or which one the caller holds.
"""
from __future__ import annotations

# Postgres has no function for "the grade, however it was written", so this is
# it: lowercase, and drop the `grade-` prefix wherever it appears.
_NORM = "REPLACE(LOWER({side}), 'grade-', '')"


def clause(column: str = "grade", param: str = "grade") -> str:
    """SQL comparing a grade column to a bind parameter, however either is spelt.

    >>> clause("a.grade")
    "REPLACE(LOWER(a.grade), 'grade-', '') = REPLACE(LOWER(:grade), 'grade-', '')"
    """
    return (f"{_NORM.format(side=column)} = "
            f"{_NORM.format(side=':' + param)}")
