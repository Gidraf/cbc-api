"""Clearing generated content without clearing the things that are not content.

The per-subject delete cleared four tables and left artifacts, media, scopes,
reviews and ingest status behind — which is why re-ingesting produced orphans
that referenced designs no longer there.
"""
from __future__ import annotations

import pytest

from app.services import factory_reset as reset


@pytest.fixture
def db(monkeypatch):
    state = {"counts": {}, "deleted": [], "fail": set()}

    def fetch_one(sql, params=None):
        table = sql.split(" FROM ")[1].split(" WHERE ")[0].strip()
        return {"n": state["counts"].get(table, 0)}

    def execute(sql, params=None):
        table = sql.split(" FROM ")[1].split(" WHERE ")[0].strip()
        if table in state["fail"]:
            raise RuntimeError("permission denied")
        state["deleted"].append(table)

    monkeypatch.setattr("app.infra.db.fetch_one", fetch_one)
    monkeypatch.setattr("app.infra.db.execute", execute)
    return state


def test_it_deletes_nothing_without_the_confirmation(db) -> None:
    db["counts"] = {"artifacts": 40, "curriculum_substrands": 12}

    report = reset.run()

    assert report.dry_run
    assert report.total == 52
    assert db["deleted"] == [], "a dry run deleted rows"
    assert "Nothing has been deleted" in report.to_dict()["message"]


def test_a_near_miss_confirmation_is_still_a_dry_run(db) -> None:
    """A boolean is too easy to send by accident from a form or a retry."""
    db["counts"] = {"artifacts": 40}

    assert reset.run(confirm="yes").dry_run
    assert reset.run(confirm="delete all generated content").dry_run
    assert db["deleted"] == []


def test_the_exact_phrase_deletes(db) -> None:
    db["counts"] = {"artifacts": 40, "curriculum_designs": 7}

    report = reset.run(confirm=reset.CONFIRMATION)

    assert not report.dry_run
    assert "artifacts" in db["deleted"]
    assert "curriculum_designs" in db["deleted"]


def test_children_are_deleted_before_their_parents(db) -> None:
    """A reset that removes designs before the sub-strands referencing them
    leaves rows nothing can resolve."""
    db["counts"] = {t.table: 1 for t in reset.DERIVED}

    reset.run(confirm=reset.CONFIRMATION)

    order = db["deleted"]
    assert order.index("curriculum_substrands") < order.index("curriculum_designs")
    assert order.index("artifact_reviews") < order.index("artifacts")
    assert order.index("artifact_labels") < order.index("artifacts")
    assert order.index("substrand_resources") < order.index("curriculum_designs")


@pytest.mark.parametrize("table", [
    "app_users", "api_keys", "provider_configs", "stage_bindings",
    "schema_migrations", "prompt_versions",
])
def test_configuration_is_never_touched(table) -> None:
    """Losing these turns a content reset into an outage."""
    assert table in reset.PROTECTED
    assert table not in {t.table for t in reset.DERIVED}


def test_a_subject_reset_requires_a_grade(db) -> None:
    """Subject names repeat across grades — "Mathematical Activities" exists at
    every level — so clearing one by name alone takes every grade's copy."""
    report = reset.run(subject="Mathematical Activities", confirm=reset.CONFIRMATION)

    assert db["deleted"] == []
    assert "needs a grade too" in report.failed[0]["error"]


def test_a_narrowed_reset_leaves_unscoped_tables_alone(db) -> None:
    """A table with no grade column cannot be narrowed, and deleting all of it
    for a one-grade reset would take every other grade with it."""
    db["counts"] = {t.table: 5 for t in reset.DERIVED}

    report = reset.run(grade="grade-pp1", confirm=reset.CONFIRMATION)

    assert "diagram_registry" not in db["deleted"]
    assert any(s["table"] == "diagram_registry" for s in report.skipped)
    assert "artifacts" in db["deleted"], "a scoped table must still be cleared"


def test_a_full_reset_clears_the_unscoped_tables_too(db) -> None:
    db["counts"] = {t.table: 5 for t in reset.DERIVED}

    reset.run(confirm=reset.CONFIRMATION)

    assert "diagram_registry" in db["deleted"]


def test_a_partial_failure_is_reported_as_incomplete(db) -> None:
    """Reporting success after a half-finished delete leaves content pointing at
    rows that are gone, and nobody looking for it."""
    db["counts"] = {"artifacts": 5, "curriculum_designs": 2}
    db["fail"] = {"curriculum_designs"}

    report = reset.run(confirm=reset.CONFIRMATION)

    assert report.failed
    assert "INCOMPLETE" in report.to_dict()["message"]


def test_an_empty_table_is_counted_but_not_deleted_from(db) -> None:
    db["counts"] = {"artifacts": 0}

    reset.run(confirm=reset.CONFIRMATION)

    assert "artifacts" not in db["deleted"]


def test_the_dataset_is_never_a_target() -> None:
    """The Langfuse dataset is the source of truth. If the reset could touch it
    there would be nothing left to rebuild from."""
    tables = {t.table for t in reset.DERIVED}

    assert not any("dataset" in t and t != "dataset_ingest_status" for t in tables)
    assert "dataset_ingest_status" in tables, "the ingest LEDGER is derived and must clear"


def test_the_route_is_admin_only_and_dry_run_by_default() -> None:
    route = open("app/routes/curriculum.py").read()
    block = route[route.index("def factory_reset("):]
    block = block[: block.index("\n@router.")]

    signature = route[route.index("def factory_reset("): route.index("def factory_reset(") + 300]
    assert 'require_roles("admin")' in signature, "a full wipe must not be operator-callable"
    assert 'confirm: str = ""' in route
    assert "FACTORY RESET by %s" in block, "a destructive run must name who ran it"
