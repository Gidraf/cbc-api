"""What the notes taught, in the form the stations after them can read.

The questions station was handed the notes as `json.dumps(notes)[:2000]` —
the first two thousand characters of a sixty-thousand-character document,
which is the title, the intro and half of lesson one's citations. The batch
route did better and still read the wrong keys: it looked for
`full_lecture_notes` and `hour_title` on modules that carry
`teacher_exposition` and `title`, so every lesson came through as
"--- Hour 1 ---" followed by nothing. Either way the model wrote questions
from the design alone, and the notes it was supposed to be grounded in
might as well not have existed.

This reads the module shape the planner actually writes and hands each
station the slice it needs:

- questions get every lesson's outcome, what was taught, the worked
  examples (statement and answer, marked as already used), the key
  questions and the misconceptions — so the paper is pitched where the
  lessons were and does not repeat them;
- diagrams get the figures the lessons asked for, lesson by lesson;
- activities get the lesson titles, outcomes and what learners did, so a
  task extends a lesson rather than restating it.

Budgets are in characters and generous: a grade-9 guide is about ten to
fourteen thousand characters of exposition, and the models this runs on
read that comfortably. Cutting it to fit a 2024 context window is how the
last version lost the content.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MAX_CHARS = 16_000
EXPOSITION_PER_LESSON = 2_200
MAX_EXAMPLES_PER_LESSON = 8


@dataclass(slots=True)
class Digest:
    text: str = ""
    lessons: list[str] = field(default_factory=list)
    examples: int = 0
    chars_dropped: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"lessons": len(self.lessons), "examples": self.examples,
                "chars": len(self.text), "chars_dropped": self.chars_dropped}


def modules_of(notes: Any) -> list[dict[str, Any]]:
    """The lessons, under whichever key this guide filed them."""
    if not isinstance(notes, dict):
        return []
    for key in ("modules", "hour_modules", "key_concepts"):
        value = notes.get(key)
        if isinstance(value, list) and value:
            return [m for m in value if isinstance(m, dict)]
    return []


def title_of(module: dict[str, Any], number: int) -> str:
    return str(module.get("title") or module.get("hour_title") or module.get("heading")
               or f"Lesson {number}").strip()


def exposition_of(module: dict[str, Any]) -> str:
    """The taught content, under whichever key this generator wrote it."""
    for key in ("teacher_exposition", "full_lecture_notes", "detailed_exposition", "content"):
        value = module.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    parts = []
    for phase in module.get("lesson_flow") or []:
        if isinstance(phase, dict) and phase.get("what_the_teacher_does"):
            parts.append(str(phase["what_the_teacher_does"]).strip())
    return " ".join(parts)


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # Back to the last sentence end, so the cut reads as an ending.
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    if end > limit * 0.6:
        cut = cut[: end + 1]
    return cut.rstrip() + " […]"


def _examples_of(module: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for example in module.get("worked_examples") or []:
        if not isinstance(example, dict):
            continue
        statement = re.sub(r"\s+", " ", str(example.get("statement") or "")).strip()
        answer = re.sub(r"\s+", " ", str(example.get("answer") or "")).strip()
        if statement:
            out.append((statement, answer))
    return out


def _strings(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("misconception") or item.get("text") or item.get("title") or ""
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        if text:
            out.append(text)
    return out[:limit]


def _heading(number: int, name: str) -> str:
    # The planner titles lessons "Lesson 3: …" already; do not say it twice.
    label = name if re.match(r"^\s*lesson\s+\d+\s*[:\-–—]", name, re.I) else f"Lesson {number}: {name}"
    return f"--- {label} ---"


def for_questions(notes: Any, *, budget: int = MAX_CHARS) -> Digest:
    """Every lesson: outcome, what was taught, what was already worked.

    The budget is shared across lessons, not spent from the front: a guide
    cut at the twelfth lesson would leave the paper testing eleven.
    """
    digest = Digest()
    modules = modules_of(notes)
    if not modules:
        return digest

    head: list[str] = []
    title = str(notes.get("title") or "").strip()
    if title:
        head.append(title)
    intro = _clip(str(notes.get("intro") or notes.get("summary") or ""), 600)
    if intro:
        head.append(intro)

    # The fixed parts first — heading, outcome, examples, questions,
    # misconceptions — so the exposition gets what they leave.
    fixed: list[list[str]] = []
    expositions: list[str] = []
    for number, module in enumerate(modules, start=1):
        name = title_of(module, number)
        digest.lessons.append(name)
        lines = [_heading(number, name)]
        intent = _clip(str(module.get("learning_intent") or ""), 400)
        if intent:
            lines.append(f"Outcome: {intent}")
        tail: list[str] = []
        examples = _examples_of(module)
        if examples:
            tail.append("Already worked in the guide (write NEW tasks at this demand; "
                        "do not set these again):")
            for statement, answer in examples[:MAX_EXAMPLES_PER_LESSON]:
                tail.append(f"  • {_clip(statement, 260)}" + (f"  → {_clip(answer, 80)}" if answer else ""))
            digest.examples += len(examples)
        asked = _strings(module.get("key_questions"), 6)
        if asked:
            tail.append("Key questions asked in class: " + " | ".join(_clip(q, 160) for q in asked))
        wrong = _strings(module.get("common_misconceptions"), 4)
        if wrong:
            tail.append("Misconceptions to test for: " + " | ".join(_clip(w, 160) for w in wrong))
        fixed.append(lines + tail)
        expositions.append(exposition_of(module))

    spent = sum(len(line) + 1 for block in fixed for line in block) + sum(len(h) + 2 for h in head)
    per_lesson = min(EXPOSITION_PER_LESSON, max(200, (budget - spent) // max(1, len(modules)) - 10))

    blocks: list[str] = []
    for lines, exposition in zip(fixed, expositions):
        taught = _clip(exposition, per_lesson)
        body = lines[:2] if len(lines) > 1 and lines[1].startswith("Outcome:") else lines[:1]
        rest = lines[len(body):]
        if taught:
            body = [*body, f"Taught: {taught}"]
        blocks.append("\n".join([*body, *rest]))

    text = "\n\n".join([*head, *blocks]).strip()
    if len(text) > budget:
        digest.chars_dropped = len(text) - budget
        text = text[:budget].rstrip() + " […]"
    digest.text = text
    return digest


def index(notes: Any) -> str:
    """One line per lesson: number, title, outcome. For a slot that wants
    the shape of the guide and not its contents."""
    lines = []
    for number, module in enumerate(modules_of(notes), start=1):
        intent = _clip(str(module.get("learning_intent") or ""), 160)
        lines.append(f"{number}. {title_of(module, number)}" + (f" — {intent}" if intent else ""))
    return "\n".join(lines)


def for_activities(notes: Any, *, budget: int = 8_000) -> str:
    """The lessons as they run: what was taught and what learners did, so an
    activity extends a lesson instead of restating it."""
    blocks: list[str] = []
    modules = modules_of(notes)
    per_lesson = max(400, budget // max(1, len(modules)))
    for number, module in enumerate(modules, start=1):
        lines = [f"--- Lesson {number}: {title_of(module, number)} ---"]
        intent = _clip(str(module.get("learning_intent") or ""), 300)
        if intent:
            lines.append(f"Outcome: {intent}")
        done = [str(p.get("what_learners_do") or "").strip()
                for p in (module.get("lesson_flow") or []) if isinstance(p, dict)]
        done = [d for d in done if d]
        if done:
            lines.append("Learners already did: " + _clip(" ".join(done), per_lesson // 2))
        used = _strings(module.get("learning_experiences_used"), 6)
        if used:
            lines.append("Experiences used: " + "; ".join(used))
        resources = _strings(module.get("resources_needed"), 10)
        if resources:
            lines.append("Resources the teacher has: " + ", ".join(resources))
        taught = _clip(exposition_of(module), per_lesson // 2)
        if taught:
            lines.append(f"Taught: {taught}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)[:budget]


def for_diagrams(notes: Any, *, budget: int = 8_000) -> str:
    """What each lesson asked to be drawn, with the text around it."""
    from . import asset_requirements

    modules = modules_of(notes)
    if not modules:
        return ""
    wanted = asset_requirements.read({"modules": modules}).items
    by_module: dict[int, list[Any]] = {}
    for item in wanted:
        by_module.setdefault(int(item.module_number or 0), []).append(item)

    blocks: list[str] = []
    per_lesson = max(400, budget // max(1, len(modules)))
    for number, module in enumerate(modules, start=1):
        lines = [f"--- Lesson {number}: {title_of(module, number)} ---"]
        intent = _clip(str(module.get("learning_intent") or ""), 240)
        if intent:
            lines.append(f"Outcome: {intent}")
        asks = by_module.get(number) or by_module.get(int(module.get("module_number") or 0)) or []
        if asks:
            lines.append("Figures this lesson asks for:")
            for item in asks:
                where = f" (in: {item.topic})" if getattr(item, "topic", "") else ""
                lines.append(f"  • [{item.kind}] {_clip(item.what, 200)}{where}")
        taught = _clip(exposition_of(module), per_lesson // 2)
        if taught:
            lines.append(f"Taught: {taught}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)[:budget]
