"""A reviewer's own words, and what has to be rebuilt because of them.

A model reviewer scores dimensions. A person reads the thing and knows why it
is wrong — "lesson 4 teaches a parable the design does not carry" — and that
had nowhere to go but a conversation. A systematic fault had to be described to
whoever runs the console rather than to the pipeline.

The half that matters is the second one: a lesson plan that was wrong did not
only produce a wrong plan. It produced the material said aloud from it, the
diagrams drawn against it, the activities, the experiments, and the questions
written from all of those.
"""
from __future__ import annotations

import inspect

import pytest

from app.services import review_feedback as rf


class _Artifact:
    def __init__(self, kind="notes", artifact_id="art_notes_1"):
        self.kind = kind
        self.artifact_id = artifact_id
        self.grade = "grade-9"
        self.subject = "Mathematics"
        self.sub_strand_name = "Integers"
        self.version = 3
        self.comments = []


@pytest.fixture
def registry(monkeypatch):
    from app.services import artifact_registry

    filed: list[dict] = []
    rows = {
        "material": [{"artifact_id": "art_material_1", "version": 12,
                      "sub_strand_name": "Integers"}],
        "diagram": [{"artifact_id": "art_diagram_1", "version": 9,
                     "sub_strand_name": "Integers"}],
        "question": [{"artifact_id": "art_question_1", "version": 2,
                      "sub_strand_name": "Integers"}],
    }
    monkeypatch.setattr(artifact_registry, "get", lambda _id: _Artifact())
    monkeypatch.setattr(artifact_registry, "search",
                        lambda **k: rows.get(k.get("kind"), []))
    monkeypatch.setattr(artifact_registry, "add_comment",
                        lambda aid, body, **k: filed.append(
                            {"artifact_id": aid, "body": body, **k}) or
                        {"comment_id": "c1", "body": body})
    return filed


# ── what a comment invalidates ──────────────────────────────────────────────


def test_a_lesson_plan_invalidates_everything_drawn_from_it() -> None:
    kinds = rf.downstream_kinds("notes")

    for expected in ("material", "diagram", "activity", "experiment",
                     "simulation", "question"):
        assert expected in kinds, expected


def test_the_material_does_not_invalidate_the_diagrams() -> None:
    """They illustrate the plan, not the words said aloud from it. Getting
    this wrong in the generous direction marks a sub-strand's whole output
    stale over a typo."""
    assert rf.downstream_kinds("material") == ("question",)
    assert "diagram" not in rf.downstream_kinds("material")


def test_a_diagram_invalidates_the_questions_written_against_it() -> None:
    assert rf.downstream_kinds("diagram") == ("question",)


def test_a_kind_with_nothing_below_it_invalidates_nothing() -> None:
    assert rf.downstream_kinds("question") == ()
    assert rf.downstream_kinds("nonsense") == ()


# ── filing a note ───────────────────────────────────────────────────────────


def test_a_note_marks_what_was_built_from_the_plan(registry) -> None:
    feedback = rf.submit("art_notes_1",
                         "Lesson 4 teaches a parable the design does not carry.",
                         action=rf.REWRITE, author="gidraf")

    kinds = sorted({s.kind for s in feedback.stale})
    assert kinds == ["diagram", "material", "question"]
    assert feedback.action == rf.REWRITE
    # And the reviewer's reason is written onto each stale version, where a
    # person opening it will read it.
    marked = [f for f in registry if f.get("dimension") == "stale"]
    assert len(marked) == 3
    assert "sent back by a reviewer" in marked[0]["body"]


def test_the_note_itself_is_filed_against_the_version_reviewed(registry) -> None:
    rf.submit("art_notes_1", "The worked example uses litres, not millilitres.",
              action=rf.REWRITE, author="gidraf")

    own = [f for f in registry if f["artifact_id"] == "art_notes_1"]
    assert len(own) == 1
    assert own[0]["dimension"] == "reviewer:rewrite"
    assert "millilitres" in own[0]["body"]


def test_a_note_only_comment_rebuilds_nothing(registry) -> None:
    """Not every observation is a rejection."""
    feedback = rf.submit("art_notes_1", "Reads well. Worth keeping the analogy.",
                         action=rf.NOTE_ONLY, author="gidraf")

    assert feedback.stale == []
    assert "Nothing was marked for rebuilding" in feedback.summary()
    assert not [f for f in registry if f.get("dimension") == "stale"]


def test_an_empty_note_is_refused(registry) -> None:
    from app.errors import ApiError

    with pytest.raises(ApiError) as caught:
        rf.submit("art_notes_1", "   ", action=rf.REWRITE)
    assert "What is wrong with it" in str(caught.value)


def test_an_unknown_action_is_refused(registry) -> None:
    from app.errors import ApiError

    with pytest.raises(ApiError):
        rf.submit("art_notes_1", "Wrong.", action="delete_everything")


def test_nothing_is_deleted(registry) -> None:
    """The old version may be in a classroom already. Throwing it away because
    its parent changed takes content out of circulation on a guess."""
    source = inspect.getsource(rf)

    assert "delete" not in source.lower().replace("deleted", "").replace(
        "deletes", ""), "staleness is recorded, never enforced by deletion"
    assert "marked, not deleted" in inspect.getsource(rf.Feedback.summary)


def test_the_summary_says_what_a_person_now_has_to_do(registry) -> None:
    feedback = rf.submit("art_notes_1", "Wrong units throughout.",
                         action=rf.REWRITE, author="gidraf")

    says = feedback.summary()
    assert "3 version(s) built from it are now stale" in says
    assert "1 diagram, 1 material, 1 question" in says


def test_a_registry_that_fails_does_not_lose_the_note(monkeypatch) -> None:
    """Filing the reviewer's words is the point; marking the children is not
    worth losing them over."""
    from app.services import artifact_registry

    monkeypatch.setattr(artifact_registry, "get", lambda _id: _Artifact())
    monkeypatch.setattr(artifact_registry, "add_comment",
                        lambda aid, body, **k: {"comment_id": "c1"}
                        if aid == "art_notes_1" else (_ for _ in ()).throw(
                            RuntimeError("db down")))

    def _boom(**k):
        raise RuntimeError("db down")

    monkeypatch.setattr(artifact_registry, "search", _boom)

    feedback = rf.submit("art_notes_1", "Wrong.", action=rf.REWRITE)
    assert feedback.comment
    assert feedback.stale == []


# ── feeding it back into the next generation ────────────────────────────────


def test_the_notes_a_regeneration_must_answer_are_readable(monkeypatch) -> None:
    from app.services import artifact_registry

    artifact = _Artifact()
    artifact.comments = [
        {"dimension": "reviewer:rewrite", "body": "Wrong units."},
        {"dimension": "stale", "body": "Marked stale."},
        {"dimension": "accuracy", "body": "A model's score, not a person's."},
        {"dimension": "reviewer", "body": "Also fix lesson 4."},
    ]
    monkeypatch.setattr(artifact_registry, "get", lambda _id: artifact)

    assert rf.directives_for("art_notes_1") == ["Wrong units.", "Also fix lesson 4."]


def test_the_instruction_says_they_are_not_suggestions() -> None:
    instruction = rf.as_instruction(["Wrong units.", "Lesson 4 is off-design."])

    assert "WHAT A REVIEWER SENT THIS BACK FOR" in instruction
    assert "will be rejected again" in instruction
    assert "1. Wrong units." in instruction
    assert "Keep everything the reviewer did not object to" in instruction


def test_no_notes_is_an_empty_instruction_not_an_empty_heading() -> None:
    assert rf.as_instruction([]) == ""


def test_the_route_files_and_reports_without_regenerating() -> None:
    from app.routes import artifacts

    source = inspect.getsource(artifacts.add_reviewer_note)

    assert "review_feedback.submit(" in source
    assert "regenerate" not in source.split('"""')[2], \
        "the route reports the consequence; it does not act on it"


def test_the_console_offers_the_note_where_a_version_is_reviewed() -> None:
    from pathlib import Path

    frontend = Path(__file__).resolve().parents[2] / "frontend-web"
    review = " ".join((frontend / "src/views/VersionReview.tsx").read_text().split())
    panel = " ".join((frontend / "src/ui/ReviewerNote.tsx").read_text().split())

    assert "ReviewerNote" in review
    # Three actions, because not every observation is a rejection.
    assert "Send it back" in panel and "Just a note" in panel
    assert "marked stale, not deleted" in panel
    # And the notes are shown, because a regeneration has to answer them.
    assert "useReviewerNotes" in panel
