"""The board reporting 0/0 for a sub-strand it had generated everything for.

    NOTES 0/0   VISUALS 0/0   MEDIA 0/0   PRACTICALS 0/0   QUESTIONS 0/0
    Lesson material — Blocked: none exist yet for this sub-strand
    Diagrams        — Blocked: none exist yet for this sub-strand

Two independent faults, either of which alone produces that screen.
"""
from __future__ import annotations

import inspect

import pytest

from app.services.coverage import compute_substrand_coverage
from app.services import substrand_bundle

NODE = {"sub_strand_name": "Integers", "allocated_hours": "6 lessons", "slos": []}

ARTIFACT_ROWS = [
    {"subject": "Mathematics", "sub_strand_name": "Integers", "kind": "notes",
     "content": {"modules": [{"module_number": n} for n in range(1, 7)]}},
    {"subject": "Mathematics", "sub_strand_name": "Integers", "kind": "diagram",
     "content": {"visuals": [{"diagram_title": "Number line"}]}},
    {"subject": "Mathematics", "sub_strand_name": "Integers", "kind": "activity",
     "content": {"activities": [{"activity_name": "Walk it"}]}},
]


@pytest.fixture()
def filed(monkeypatch):
    import app.infra.db as db
    monkeypatch.setattr(db, "fetch_all", lambda q, p=None: ARTIFACT_ROWS)


# ── fault one: coverage read a table nothing writes ─────────────────────────

def test_the_index_is_built_from_the_artifacts(filed) -> None:
    index = substrand_bundle.index_for_grade("grade-9")

    assert ("mathematics", "integers") in index
    bundle = index[("mathematics", "integers")]
    assert len(bundle["notes"]["modules"]) == 6
    assert len(bundle["diagrams"]) == 1
    assert len(bundle["activities"]) == 1


def test_coverage_scores_what_the_stations_filed(filed) -> None:
    bundle = substrand_bundle.index_for_grade("grade-9")[("mathematics", "integers")]
    report = compute_substrand_coverage(
        NODE, {**bundle, "media": [], "approved": {"total": 0, "approved": 0}})

    assert report["dimensions"]["notes"]["generated"] == 6
    assert report["dimensions"]["notes"]["percentage"] == 100
    assert report["dimensions"]["notes"]["planned"] is True
    assert report["dimensions"]["visuals"]["generated"] == 1


def test_the_gate_that_locks_the_next_station_now_opens(filed) -> None:
    """`planned` is what the material and diagram stations read. It was False
    for a sub-strand with six lessons filed."""
    bundle = substrand_bundle.index_for_grade("grade-9")[("mathematics", "integers")]
    report = compute_substrand_coverage(
        NODE, {**bundle, "media": [], "approved": {}})

    assert report["dimensions"]["notes"]["planned"] is True


def test_the_coverage_route_reads_the_artifacts_first() -> None:
    from app.routes import admin_langfuse

    source = inspect.getsource(admin_langfuse)
    assert "substrand_bundle.index_for_grade" in source
    # And the published row still counts, for content filed before the stations.
    assert "not in res_index" in source


def test_an_index_failure_leaves_the_screen_standing(monkeypatch) -> None:
    import app.infra.db as db

    monkeypatch.setattr(db, "fetch_all",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert substrand_bundle.index_for_grade("grade-9") == {}


# ── fault two: the console read key names the API never sends ───────────────

def test_the_console_reads_the_keys_the_service_returns() -> None:
    """`generated_count` and `required_count` do not exist. The console read
    them, so every station showed "0 of 0 produced" whatever the data said —
    and the gates that read the same numbers locked the stations below."""
    import pathlib

    served = set(compute_substrand_coverage(NODE, {})["dimensions"]["notes"])
    assert {"generated", "required"} <= served
    assert "generated_count" not in served
    assert "required_count" not in served

    console = (pathlib.Path(__file__).resolve().parents[2]
               / "frontend-web/src/views/ContentFactory.tsx").read_text()

    # Property ACCESS, not the comment that explains why these are gone.
    import re

    for absent in ("generated_count", "required_count", "remaining_count",
                   "generated_hours", "required_hours"):
        used = re.search(rf"[.\?]\s*{absent}\b|^\s*{absent}\s*:", console, re.M)
        assert not used, f"{absent} is not a key the API sends"

    assert "dim.generated ?? 0" in console
    assert "gate.generated ?? 0" in console
