"""Refuse to author from a record that was never parsed.

Hindu Religious Education PP1 ingested as ONE strand holding ONE sub-strand,
both named "1.0 CREATION", with 54 shredded fragments — "say the first",
"appreciate the", "for", ",", "249:19  ● Library" — scraped from all six
strands, and no lesson count. The design's own summary page says six strands,
sixteen sub-strands, ninety lessons.

The pipeline generated from it and reported "Lesson Coverage: complete, 100%",
because one module was asked for and one arrived. SLO coverage scored 96%,
structural completeness 100%. Every measure agreed. They were all measuring the
wrong thing correctly, which is the failure mode a score cannot catch.
"""
from __future__ import annotations

import pytest

from app.errors import ApiError
from app.services.substrand_integrity import MAX_PLAUSIBLE_SLOS, check, require

_WRECKAGE = [
    "recognize self,", "say the first", "appreciate the self", "mention the names",
    "relate with the", "appreciate their", "name the location", "identify plants and",
    "appreciate", "mention five", "for", ",", "241:48  • Picking litterfrom",
    "249:19  ● Library", "249:34  Enlightened Beings ● Oral questioning",
]

_SOUND = [
    "identify three qualities of God",
    "practice saying short prayers",
    "appreciate God as a loving heavenly father",
]


def test_the_hre_record_is_refused() -> None:
    report = check("grade-pp1", "Hindu Religious Education",
                   "1.0 CREATION", "1.0 CREATION", _WRECKAGE * 4, "")

    assert not report.usable
    found = {p["check"] for p in report.problems}
    assert found == {
        "strand_is_substrand", "too_many_outcomes",
        "shredded_outcomes", "page_debris", "no_lesson_count",
    }


def test_a_sound_record_passes() -> None:
    assert check("grade-pp1", "Christian Religious Education",
                 "Creation", "Our God", _SOUND, "7 lessons").usable


def test_a_sub_strand_named_after_its_strand_is_the_block_the_parser_could_not_read() -> None:
    report = check("grade-pp1", "X", "1.0 CREATION", "1.0 CREATION", _SOUND, "7 lessons")

    assert any(p["check"] == "strand_is_substrand" for p in report.problems)
    assert "whole strand was stored as a single sub-strand" in report.problems[0]["what"]


def test_a_whole_learning_areas_outcomes_on_one_sub_strand_is_refused() -> None:
    """No KICD sub-strand has fifty-four outcomes."""
    report = check("grade-pp1", "X", "Creation", "Our God",
                   [f"identify quality number {i} of God" for i in range(54)], "7 lessons")

    problem = next(p for p in report.problems if p["check"] == "too_many_outcomes")
    assert str(MAX_PLAUSIBLE_SLOS) in problem["what"]


@pytest.mark.parametrize("fragment", [
    "say the first", "appreciate the", "for", ",", "relate with the",
])
def test_a_shredded_column_is_recognised_as_a_fragment(fragment) -> None:
    report = check("grade-pp1", "X", "Creation", "Our God",
                   [fragment, fragment, fragment], "7 lessons")

    assert any(p["check"] == "shredded_outcomes" for p in report.problems)


def test_a_page_address_in_an_outcome_names_the_extractor_as_the_cause() -> None:
    report = check("grade-pp1", "X", "Creation", "Our God",
                   _SOUND + ["241:48  • Picking litterfrom"], "7 lessons")

    problem = next(p for p in report.problems if p["check"] == "page_debris")
    assert "scraping lines rather than reading the table" in problem["what"]


def test_a_missing_lesson_count_is_refused() -> None:
    """Without it the guide has no idea how many lessons to plan, and one module
    for ninety lessons scores as complete."""
    report = check("grade-pp1", "X", "Creation", "Our God", _SOUND, "")

    assert any(p["check"] == "no_lesson_count" for p in report.problems)


def test_the_refusal_says_what_to_do_next() -> None:
    with pytest.raises(ApiError) as caught:
        require("grade-pp1", "Hindu Religious Education",
                "1.0 CREATION", "1.0 CREATION", _WRECKAGE, "")

    message = caught.value.message
    assert caught.value.code == "MISSING_PARENT_CONTEXT"
    assert "ingest-learning-area" in message
    assert "structure-report" in message
    assert "nothing generated from it can be true" in message


def test_notes_stop_before_the_tokens_are_spent() -> None:
    route = open("app/routes/curriculum.py").read()
    notes = route[route.index("def factory_generate_notes"):]
    notes = notes[: notes.index("\n@router.")]

    assert "substrand_integrity.require" in notes
    # Before the model call, not after the gate has scored the wreckage.
    assert notes.index("substrand_integrity.require") < notes.index("llm_client.generate")


# ── Two fabrications the same run exposed ───────────────────────────────────

def test_no_invented_key_inquiry_question() -> None:
    """The fallback asked "How does 1.0 CREATION apply to real-world Kenyan
    national development?" — invented, and forbidden by the PP1 register, which
    says examples come from the child's own world, not national development."""
    route = open("app/routes/curriculum.py").read()

    assert "apply to real-world Kenyan national development" not in route
    assert "do not invent one" in route


def test_hazard_criteria_fit_the_sub_strand() -> None:
    """All five were attached to every sub-strand of every subject, so a
    Pre-Primary lesson on greetings carried rabies and hoe-handling criteria. A
    hazard list that does not apply teaches the reader to skip the field where
    it does."""
    from app.services.curriculum_extractor import _hazard_criteria

    assert _hazard_criteria("sing songs about God and say a short prayer", []) == []

    yoga = _hazard_criteria("practice simple yoga asanas and postures", [])
    assert len(yoga) == 1 and "non-slip" in yoga[0]

    farm = " ".join(_hazard_criteria("prepare the soil with manure using a hoe", []))
    assert "soil/manure" in farm and "hoe" in farm
    assert "rabies" not in farm and "bite" not in farm


def test_a_nature_walk_gets_the_criterion_it_actually_needs() -> None:
    from app.services.curriculum_extractor import _hazard_criteria

    walk = " ".join(_hazard_criteria("take a nature walk in the school neighbourhood", []))

    assert "supervised" in walk and "route is checked" in walk
