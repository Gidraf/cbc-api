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


# ── two counters, two tables, no reconciliation ─────────────────────────────


def test_ingested_and_written_are_reported_as_different_facts() -> None:
    """A grade read "16 of 16 ingested" on one screen and "Grade 9 — 1/16" on
    another, with nothing saying they count different tables.

    "Ingested" means the document was PROCESSED. It does not mean a design came
    out of it, and the difference is real work missing.
    """
    import inspect

    from app.services import dataset_ingest
    from app.services.langfuse_context import langfuse_context_service

    # The grade list now reports both numbers rather than one.
    source = inspect.getsource(langfuse_context_service.list_datasets)
    assert '"design_count"' in source
    assert '"ingested_count"' in source
    assert "FROM dataset_ingest_status" in source

    # And the dataset screen can name exactly which items are the gap.
    missing = inspect.getsource(dataset_ingest.designs_missing)
    assert "curriculum_designs" in missing
    assert "s.status = 'ingested'" in missing
    # A combined design records one id per learning area in `design_ids`, so
    # checking only the primary reports a document that produced five designs
    # as having produced none.
    assert "s.design_ids" in missing and "NOT EXISTS" in missing
    # Matched the way every other grade comparison is.
    assert "REPLACE(LOWER(s.grade), 'grade-', '')" in missing


def test_the_console_shows_the_gap_rather_than_two_numbers() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "frontend-web/src"
    datasets = " ".join((root / "views/Datasets.tsx").read_text().split())
    queries = " ".join((root / "lib/queries.ts").read_text().split())

    assert "produced no curriculum design" in datasets
    assert "designs_missing" in datasets
    # And the grade list itself flags it, because that is where the low number
    # appears with no explanation next to it.
    assert "read, no design" in queries


# ── the grade a design is filed under ───────────────────────────────────────


def test_a_grade_is_read_however_the_cover_spells_it() -> None:
    """The separator was a REQUIRED space.

    So the pattern matched the words on a cover page and matched NONE of the
    slugs the system itself uses — which is how the fallback to the grade the
    operator declared could never fire, and sixteen Grade 9 designs were filed
    under grade-7 by a default while Grade 9 read as empty.
    """
    from app.services.curriculum_extractor import _GRADE_NUM

    for spelling in ("GRADE 9", "Grade9", "GRADE-9", "grade-9", "grade_9",
                     "Agriculture Grade9 1.8.2024 -Proofread"):
        found = _GRADE_NUM.search(spelling)
        assert found and found.group(1) == "9", spelling


def test_the_dataset_settles_it_when_the_cover_does_not() -> None:
    """The dataset the operator chose is a fact, not a guess."""
    from app.services.curriculum_extractor import _grade_from_text

    assert _grade_from_text("", {"grade": "grade-9"}) == ("grade-9", "Junior School")
    assert _grade_from_text("AGRICULTURE Grade9 CURRICULUM DESIGN",
                            {"grade": "grade-9"})[0] == "grade-9"

    # A cover that names a grade still wins — that is how a misfiled document
    # is caught rather than silently relabelled.
    assert _grade_from_text("MATHEMATICS GRADE 4", {"grade": "grade-9"})[0] == "grade-4"


def test_nothing_is_ever_filed_under_a_guessed_grade() -> None:
    """Defaulting put a design in another cohort's curriculum, where it stays
    invisible until questions are generated from it."""
    import inspect

    from app.services import curriculum_extractor

    source = inspect.getsource(curriculum_extractor.CurriculumExtractorService._parse_curriculum_text)
    assert 'grade, level = "grade-7", "Basic Education"' not in source
    assert "INVALID_GRADE_DATASET" in source
    assert "the dataset it was ingested from" in source
