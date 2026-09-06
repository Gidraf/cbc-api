"""Who is READING the guide, as against who it is for.

Everything in `level_register` described the LEARNER. Nothing described the
teacher — and a guide is written for a teacher. So a Grade 9 lesson spent
twenty minutes explaining which key on a calculator is the minus sign, at the
same level of detail a PP1 guide explains how to hold up a picture. Both were
correct for their learner, and only one was written for a professional.

What separates the bands is not competence. A pre-primary teacher is not less
able; they are managing thirty four-year-olds through a song and need the words
and the actions. A senior-school specialist needs the syllabus boundary and the
misconception, not the method.
"""
from __future__ import annotations

import pytest

from app.services.level_register import teacher_band, teacher_block


@pytest.mark.parametrize("grade,level", [
    ("grade-pp1", "Pre-Primary"), ("grade-pp2", "Pre-Primary"),
    ("grade-1", "Lower Primary"), ("grade-3", "Lower Primary"),
    ("grade-4", "Upper Primary"), ("grade-6", "Upper Primary"),
    ("grade-7", "Junior School"), ("grade-9", "Junior School"),
    ("grade-10", "Senior School"), ("grade-12", "Senior School"),
    ("dte", "Tertiary"),
])
def test_every_grade_lands_in_the_band_its_teacher_belongs_to(grade, level) -> None:
    band = teacher_band(grade)
    assert band is not None and band.level == level


def test_an_unknown_grade_says_nothing_rather_than_guessing() -> None:
    """Told the wrong band, a generator writes a Grade 11 guide that explains
    what a variable is."""
    assert teacher_band("nonsense") is None
    assert teacher_block("nonsense") == ""


def test_the_junior_band_forbids_the_thing_that_went_wrong() -> None:
    """Lesson 5 of a Grade 9 Integers guide explained how to press the minus
    key on a calculator."""
    block = teacher_block("grade-9")

    assert "which key on a calculator is the minus sign" in block
    assert "Do not re-teach earlier grades" in block
    assert "every operation, rule and procedure taught in earlier grades" in block


def test_the_pre_primary_band_asks_for_the_opposite() -> None:
    """The same instruction that is patronising at Grade 9 is the whole point
    at PP1: the words are said aloud verbatim."""
    block = teacher_block("grade-pp1")

    assert "the exact words to say" in block
    assert "Do not explain what a song is" in block
    assert "re-teach" not in block


def test_a_trainee_teacher_is_an_adult_learning_to_teach() -> None:
    """The opposite of every other band: the pedagogy is the content."""
    block = teacher_block("dte")

    assert "why this method" in block
    assert "Do not write as though the reader were a child" in block


def test_each_band_says_what_to_assume_and_what_to_spell_out() -> None:
    for grade in ("grade-pp1", "grade-2", "grade-5", "grade-9", "grade-11"):
        block = teacher_block(grade)
        assert "Assume, and never explain:" in block, grade
        assert "Spell out, because it is genuinely specific" in block, grade
        assert "Write for a colleague, not for a novice" in block, grade


def test_the_bands_differ_from_one_another() -> None:
    """Four bands that say the same thing are one band."""
    blocks = {teacher_block(g) for g in
              ("grade-pp1", "grade-2", "grade-5", "grade-9", "grade-11")}
    assert len(blocks) == 5


# ── the wiring ──────────────────────────────────────────────────────────────


def test_every_prompt_that_says_who_the_learner_is_also_says_who_reads_it() -> None:
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    for name, prompt in SEED_AGENT_PROMPTS.items():
        text = prompt if isinstance(prompt, str) else str(prompt)
        if "{{ level_register }}" in text:
            assert "{{ teacher_band }}" in text, name


def test_every_station_that_passes_the_register_passes_the_band() -> None:
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    for rel in ("app/routes/curriculum.py", "app/routes/questions.py",
                "app/services/pipeline.py"):
        source = (root / rel).read_text()
        assert source.count('"level_register": register_block(') == \
            source.count('"teacher_band": teacher_block('), rel
