"""The exam studio sets a question once.

Adding from the bank sent `[...the list on screen, qid]`, and the server kept
whatever it was sent — the same id twice, or the same question filed in the
bank under two ids, both printed.
"""
from __future__ import annotations

import pytest

from app.services import exam_drafts

BANK = {
    "q1": "Explain why copper conducts electricity.",
    "q2": "State two properties of metals.",
    "q2-copy": "State two properties of metals.",
    "q3": "Describe how to separate salt from sand.",
}


@pytest.fixture()
def draft(monkeypatch):
    row = {"draft_id": "d1", "status": "draft", "snapshot": {},
           "items": [{"question_id": "q1", "overrides": {}},
                     {"question_id": "q2", "overrides": {"max_marks": 3}}]}
    saved: dict = {}

    def update(draft_id, patch, owner=""):
        saved.update(patch)
        return {**row, **patch}

    from app.services import question_dna

    monkeypatch.setattr(exam_drafts, "get", lambda draft_id, owner="": row)
    monkeypatch.setattr(exam_drafts, "update", update)
    monkeypatch.setattr(
        question_dna.question_dna_service, "get_question",
        lambda qid: {"question_id": qid, "question_text": BANK[qid],
                     "curriculum_link": {}, "pedagogical_dna": {}})
    return saved


def _ids(saved: dict) -> list[str]:
    return [i["question_id"] for i in saved["items"]]


def test_the_same_id_twice_is_set_once(draft) -> None:
    out = exam_drafts.reorder("d1", ["q1", "q2", "q3", "q3", "q1"])

    assert _ids(draft) == ["q1", "q2", "q3"]
    assert sorted(out["skipped_duplicates"]) == ["q1", "q3"]


def test_the_same_question_under_another_id_is_refused(draft) -> None:
    out = exam_drafts.reorder("d1", ["q1", "q2", "q2-copy"])

    assert _ids(draft) == ["q1", "q2"]
    assert out["skipped_duplicates"] == ["q2-copy"]


def test_the_item_already_placed_wins_even_when_the_copy_is_listed_first(draft) -> None:
    """What is refused is the one being added, never the one the builder
    placed and may already have corrected."""
    exam_drafts.reorder("d1", ["q2-copy", "q1", "q2"])

    assert _ids(draft) == ["q1", "q2"]
    assert draft["items"][1]["overrides"] == {"max_marks": 3}


def test_a_new_question_is_added(draft) -> None:
    out = exam_drafts.reorder("d1", ["q1", "q2", "q3"])

    assert _ids(draft) == ["q1", "q2", "q3"]
    assert out["skipped_duplicates"] == []


def test_reordering_alone_does_not_read_the_bank(draft, monkeypatch) -> None:
    from app.services import question_dna

    def boom(qid):
        raise AssertionError("moving an item must not load the paper")

    monkeypatch.setattr(question_dna.question_dna_service, "get_question", boom)
    exam_drafts.reorder("d1", ["q2", "q1"])

    assert _ids(draft) == ["q2", "q1"]


def test_the_figure_floor_does_not_swap_in_a_copy() -> None:
    from types import SimpleNamespace

    on = {"question_id": "a", "question_type": "short_answer", "question_text": "Name a metal."}
    copy = {"question_id": "b", "question_type": "short_answer", "question_text": "Name a metal.",
            "diagram": {"x": 1}}
    other = {"question_id": "c", "question_type": "short_answer",
             "question_text": "Label the parts of the circuit.", "diagram": {"x": 1}}
    plain = {"question_id": "d", "question_type": "short_answer", "question_text": "Define an element."}
    section = SimpleNamespace(items=[on, plain])
    paper = SimpleNamespace(items=[on, plain], sections=[section])

    exam_drafts._raise_figure_floor(paper, [copy, other], floor=2)

    ids = [q["question_id"] for q in section.items]
    assert "b" not in ids
    assert "c" in ids
