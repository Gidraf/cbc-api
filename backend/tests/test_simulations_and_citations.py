"""Interactive simulation briefs, media grounded in the notes, and citations
that are resolved rather than trusted.

A diagram is a still picture of a thing; a simulation is the thing behaving.
Media planned from the outcomes alone came back generic, because the outcomes
never mention the volcano the notes describe. And a manufactured "202:14"
survives every inspection short of opening page 202 — which nobody does when
the field is already filled in.
"""
from __future__ import annotations

import pytest

from app.services.citation_check import MIN_OVERLAP, collect, verify
from app.services.lesson_content import summarise_activities, summarise_notes
from app.services.simulation_validators import MIN_BUILD_PROMPT_TOKENS, check

_RULE = "=" * 80
_DOC = (
    f"{_RULE}\nPAGE 202 OF 296\n{_RULE}\n\n"
    "Summary of Strands and Sub-Strands\n"
    "1.1 Our God 7 lessons\n"
    "Learners identify three qualities of God\n"
)


def _sim(**over):
    base = {
        "title": "Stretching a spring",
        "purpose": "relate force to extension",
        "build_prompt": "x" * (MIN_BUILD_PROMPT_TOKENS * 4),
        "concept_model": {
            "explanation": "Hooke's law relates restoring force to extension.",
            "equations": ["F = -kx"],
            "assumptions": ["The spring stays within its elastic limit."],
        },
        "learner_controls": [
            {"control": "slider", "label": "Pull", "parameter": "x",
             "range": "0 to 0.25", "unit": "m"},
        ],
        "acceptance_criteria": ["Pulling to 0.25 m must read 5.0 N."],
        "predict_step": "What will happen to the force as you pull further?",
        "technology": {"stack": "CSS + vanilla JS"},
        "accessibility": {"text_alternative": "A table of force against extension."},
    }
    base.update(over)
    return base


# ── Simulation briefs ───────────────────────────────────────────────────────

def test_a_complete_brief_passes() -> None:
    assert check([_sim()]).sound


def test_a_brief_with_no_model_is_refused() -> None:
    """A simulation that is subtly wrong teaches the wrong thing more
    convincingly than a wrong sentence — the learner watched it happen."""
    report = check([_sim(concept_model={})])

    assert not report.sound
    assert any(f.check == "no_model" for f in report.errors)


def test_a_model_with_no_equation_is_refused() -> None:
    """A developer who has to derive the model will get it wrong, and a reviewer
    cannot check what was never stated."""
    report = check([_sim(concept_model={"explanation": "Springs stretch.", "assumptions": ["x"]})])

    assert any(f.check == "no_equations" for f in report.errors)


def test_a_title_is_not_a_brief() -> None:
    report = check([_sim(build_prompt="Show Newton's second law with a spring.")])

    assert not report.sound
    assert any(f.check == "too_short" for f in report.errors)


def test_a_simulation_with_nothing_to_change_is_a_diagram() -> None:
    report = check([_sim(learner_controls=[])])

    assert any(f.check == "no_controls" for f in report.errors)


def test_a_brief_with_no_acceptance_criteria_is_refused() -> None:
    """Nothing else tells a working simulation from a plausible-looking one."""
    report = check([_sim(acceptance_criteria=[])])

    assert any(f.check == "no_acceptance_criteria" for f in report.errors)


def test_three_js_is_flagged_as_heavy() -> None:
    """Most Kenyan school devices are not."""
    report = check([_sim(technology={"stack": "Three.js"})])

    assert report.sound, "heavy is a warning, not a block"
    assert any(f.check == "heavy_stack" for f in report.findings)


def test_a_simulation_the_learner_cannot_predict_first_is_flagged() -> None:
    """A simulation that is only a toy produces delight and no learning."""
    report = check([_sim(predict_step="")])

    assert any(f.check == "no_predict_step" for f in report.findings)


def test_the_prompt_says_what_earns_a_simulation() -> None:
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    prompt = SEED_AGENT_PROMPTS["simulation-generator"]
    flat = prompt.replace("\n", " ")

    assert "You do NOT write the code" in flat
    assert "a diagram with extra steps" in flat
    assert "predict, then act, then explain" in flat
    assert "runs offline" in flat


# ── Media grounded in what the notes actually say ───────────────────────────

def test_the_notes_are_summarised_lesson_by_lesson() -> None:
    """An asset serves one lesson, and a planner that cannot see which lesson
    said what cannot say which lesson its asset belongs to."""
    body, titles = summarise_notes({"modules": [
        {"title": "Lesson 1: Volcanoes", "teacher_exposition": "Mount Longonot erupts."},
        {"title": "Lesson 2: Rift valley", "teacher_exposition": "The valley formed."},
    ]})

    assert titles == ["Lesson 1: Volcanoes", "Lesson 2: Rift valley"]
    assert "Mount Longonot" in body
    assert "--- Lesson 2: Rift valley ---" in body


def test_the_experiment_a_teacher_will_run_reaches_the_planner() -> None:
    summary = summarise_activities({"experiments": [
        {"title": "Model volcano", "aim": "show an eruption",
         "materials_needed": ["baking soda", "vinegar"], "procedure": ["Build the cone"]},
    ]})

    assert "Model volcano" in summary
    assert "baking soda" in summary
    assert "Build the cone" in summary


def test_the_media_prompt_briefs_what_the_notes_describe() -> None:
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    flat = SEED_AGENT_PROMPTS["media-prompt-generator"].replace("\n", " ")

    assert "not for the sub-strand in the abstract" in flat
    assert "Mount Longonot" in flat
    assert "One image for a seven-lesson sub-strand is not a media plan" in flat


# ── Citations resolved, not trusted ─────────────────────────────────────────

def test_a_real_citation_verifies() -> None:
    report = verify(
        {"citations": [{"claim": "seven lessons", "ref": "202:2",
                        "quote": "1.1 Our God 7 lessons"}]},
        _DOC,
    )

    assert report.verified == 1
    assert report.percentage == 100


def test_an_address_that_does_not_exist_fails() -> None:
    report = verify({"citations": [{"ref": "999:4", "quote": "anything"}]}, _DOC)

    assert report.verified == 0
    assert "does not exist in this document" in report.citations[0].reason


def test_a_quote_that_is_not_at_the_address_fails() -> None:
    """This is the citation that survives inspection: the address is real, so
    it looks checked, and the claim it supports is unsupported."""
    report = verify(
        {"citations": [{"claim": "the wise men",
                        "ref": "202:1", "quote": "the wise men brought gold and myrrh"}]},
        _DOC,
    )

    assert report.verified == 0
    assert "is unsupported" in report.citations[0].reason


def test_wrapped_source_text_still_verifies() -> None:
    """A design's own text wraps mid-phrase across columns, so an exact match
    would fail on citations that are perfectly good."""
    report = verify(
        {"citations": [{"ref": "202:3", "quote": "learners identify qualities of God"}]},
        _DOC,
    )

    assert report.verified == 1


def test_citations_are_found_wherever_they_live() -> None:
    """Notes cite per module; questions cite on their curriculum block."""
    found = collect({
        "modules": [{"citations": [{"ref": "202:1", "quote": "a"}]}],
        "questions": [{"guideline_quote": "b", "guideline_reference": {"ref": "203:4"},
                       "kicd_alignment": "assesses outcome (a)"}],
    })

    assert sorted(c.ref for c in found) == ["202:1", "203:4"]


def test_no_document_is_reported_rather_than_passing_everything() -> None:
    report = verify({"citations": [{"ref": "202:1", "quote": "a"}]}, "")

    assert not report.document_available
    assert report.verified == 0


def test_the_notes_prompt_forbids_manufacturing_an_address() -> None:
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    flat = SEED_AGENT_PROMPTS["note-generator"].replace("\n", " ")

    assert "CITE THE DESIGN" in flat
    assert "an unverifiable citation is worse than none" in flat
    assert "uncited_content" in flat


def test_questions_say_how_they_serve_the_kicd_goal() -> None:
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    flat = SEED_AGENT_PROMPTS["question-generator"].replace("\n", " ")

    assert "kicd_alignment" in flat
    assert "which competency and value it develops" in flat
    assert "assessing something KICD did not ask for" in flat
