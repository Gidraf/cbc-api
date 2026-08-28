"""A teacher's guide must plan every lesson the design funds.

The hour-module schema lived in an appended directive that was deleted along
with an agriculture worked example; the Langfuse prompt's own schema returns
`key_concepts` and no lesson structure at all. Notes came back, a fallback
turned concepts into modules with a hardcoded 60 minutes, and coverage counted
a guide that could not be scheduled. From the console it looked as though notes
were not generating.
"""
from __future__ import annotations

import pytest

from app.services.notes_coverage import MIN_BODY_CHARS, check
from app.services.time_allocation import parse

# Scaled to the floor rather than hardcoded, so raising the floor does not
# silently turn these fixtures into the thin modules they exist to distinguish
# a complete guide from.
_BODY = "The teacher holds up the picture and asks the class. " * (
    MIN_BODY_CHARS // 40
)


def _module(number, body=_BODY, minutes=30, **extra):
    return {
        "module_number": number, "title": f"Lesson {number}",
        "duration_minutes": minutes, "teacher_exposition": body, **extra,
    }


def _seven():
    return parse("7 lessons", "grade-pp1")


def test_a_guide_that_plans_every_lesson_is_complete() -> None:
    notes = {"modules": [_module(i) for i in range(1, 8)]}

    coverage = check(notes, _seven())

    assert coverage.complete
    assert coverage.percentage == 100
    assert coverage.modules_required == 7


def test_a_short_guide_names_the_lessons_with_no_plan() -> None:
    """Fewer modules than lessons cannot be scheduled: the missing lessons have
    no plan and nobody can see which ones they are."""
    notes = {"modules": [_module(i) for i in (1, 2, 3, 4)]}

    coverage = check(notes, _seven())

    assert not coverage.complete
    assert coverage.missing_numbers == [5, 6, 7]
    assert coverage.percentage == 57


def test_a_gap_in_the_middle_is_found_not_just_a_short_tail() -> None:
    notes = {"modules": [_module(i) for i in (1, 2, 5, 6, 7)]}

    coverage = check(notes, _seven())

    assert coverage.missing_numbers == [3, 4]


def test_two_modules_numbered_the_same_are_reported() -> None:
    """Seven modules where two are 'Lesson 3' still leaves a lesson unplanned."""
    notes = {"modules": [_module(n) for n in (1, 2, 3, 3, 5, 6, 7)]}

    coverage = check(notes, _seven())

    assert coverage.duplicate_numbers == [3]
    assert coverage.missing_numbers == [4]
    assert not coverage.complete


def test_a_module_too_short_to_teach_from_is_not_a_lesson_plan() -> None:
    """A guide of headings reads complete to every count."""
    notes = {"modules": [_module(i) for i in range(1, 7)] + [_module(7, body="Sing a song.")]}

    coverage = check(notes, _seven())

    assert not coverage.complete
    assert [t["module"] for t in coverage.thin_modules] == [7]
    assert coverage.thin_modules[0]["chars"] < MIN_BODY_CHARS


def test_substance_in_the_lesson_flow_counts_as_substance() -> None:
    """A guide that puts its detail in the flow is not thin because the
    exposition is short — which is exactly the shape a pre-primary guide takes."""
    notes = {"modules": [
        _module(i, body="Short intro.", lesson_flow=[
            {"phase": "Development", "what_the_teacher_does": "x" * MIN_BODY_CHARS,
             "what_learners_do": "y" * MIN_BODY_CHARS},
        ])
        for i in range(1, 8)
    ]}

    assert check(notes, _seven()).complete


def test_the_older_schema_is_still_measured() -> None:
    """A guide generated before the rename is measured, not reported as empty."""
    notes = {"hour_modules": [
        {"hour_number": i, "full_lecture_notes": _BODY, "duration_minutes": 30}
        for i in range(1, 8)
    ]}

    assert check(notes, _seven()).complete


def test_planned_minutes_are_compared_with_allocated_minutes() -> None:
    """A teacher checking a scheme of work needs the hours to add up."""
    notes = {"modules": [_module(i, minutes=30) for i in range(1, 8)]}

    coverage = check(notes, _seven())

    assert coverage.minutes_planned == 210
    assert coverage.minutes_allocated == 210


def test_an_outcome_no_module_claims_is_named() -> None:
    notes = {"modules": [
        _module(i, slos_covered=["identify three qualities of God"]) for i in range(1, 8)
    ]}

    coverage = check(notes, _seven(), [
        {"text": "identify three qualities of God"},
        {"text": "practice saying short prayers"},
    ])

    assert coverage.slos_untaught == ["practice saying short prayers"]


def test_the_printed_length_is_reported() -> None:
    """The guide is printed and taught from, so its length is a real property
    of the deliverable rather than a token count."""
    notes = {"modules": [_module(i, body="x" * 6_000) for i in range(1, 8)]}

    assert check(notes, _seven()).to_dict()["estimated_printed_pages"] == 14.0


def test_notes_with_no_modules_are_zero_not_complete() -> None:
    coverage = check({"key_concepts": []}, _seven())

    assert coverage.modules_found == 0
    assert not coverage.complete
    assert coverage.percentage == 0


# ── The prompt and the wiring ───────────────────────────────────────────────

def test_the_prompt_asks_for_one_module_per_lesson() -> None:
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    prompt = SEED_AGENT_PROMPTS["note-generator"]

    assert "ONE MODULE PER ALLOCATED LESSON" in prompt
    assert '"modules"' in prompt
    assert "scheme of work" in prompt
    assert "Fewer modules than lessons is a defect" in prompt


def test_the_guide_is_written_to_the_teacher_not_the_learner() -> None:
    """Thin notes for young learners is the most common way this guide fails:
    the learner's level governs what may be ASKED OF THEM, not how much
    guidance the teacher receives."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    prompt = SEED_AGENT_PROMPTS["note-generator"]

    assert "The READER is a Kenyan teacher" in prompt
    assert "needs MORE support, not less" in prompt.replace("\n", " ")
    assert "scheme_of_work_summary" in prompt


def test_the_media_prompt_survived_the_rewrite() -> None:
    """It sat between note-generator and diagram-generator and was deleted by a
    replacement keyed on those two boundaries."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    assert "media-prompt-generator" in SEED_AGENT_PROMPTS
    assert len(SEED_AGENT_PROMPTS["media-prompt-generator"]) > 3_000


def test_every_reader_of_the_notes_finds_the_new_key() -> None:
    """Six places read hour_modules. One missed rename reads zero silently."""
    for path in ("app/services/coverage.py", "app/services/artifact_dna.py",
                 "app/services/dna_scoring.py", "app/services/stage_guard.py",
                 "app/routes/admin_langfuse.py"):
        source = open(path).read()
        if "hour_modules" in source:
            assert 'get("modules")' in source, f"{path} never reads the new key"
