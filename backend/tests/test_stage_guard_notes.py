"""Diagrams refusing to run for a sub-strand whose lesson plan exists.

    Diagrams failed after 2 attempts: MISSING_PARENT_CONTEXT: Cannot generate
    asset_plan: notes is missing. Generate the lesson notes for this
    sub-strand first. — Run the 7 stages this needs

Two faults in one sentence. The plan was written, reviewed, scored and filed —
the guard only ever read the request body, and the board queues a sub-strand,
not a payload. And "7 stages" was the whole pipeline, because `asset_plan` is
not a name the board uses.
"""
from __future__ import annotations

import pytest

from app.services import stage_guard
from app.services.remedies import missing_upstream

NOTES = {"modules": [
    {"hour_index": 1, "hour_title": "Lesson 1", "teacher_exposition": "An integer."},
    {"hour_index": 2, "hour_title": "Lesson 2", "teacher_exposition": "PEMDAS."},
]}


@pytest.fixture()
def filed(monkeypatch):
    """A lesson plan filed for this sub-strand, as the board would have it."""
    class Artifact:
        content = NOTES

    from app.services import artifact_registry

    monkeypatch.setattr(artifact_registry, "search",
                        lambda *a, **k: [{"artifact_id": "art_notes_x"}])
    monkeypatch.setattr(artifact_registry, "get", lambda _id: Artifact())
    return Artifact


@pytest.fixture()
def nothing_filed(monkeypatch):
    from app.services import artifact_registry

    monkeypatch.setattr(artifact_registry, "search", lambda *a, **k: [])


# ── the guard finds what is filed ───────────────────────────────────────────

def test_a_stage_queued_from_the_board_finds_the_filed_plan(filed) -> None:
    """The board sends no `notes_content`. That is not the same as having none."""
    context = stage_guard.require_context(
        "asset_plan", grade="grade-9", subject="Mathematics",
        strand="Numbers", sub_strand="Integers",
        notes_content=None, derive_skill=False,
    )

    assert context is not None


def test_it_still_refuses_when_nothing_is_filed(nothing_filed) -> None:
    """The guard exists to stop a station inventing what it was not given."""
    from app.errors import ApiError

    with pytest.raises(ApiError) as raised:
        stage_guard.require_context(
            "asset_plan", grade="grade-9", subject="Mathematics",
            strand="Numbers", sub_strand="Nothing",
            notes_content=None, derive_skill=False,
        )

    assert raised.value.code == "MISSING_PARENT_CONTEXT"
    assert "notes is missing" in str(raised.value)


def test_a_payload_still_wins_over_what_is_filed(filed) -> None:
    """A caller passing notes is regenerating from those, not from the last
    version somebody happened to file."""
    passed = {"modules": [{"hour_index": 1, "hour_title": "Only one",
                           "teacher_exposition": "x"}]}

    assert len(stage_guard._hours_from(passed)) == 1


def test_a_lookup_failure_does_not_crash_the_stage(monkeypatch) -> None:
    from app.services import artifact_registry

    def boom(*a, **k):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(artifact_registry, "search", boom)
    assert stage_guard._filed_notes("grade-9", "Mathematics", "Integers") is None


# ── and the route it offers is the one that helps ───────────────────────────

def test_the_diagram_planner_is_told_to_run_the_lesson_plan() -> None:
    """It said "Run the 7 stages this needs" — the entire pipeline — because
    `asset_plan` is not a name on the board and the lookup fell through."""
    remedy = missing_upstream("grade-9", "Mathematics", "asset_plan",
                              have={"ingest", "strands", "substrands"})

    assert [s["stage"] for s in remedy.steps] == ["notes"]
    assert "7 stages" not in remedy.label


def test_material_is_not_a_prerequisite_for_a_diagram() -> None:
    """It sits earlier on the board, and the diagram planner does not use it.
    Sending an operator to run it wastes a generation."""
    remedy = missing_upstream("grade-9", "Mathematics", "asset_plan", have=set())
    stages = [s["stage"] for s in remedy.steps]

    assert "material" not in stages
    assert stages == ["strands", "substrands", "notes"]


def test_nothing_missing_reads_as_a_sentence() -> None:
    """"Run the 0 stages this needs" reads as a bug, and was one."""
    remedy = missing_upstream(
        "grade-9", "Mathematics", "activity",
        have={"ingest", "strands", "substrands", "notes", "material",
              "diagram", "media", "simulation"})

    assert "0 stages" not in remedy.label
    assert remedy.steps == []


def test_a_stage_the_board_does_not_know_offers_no_route() -> None:
    """Naming nothing beats naming the whole pipeline."""
    remedy = missing_upstream("grade-9", "Mathematics", "made_up")

    assert remedy.kind == "open"
    assert remedy.steps == []
    assert "not a stage on the board" in remedy.why


@pytest.mark.parametrize("lineage, board", [
    ("asset_plan", "diagram"),
    ("hour_note", "notes"),
    ("substrand", "substrands"),
    ("question", "questions"),
    ("strand", "strands"),
])
def test_every_lineage_name_maps_onto_the_board(lineage: str, board: str) -> None:
    """Five of the seven were spelled differently, and each one that is not
    mapped falls through to "everything on the board"."""
    from app.services.remedies import CHAIN, LINEAGE_STAGE

    assert LINEAGE_STAGE[lineage] == board
    assert board in CHAIN
