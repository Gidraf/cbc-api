"""Guards stop new bad rows; repairs remove the ones already stored.

A schema migration runs once. Content keeps arriving, so a sweep that removes
raw page debris has to keep running across every grade and subject until it
stops finding anything.
"""
from __future__ import annotations

import pytest

from app.services import data_repairs


@pytest.fixture
def db(monkeypatch):
    state = {"substrands": [], "designs": [], "deleted": [], "updated": [], "recorded": []}

    def fetch_all(sql, params=None):
        # Order matters: the designs sweep names curriculum_substrands in a
        # NOT EXISTS subquery, so match the outer table first.
        if "FROM curriculum_designs" in sql:
            return state["designs"]
        if "FROM curriculum_substrands" in sql:
            return state["substrands"]
        return []

    def execute(sql, params=None):
        if sql.strip().startswith("DELETE"):
            state["deleted"].append(params)
        elif sql.strip().startswith("UPDATE"):
            state["updated"].append(params)

    monkeypatch.setattr("app.infra.db.fetch_all", fetch_all)
    monkeypatch.setattr("app.infra.db.execute", execute)
    monkeypatch.setattr(data_repairs, "_record",
                        lambda result: state["recorded"].append(result.repair_id))
    return state


def test_the_debris_row_is_removed(db) -> None:
    db["substrands"] = [
        {"id": 1, "grade": "grade-pp1", "subject": "Christian Religious Education",
         "strand_name": "4.0 CHRISTIAN VALUES", "sub_strand_name": "4.0 CHRISTIAN VALUES",
         "values": ["214:34  Communication: Learners develop communication skills"]},
        {"id": 2, "grade": "grade-pp1", "subject": "Christian Religious Education",
         "strand_name": "The Church", "sub_strand_name": "A House of God",
         "values": ["Unity", "Patriotism"]},
    ]

    outcome = data_repairs.run_repairs(only="001_purge_substrand_debris")

    assert outcome["rows_affected"] == 1
    assert [d["id"] for d in db["deleted"]] == [1]
    assert not outcome["clean"]


def test_a_clean_database_is_a_no_op(db) -> None:
    """It runs on every boot, so it must cost nothing when there is nothing."""
    db["substrands"] = [
        {"id": 2, "grade": "grade-pp1", "subject": "Christian Religious Education",
         "strand_name": "The Church", "sub_strand_name": "A House of God",
         "values": ["Unity"]},
    ]

    outcome = data_repairs.run_repairs()

    assert outcome["clean"] is True
    assert db["deleted"] == []
    assert db["updated"] == []


def test_a_dry_run_changes_nothing_but_reports_everything(db) -> None:
    db["substrands"] = [
        {"id": 1, "grade": "grade-pp1", "subject": "CRE",
         "strand_name": "Christian Values", "sub_strand_name": "Love for God",
         "slos": ["[PAGE 215]", "identify three ways of loving God"]},
    ]

    outcome = data_repairs.run_repairs(dry_run=True)

    assert outcome["rows_affected"] == 1
    assert db["deleted"] == []
    assert db["recorded"] == [], "a dry run must not record itself as a run"
    assert outcome["repairs"][0]["detail"][0]["reason"]


def test_numbered_names_are_collapsed(db) -> None:
    db["substrands"] = [
        {"id": 3, "grade": "grade-pp1", "subject": "CRE",
         "strand_name": "4.0 Christian Values", "sub_strand_name": "4.1 Love for God"},
    ]

    outcome = data_repairs.run_repairs(only="002_denumber_strand_names")

    assert outcome["rows_affected"] == 1
    assert db["updated"][0]["strand"] == "Christian Values"
    assert db["updated"][0]["sub"] == "Love for God"


def test_a_name_already_clean_is_left_alone(db) -> None:
    db["substrands"] = [
        {"id": 4, "grade": "grade-pp1", "subject": "CRE",
         "strand_name": "The Church", "sub_strand_name": "A House of God"},
    ]

    assert data_repairs.run_repairs(only="002_denumber_strand_names")["clean"]


def test_the_documentless_design_row_is_dropped(db) -> None:
    """Saving sub-strands used to mint "cd_grade-pp1_chri" — no document, newer
    than the real design, and it won every ORDER BY updated_at lookup."""
    db["designs"] = [
        {"design_id": "cd_grade-pp1_chri", "grade": "grade-pp1", "subject": "CRE"},
    ]

    outcome = data_repairs.run_repairs(only="003_drop_documentless_designs")

    assert outcome["rows_affected"] == 1
    assert db["deleted"][0]["id"] == "cd_grade-pp1_chri"


def test_one_failing_repair_does_not_stop_the_others(db, monkeypatch) -> None:
    def boom(dry_run):
        raise RuntimeError("table missing")

    monkeypatch.setattr(data_repairs, "REPAIRS",
                        [("001_boom", boom),
                         ("002_denumber_strand_names", data_repairs._denumber_names)])
    db["substrands"] = [
        {"id": 5, "grade": "grade-pp1", "subject": "CRE",
         "strand_name": "4.0 Christian Values", "sub_strand_name": "4.1 Love for God"},
    ]

    outcome = data_repairs.run_repairs()

    assert outcome["status"] == "partial"
    assert outcome["repairs"][0]["error"]
    assert outcome["repairs"][1]["rows_affected"] == 1


def test_the_sweeps_run_at_startup_like_migrations() -> None:
    """Both were things a person had to remember, and forgetting either was
    silent: prompts served their variables stripped, debris rows stayed."""
    main = open("app/main.py").read()
    startup = main[main.index("def startup("):]
    startup = startup[: startup.index("\n@app.")]

    assert "sync_prompts()" in startup
    assert "run_repairs()" in startup
    assert startup.index("run_migrations()") < startup.index("run_repairs()"), (
        "a repair that runs before its migration has no table to repair"
    )
