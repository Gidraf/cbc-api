"""What an auto-run card says, and what it does not claim.

A Simulations card showing a count of "—" and the words "✋ you run this" was
read as "you have run this", on a grade where nothing had been run at all. The
card was correct: `on` is the auto-run POLICY — whether the stage is included
in the unattended run — and has nothing to do with what has happened.

Two labels on one small card, one about policy and one about history, and only
the second was worded as such.
"""
from __future__ import annotations

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend-web"
PANEL = " ".join((FRONTEND / "src/views/AutoRunPanel.tsx").read_text().split())


def test_the_badge_says_whether_it_is_automatic_not_whether_it_ran() -> None:
    assert '"▶ in the auto run" : "✋ not in the auto run"' in PANEL
    # The wording that read as a status is gone.
    assert "you run this" not in PANEL


def test_the_tooltip_says_what_the_click_will_do() -> None:
    """A toggle whose label describes a state and not the consequence of
    pressing it is a toggle people press to find out."""
    assert "Included in the unattended run. Click to leave it out" in PANEL
    assert "Left out of the unattended run; nothing here starts it" in PANEL


def test_the_counts_are_the_only_thing_reporting_history() -> None:
    assert "built so far" in PANEL
    assert "Nothing built here yet" in PANEL


def test_a_held_back_stage_stops_the_run_rather_than_being_skipped() -> None:
    """Unchanged, and worth holding: a run that skipped a held-back stage would
    build the stages after it on content nobody made."""
    assert "The run does not skip past a held-back stage — it stops there." in PANEL
