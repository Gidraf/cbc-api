"""What lesson N+1 needs to know about lesson N.

The material station already writes one call per piece, and told each call
nothing about the others — which produced one expression worked sixteen times
and lesson 6 a renumbered lesson 3. Splitting the PLAN the same way would
reproduce that fault at the more expensive level unless each lesson is handed
what came before.
"""
from __future__ import annotations

import pytest

from app.services import lesson_handoff as lh
from app.services import task_demand

FLOOR = task_demand.floor_for("grade-9", "Mathematics")

MODULE = {
    "module_number": 1,
    "module_title": "Basic Operations on Integers",
    "slos": ["perform basic operations on integers"],
    "exposition_segments": [
        {"topic": "Introduction to Integers",
         "body": r"For example $5 + (-3) = 2$.",
         "bridge": "Now that we can add, we will subtract."},
        {"topic": "Adding integers",
         "body": r"Evaluate $-7 + 4 - (-2)$.",
         "bridge": "Next we meet multiplication."},
    ],
}


# ── what the last lesson leaves behind ──────────────────────────────────────


def test_the_handoff_carries_what_was_taught_and_worked() -> None:
    handoff = lh.read(MODULE)

    assert handoff.lesson == 1
    assert "Introduction to Integers" in handoff.taught
    assert any("5 + (-3)" in t for t in handoff.tasks)


def test_it_carries_the_sentence_the_lesson_ended_on() -> None:
    """A guide whose lessons do not join is six lessons about the same
    sub-strand rather than one sub-strand taught."""
    assert lh.read(MODULE).ended_on == "Next we meet multiplication."


def test_a_lesson_with_nothing_in_it_hands_over_nothing() -> None:
    assert lh.read({}).empty
    assert lh.read({"module_number": 2}).empty


def test_the_block_tells_the_next_lesson_not_to_repeat_the_tasks() -> None:
    block = lh.block(lh.read(MODULE), None)

    assert "5 + (-3)" in block
    assert "Next we meet multiplication." in block
    assert "with different numbers" in block, "the renumbered clone is named"
    assert "BUILD ON IT" in block


def test_the_first_lesson_is_told_it_is_the_first() -> None:
    """Introduce rather than revise. A caller with neither a previous lesson
    nor a step has nothing to say and gets nothing — the real caller always
    has the step."""
    assert lh.block(None, None) == ""

    block = lh.block(None, lh.ladder(6, FLOOR)[0])

    assert "FIRST lesson" in block and "introduce rather than revise" in block


# ── the ladder ──────────────────────────────────────────────────────────────


def test_the_opening_lessons_may_sit_below_the_sub_strand_floor() -> None:
    """Applying the top of the range to lesson 1 would demand a compound
    fraction of learners who have not yet met the sign rule."""
    steps = lh.ladder(6, FLOOR)

    assert not steps[0].reaches_the_floor
    assert steps[0].depth == 0


def test_the_later_lessons_must_reach_it() -> None:
    """Applying nothing until lesson 6 is what produced six flat lessons."""
    steps = lh.ladder(6, FLOOR)

    assert steps[-1].reaches_the_floor
    assert steps[-1].depth == FLOOR.depth
    assert steps[-1].operations == FLOOR.operations


def test_no_lesson_is_ever_allowed_to_be_primary_arithmetic() -> None:
    """The relief makes an opening lesson simpler, never primary. Two
    operations is where `infant_arithmetic` starts refusing anyway, so the
    ladder never promises what the gate will reject."""
    for lessons in (1, 2, 3, 6, 12):
        for step in lh.ladder(lessons, FLOOR):
            assert step.operations >= 2 and step.kinds >= 2


def test_the_ladder_is_shallow_on_purpose() -> None:
    """A rung per lesson invents a difficulty curve nobody asked for, and
    makes lesson 3 fail for being as hard as lesson 4."""
    reaching = [s.reaches_the_floor for s in lh.ladder(6, FLOOR)]

    assert reaching.count(False) <= 2
    assert reaching[-1] is True


def test_a_grade_with_no_floor_gets_no_ladder() -> None:
    assert lh.ladder(6, task_demand.floor_for("grade-1")) == []
    assert lh.ladder(0, FLOOR) == []


@pytest.mark.parametrize("lessons", [1, 2, 3, 6, 12])
def test_every_lesson_gets_exactly_one_step(lessons: int) -> None:
    steps = lh.ladder(lessons, FLOOR)

    assert [s.lesson for s in steps] == list(range(1, lessons + 1))
    assert all(s.of == lessons for s in steps)


def test_the_wording_is_grammatical() -> None:
    """"at least 1 operations of 1 kinds" reads as a bug in the guide."""
    block = lh.block(None, lh.ladder(6, FLOOR)[0])

    assert "1 kinds" not in block and "1 operations" not in block


def test_the_block_is_editable_without_a_deploy() -> None:
    from app.services.prompt_sync import _all_prompts

    assert "lesson-handoff" in _all_prompts()


# ── the route writes one lesson per call ────────────────────────────────────


def _fake_run(lessons: int):
    """Drive the real loop with a model that always numbers its module 1."""
    import types
    import unittest.mock as mock

    from app.routes import curriculum

    from app.services.cost_tracker import TokenUsage

    seen: list[str] = []

    class Resp:
        def __init__(self, content):
            self.content = content
            self.usage = TokenUsage()
            self.model = "fake"
            self.provider = "fake"

    def generate(resolved, messages, temperature=0.15):
        seen.append(messages[-1]["content"])
        n = len(seen)
        return Resp({
            "title": "Integers", "intro": "envelope field",
            "modules": [{
                "module_number": 1,
                "module_title": f"Written for call {n}",
                "exposition_segments": [{
                    "topic": f"Topic {n}",
                    "body": r"Evaluate $-15 \div 3 - (-2) \times (-4) + 6$.",
                    "bridge": f"On to part {n + 1}."}]}]})

    log = types.SimpleNamespace(step=lambda *a, **k: None)
    ctx = types.SimpleNamespace(
        messages=[{"role": "user", "content": "the whole sub-strand"}])
    with mock.patch("app.services.llm_client.llm_client.generate", generate):
        out = curriculum._plan_lesson_by_lesson(
            ctx, object(), lessons=lessons, grade="grade-9",
            subject="Mathematics", strand="Numbers", sub_strand="Integers",
            run_log=log)
    # The planner now returns a response; these tests read the guide it wrote.
    return out.content, seen


def test_one_call_is_made_per_lesson() -> None:
    out, seen = _fake_run(4)

    assert len(seen) == 4
    assert len(out["modules"]) == 4


def test_the_loop_numbers_the_lessons_itself() -> None:
    """A model's own numbering restarts at 1 on every call. The guide's lesson
    4 is the fourth call, not whatever the fourth call called it."""
    out, _ = _fake_run(4)

    assert [m["module_number"] for m in out["modules"]] == [1, 2, 3, 4]


def test_the_envelope_survives_the_split() -> None:
    """The guide's own title and intro come from the first call; only the
    modules are collected."""
    out, _ = _fake_run(3)

    assert out["title"] == "Integers" and out["intro"] == "envelope field"
    assert "hour_modules" not in out, "the mirror is added later, once"


def test_each_call_is_told_which_lesson_it_is_writing() -> None:
    _, seen = _fake_run(4)

    assert "LESSON 1 OF 4" in seen[0]
    assert "LESSON 3 OF 4" in seen[2]


def test_the_second_lesson_is_handed_the_first() -> None:
    _, seen = _fake_run(4)

    assert "FIRST lesson" in seen[0]
    assert "Written for call 1" in seen[1]
    assert "On to part 2." in seen[1], "the sentence lesson 1 ended on"
    assert "÷" in seen[1], "the task lesson 1 worked"


def test_the_later_lessons_are_told_to_reach_the_grade() -> None:
    _, seen = _fake_run(4)

    assert "must REACH the grade" in seen[3]


def test_the_prompt_names_the_objective_trap() -> None:
    """Writing "(addition, subtraction)" into the objective deleted
    multiplication and division from a whole sub-strand."""
    from app.services.langfuse_seed import SEED_PROMPT_BLOCKS

    block = SEED_PROMPT_BLOCKS["note-one-lesson"]
    assert "must not narrow the outcome" in block
    assert "(addition, subtraction)" in block


def test_a_single_lesson_sub_strand_still_uses_one_call() -> None:
    """There is no sequence to carry, and the loop would only add a round
    trip."""
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_notes)
    assert "if allocation.modules > 1:" in source
    assert "if resp is None:" in source, "the single call remains"


def test_one_failed_lesson_does_not_lose_the_others() -> None:
    import types
    import unittest.mock as mock

    from app.routes import curriculum

    calls = {"n": 0}

    from app.services.cost_tracker import TokenUsage

    class Resp:
        def __init__(self, content):
            self.content = content
            self.usage = TokenUsage(prompt_tokens=100, completion_tokens=50,
                                    total_tokens=150)
            self.model = "gpt-4o"
            self.provider = "openai"

    def generate(resolved, messages, temperature=0.15):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("provider timed out")
        return Resp({"modules": [{"module_number": 1, "module_title": "ok"}]})

    log = types.SimpleNamespace(step=lambda *a, **k: None)
    ctx = types.SimpleNamespace(messages=[{"role": "user", "content": "x"}])
    with mock.patch("app.services.llm_client.llm_client.generate", generate):
        out = curriculum._plan_lesson_by_lesson(
            ctx, object(), lessons=3, grade="grade-9", subject="Mathematics",
            strand="Numbers", sub_strand="Integers", run_log=log)

    assert [m["module_number"] for m in out.content["modules"]] == [1, 3]


def test_the_per_lesson_run_reports_usage_like_a_single_call() -> None:
    """"Lesson plan failed after 2 attempts: cannot access local variable
    'resp' where it is not associated with a value."

    The route read `resp.usage` at the end, and `resp` was only ever assigned
    by the single-call fallback. Every multi-lesson guide was written, checked,
    repaired and SAVED — and then the response crashed, so the operator saw an
    error and a new version at the same time, twice per run.
    """
    import types
    import unittest.mock as mock

    from app.routes import curriculum
    from app.services.cost_tracker import TokenUsage

    class Resp:
        def __init__(self):
            self.content = {"modules": [{"module_number": 1, "module_title": "ok"}]}
            self.usage = TokenUsage(prompt_tokens=100, completion_tokens=50,
                                    total_tokens=150)
            self.model = "gpt-4o"
            self.provider = "openai"

    log = types.SimpleNamespace(step=lambda *a, **k: None)
    ctx = types.SimpleNamespace(messages=[{"role": "user", "content": "x"}])
    with mock.patch("app.services.llm_client.llm_client.generate",
                    lambda *a, **k: Resp()):
        out = curriculum._plan_lesson_by_lesson(
            ctx, object(), lessons=3, grade="grade-9", subject="Mathematics",
            strand="Numbers", sub_strand="Integers", run_log=log)

    # Three calls, summed, in the shape the route already reads.
    assert out.usage.prompt_tokens == 300
    assert out.usage.completion_tokens == 150
    assert out.usage.total_tokens == 450
    assert out.model == "gpt-4o" and out.provider == "openai"
    assert len(out.content["modules"]) == 3


def test_the_route_reads_one_resp_whichever_path_wrote_the_guide() -> None:
    import inspect

    from app.routes import curriculum

    source = inspect.getsource(curriculum.factory_generate_notes)
    planner = source.index("resp = _plan_lesson_by_lesson(")
    fallback = source.index("resp = llm_client.generate(resolved, context.messages")
    content = source.index("notes_content = resp.content")
    assert planner < fallback < content, \
        "both branches assign resp BEFORE anything reads it"
