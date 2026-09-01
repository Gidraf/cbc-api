"""One way to compare a grade, everywhere.

The same grade is written four ways across this system — "PP1", "pp1",
"grade-pp1", "Grade-PP1" — because it arrives from a Langfuse dataset name, a
URL path, a design's cover page and an operator's typing, and nothing forced
them to agree.

Every query then invented its own comparison, and the exact ones worked for
whichever grade happened to be ingested with the spelling the code passed. A
fully ingested Grade 9 reported every subject as missing while PP1 was fine.
"""
from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# An UPDATE ... SET assigns; it does not compare. And the helper's own
# docstring quotes the broken forms in order to explain them.
_ALLOWED = {"content_type_classifier.py", "grade_sql.py"}

_EXACT = re.compile(r"(?<!LOWER\()\b(?:\w+\.)?grade\s*=\s*:(?:grade|alt_grade|alt)\b")


def test_no_query_compares_a_grade_exactly() -> None:
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        if path.name in _ALLOWED:
            continue
        for i, line in enumerate(path.read_text().splitlines(), start=1):
            if "REPLACE(LOWER(" in line or "LOWER(" in line:
                continue
            if _EXACT.search(line):
                offenders.append(f"{path.relative_to(APP)}:{i}  {line.strip()[:80]}")
    assert not offenders, (
        "case-sensitive grade comparison — use services.grade_sql.clause(), which "
        "normalises BOTH sides:\n  " + "\n  ".join(offenders)
    )


def test_the_comparison_normalises_both_sides() -> None:
    """Normalising only the value passed IN is how the bug survived a fix: the
    caller held `grade-9` and the row held `9`, or the other way round."""
    from app.services.grade_sql import clause

    sql = clause("d.grade")
    assert "REPLACE(LOWER(d.grade), 'grade-', '')" in sql
    assert "REPLACE(LOWER(:grade), 'grade-', '')" in sql


def test_every_grade_normalises_to_one_slug() -> None:
    from app.services.grade_order import normalize_grade

    for spelling in ("Grade 9", "grade-9", "GRADE_9", "9", " grade  9 "):
        assert normalize_grade(spelling) == "grade-9", spelling
    for spelling in ("PP1", "pp1", "grade-pp1", "Grade PP1"):
        assert normalize_grade(spelling) == "grade-pp1", spelling


def test_the_subjects_listing_finds_an_upper_grade() -> None:
    """The query behind "ingested or missing" was the plainest case-sensitive
    comparison in the codebase, and it is what the operator sees first."""
    import inspect

    from app.services.langfuse_context import langfuse_context_service

    source = inspect.getsource(langfuse_context_service.get_available_subjects)
    assert "REPLACE(LOWER(grade), 'grade-', '')" in source
    assert source.count("WHERE grade = :grade") == 0


def test_every_grade_has_a_published_subject_list_and_a_register() -> None:
    """A grade with neither reports as empty rather than as unconfigured."""
    from app.services.curriculum_catalogue import expected_subjects
    from app.services.grade_order import GRADE_SEQUENCE
    from app.services.level_register import register_block

    for slug, label, _level in GRADE_SEQUENCE:
        assert expected_subjects(slug), f"{label} publishes no subjects"
        block = register_block(slug)
        assert "AUDIENCE:" in block, label
        assert "PRACTICAL WORK:" in block, label
