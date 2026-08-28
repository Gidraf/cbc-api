"""A teaching profile must not contradict the register it sits beside.

The profile is injected into every authoring prompt for its subject and grade,
alongside the level register. Written without the register, it contradicted it
in the same prompt: "flowcharts illustrating the relationship between God,
creation, and human values" and "practical laboratory experiences" prescribed
for four-year-olds the register says cannot read a flowchart and must not
handle chemicals, heat or sharp tools.

Two opposite instructions in front of one author means one of them gets
followed, and nothing records which.
"""
from __future__ import annotations

import re


def _generator_source() -> str:
    """The generator's source with adjacent string literals joined.

    The prompt is written as many quoted fragments, so a phrase the model sees
    as one sentence is split across two literals in the file. Searching the raw
    source for it fails on a prompt that is perfectly correct.
    """
    source = open("app/services/content_type_classifier.py").read()
    start = source.index("def ai_generate_profile_from_dataset")
    block = source[start: source.index("\ndef ", start + 10)]
    return re.sub(r'"\s*\n\s*"', "", block)


def test_the_profile_is_written_against_the_register() -> None:
    block = _generator_source()

    assert "register_block(grade)" in block
    assert "WHO THIS PROFILE IS FOR" in block
    assert "Prescribe nothing the register rules out" in block


def test_flowcharts_are_no_longer_demanded_of_every_subject() -> None:
    """A flowchart, a table, a graph and a labelled schematic all require
    reading."""
    block = _generator_source()

    assert "flowcharts, structural apparatus" not in block
    assert "where the register says the learner cannot read" in block.replace("\n", " ")


def test_laboratory_work_is_no_longer_demanded_of_every_subject() -> None:
    block = _generator_source()

    assert "practical laboratory/field experiments" not in block
    assert "play-based and sensory work is the practical work at that level" in block.replace("\n", " ")


def test_the_prompt_no_longer_orders_the_model_to_produce_statistics() -> None:
    """This is where the fabricated figures came from: the field DEMANDED four
    to six statistics with official sources the model had no way to obtain, so
    it invented them. Labelling them unverified downstream treated the symptom."""
    block = _generator_source()

    assert "authentic Kenyan empirical datasets, statistics" not in block
    assert "Return an EMPTY LIST if you cannot" in block
    assert "An empty list is the correct answer here far more often than not" in block


def test_an_invented_hazard_is_named_as_a_defect() -> None:
    block = _generator_source()

    assert "invented hazard trains teachers to ignore the field" in block.replace("\n", " ")


def test_case_studies_are_not_presented_as_documented_events() -> None:
    block = _generator_source()

    assert "do not present them as reported cases" in block.replace("\n", " ")


def test_the_register_reaches_the_prompt_for_a_real_grade() -> None:
    from app.services.level_register import register_block

    register = register_block("grade-pp1")

    assert "read a flowchart, a table, a graph or a labelled diagram" in register
    assert "There are no experiments at this level" in register
