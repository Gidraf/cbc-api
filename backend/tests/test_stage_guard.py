"""The guard turns a flat payload into a lineage check and a skill."""
from __future__ import annotations

import pytest

from app.errors import ApiError
from app.services import stage_guard as sg
from app.services.content_lineage import ASSET_PLAN, DIAGRAM, HOUR_NOTE, QUESTION


class Skill:
    subject, grade, persona = "Science", "grade-7", "A science educator"


@pytest.fixture(autouse=True)
def skill_present(monkeypatch):
    """Default: a skill already exists, so tests isolate the lineage rules."""
    monkeypatch.setattr(sg, "ensure_skill", lambda *a, **k: (Skill(), {"status": "existing"}))


NOTES = {"hour_modules": [
    {"hour_index": 1, "hour_title": "Hour 1", "full_lecture_notes": "Cells and their parts"},
    {"hour_index": 2, "hour_title": "Hour 2", "full_lecture_notes": "Cell division"},
]}


def test_notes_generate_when_their_parents_are_present():
    ctx = sg.require_context(
        HOUR_NOTE, grade="grade-7", subject="Science",
        strand="1.0 Living Things", sub_strand="1.1 Cells",
    )
    assert ctx["manifest"]["layers_used"] == ["strand", "substrand", "skill"]


def test_notes_are_refused_without_a_substrand():
    with pytest.raises(ApiError) as exc:
        sg.require_context(HOUR_NOTE, grade="grade-7", subject="Science", strand="1.0 Living Things")
    assert exc.value.code == "MISSING_PARENT_CONTEXT"
    assert exc.value.status_code == 422
    assert "sub-strands" in exc.value.message


def test_planning_assets_is_refused_before_the_notes_exist():
    with pytest.raises(ApiError) as exc:
        sg.require_context(
            ASSET_PLAN, grade="grade-7", subject="Science",
            strand="1.0 Living Things", sub_strand="1.1 Cells",
        )
    assert exc.value.code == "MISSING_PARENT_CONTEXT"
    assert "lesson notes" in exc.value.message


def test_planning_assets_works_once_notes_exist():
    ctx = sg.require_context(
        ASSET_PLAN, grade="grade-7", subject="Science",
        strand="1.0 Living Things", sub_strand="1.1 Cells", notes_content=NOTES,
    )
    assert "Cells and their parts" in ctx["context"]
    assert "Cell division" in ctx["context"]


def test_a_rendered_visual_sees_only_its_own_hour():
    ctx = sg.require_context(
        DIAGRAM, grade="grade-7", subject="Science",
        strand="1.0 Living Things", sub_strand="1.1 Cells",
        notes_content=NOTES, target_hour=1,
    )
    assert "Cells and their parts" in ctx["context"]
    assert "Cell division" not in ctx["context"], "hour 2 is a different lesson"


def test_asking_for_an_hour_that_has_no_notes_is_refused():
    with pytest.raises(ApiError) as exc:
        sg.require_context(
            DIAGRAM, grade="grade-7", subject="Science",
            strand="1.0 Living Things", sub_strand="1.1 Cells",
            notes_content=NOTES, target_hour=4,
        )
    assert "Hour 4 has no lesson notes" in exc.value.message


def test_questions_need_both_notes_and_assets():
    with pytest.raises(ApiError):
        sg.require_context(
            QUESTION, grade="grade-7", subject="Science",
            strand="1.0 Living Things", sub_strand="1.1 Cells", notes_content=NOTES,
        )

    ctx = sg.require_context(
        QUESTION, grade="grade-7", subject="Science",
        strand="1.0 Living Things", sub_strand="1.1 Cells",
        notes_content=NOTES, assets=[{"title": "Plant cell diagram"}],
    )
    assert "Plant cell diagram" in ctx["context"]


# ── The skill layer ─────────────────────────────────────────────────────────

def test_a_missing_skill_is_derived_rather_than_blocking(monkeypatch):
    monkeypatch.setattr(
        sg, "ensure_skill",
        lambda *a, **k: (Skill(), {"status": "derived", "review_note": "not reviewed"}),
    )
    ctx = sg.require_context(
        HOUR_NOTE, grade="grade-7", subject="Science",
        strand="1.0 Living Things", sub_strand="1.1 Cells",
    )
    assert ctx["skill"]["status"] == "derived"
    assert "A science educator" in ctx["context"]


def test_generation_continues_unskilled_when_none_can_be_derived(monkeypatch):
    """An absent skill degrades quality; an absent parent invents facts."""
    monkeypatch.setattr(sg, "ensure_skill", lambda *a, **k: (None, {"status": "unavailable"}))
    ctx = sg.require_context(
        HOUR_NOTE, grade="grade-7", subject="Science",
        strand="1.0 Living Things", sub_strand="1.1 Cells",
    )
    assert ctx["skill"]["status"] == "unavailable"
    assert ctx["manifest"]["layers_missing_optional"] == ["skill"]
