"""How demanding THIS sub-strand's tasks must be, read out of its own design.

The band floors are honest as far as they go and they do not go far: Grade 7
and Grade 9 share one, because inventing a difference between them would have
been inventing a syllabus. The designs already contain the difference — a
sub-strand's outcomes are written in command words, its rubric separates
performance levels in the same words, and its allocated hours say how much work
is expected. So the profile is extracted rather than authored.

A generated profile is not trusted because a model produced it.
"""
from __future__ import annotations

import pytest

from app.services import demand_profile as dp

GOOD = {
    "top": 4, "distinct": 3,
    "mix": [{"rank": 2, "share": 0.4}, {"rank": 3, "share": 0.3},
            {"rank": 4, "share": 0.3}],
    "operations": 2, "kinds": 2, "depth": 1,
    "exemplar_question": r"Compare the value of $-15 \div 3 - (-2) \times (-4)$ "
                         r"with $(-3)(4) + 15$.",
    "exemplar_answer": "-7 and 3, so the second is larger",
    "marks": "3",
    "because": "the rubric's top level marks combined operations on integers",
    "design_quote": "applies combined operations on integers accurately",
}


def _validate(**changes):
    return dp.validate({**GOOD, **changes}, grade="grade-9",
                       subject="Mathematics", strand="Numbers",
                       sub_strand="Integers")


# ── what is accepted ────────────────────────────────────────────────────────


def test_a_sound_profile_is_accepted() -> None:
    profile, problems = _validate()

    assert profile and not problems
    assert profile.top == 4 and profile.numeric
    assert profile.sub_strand == "Integers"


def test_rounded_shares_are_a_correct_answer_from_a_careful_model() -> None:
    profile, _ = _validate(mix=[{"rank": 2, "share": 0.34},
                                {"rank": 3, "share": 0.33},
                                {"rank": 4, "share": 0.33}])

    assert profile


# ── what is refused, and why refusing matters ───────────────────────────────


def test_a_profile_whose_exemplar_is_easier_than_its_own_floor_is_refused() -> None:
    """This is the check that matters. A generator imitates the exemplar, not
    the numbers beside it, so a profile demanding an evaluation and showing a
    list has told every station downstream to write lists."""
    profile, problems = _validate(exemplar_question="List three integers.")

    assert profile is None
    assert any("exemplar asks only" in p for p in problems)


def test_a_profile_whose_exemplar_misses_its_own_arithmetic_floor_is_refused() -> None:
    profile, problems = _validate(
        operations=4, kinds=4, depth=2,
        exemplar_question="Compare $2 + 3$ with $4 + 1$.",
        exemplar_answer="both are 5")

    assert profile is None
    assert any("arithmetic floor" in p for p in problems)


def test_a_rung_that_is_not_on_the_ladder_is_refused() -> None:
    """A model that invents a seventh level of Bloom is refused rather than
    stored — the profile is consulted by every station afterwards, so a wrong
    one is wrong everywhere and quietly."""
    profile, problems = _validate(top=7)

    assert profile is None and "ladder" in problems[0]


def test_a_profile_that_quotes_no_design_is_refused() -> None:
    """Otherwise it is a recollection of the subject rather than a reading of
    the design, and the two read identically."""
    profile, problems = _validate(design_quote="")

    assert profile is None
    assert any("recollection" in p for p in problems)


def test_a_profile_with_no_exemplar_is_refused() -> None:
    profile, problems = _validate(exemplar_question="")

    assert profile is None
    assert any("generator actually imitates" in p for p in problems)


def test_a_mix_that_does_not_add_up_is_refused() -> None:
    profile, problems = _validate(mix=[{"rank": 2, "share": 0.9},
                                       {"rank": 4, "share": 0.9}])

    assert profile is None
    assert any("add up to 1.80" in p for p in problems)


def test_a_mix_that_never_reaches_the_floor_it_states_is_refused() -> None:
    profile, problems = _validate(mix=[{"rank": 1, "share": 0.5},
                                       {"rank": 2, "share": 0.5}])

    assert profile is None
    assert any("never reaches rung 4" in p for p in problems)


def test_something_that_is_not_a_profile_at_all_is_refused_without_raising() -> None:
    for junk in ("not json", "[]", 7, None):
        profile, problems = dp.validate(junk)
        assert profile is None and problems


# ── the block every station is given ────────────────────────────────────────


def test_with_no_profile_the_band_floor_is_still_stated() -> None:
    """A sub-strand nobody has extracted yet is measured less precisely, never
    waved through."""
    block = dp.block_for("grade-9", "Mathematics", None)

    assert "WHAT THE TASK ASKS FOR" in block
    assert "HOW HARD THE ARITHMETIC HAS TO BE" in block


def test_a_subject_with_no_arithmetic_floor_still_gets_the_ladder() -> None:
    block = dp.block_for("grade-9", "Christian Religious Education", None)

    assert "WHAT THE TASK ASKS FOR" in block
    assert "HOW HARD THE ARITHMETIC" not in block


def test_the_profile_puts_its_own_worked_task_in_front_of_the_generator() -> None:
    profile, _ = _validate()
    block = dp.block_for("grade-9", "Mathematics", profile)

    assert "THIS SUB-STRAND'S OWN DEMAND" in block
    assert profile.exemplar_question in block
    assert profile.exemplar_answer in block
    assert profile.design_quote in block
    assert "do not copy it" in block


def test_the_youngest_get_no_demand_block_at_all() -> None:
    assert dp.block_for("grade-pp1", "Mathematical Activities", None) == ""


# ── the judgement the gates ask for ─────────────────────────────────────────


def test_both_halves_are_measured_independently() -> None:
    """A set can be arithmetically demanding and ask only for recall, and it
    can ask for an evaluation of nothing harder than 7 - 4."""
    hard_sums_easy_asks = [
        {"stem": r"State the value of $-15 \div 3 - (-2) \times (-4) + 6$."},
        {"stem": r"State the value of $(-3)(4) + 15 - 2$."},
    ]
    judgement = dp.judge(hard_sums_easy_asks, grade="grade-9",
                         subject="Mathematics")

    assert not judgement.numeric.below
    assert judgement.command.below
    assert judgement.below


def test_a_judgement_with_no_stored_profile_uses_the_band_floor() -> None:
    judgement = dp.judge([{"stem": "List two integers."}], grade="grade-9",
                         subject="Mathematics", sub_strand="Integers")

    assert judgement.profile is None
    assert judgement.below
    assert judgement.to_dict()["from_profile"] is False


def test_a_judgement_never_raises_without_a_database() -> None:
    """Every station calls this. One that cannot reach the database must be
    told the band rule rather than fail the run."""
    assert dp.for_prompt("grade-9", "Mathematics", "Numbers", "Integers")
    assert dp.judge([], grade="grade-9", subject="Mathematics",
                    sub_strand="Integers") is not None


# ── it reaches every station that authors a task ────────────────────────────


def test_every_authoring_prompt_has_a_slot_for_it() -> None:
    """A binding whose template never mentions the slot replaces nothing, and
    the whole matrix is composed, paid for and thrown away."""
    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    for agent in ("note-generator", "material-generator", "question-generator",
                  "activity-generator", "diagram-generator",
                  "simulation-generator", "diagram-question-agent",
                  "media-prompt-generator"):
        assert "{{ demand_profile }}" in SEED_AGENT_PROMPTS[agent], agent


def test_every_slot_that_exists_is_actually_bound() -> None:
    from app.services import prompt_bindings

    report = prompt_bindings.alignment_report()

    assert report["aligned"], report["says"]


def test_activities_experiments_and_diagram_questions_are_covered() -> None:
    """The user's own list. A diagram is the easiest thing in the system to ask
    a naming question about, and an experiment written as a recipe asks for
    nothing at all."""
    import pathlib

    from app.services.langfuse_seed import SEED_AGENT_PROMPTS

    for agent in ("activity-generator", "simulation-generator",
                  "diagram-question-agent"):
        assert "{{ demand_profile }}" in SEED_AGENT_PROMPTS[agent], agent

    agent_source = pathlib.Path(
        "app/services/diagram_question_agent.py").read_text()
    assert '("demand_profile", demand_profile.for_prompt(' in agent_source


def test_the_profile_is_read_where_the_design_is_still_in_hand() -> None:
    """Sub-strand generation is the one moment the outcomes, the rubric, the
    funded hours and the design text are all present at once."""
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum)
    assert "_profile_substrands(payload, sub_strands, rubrics," in source
    assert '"demand_profiles": profiles,' in source


def test_a_refused_profile_does_not_fail_the_substrand_run() -> None:
    """A profile is an improvement on the band floor, not a precondition for
    having one."""
    import inspect

    from app.routes import curriculum

    body = inspect.getsource(curriculum._profile_substrands)
    assert "except Exception" in body
    assert "refused.append(" in body
