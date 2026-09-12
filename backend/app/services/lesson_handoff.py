"""What lesson N+1 needs to know about lesson N.

The plan station writes all six lessons in one call. The material station
writes one piece per call and, until this week, told each call nothing about
the others — and the result was one expression worked sixteen times and lesson
6 a renumbered lesson 3.

Splitting the plan the same way would reproduce that fault at the more
expensive level, unless each lesson is handed what came before. So this is the
hand-off: what the last lesson taught, the tasks it used, the sentence it ended
on, and how demanding it got.

WHY THE DIFFICULTY IS A LADDER AND NOT A FLOOR. A sub-strand's demand profile
says what a task at the TOP of its range looks like. Applying that to lesson 1
would demand a compound fraction of learners who have not yet met the sign
rule; applying nothing until lesson 6 is what produced six flat lessons. So
each lesson carries its own step: the first sits below the sub-strand's floor
deliberately, the last must reach it, and no lesson may be easier than the one
before it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The first lesson of a sub-strand introduces; it is allowed to be simpler than
# the sub-strand's own floor, because a learner meeting the sign rule for the
# first time cannot be handed a compound fraction. What it may NOT be is
# simpler than the level below — that is the primary-school work the whole
# demand floor exists to keep out.
FIRST_LESSON_RELIEF = 1


@dataclass
class Step:
    """What one lesson in the sequence has to reach."""

    lesson: int
    of: int
    operations: int
    kinds: int
    depth: int
    reaches_the_floor: bool
    # Whether the kinds must MIX: one of + − with one of × ÷ ^ √, so that the
    # order of operations decides the answer. Two kinds counted as `+` and `−`
    # let `50 − 20 + 15` pass a Grade 9 rung; that is the Grade 4 arithmetic
    # the floor exists to keep out.
    order_matters: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"lesson": self.lesson, "of": self.of,
                "operations": self.operations, "kinds": self.kinds,
                "depth": self.depth,
                "reaches_the_floor": self.reaches_the_floor,
                "order_matters": self.order_matters}


def ladder(lessons: int, floor: Any) -> list[Step]:
    """The demand each lesson has to reach, rising to the sub-strand's floor.

    Deliberately shallow: two steps, not six. A ladder with a rung per lesson
    invents a difficulty curve nobody asked for and makes lesson 3 fail for
    being as hard as lesson 4. What it enforces is that the guide STARTS below
    where it ENDS, and that it ends at the grade.
    """
    if lessons < 1 or floor is None:
        return []
    steps: list[Step] = []
    for n in range(1, lessons + 1):
        early = n <= max(1, lessons // 3)
        relief = FIRST_LESSON_RELIEF if early else 0
        steps.append(Step(
            lesson=n, of=lessons,
            operations=max(2, floor.operations - relief),
            kinds=max(2, floor.kinds - relief),
            depth=0 if early else floor.depth,
            reaches_the_floor=not early,
            order_matters=bool(floor.order_matters),
        ))
    return steps


def worked_examples_rule(subject: str | None, floor: Any,
                         profile: Any = None) -> str:
    """What one lesson is told about its worked examples, for THIS subject
    and THIS grade — or nothing, where the subject has no such rule.

    The rule used to be written into the lesson prompt itself, for every
    subject and every grade, with Grade 9 integer exemplars: a PP1 CRE lesson
    was told its worked examples must let BODMAS decide the answer.

    `profile` is the sub-strand's own demand, read from its design, where one
    has been extracted. The level's floor is a floor; the design's own figure
    is usually higher, and a model told the floor writes to the floor — a
    guide came back with every example at exactly two operations because
    that is what this rule had said.
    """
    if not subject or "math" not in subject.lower() or floor is None:
        return ""
    operations = max(int(floor.operations), int(getattr(profile, "operations", 0) or 0))
    kinds = max(int(floor.kinds), int(getattr(profile, "kinds", 0) or 0))
    depth = max(int(floor.depth), int(getattr(profile, "depth", 0) or 0))
    lines = [
        "=== WORKED EXAMPLES — REQUIRED (NON-NEGOTIABLE) ===",
        "`worked_examples` must hold AT LEAST TWO examples in this lesson, "
        "including a lesson whose outcome is \"appreciate\" or \"apply\". An "
        "empty list is a rejected lesson, not a shorter one. Each example: a "
        "statement in the words a learner reads, the working step by step in "
        "LaTeX between single dollars, the REASON at every step, and the answer.",
        "A NEW expression every time, and a NEW SHAPE: do not work an expression "
        "that any earlier lesson of this guide has already worked — the hand-off "
        "above lists them — and do not work one of the same shape with the "
        "numbers changed. Six lessons each working `a + b × (−c) − d` over "
        "`e − (−f)` is one example printed six times.",
        "Where this lesson's outcome is about real-life situations, applying or "
        "appreciating, at least one example is a SITUATION — a temperature that "
        "falls and rises, money owed and paid, height above and below sea level "
        "— with the integers and operations arising from it and the answer in "
        "its units. A bare expression under a real-life heading serves a "
        "different lesson from the one on the tin. A situation still has to "
        "reach the grade: three days each 4°C colder is 3 × (−4); five items "
        "at KSh 120 with KSh 200 off is 5 × 120 − 200; a debt shared four ways "
        "is ÷ 4. A change FROM one value TO another is final minus initial — "
        "from 5°C to −3°C is −3 − 5 = −8, not 5 + (−3).",
        "Every answer in an Integers sub-strand is an integer. Choose the "
        "numbers so that every division is exact.",
        "The exposition must teach what the examples use. Before an example "
        "multiplies or divides signed numbers, this lesson or an earlier one "
        "must have STATED the sign rule in its own prose, with the reason.",
        "",
        f"At {floor.level} level, {floor.because}. So the HARDER of each "
        f"lesson's two examples must use at least {operations} operations of "
        f"{_plural(kinds, 'different kind')}"
        + (", mixing + or − with × or ÷ so that the ORDER of operations "
           "decides the answer" if floor.order_matters else "")
        + (", with a bracket or fraction bar" if depth else "")
        + ". That is the least — not the target. The design's own item at the "
          "top of its range is shown above; write to that.",
    ]
    if profile is not None and getattr(profile, "exemplar_question", ""):
        lines.append(
            "This sub-strand's own design asks for items like: "
            + str(profile.exemplar_question).strip()
            + " — write your own at that demand, not this one.")
    if floor.order_matters:
        lines.append(
            "One kind of operation, however long the sum or whatever story is "
            "wrapped round it, is below this grade: $50 - 20 + 15$ and "
            "$7 + (-3)$ are not worked examples at this level.")
    shapes = [floor.exemplar, *floor.also]
    lines.append("Shapes at this level (write your OWN — these show the SHAPE, "
                 "not the question): " + "   ".join(shapes))
    return "\n".join(lines)


@dataclass
class Handoff:
    """The previous lesson, as the next one needs to see it."""

    lesson: int = 0
    title: str = ""
    taught: list[str] = field(default_factory=list)
    tasks: list[str] = field(default_factory=list)
    ended_on: str = ""
    outcomes: list[str] = field(default_factory=list)
    # Every expression worked by ANY lesson before this one, not only the last.
    # A hand-off that named only the previous lesson's tasks let lesson 5 work
    # what lesson 3 had worked, and the duplicate check then sent it back.
    earlier_tasks: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.title or self.taught or self.tasks)

    def to_dict(self) -> dict[str, Any]:
        return {"lesson": self.lesson, "title": self.title,
                "taught": self.taught, "tasks": self.tasks,
                "ended_on": self.ended_on, "outcomes": self.outcomes,
                "earlier_tasks": self.earlier_tasks}


def read(module: dict[str, Any],
         before: Handoff | None = None) -> Handoff:
    """What the lesson just written leaves behind for the next one.

    `before` is the hand-off this lesson was itself written from; its tasks
    are carried forward so the list of worked expressions grows lesson by
    lesson instead of being replaced.
    """
    from . import task_demand

    if not isinstance(module, dict):
        return Handoff(earlier_tasks=_all_tasks(before))

    segments = [s for s in (module.get("exposition_segments") or [])
                if isinstance(s, dict)]
    taught = [str(s.get("topic") or "").strip()
              for s in segments if str(s.get("topic") or "").strip()]

    tasks: list[str] = []
    for segment in segments:
        for item in task_demand.items_in_prose(str(segment.get("body") or "")):
            expression = item.get("statement") or ""
            if expression and expression not in tasks:
                tasks.append(expression)
    for example in (module.get("worked_examples") or []):
        if isinstance(example, dict):
            found = task_demand.measure_item(example).expression
            if found and found not in tasks:
                tasks.append(found)

    # The last bridge is the sentence the lesson ended on, and it is what the
    # next lesson has to pick up. A guide whose lessons do not join is six
    # lessons about the same sub-strand rather than one sub-strand taught.
    ended = ""
    for segment in reversed(segments):
        bridge = str(segment.get("bridge") or "").strip()
        if bridge:
            ended = bridge
            break

    return Handoff(
        lesson=int(module.get("module_number") or 0),
        title=str(module.get("module_title") or module.get("title") or "").strip(),
        taught=taught[:8],
        tasks=tasks[:8],
        ended_on=ended,
        outcomes=[str(s) for s in (module.get("slos") or [])][:4],
        earlier_tasks=_all_tasks(before),
    )


def _all_tasks(before: Handoff | None) -> list[str]:
    """Everything worked before the lesson `before` describes, plus its own."""
    if before is None:
        return []
    out = list(before.earlier_tasks)
    for task in before.tasks:
        if task not in out:
            out.append(task)
    return out[:40]


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def block(previous: Handoff | None, step: Step | None) -> str:
    """What the next lesson is told, as prompt text."""
    if previous is None and step is None:
        return ""

    from .prompt_store import render

    if previous is None or previous.empty:
        before = ("This is the FIRST lesson of the sub-strand. Nothing has been "
                  "taught yet, so introduce rather than revise.")
    else:
        bits = [f"Lesson {previous.lesson}"
                + (f" — {previous.title}" if previous.title else "")]
        if previous.taught:
            bits.append("  taught: " + "; ".join(previous.taught))
        if previous.tasks:
            bits.append("  worked: " + "; ".join(previous.tasks))
        if previous.ended_on:
            bits.append(f"  ended on: \"{previous.ended_on}\"")
        if previous.earlier_tasks:
            bits.append("Worked by lessons before that (do not work any of "
                        "these again either): "
                        + "; ".join(previous.earlier_tasks))
        before = "\n".join(bits)

    if step is None:
        demand = ""
    elif step.reaches_the_floor:
        demand = (f"Lesson {step.lesson} of {step.of} is past the opening of "
                  f"this sub-strand, so its work must REACH the grade: at "
                  f"least {step.operations} operations of "
                  f"{_plural(step.kinds, 'kind')}, with something bracketed.")
    else:
        demand = (f"Lesson {step.lesson} of {step.of} opens the sub-strand. It "
                  f"may sit below the sub-strand's own floor — at least "
                  f"{step.operations} operations of "
                  f"{_plural(step.kinds, 'kind')} — because a learner meeting "
                  f"this for the first time cannot be handed the hardest form "
                  f"of it. It may NOT be primary-school arithmetic.")

    return render("lesson-handoff", _BLOCK, before=before, demand=demand)


_BLOCK = """=== WHERE THE LAST LESSON LEFT OFF ===
{{ before }}

PICK UP FROM THERE. This lesson is the next one a learner reads, not another lesson about the same sub-strand. Do not re-teach what is listed above, do not re-use the tasks it worked, and do not write the same lesson with different numbers — a lesson that works the same idea on new figures is the same lesson, and it takes the place of the one the design funded.

BUILD ON IT. Where the last lesson established a rule, this one uses it on something harder; where it worked one operation, this one combines it with another.

{{ demand }}"""


def seed_prompts() -> dict[str, str]:
    return {"lesson-handoff": _BLOCK}
