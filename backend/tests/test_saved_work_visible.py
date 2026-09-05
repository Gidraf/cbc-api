"""Work that was filed, still visible after you navigate away.

A station's panel rendered the RESULT of the run that had just happened, and
that state is cleared whenever the sub-strand changes. So generating the lesson
material and then navigating away emptied the panel — and the work looked lost.

It was filed the whole time: versioned, gated, reviewable, two clicks away
under "Versions". Notes already had a fallback to the filed artifact. No other
station did.
"""
from __future__ import annotations

import pathlib

CONSOLE = (pathlib.Path(__file__).resolve().parents[2]
           / "frontend-web/src/views/ContentFactory.tsx").read_text()


def test_a_station_with_no_live_run_shows_what_is_filed() -> None:
    assert "function SavedStationWork(" in CONSOLE
    assert "lastResult?.station !== station.id" in CONSOLE, \
        "shown exactly when there is no live result for this station"


def test_it_says_the_work_is_saved_and_which_version() -> None:
    """"saved · Lesson material · version 3" is the whole point: the panel has
    to say the work exists, not merely stop being empty."""
    assert 'Badge tone="ok">saved' in CONSOLE
    assert "version {newest.version}" in CONSOLE


def test_it_shows_the_score_the_version_was_filed_with() -> None:
    assert "provenance.gate_score" in CONSOLE
    assert "provenance.gate_passed" in CONSOLE


def test_it_shows_what_the_checks_found() -> None:
    """The findings were already filed onto the artifact; nothing read them
    back."""
    assert "provenance.measured" in CONSOLE
    assert "What the checks found when it was filed" in CONSOLE


def test_it_points_at_where_the_content_is() -> None:
    assert "Versions, review and approval" in CONSOLE


def test_it_covers_every_station_not_just_notes() -> None:
    """The fallback is keyed on the station's own kind."""
    assert "STATION_KIND[station.id]" in CONSOLE


def test_the_search_returns_the_score_so_no_second_fetch_is_needed() -> None:
    import inspect

    from app.services import artifact_registry

    source = inspect.getsource(artifact_registry.search)
    assert "a.provenance" in source


def test_the_gate_score_is_on_the_artifact_to_be_read_back() -> None:
    """`SavedStationWork` reads `provenance.gate_score`; this is what puts it
    there."""
    from app.services.measured_findings import provenance_for

    filed = provenance_for(
        {"quality_gate": {"passed": False, "overall_score": 50,
                          "reviewer": {"feedback": []}, "next_actions": ["fix it"]}},
        {"source": "factory_generate_material"},
    )

    assert filed["gate_score"] == 50
    assert filed["gate_passed"] is False
    assert filed["measured"] == ["fix it"]
    assert filed["source"] == "factory_generate_material"
