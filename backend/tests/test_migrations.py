"""Migrations are append-only.

A table added to the body of an already-applied migration never runs: the
version is recorded in schema_migrations, so the whole script is skipped
forever. It works on a fresh database and fails on every existing one, which is
exactly the case local tests miss.
"""
from __future__ import annotations

import re

from app.infra.db import MIGRATIONS


def test_versions_are_unique_and_ordered():
    versions = [v for v, _sql in MIGRATIONS]
    assert len(versions) == len(set(versions)), "duplicate migration version"

    numbers = [int(re.match(r"(\d+)", v).group(1)) for v in versions]
    assert numbers == sorted(numbers), f"migrations out of order: {versions}"


def test_every_migration_has_a_numeric_prefix_and_a_body():
    for version, sql in MIGRATIONS:
        assert re.match(r"^\d{3}_[a-z0-9_]+$", version), f"bad version name: {version}"
        assert sql.strip(), f"migration {version} is empty"


def test_each_table_is_created_in_exactly_one_migration():
    """Two migrations creating the same table means one of them is dead code."""
    created: dict[str, str] = {}
    for version, sql in MIGRATIONS:
        for table in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", sql):
            assert table not in created, (
                f"table '{table}' is created in both {created[table]} and {version}"
            )
            created[table] = version


def test_dataset_ingest_status_ships_as_its_own_migration():
    """Pins the specific mistake: it was first added inside 005, already applied."""
    owner = next(
        (v for v, sql in MIGRATIONS if "CREATE TABLE IF NOT EXISTS dataset_ingest_status" in sql),
        None,
    )
    assert owner is not None, "dataset_ingest_status is not created by any migration"
    assert owner == "013_dataset_ingest_status", (
        f"dataset_ingest_status must live in its own new migration, found in {owner}"
    )


def test_columns_the_ingest_service_reads_all_exist():
    sql = next(sql for v, sql in MIGRATIONS if v == "013_dataset_ingest_status")
    for column in (
        "item_id", "grade", "file_id", "title", "declared_subject",
        "resolved_subject", "design_id", "status", "char_count", "error",
        "selected_at", "started_at", "finished_at", "updated_at",
    ):
        assert re.search(rf"\b{column}\b", sql), f"column '{column}' missing from the table"
