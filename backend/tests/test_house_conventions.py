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

    assert "shillings" in block
    assert "Metric" in block
    assert "Brackets" in block


@pytest.mark.parametrize("subject", [
    "Christian Religious Education", "Integrated Science", "Physics",
    "Chemistry", "Agriculture", "Kiswahili", "Business Studies", "Home Science",
])
def test_the_order_of_operations_goes_to_mathematics_only(subject: str) -> None:
    """Told how BODMAS governs the working, a Grade 9 Integrated Science paper
    set three BODMAS drills and called one an "atomic stability quotient"."""
    assert "BODMAS" not in notation.for_prompt(subject, grade="grade-9"), subject


def test_mathematics_is_told_bodmas_and_never_pemdas() -> None:
    """"Use BODMAS" leaves PEMDAS available. "Never PEMDAS" does not."""
    block = notation.for_prompt("Mathematics", grade="grade-9")

    assert "BODMAS" in block
    assert "Never PEMDAS" in block


def test_it_names_the_thing_to_avoid_not_only_the_thing_to_do() -> None:
    block = notation.house_block()

    assert 'never "$250"' in block
    assert 'never "parentheses"' in block


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

    assert "shillings" in cre
    assert "frac" not in cre.lower(), "and none of the LaTeX it will never use"


def test_the_block_stays_short() -> None:
    """It goes to every subject, and every irrelevant instruction makes the
    relevant ones harder to find."""
    assert len(notation.house_block()) < 1200


def test_computer_science_is_not_given_chemistry() -> None:
    """"Science" in the name matched the sciences, and Computer Science was
    sent the page on balancing equations."""
    assert notation.CHEMISTRY_BLOCK not in notation.for_prompt("Computer Science")
    assert notation.CHEMISTRY_BLOCK in notation.for_prompt("Integrated Science")


def test_physical_education_is_not_given_physics() -> None:
    """`physic` matched "Physical", so PE was sent the solar system and the
    science-calculation rules."""
    from app.services import prompt_fragments as pf

    pe = {f.name for f in pf.for_context("Physical Education", "notes", "grade-9")}
    assert "physical-education" in pe
    assert not pe & {"astronomy-solar-system", "science-calculation-demand"}
    assert notation.PHYSICS_BLOCK not in notation.for_prompt("Physical Education")
    assert notation.PHYSICS_BLOCK in notation.for_prompt("Physics")


def test_physical_science_is_not_given_physical_education() -> None:
    from app.services import prompt_fragments as pf

    names = {f.name for f in pf.for_context("Physical Science", "notes", "grade-10")}
    assert "physical-education" not in names


@pytest.mark.parametrize("subject", ["Integrated Science", "Social Studies", "CRE", "English"])
def test_the_integer_working_rules_reach_mathematics_only(subject: str) -> None:
    """The lesson-material prompt carried the sign-substitution rules and the
    Grade 9 integer fraction to every subject."""
    from app.services import prompt_fragments as pf
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    assert "-15" not in SEED_AGENT_PROMPTS["material-generator"]
    assert "g9-mat" not in SEED_AGENT_PROMPTS["material-generator"]
    assert "-15" not in pf.compose(subject, "material", "grade-9")
    assert "SIGNED VALUE" in pf.compose("Mathematics", "material", "grade-9")


def test_the_figure_share_names_this_subjects_own_figures() -> None:
    from app.services import figure_sketch

    share = lambda s: figure_sketch.prompt_block(s).split("HOW MANY", 1)[1]
    assert "number line" in share("Mathematics")
    assert "population pyramid" in share("Social Studies") and "number line" not in share("Social Studies")
    assert "results table" in share("Integrated Science") and "number line" not in share("Integrated Science")
    assert "HOW MANY" not in figure_sketch.prompt_block("English")
