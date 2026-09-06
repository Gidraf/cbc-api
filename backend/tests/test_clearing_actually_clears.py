"""Clearing a grade has to clear the things that come back.

Clearing a grade and regenerating its strands brought the diagrams back. Not a
caching problem: `uploaded_assets` — the table that holds every drawn figure
and every uploaded one — was in neither cleaner. The rows survived, and the
book attaches whatever is filed for a sub-strand to the next plan written for
it, so the figures reappeared under the new strands as though they had been
regenerated.

The same held for three other tables added since the cleaners were written. A
cleaner that is not extended when a table is added is a cleaner that quietly
stops clearing, so this test names the tables rather than trusting the lists.
"""
from __future__ import annotations

import re

import pytest

from app.infra.db import MIGRATIONS
from app.services import factory_reset, scoped_delete

# Every table that holds GENERATED content, as against curriculum the operator
# ingested or configuration they set.
CONTENT_TABLES = {
    "artifacts", "substrand_media", "substrand_resources", "question_dna",
    "uploaded_assets", "material_drafts", "question_events",
}


def _reset_tables() -> set[str]:
    return {t.table for t in factory_reset.DERIVED}


def _scoped_tables() -> set[str]:
    return {t.table for t in scoped_delete.DERIVED}


@pytest.mark.parametrize("table", sorted(CONTENT_TABLES))
def test_a_grade_reset_clears_every_table_that_holds_content(table: str) -> None:
    assert table in _reset_tables(), (
        f"{table} holds generated content and a grade reset leaves it behind")


@pytest.mark.parametrize("table", sorted(CONTENT_TABLES))
def test_a_scoped_delete_clears_them_too(table: str) -> None:
    assert table in _scoped_tables(), (
        f"{table} survives deleting the sub-strand it belongs to")


def test_the_drawings_are_the_ones_that_came_back() -> None:
    """Named on its own because this is the row that produced the symptom: the
    book attaches whatever is filed for a sub-strand, so a surviving drawing
    reappears under the next plan without anything regenerating it."""
    assert "uploaded_assets" in _reset_tables()
    assert "uploaded_assets" in _scoped_tables()


def test_the_daily_plan_is_not_content_and_survives_a_scoped_delete() -> None:
    """A target is what a scope is MEANT to produce. Deleting one sub-strand's
    content should not silently wipe the grade's plan for the day."""
    assert "question_targets" in _reset_tables(), "a whole-grade reset does clear it"
    assert "question_targets" not in _scoped_tables()


def _columns(table: str) -> set[str]:
    for _version, sql in MIGRATIONS:
        found = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n        \);",
                          sql, re.S)
        if found:
            return set(re.findall(r"^\s+([a-z_]+)\s+[A-Z]", found.group(1), re.M))
    return set()


@pytest.mark.parametrize("target", [
    t for t in factory_reset.DERIVED if t.grade_column or t.subject_column])
def test_every_reset_narrows_on_a_column_that_exists(target) -> None:
    """A cleaner narrowing on a column the table does not have deletes nothing
    and reports success, which is worse than not running."""
    columns = _columns(target.table)
    if not columns:
        pytest.skip(f"{target.table} is not created by a numbered migration")
    for column in (target.grade_column, target.subject_column):
        if column:
            assert column in columns, f"{target.table} has no column '{column}'"


@pytest.mark.parametrize("target", [
    t for t in scoped_delete.DERIVED if t.grade or t.strand or t.sub_strand])
def test_every_scoped_delete_narrows_on_a_column_that_exists(target) -> None:
    columns = _columns(target.table)
    if not columns:
        pytest.skip(f"{target.table} is not created by a numbered migration")
    for column in (target.grade, target.subject, target.strand, target.sub_strand):
        if column:
            assert column in columns, f"{target.table} has no column '{column}'"


# ── the grade has to match however it was written ───────────────────────────


@pytest.mark.parametrize("stored", ["grade-9", "Grade-9", "GRADE-9", "9"])
def test_a_reset_matches_a_grade_however_it_was_filed(stored: str) -> None:
    """The clause was a bare `=`, which is case-sensitive in Postgres. A row
    filed as "Grade-9" survived a reset of "grade-9": nothing removed, success
    reported, and the content back on the next read."""
    target = next(t for t in factory_reset.DERIVED if t.table == "uploaded_assets")

    sql, _params = target.where(stored, "Mathematics")

    assert "REPLACE(LOWER(grade), 'grade-', '')" in sql
    assert "= :grade OR" not in sql, "a bare equality misses a differing case"


def test_a_scoped_delete_matches_it_the_same_way() -> None:
    target = next(t for t in scoped_delete.DERIVED if t.table == "uploaded_assets")

    sql, _params = target.clause("Grade-9", "Mathematics", "Numbers", "Integers")

    assert "REPLACE(LOWER(grade), 'grade-', '')" in sql
    assert "LOWER(sub_strand) = LOWER(:sub_strand)" in sql


def test_a_table_with_no_grade_is_left_alone_by_a_grade_reset() -> None:
    """A grade-limited reset that cannot narrow a table must skip it rather
    than delete every row in it."""
    class _NoGrade:
        pass

    targets = [t for t in factory_reset.DERIVED
               if not (t.grade_column or t.grade_json or t.via_artifacts)]
    for target in targets:
        sql, _ = target.where("grade-9", "")
        assert sql == "", f"{target.table} would be cleared for every grade"
