"""The shared prompts must not smuggle in a subject, a level, or a fact.

A model follows a concrete example over an abstract instruction. These prompts
carried worked examples about Kenyan agriculture, a hardcoded "4 hours", and a
values list that was not the Kenyan one — so every learning area at every level
inherited them.
"""
from __future__ import annotations

import pytest

from app.services.langfuse_context import context_safe_package, focus_subject_context
from app.services.langfuse_seed import SEED_AGENT_PROMPTS, SEED_MASTER_CONTEXT

# The eight the Constitution and the KICD designs actually use.
KENYAN_VALUES = ("Love", "Responsibility", "Respect", "Unity",
                 "Peace", "Patriotism", "Social Justice", "Integrity")
# The set that was in the master context: Values for Australian Schooling.
NOT_KENYAN_VALUES = ("Care and Compassion", "Understanding and Tolerance",
                     "Honesty and Trustworthiness", "Being Ethical")


def test_the_master_context_states_the_kenyan_core_values() -> None:
    for value in KENYAN_VALUES:
        assert value in SEED_MASTER_CONTEXT, f"{value} missing from the master context"
    for wrong in NOT_KENYAN_VALUES:
        assert wrong not in SEED_MASTER_CONTEXT, (
            f"'{wrong}' is from the Australian values list, not the Kenyan one. "
            "It was contradicting the correct list in the same prompt."
        )


@pytest.mark.parametrize("agent", sorted(SEED_AGENT_PROMPTS))
def test_no_prompt_hardcodes_an_agriculture_example(agent: str) -> None:
    """These set the register for Kiswahili, Music and pre-primary phonics too."""
    text = SEED_AGENT_PROMPTS[agent]
    banned = [
        "Kenyan agriculture/industry",
        "farm plots",
        "using local apparatus",
        "Agricultural Economic Sectors",
        "agro-ecological zones, cultural",
        "county agricultural/environmental scenario",
        "CAADP",
    ]
    found = [b for b in banned if b in text]
    assert not found, f"{agent} still hardcodes: {found}"


@pytest.mark.parametrize(
    "agent",
    [a for a in sorted(SEED_AGENT_PROMPTS) if a != "curriculum-extractor"],
)
def test_every_authoring_and_review_prompt_receives_the_level_register(agent: str) -> None:
    """The extractor runs before the grade is known; everything else knows it."""
    assert "{{ level_register }}" in SEED_AGENT_PROMPTS[agent], (
        f"{agent} does not know who it is writing for, so the prompt's own "
        "examples decide the level."
    )


def test_no_prompt_supplies_a_default_time_allocation() -> None:
    """'4 hours' as a worked example produced '4 hours' for every sub-strand."""
    for agent, text in SEED_AGENT_PROMPTS.items():
        for line in text.splitlines():
            if '"allocated_hours"' in line or '"allocated_time"' in line:
                assert "design's own" in line or "{{" in line, (
                    f"{agent} anchors a time allocation: {line.strip()}"
                )


def test_the_substrand_prompt_is_extraction_not_invention() -> None:
    text = SEED_AGENT_PROMPTS["substrand-generator"]

    assert "EXTRACTION, not design" in text
    assert "verbatim" in text
    # The affective SLO was being dropped from every sub-strand.
    assert "appreciate" in text and "attitude" in text
    # Diagrams, experiments and safety must be conditional, not mandatory.
    assert "CONDITIONAL, not mandatory" in text
    assert "An empty list is a" in text
    # A theme is a third axis, not a strand and not a sub-strand.
    assert '"theme"' in text
    assert "THEME x STRAND" in text
    # Every item must be traceable to the page it came from.
    assert '"source_pages"' in text


def test_the_substrand_prompt_refuses_a_strand_that_is_not_in_the_document() -> None:
    """It was asked to break down '1.0 LANGUAGE ACTIVITIES', which is a learning
    area, and invented a decomposition rather than saying so."""
    text = SEED_AGENT_PROMPTS["substrand-generator"]
    assert '"not_found": true' in text
    assert "strands_actually_present" in text


def test_the_strand_prompt_actually_receives_the_document() -> None:
    """It never had {{ source_material_text }}, so the un-chunked path generated
    strands from the model's own knowledge while reporting grounded: true."""
    assert "{{ source_material_text }}" in SEED_AGENT_PROMPTS["strand-generator"]


def test_the_strand_prompt_separates_learning_areas_themes_and_strands() -> None:
    text = SEED_AGENT_PROMPTS["strand-generator"]
    assert "Do NOT report the learning area itself as a strand" in text
    assert "Do NOT report a THEME as a strand" in text
    assert '"themes"' in text


def test_reviewers_do_not_mark_down_correct_age_appropriate_content() -> None:
    """The panel rejected anything not set on a farm, which fails correct
    pre-primary content by design."""
    for agent in ("layer-reviewer", "reviewer-panel", "approver-agent1", "approver-agent2"):
        text = SEED_AGENT_PROMPTS[agent]
        assert "must never be marked down" in text, f"{agent} lacks the guard"


def test_downstream_agent_prompts_are_stripped_from_curriculum_context() -> None:
    stored = {
        "slos": ["identify three qualities of God"],
        "allocated_hours": "4 hours",
        "notes_prompt": "x" * 5000,
        "question_prompt": "y" * 5000,
        "reviewer_prompt": "z" * 5000,
    }
    safe = context_safe_package(stored)

    assert safe["slos"] == ["identify three qualities of God"]
    assert not [k for k in safe if k.endswith("_prompt")]


def test_the_blueprint_is_narrowed_to_the_strand_being_worked_on() -> None:
    ctx = {
        "subject": "Language Activities",
        "strands": [
            {"name": "1.0 CREATION", "sub_strands": []},
            {"name": "4.0 CHRISTIAN VALUES", "sub_strands": []},
            {"name": "Listening and Speaking", "sub_strands": [{"name": "1.1.1 Greetings"}]},
        ],
    }

    focused = focus_subject_context(ctx, "Listening and Speaking")

    assert [s["name"] for s in focused["strands"]] == ["Listening and Speaking"]
    assert focused["focused_on"] == "Listening and Speaking"


def test_a_blueprint_that_matches_nothing_is_emptied_not_substituted() -> None:
    """Sending the wrong strands as a SYSTEM message outranked the real request."""
    ctx = {"strands": [{"name": "1.0 CREATION"}, {"name": "4.0 CHRISTIAN VALUES"}]}

    focused = focus_subject_context(ctx, "Listening and Speaking")

    assert focused["strands"] == []
    assert "Read the curriculum design document instead" in focused["note"]
    assert "do not substitute another strand" in focused["note"]
