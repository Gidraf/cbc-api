"""What every Kenyan classroom takes for granted, and a model does not.

A Grade 9 Integers guide came back teaching **PEMDAS** — an acronym no Kenyan
learner has been taught and no Kenyan paper will use — and pricing a person's
expenses in **$50** and **$2000** in the same lesson that elsewhere said
"shillings". Neither is a style preference. One teaches the wrong thing; the
other describes somebody else's country.
"""
from __future__ import annotations

import pytest

from app.services import notation


@pytest.mark.parametrize("subject", [
    "Mathematics", "Christian Religious Education", "Integrated Science",
    "Home Science", "Agriculture", "Kiswahili", "Business Studies",
])
def test_every_subject_writes_to_the_same_house_conventions(subject: str) -> None:
    """"Only mathematics needs this" was never true: a History guide prices
    things and a Home Science guide measures them."""
    block = notation.for_prompt(subject)

    assert "BODMAS" in block
    assert "shillings" in block
    assert "Metric" in block


def test_it_names_the_thing_to_avoid_not_only_the_thing_to_do() -> None:
    """"Use BODMAS" leaves PEMDAS available. "Never PEMDAS" does not."""
    block = notation.house_block()

    assert "Never PEMDAS" in block
    assert 'never "$250"' in block
    assert 'never the word\n    "parentheses"' in block or "brackets" in block


def test_the_examples_are_places_a_kenyan_learner_recognises() -> None:
    block = notation.house_block()

    for grounded in ("matatu", "shamba", "Nakuru", "Kisumu"):
        assert grounded in block, grounded
    # And the ones that give an American guide away.
    for foreign in ("dime", "yards", "mall"):
        assert foreign in block, foreign


def test_a_subject_that_needs_no_notation_still_gets_the_conventions() -> None:
    """CRE has no equations to balance and still prices things and spells."""
    cre = notation.for_prompt("Christian Religious Education")

    assert "BODMAS" in cre
    assert "frac" not in cre.lower(), "and none of the LaTeX it will never use"


def test_the_block_stays_short() -> None:
    """It goes to every subject, and every irrelevant instruction makes the
    relevant ones harder to find."""
    assert len(notation.house_block()) < 1200
