"""Matching the pictures that exist to the places the page keeps for them.

The plan asks for "a number line diagram from -6 to +6 marked at every
integer". The diagram station filed "Number line showing integers from -6 to
6". Same picture, not one identical string — and the renderer's `assets` map
was keyed on an exact lowercased description, so it would never have matched
even if anybody had passed one. Nobody did.
"""
from __future__ import annotations

import pytest

from app.services.asset_requirements import Requirement
from app.services.lesson_assets import _score, match


def _req(what: str, kind: str = "diagram") -> Requirement:
    return Requirement(kind=kind, what=what, module_number=1, module_title="L")


@pytest.mark.parametrize("wanted, filed", [
    ("a number line diagram from -6 to +6 marked at every integer",
     "Number line showing integers from -6 to 6"),
    ("a labelled diagram of the human digestive system",
     "Diagram: the human digestive system, labelled"),
    ("a short video clip showing temperature falling below zero",
     "Temperature falling below zero in Nairobi"),
])
def test_a_rewording_of_the_same_picture_matches(wanted: str, filed: str) -> None:
    assert _score(wanted, filed) >= 0.6


@pytest.mark.parametrize("wanted, filed", [
    ("a labelled diagram of the human digestive system", "The respiratory system"),
    ("a number line diagram from -6 to +6", "Photograph of a Nairobi market"),
    ("a diagram of the water cycle", "A bar chart of rainfall in Kisumu"),
])
def test_a_different_picture_does_not_fill_the_slot(wanted: str, filed: str) -> None:
    """Worse than a placeholder: nobody checks a slot that looks filled."""
    assert _score(wanted, filed) < 0.6


def test_a_video_never_fills_a_slot_kept_for_a_diagram() -> None:
    filled = match(
        [_req("the human digestive system", kind="diagram")],
        [{"kind": "video", "title": "The human digestive system", "url": "u"}],
    )
    assert filled == {}


def test_one_asset_fills_at_most_one_slot() -> None:
    """Two near-identical requests must not both show the same picture, which
    would read as though both had been drawn."""
    filled = match(
        [_req("a number line from -6 to +6"), _req("a number line from -10 to +10")],
        [{"kind": "diagram", "title": "Number line from -6 to 6", "url": "u1"}],
    )
    assert len(filled) == 1


def test_the_best_candidate_wins_when_several_are_close() -> None:
    filled = match(
        [_req("a labelled diagram of the human digestive system")],
        [{"kind": "diagram", "title": "The human circulatory system", "url": "u1"},
         {"kind": "diagram", "title": "The human digestive system, labelled", "url": "u2"}],
    )
    assert list(filled.values())[0]["url"] == "u2"


def test_nothing_filed_means_nothing_matched() -> None:
    assert match([_req("anything")], []) == {}
    assert match([], [{"kind": "diagram", "title": "x", "url": "u"}]) == {}
