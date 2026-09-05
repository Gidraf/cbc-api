"""Not paying twice for work a crash interrupted.

The material station makes one model call per directive, and a sub-strand runs
to twenty or more. Nothing was written down until the last one landed: the loop
filled a list in memory and filed a version after it. A run that died on piece
19 of 21 threw away nineteen paid-for calls, and the queue's own retry started
again from piece one.
"""
from __future__ import annotations

import inspect

import pytest

from app.services import material_draft


def _piece(lesson: int, index: int, said: str = "words here") -> dict:
    return {"module_number": lesson, "index": index, "say": said,
            "topic": f"Part {index}"}


# ── what counts as already done ─────────────────────────────────────────────

def test_pieces_with_words_are_not_generated_again() -> None:
    done = material_draft.done_indexes([_piece(1, 1), _piece(1, 2), _piece(2, 1)])

    assert done == {(1, 1), (1, 2), (2, 1)}


def test_a_piece_that_came_back_empty_is_tried_again() -> None:
    """It cost a call and produced nothing. Resuming past it would ship the gap
    it left as though it were finished work."""
    done = material_draft.done_indexes([
        _piece(1, 1),
        {"module_number": 1, "index": 2, "say": ""},
        {"module_number": 1, "index": 3, "say": "   "},
        {"module_number": 1, "index": 4, "error": "timeout"},
    ])

    assert done == {(1, 1)}


# ── the key ─────────────────────────────────────────────────────────────────

def test_a_draft_belongs_to_one_plan_version() -> None:
    """Material written from version 2 of a plan is not a resumable half of
    material for version 3 — the directives themselves have changed, and
    resuming across that splices two different lessons together."""
    v2 = material_draft.key_for("grade-9", "Mathematics", "Integers", "art_plan_v2")
    v3 = material_draft.key_for("grade-9", "Mathematics", "Integers", "art_plan_v3")

    assert v2 != v3


def test_the_same_run_resolves_to_the_same_draft() -> None:
    args = ("grade-9", "Mathematics", "Integers", "art_plan_v2")
    assert material_draft.key_for(*args) == material_draft.key_for(*args)
    # Spelling of the grade must not split one run into two drafts.
    assert (material_draft.key_for("Grade-9", "Mathematics", "Integers", "art_plan_v2")
            == material_draft.key_for("grade-9", "mathematics", "integers", "art_plan_v2"))


# ── a draft is an optimisation, never a failure ─────────────────────────────

def test_a_store_that_is_down_does_not_fail_the_generation(monkeypatch) -> None:
    """Losing a draft costs money. Failing the run over one costs the run."""
    import app.infra.db as db

    def boom(*a, **k):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(db, "fetch_one", boom)
    monkeypatch.setattr(db, "execute", boom)
    monkeypatch.setattr(db, "fetch_all", boom)

    assert material_draft.load("draft_x") == []
    assert material_draft.pending() == []
    material_draft.save("draft_x", [_piece(1, 1)])      # must not raise
    material_draft.clear("draft_x")                     # must not raise


# ── the station uses it ─────────────────────────────────────────────────────

def test_the_station_saves_after_every_piece_not_at_the_end() -> None:
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_material)
    loop = source.split("for i, directive in enumerate(plan.directives")[1]
    before_content = loop.split("content = {")[0]

    assert "material_draft.save(" in before_content, \
        "the draft must be written inside the loop, not after it"


def test_the_station_resumes_from_what_was_kept() -> None:
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_material)

    assert "material_draft.load(draft_key)" in source
    assert "done_indexes" in source
    assert "continue" in source, "an already-written directive is skipped"


def test_the_draft_is_deleted_once_a_version_is_filed() -> None:
    """A draft that outlives its version would be resumed into the next run."""
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_material)
    assert "material_draft.clear(draft_key)" in source


def test_a_resumed_run_files_the_pieces_in_the_plans_order() -> None:
    """A resumed run appends after what it recovered, so the pieces are no
    longer in the order the plan describes."""
    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_material)
    assert "written.sort(" in source
    assert "order.get(" in source


def test_an_interrupted_run_can_be_seen(monkeypatch) -> None:
    from app.routes import curriculum

    monkeypatch.setattr(material_draft, "pending", lambda **k: [{
        "draft_key": "draft_x", "grade": "grade-9", "subject": "Mathematics",
        "strand": "Numbers", "sub_strand": "Integers",
        "plan_artifact_id": "art_plan", "plan_version": 2,
        "model": "gpt-4o-mini", "llm_calls": 19, "updated_at": "now",
        "pieces_written": 19,
    }])

    out = curriculum.factory_material_drafts(grade="grade-9", subject="", _=None)

    assert out["count"] == 1
    assert out["drafts"][0]["pieces_written"] == 19
    assert out["drafts"][0]["sub_strand"] == "Integers"
    assert "carries on from what is here" in out["note"]


def test_the_table_exists() -> None:
    from app.infra.db import MIGRATIONS

    names = [name for name, _sql in MIGRATIONS]
    assert "028_material_drafts" in names

    sql = dict(MIGRATIONS)["028_material_drafts"]
    assert "material_drafts" in sql and "pieces JSONB" in sql
