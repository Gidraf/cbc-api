"""One picture, one copy — in the book and in the bucket.

`asset_id` is a hash of the title, so redrawing the SAME figure replaces it.
But regenerating a diagram plan renames what it plans, and each new name filed
a new row beside the last. A sub-strand with one number line in it printed four
plates:

    DIAGRAM 1.1  Visual Representation of Integers
    DIAGRAM 1.2  Representation of Integers on a Number Line
    DIAGRAM 1.3  Visual Representation of Integers on a Number Line
    DIAGRAM 1.4  Basic Operations on Integers

Three of those are the same number line. The fourth is a different picture and
must keep its plate.
"""
from __future__ import annotations

import pytest

from app.services import asset_uploads, lesson_assets

LINES = ["Number Line",
         "Visual Representation of Integers",
         "Representation of Integers on a Number Line",
         "Visual Representation of Integers on a Number Line"]
OTHER = "Basic Operations on Integers"


def test_the_renamings_form_one_chain() -> None:
    """Grouping is transitive because it has to be: "Number Line" and "Visual
    Representation of Integers" share no words at all, and are linked only
    through the name the regeneration between them produced."""
    assert not lesson_assets.same_subject(LINES[0], LINES[1])
    assert lesson_assets.same_subject(LINES[1], LINES[2])
    assert lesson_assets.same_subject(LINES[2], LINES[0])


@pytest.mark.parametrize("title", LINES)
def test_a_different_picture_keeps_its_own_plate(title: str) -> None:
    """Measured, not assumed: these score 0.00 against each other."""
    assert not lesson_assets.same_subject(OTHER, title)


def test_the_book_shows_one_of_each(monkeypatch) -> None:
    rows = [{"kind": "diagram", "title": t, "svg": "<svg/>"}
            for t in LINES + [OTHER]]

    kept = [a["title"] for a in lesson_assets.dedupe(rows)]

    assert kept == [LINES[0], OTHER]


def test_the_first_one_offered_is_the_one_kept() -> None:
    """Callers pass them newest-first, and a person's upload ahead of a
    station's older attempt."""
    rows = [{"kind": "diagram", "title": LINES[2], "svg": "<svg>new</svg>"},
            {"kind": "diagram", "title": LINES[0], "svg": "<svg>old</svg>"}]

    assert lesson_assets.dedupe(rows)[0]["svg"] == "<svg>new</svg>"


def test_photographs_and_video_are_never_collapsed() -> None:
    """Two photographs of the same thing are two photographs, and a video is
    not a duplicate of a drawing."""
    rows = [{"kind": "image", "title": "Market scene"},
            {"kind": "image", "title": "Market scene in Nairobi"},
            {"kind": "video", "title": "Market scene"}]

    assert len(lesson_assets.dedupe(rows)) == 3


def test_filing_a_drawing_deletes_the_earlier_copies(monkeypatch) -> None:
    """"Only one copy, to save space" — the rows AND the stored objects."""
    listed = [{"asset_id": "ast_old1", "kind": "diagram", "title": LINES[1]},
              {"asset_id": "ast_old2", "kind": "diagram", "title": LINES[2]},
              {"asset_id": "ast_other", "kind": "diagram", "title": OTHER},
              {"asset_id": "ast_photo", "kind": "image", "title": LINES[1]}]
    monkeypatch.setattr(asset_uploads, "list_for", lambda *a, **k: listed)
    removed: list[str] = []
    monkeypatch.setattr(asset_uploads, "remove",
                        lambda aid: removed.append(aid) or True)

    gone = asset_uploads.supersede("grade-9", "Mathematics", "Integers",
                                   LINES[3], keep="ast_new")

    assert gone == ["ast_old1", "ast_old2"]
    assert "ast_other" not in removed, "a different picture is left alone"
    assert "ast_photo" not in removed, "a photograph is not a drawing"


def test_the_copy_just_filed_is_never_deleted(monkeypatch) -> None:
    monkeypatch.setattr(asset_uploads, "list_for", lambda *a, **k: [
        {"asset_id": "ast_new", "kind": "diagram", "title": LINES[0]}])
    monkeypatch.setattr(asset_uploads, "remove",
                        lambda aid: pytest.fail(f"deleted {aid}"))

    assert asset_uploads.supersede("g", "s", "ss", LINES[0], keep="ast_new") == []


def test_a_lookup_failure_does_not_fail_the_filing(monkeypatch) -> None:
    """Filing the drawing is the point; tidying up after it is not."""
    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(asset_uploads, "list_for", _boom)

    assert asset_uploads.supersede("g", "s", "ss", "Number Line",
                                   keep="ast_new") == []


def test_a_drawing_the_plan_already_names_differently_is_not_added_twice(
        monkeypatch) -> None:
    """The plan says "Number line"; the station drew "Visual Representation of
    Integers on a Number Line". One picture, one plate."""
    monkeypatch.setattr(lesson_assets, "collect", lambda *a, **k: [
        {"kind": "diagram", "title": LINES[3], "svg": "<svg/>"}])
    plan = {"modules": [{"title": "Lesson 1", "module_number": 1,
                         "visuals": [{"diagram_title": "Number line"}]}]}

    out = lesson_assets.with_drawn(plan, "grade-9", "Mathematics", "Integers")

    assert len(out["modules"][0]["visuals"]) == 1


def test_superseding_follows_the_same_chain_the_book_does(monkeypatch) -> None:
    """Comparing each stored row against the new title one pair at a time left
    behind the renamings linked only through a third — which is most of them.
    "Visual Representation of Integers" shares no words with the name being
    filed, and is still the same number line."""
    listed = [{"asset_id": f"ast_{i}", "kind": "diagram", "title": t}
              for i, t in enumerate(LINES[:3])]
    listed.append({"asset_id": "ast_other", "kind": "diagram", "title": OTHER})
    monkeypatch.setattr(asset_uploads, "list_for", lambda *a, **k: listed)
    removed: list[str] = []
    monkeypatch.setattr(asset_uploads, "remove",
                        lambda aid: removed.append(aid) or True)

    gone = asset_uploads.supersede("grade-9", "Mathematics", "Integers",
                                   LINES[3], keep="ast_new")

    assert sorted(gone) == ["ast_0", "ast_1", "ast_2"]
    assert "ast_other" not in removed
