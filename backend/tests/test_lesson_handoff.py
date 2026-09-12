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


# Twelve expressions of twelve shapes, every one an integer, so a fake lesson
# built from any two of them passes the write-time checks: at grade, signed,
# not a clone of another lesson's shape, integer answers, working the engine
# can verify.
POOL: list[tuple[str, str]] = [
    (r"-18 - (-12) \times 2 + (-7)", "-1"),
    (r"\dfrac{(-9 + 4) \times (-6)}{-2 \times 5}", "-3"),
    (r"(-6) \times (-4) \div (-2) + 3", "-9"),
    (r"-40 \div (-8) + (-3) \times 6 - (-11)", "-2"),
    (r"(7 - 12) \times (-3) + 20 \div (-4)", "10"),
    (r"(3 + (-9)) \div (-2) - 4 \times (-5)", "23"),
    (r"-30 \div (-5) \times (-2) + 14", "2"),
    (r"(-8 + 2) \times (-3) - (-10)", "28"),
    (r"\dfrac{(-20) \div 4 + 9}{-2}", "-2"),
    (r"-5 \times (-3) - (-4) \times (-6) + 1", "-8"),
    (r"(-12 \div (-3) + (-7)) \times 2", "-6"),
    (r"-9 + (-3) \times (-4) \div (-6) - 2", "-13"),
]


def _example(k: int) -> dict:
    expr, answer = POOL[k % len(POOL)]
    return {"statement": f"Work out ${expr}$.",
            "steps": [{"working": f"${expr} = {answer}$", "because": "BODMAS, signs carried"}],
            "answer": answer}


def _two_examples(lesson: int) -> list[dict]:
    return [_example(2 * (lesson - 1)), _example(2 * (lesson - 1) + 1)]


_SENTENCES = [
    "The number line runs both ways and zero is where the signs change.",
    "A debt grows when more is borrowed and shrinks when some is repaid.",
    "A thermometer reads below zero on a cold morning on the mountain.",
    "Brackets are worked first because they group what belongs together.",
    "Two negatives multiplied give a positive because the direction reverses twice.",
    "Dividing a negative by a positive shares a loss among several people.",
    "A fraction bar is a pair of brackets the learner has to supply.",
    "Checking by substitution shows whether the order of operations was kept.",
]


def _complete(module: dict, lesson: int) -> dict:
    """A fake module with enough in it that the write-time checks pass, and
    with prose of its own so two fakes are not the same block of exposition."""
    sentence = _SENTENCES[lesson % len(_SENTENCES)]
    module.setdefault("exposition_segments", [
        {"topic": f"Topic {lesson}",
         "body": "Learners discuss integers in pairs. " + (sentence + " ") * 25,
         "bridge": f"On to part {lesson + 1}."}])
    module.setdefault("worked_examples", _two_examples(lesson))
    module.setdefault("learning_experiences_used", ["discuss integers"])
    return module


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
            "modules": [_complete({
                "module_number": 1,
                "module_title": f"Written for call {n}",
                "exposition_segments": [{
                    "topic": f"Topic {n}",
                    "body": r"Evaluate $-15 \div 3 - (-2) \times (-4) + 6$. " * 8,
                    "bridge": f"On to part {n + 1}."}]}, n)]})

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
    """The guide's intro comes from the first call; only the modules are
    collected. The title is the sub-strand's — lesson 1 used to title the
    whole guide after itself."""
    out, _ = _fake_run(3)

    assert out["title"] == "Teacher's Guide: Integers" and out["intro"] == "envelope field"
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
        return Resp({"modules": [_complete({"module_number": 1, "module_title": "ok"}, calls["n"])]})

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

    import itertools

    from app.routes import curriculum
    from app.services.cost_tracker import TokenUsage

    calls = itertools.count(1)

    class Resp:
        def __init__(self):
            self.content = {"modules": [_complete({"module_number": 1, "module_title": "ok"},
                                                  next(calls))]}
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


# ── every earlier lesson, not only the last ──────────────────────────────────


def test_the_handoff_accumulates_what_every_earlier_lesson_worked() -> None:
    """Lesson 5 worked what lesson 3 had worked. The hand-off named only the
    previous lesson's tasks, so lesson 5 was never told about lesson 3's."""
    first = lh.read(MODULE)
    second = lh.read({
        "module_number": 2, "module_title": "Multiplying",
        "exposition_segments": [{"topic": "Sign rule",
                                 "body": r"Work out $(-3) \times (-4) + 10$."}]},
        first)
    third = lh.read({"module_number": 3, "module_title": "Dividing"}, second)

    assert any("5 + (-3)" in t for t in second.earlier_tasks)
    assert any("5 + (-3)" in t for t in third.earlier_tasks), "carried two lessons on"
    assert any("(-3)" in t and "(-4)" in t for t in third.earlier_tasks)

    block = lh.block(third, None)
    assert "5 + (-3)" in block and "lessons before that" in block


def test_the_fourth_call_is_told_what_the_first_worked() -> None:
    _, seen = _fake_run(4)

    assert "Written for call 1" in seen[1]
    # Lesson 1's expression is only *directly* in call 2's hand-off, but the
    # accumulated list carries it into calls 3 and 4 as well.
    assert seen[3].count("÷") >= 1
    assert "lessons before that" in seen[3]


# ── the worked-examples rule is the grade's and the subject's ────────────────


def test_a_non_maths_subject_gets_no_worked_examples_rule() -> None:
    """A PP1 CRE lesson was told its worked examples must let BODMAS decide
    the answer: the rule was written into the lesson prompt for every subject
    with Grade 9 integer exemplars."""
    assert lh.worked_examples_rule("Christian Religious Education", FLOOR) == ""
    assert lh.worked_examples_rule("Kiswahili", None) == ""


def test_a_grade_with_no_floor_gets_no_rule() -> None:
    assert lh.worked_examples_rule(
        "Mathematics", task_demand.floor_for("grade-2", "Mathematics")) == ""


def test_the_rule_carries_the_grades_own_exemplars() -> None:
    upper = lh.worked_examples_rule(
        "Mathematics", task_demand.floor_for("grade-5", "Mathematics"))
    junior = lh.worked_examples_rule("Mathematics", FLOOR)

    assert "AT LEAST TWO examples" in upper and "AT LEAST TWO examples" in junior
    assert "Upper Primary" in upper and "1\\,250 - 3 \\times 240" in upper
    assert "Junior School" in junior and "dfrac" in junior
    assert "dfrac" not in upper, "a Grade 5 lesson is not shown a Grade 9 fraction bar"
    assert "50 - 20 + 15" in junior, "the shape that is below the grade is named"


def test_a_rung_where_order_matters_is_not_met_by_two_additive_kinds() -> None:
    """`50 − 20 + 15` has two kinds and met a Junior School opening rung."""
    step = lh.ladder(6, FLOOR)[0]
    assert step.order_matters
    d = task_demand.measure("$50 - 20 + 15$")
    assert len(d.kinds) >= step.kinds and not d.order_matters


# ── checked at write time, and written again the same way ────────────────────


def _run_with(monkeypatch, lessons: int, author, design_row=None, findings=None):
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
        return Resp({"title": "x", "modules": [
            _complete(author(len(seen), messages[-1]["content"]), len(seen))]})

    log = types.SimpleNamespace(step=lambda *a, **k: None)
    ctx = types.SimpleNamespace(messages=[{"role": "user", "content": "the sub-strand"}])
    with mock.patch("app.services.llm_client.llm_client.generate", generate):
        out = curriculum._plan_lesson_by_lesson(
            ctx, object(), lessons=lessons, grade="grade-9", subject="Mathematics",
            strand="Numbers", sub_strand="Integers", run_log=log,
            design_row=design_row or {}, design_experiences=["discuss integers"],
            findings=findings)
    return out.content, seen


CLONE = {"statement": r"Evaluate $(-3 + 5) \times 2 - 4$.",
         "steps": [{"working": r"$(-3+5) \times 2 - 4 = 2 \times 2 - 4$", "because": "brackets"},
                   {"working": r"$2 \times 2 - 4 = 0$", "because": "multiply, subtract"}],
         "answer": "0"}
FRESH = {"statement": r"Evaluate $-18 - (-12) \times 2 + (-7)$.",
         "steps": [{"working": r"$-18 - (-12) \times 2 + (-7) = -18 + 24 - 7$", "because": "multiply first"},
                   {"working": r"$-18 + 24 - 7 = -1$", "because": "left to right"}],
         "answer": "-1"}
SECOND = {"statement": r"Work out $\dfrac{(-9 + 4) \times (-6)}{-2 \times 5}$.",
          "steps": [{"working": r"$\dfrac{(-9+4) \times (-6)}{-2 \times 5} = \dfrac{-5 \times (-6)}{-10}$", "because": "brackets"},
                    {"working": r"$\dfrac{30}{-10} = -3$", "because": "divide"}],
          "answer": "-3"}
THIRD = {"statement": r"Work out $-40 \div (-8) + (-3) \times 6 - (-11)$.",
         "steps": [{"working": r"$-40 \div (-8) + (-3) \times 6 - (-11) = 5 - 18 + 11$", "because": "÷ and × first"},
                   {"working": r"$5 - 18 + 11 = -2$", "because": "left to right"}],
         "answer": "-2"}


def test_a_lesson_that_clones_the_one_before_is_written_again_at_once(monkeypatch) -> None:
    """Lesson 2 worked the expression lesson 1 had worked. It used to be found
    only when the finished guide was inspected, and the fix then was writing
    the whole guide again."""
    def author(call, prompt):
        if call == 1:
            return {"module_number": 1, "title": "Lesson 1", "worked_examples": [CLONE, SECOND],
                    "learning_experiences_used": ["discuss integers"]}
        if call == 2:
            return {"module_number": 1, "title": "Lesson 2", "worked_examples": [CLONE, THIRD],
                    "learning_experiences_used": ["discuss integers"]}
        return {"module_number": 1, "title": "Lesson 2 again", "worked_examples": [FRESH, THIRD],
                "learning_experiences_used": ["discuss integers"]}

    out, seen = _run_with(monkeypatch, 2, author)

    assert len(seen) == 3, "lesson 1, lesson 2, and one retry of lesson 2"
    assert "FAILED THESE CHECKS" in seen[2] and "repeats an expression" in seen[2]
    assert out["modules"][1]["title"] == "Lesson 2 again"


def test_a_retry_that_does_no_better_is_not_kept_over_the_first(monkeypatch) -> None:
    def author(call, prompt):
        return {"module_number": 1, "title": f"Attempt {call}", "worked_examples": [CLONE, SECOND],
                "learning_experiences_used": ["discuss integers"]}

    out, seen = _run_with(monkeypatch, 2, author)

    assert len(seen) == 3, "one retry, not a loop"
    assert out["modules"][1]["title"] in {"Attempt 2", "Attempt 3"}


def test_a_regeneration_tells_each_lesson_what_the_last_guide_failed(monkeypatch) -> None:
    prompts: list[str] = []

    def author(call, prompt):
        prompts.append(prompt)
        return {"module_number": 1, "title": f"L{call}",
                "worked_examples": [[FRESH, SECOND], [CLONE, THIRD]][(call - 1) % 2],
                "learning_experiences_used": ["discuss integers"]}

    _run_with(monkeypatch, 2, author,
              findings=["Lesson 2 works an example of exactly the shape Lesson 1 already worked.",
                        "The design suggests \"x\" and no lesson uses it."])

    assert "FAILED THESE CHECKS" not in prompts[0], "lesson 1 had no finding of its own"
    assert "exactly the shape Lesson 1" in prompts[1]
    assert "no lesson uses it" not in prompts[1], "guide-wide findings are not a lesson's to fix"


def test_the_guide_is_titled_after_the_sub_strand_not_after_lesson_1(monkeypatch) -> None:
    out, _ = _run_with(monkeypatch, 1, lambda c, p: {
        "module_number": 1, "title": "Lesson 1: Basics", "worked_examples": [FRESH, SECOND],
        "learning_experiences_used": ["discuss integers"]})
    assert out["title"] == "Teacher's Guide: Integers" and out["module_count"] == 1


def test_the_rule_carries_the_sub_strands_own_demand_over_the_floor() -> None:
    """The floor is two operations. The design's own profile said four, and a
    model told two wrote every example at two."""
    import types

    profile = types.SimpleNamespace(operations=4, kinds=2, depth=1,
                                    exemplar_question="Calculate the final balance of an account "
                                                      "that starts at $-18$, receives $24$, pays $3$ "
                                                      "each to $2$ suppliers and is refunded $5$.")
    rule = lh.worked_examples_rule("Mathematics", FLOOR, profile)
    assert "at least 4 operations" in rule
    assert "starts at $-18$" in rule
    assert "not the target" in rule
    assert "at least 2 operations" in lh.worked_examples_rule("Mathematics", FLOOR, None)
