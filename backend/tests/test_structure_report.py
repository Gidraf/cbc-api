"""Turn "how accurate is this?" into a number and a next step.

The same fifteen entries were pasted three times, and the only way to judge them
was to read the KICD PDF and count by hand. A learning area holding another's
strands looks exactly like a correct one in a list.
"""
from __future__ import annotations

import pytest

from app.services import structure_report as sr

# Exactly what the console showed: six Language THEMES, all six Hindu RE
# strands, and three of Islamic RE's six — every one filed under the LEVEL.
OBSERVED = [
    "1.0 GREETINGS AND FAREWELL", "2.0 MYSELF", "3.0 MY FAMILY",
    "4.0 MY HOME", "5.0 MY NEIGHBOURHOOD", "6.0 MY SCHOOL",
    "1.0 Creation", "2.0 Manifestations of Paramatma", "3.0 Scriptures",
    "4.0 Worship", "5.0 Sadachaar", "6.0 Yoga",
    "4.0 Akhlaq (Moral Teachings)", "5.0 Siirah", "6.0 Islamic Festivals",
]


def _rows(pairs):
    return [{"subject": s, "strand_name": n, "sub_strand_count": c} for s, n, c in pairs]


@pytest.fixture
def db(monkeypatch):
    def install(rows):
        monkeypatch.setattr(sr, "fetch_all", lambda *a, **k: rows, raising=False)
        import app.infra.db as db_mod
        monkeypatch.setattr(db_mod, "fetch_all", lambda *a, **k: rows, raising=True)
    return install


def test_it_diagnoses_the_output_that_was_pasted_three_times(db) -> None:
    db(_rows([("Pre-Primary 1", name, 0) for name in OBSERVED]))

    report = sr.build_report("grade-pp1")

    # Not one of the seven published learning areas was ingested.
    assert report["totals"]["learning_areas_expected"] == 7
    assert report["totals"]["learning_areas_ingested"] == 0
    assert report["totals"]["strands_matched"] == 0
    assert report["totals"]["strand_completeness"] == 0

    # And it names the cause rather than leaving it to be read off a PDF.
    assert report["unpublished_subjects"] == ["Pre-Primary 1"]
    cause = " ".join(report["next_steps"])
    assert "is the LEVEL, not a learning area" in cause
    assert "every area overwrote the last" in cause
    assert "Clear the grade and re-ingest" in cause


def test_a_correct_split_reports_complete(db) -> None:
    from app.services.curriculum_catalogue import PRE_PRIMARY_STRUCTURE

    rows = []
    for subject, spec in PRE_PRIMARY_STRUCTURE.items():
        per = spec["sub_strand_count"] // len(spec["strands"])
        extra = spec["sub_strand_count"] - per * len(spec["strands"])
        for i, strand in enumerate(spec["strands"]):
            rows.append((subject, strand, per + (extra if i == 0 else 0)))
    db(_rows(rows))

    report = sr.build_report("grade-pp1")

    assert report["totals"]["learning_areas_ingested"] == 7
    assert report["totals"]["strand_completeness"] == 100
    assert report["totals"]["sub_strand_completeness"] == 100
    assert report["unpublished_subjects"] == []
    assert report["next_steps"] == []
    assert all(a["status"] == "complete" for a in report["learning_areas"])


def test_strands_saved_but_no_substrands_is_its_own_state(db) -> None:
    """Distinguishing "nothing ran" from "half the pipeline ran"."""
    db(_rows([
        ("Language Activities", "Listening and Speaking", 0),
        ("Language Activities", "Reading", 0),
        ("Language Activities", "Writing", 0),
    ]))

    report = sr.build_report("grade-pp1")
    language = next(a for a in report["learning_areas"] if a["subject"] == "Language Activities")

    assert language["status"] == "strands_only"
    assert language["strands"]["matched"] == 3
    assert language["sub_strands"] == {"expected": 36, "found": 0}
    assert any("generate-substrands" in s and "Language Activities" in s
               for s in report["next_steps"])


def test_a_theme_reported_as_a_strand_shows_up_as_unexpected(db) -> None:
    """The six Language themes are the exact failure this must surface."""
    db(_rows([("Language Activities", t, 1) for t in OBSERVED[:6]]))

    report = sr.build_report("grade-pp1")
    language = next(a for a in report["learning_areas"] if a["subject"] == "Language Activities")

    assert language["strands"]["matched"] == 0
    assert len(language["strands"]["unexpected"]) == 6
    assert set(language["strands"]["missing"]) == {"Listening and Speaking", "Reading", "Writing"}


def test_numbering_drift_does_not_count_as_a_mismatch(db) -> None:
    """"1.0 Creation" and "Creation" are the same strand."""
    db(_rows([
        ("Hindu Religious Education", "Creation", 3),
        ("Hindu Religious Education", "2.0 Manifestations of Paramatma", 2),
    ]))

    report = sr.build_report("grade-pp1")
    hre = next(a for a in report["learning_areas"] if a["subject"] == "Hindu Religious Education")

    assert hre["strands"]["matched"] == 2
    assert "1.0 Creation" not in hre["strands"]["missing"]


def test_an_empty_grade_asks_for_ingest_not_for_generation(db) -> None:
    db([])

    report = sr.build_report("grade-pp1")

    assert report["totals"]["learning_areas_ingested"] == 0
    assert len(report["next_steps"]) == 7
    assert all(s.startswith("Ingest the") for s in report["next_steps"])


def test_grades_without_a_published_structure_are_not_scored_against_nothing(db) -> None:
    """Only Pre-Primary has a hand-checked reference; the rest must not be
    reported as 0% simply because no reference exists."""
    db(_rows([("Integrated Science", "1.0 Mixtures, Elements and Compounds", 4)]))

    report = sr.build_report("grade-7")

    assert report["combined_design"] is False
    assert report["totals"]["strands_expected"] == 0
    assert report["totals"]["strand_completeness"] is None
    assert report["reference"] == {}
