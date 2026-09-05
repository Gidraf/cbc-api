"""Questions refusing to run for a sub-strand whose content plainly exists.

    SUBSTRAND_BUNDLE_NOT_FOUND: No generated content found for
    Mathematics · Integers in Grade 9. Generate the notes, diagrams and
    activities first.

The notes were written, reviewed, scored 89 and filed. The station looked in
`substrand_resources` — a row written only by the explicit publish-bundle step
and by the older pipeline. Nothing on the Content Factory board writes it, so
the board can never satisfy the check the board's own next station makes.
"""
from __future__ import annotations

import inspect

import pytest

from app.services import substrand_bundle

NOTES = {"modules": [{"module_number": 1, "title": "Lesson 1",
                      "teacher_exposition": "An integer is a whole number."}]}


@pytest.fixture()
def filed(monkeypatch):
    """Notes, diagrams and activities, filed as the stations file them."""
    from app.services import artifact_registry

    def search(**kw):
        kind = kw.get("kind")
        if kind == "notes":
            return [{"artifact_id": "a1", "content": NOTES}]
        if kind == "diagram":
            return [{"artifact_id": "a2",
                     "content": {"visuals": [{"diagram_title": "number line"}]}}]
        if kind == "activity":
            return [{"artifact_id": "a3",
                     "content": {"activities": [{"activity_name": "Walk it"}]}}]
        return []

    monkeypatch.setattr(artifact_registry, "search", search)


def test_the_bundle_is_assembled_from_what_the_stations_filed(filed) -> None:
    bundle = substrand_bundle.load("grade-9", "Mathematics", "Integers")

    assert bundle is not None
    assert bundle["source"] == "artifacts"
    assert bundle["notes"]["modules"]
    assert len(bundle["diagrams"]) == 1
    assert len(bundle["activities"]) == 1


def test_both_keys_a_station_might_use_are_read(monkeypatch) -> None:
    """The planner files `visuals`, a single render files `diagrams`."""
    from app.services import artifact_registry

    for key in ("visuals", "diagrams"):
        monkeypatch.setattr(artifact_registry, "search", lambda **kw: (
            [{"artifact_id": "a1", "content": NOTES}] if kw.get("kind") == "notes"
            else [{"artifact_id": "a2", "content": {key: [{"diagram_title": "x"}]}}]
            if kw.get("kind") == "diagram" else []))

        bundle = substrand_bundle.load("grade-9", "Mathematics", "Integers")
        assert bundle and len(bundle["diagrams"]) == 1, key


def test_notes_are_the_floor(monkeypatch) -> None:
    """A question grounded in diagrams alone is a question about a picture
    rather than about what the lesson teaches."""
    from app.services import artifact_registry
    import app.infra.db as db

    monkeypatch.setattr(artifact_registry, "search", lambda **kw: (
        [{"artifact_id": "a2", "content": {"visuals": [{"diagram_title": "x"}]}}]
        if kw.get("kind") == "diagram" else []))
    monkeypatch.setattr(db, "fetch_one", lambda *a, **k: None)

    assert substrand_bundle.load("grade-9", "Mathematics", "Integers") is None


def test_the_older_published_row_still_works(monkeypatch) -> None:
    """Content filed before the stations existed must keep working."""
    from app.services import artifact_registry
    import app.infra.db as db

    monkeypatch.setattr(artifact_registry, "search", lambda **kw: [])
    monkeypatch.setattr(db, "fetch_one", lambda *a, **k: {
        "notes": NOTES, "diagrams": [{"t": 1}], "activities": {},
        "curriculum": {"grade": "grade-9"}})

    bundle = substrand_bundle.load("grade-9", "Mathematics", "Integers")
    assert bundle and bundle["source"] == "published"


def test_artifacts_win_over_an_older_published_row(filed, monkeypatch) -> None:
    """Artifacts are versioned and newer than any published row for the same
    sub-strand."""
    import app.infra.db as db

    monkeypatch.setattr(db, "fetch_one", lambda *a, **k: {
        "notes": {"modules": []}, "diagrams": [], "activities": {},
        "curriculum": {}})

    assert substrand_bundle.load("grade-9", "Mathematics", "Integers")["source"] == "artifacts"


def test_a_store_that_is_down_refuses_rather_than_crashes(monkeypatch) -> None:
    from app.services import artifact_registry
    import app.infra.db as db

    def boom(*a, **k):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(artifact_registry, "search", boom)
    monkeypatch.setattr(db, "fetch_one", boom)

    assert substrand_bundle.load("grade-9", "Mathematics", "Integers") is None


def test_what_is_missing_names_the_stations() -> None:
    assert substrand_bundle.what_is_missing(None) == ["notes", "diagram", "activity"]
    assert substrand_bundle.what_is_missing(
        {"notes": NOTES, "diagrams": [], "activities": []}) == ["diagram", "activity"]
    assert substrand_bundle.what_is_missing(
        {"notes": NOTES, "diagrams": [1], "activities": [1]}) == []


# ── the station uses it ─────────────────────────────────────────────────────

def test_the_questions_station_reads_the_artifacts() -> None:
    from app.routes import questions

    source = inspect.getsource(questions.factory_generate_questions_batch)

    assert "substrand_bundle.load" in source
    assert "SELECT * FROM substrand_resources" not in source, \
        "the legacy table is a fallback inside the loader, not the only source"


def test_the_refusal_now_carries_a_route() -> None:
    """It named three stations in prose and offered no way to run any of them."""
    from app.routes import questions

    source = inspect.getsource(questions.factory_generate_questions_batch)
    assert "missing_upstream" in source


def test_the_grade_comparison_is_normalised_on_both_sides() -> None:
    """`grade IN (:grade, :alt_grade)` matched two spellings out of four."""
    from app.routes import questions

    source = inspect.getsource(questions.factory_generate_questions_batch)
    assert "grade_clause(" in source
    assert "alt_grade" not in source
