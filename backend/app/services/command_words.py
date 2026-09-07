"""What a task ASKS the learner to do, ranked, for subjects with no arithmetic.

`task_demand` measures the shape of an expression. That is the whole story in
Mathematics and no story at all in History, CRE, English or Business Studies,
where a question can be long, well written, correctly cited and still ask for
nothing harder than a list.

What separates a hard question from an easy one in those subjects is its
COMMAND WORD. "List three causes" and "Evaluate the extent to which" can be
asked about the same paragraph of the same design, and one of them is a Grade 4
task and the other a Grade 12 one. The KICD designs are written in these verbs
— the outcomes say "identify", "describe", "analyse", "justify" — and the
assessment rubrics separate performance levels with them, so they are the
curriculum's own measure of demand rather than one imposed on it.

Six rungs, lowest first. The ladder is the FALLBACK: where a sub-strand has a
generated demand profile of its own, that profile's verbs are used instead,
because a design says what it asks for better than a general ladder does. What
the ladder guarantees is that a subject with no profile yet is still measured
rather than waved through.

WHAT THIS DOES NOT DO. It never reports a task as too easy for using an easy
verb — a paper needs its opener and a lesson needs its recall question. It
reports a SET whose hardest verb never leaves the bottom of the ladder, which
is the difference between a revision sheet and a vocabulary quiz.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── the ladder ───────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Rung:
    rank: int
    name: str
    verbs: tuple[str, ...]
    asks_for: str

    def to_dict(self) -> dict[str, Any]:
        return {"rank": self.rank, "name": self.name, "verbs": list(self.verbs),
                "asks_for": self.asks_for}


LADDER: tuple[Rung, ...] = (
    Rung(1, "recall", (
        "name", "state", "list", "identify", "define", "label", "recall",
        "match", "give", "write down", "mention", "who", "when", "where"),
        "something already said, reproduced"),
    Rung(2, "understand", (
        "describe", "explain", "outline", "summarise", "summarize",
        "illustrate", "classify", "interpret", "distinguish", "give reasons",
        "what is meant by", "why"),
        "the idea in the learner's own words"),
    Rung(3, "apply", (
        "calculate", "work out", "solve", "compute", "use", "apply",
        "demonstrate", "construct", "draw", "measure", "plot", "show that",
        "find", "determine", "convert", "complete"),
        "a known procedure carried out on a new case"),
    Rung(4, "analyse", (
        "compare", "contrast", "analyse", "analyze", "examine", "investigate",
        "deduce", "derive", "account for", "relate", "differentiate between",
        "explain why", "predict"),
        "parts separated out and their relationship shown"),
    Rung(5, "evaluate", (
        "evaluate", "justify", "assess", "discuss", "argue", "criticise",
        "criticize", "judge", "to what extent", "comment on", "recommend"),
        "a judgement made and defended against a criterion"),
    Rung(6, "create", (
        "design", "devise", "compose", "plan", "formulate", "propose",
        "create", "develop", "write a", "produce a"),
        "something new the learner assembles for themselves"),
)

# Longest first, so "explain why" is read as rank 4 and not as "explain".
_VERBS: tuple[tuple[str, Rung], ...] = tuple(sorted(
    ((verb, rung) for rung in LADDER for verb in rung.verbs),
    key=lambda pair: -len(pair[0])))

_PATTERNS: tuple[tuple[re.Pattern[str], Rung], ...] = tuple(
    (re.compile(rf"\b{re.escape(verb)}\b", re.I), rung) for verb, rung in _VERBS)

_BY_RANK = {rung.rank: rung for rung in LADDER}

# Recognised so a set is measured correctly, never offered as house style.
_US_SPELLINGS = frozenset({"analyze", "summarize", "criticize"})


def _suggestable(rung: Rung, how_many: int = 4) -> list[str]:
    return [v for v in rung.verbs if v not in _US_SPELLINGS][:how_many]


def rung_of(text: str) -> Rung | None:
    """The command word governing a task, or None where there is no verb.

    The HIGHEST rung present wins rather than the first. A stem reading
    "Describe the process and evaluate its effect" asks for an evaluation; a
    learner who only describes has not answered it, and a marker marking it
    knows that even when the sentence opens with the easier verb.
    """
    found: Rung | None = None
    for pattern, rung in _PATTERNS:
        if pattern.search(text or "") and (found is None or rung.rank > found.rank):
            found = rung
    return found


# ── what a set of tasks asks for ─────────────────────────────────────────────


@dataclass
class Spread:
    """How a set of tasks is distributed across the ladder."""

    by_rank: dict[int, int] = field(default_factory=dict)
    measured: int = 0
    unverbed: int = 0
    top: Rung | None = None
    hardest_stem: str = ""

    @property
    def distinct(self) -> int:
        return len(self.by_rank)

    def to_dict(self) -> dict[str, Any]:
        return {
            "measured": self.measured, "unverbed": self.unverbed,
            "distinct": self.distinct,
            "top": self.top.to_dict() if self.top else None,
            "hardest_stem": self.hardest_stem[:200],
            "by_rank": {str(k): v for k, v in sorted(self.by_rank.items())},
            "by_name": {(_BY_RANK[k].name if k in _BY_RANK else str(k)): v
                        for k, v in sorted(self.by_rank.items())},
        }


def _stem_of(item: dict[str, Any]) -> str:
    for key in ("stem", "question", "statement", "prompt", "task", "instruction",
                "title", "what"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def spread(items: list[Any]) -> Spread:
    """Every task in a set, placed on the ladder."""
    out = Spread()
    for item in (items or []):
        text = _stem_of(item) if isinstance(item, dict) else \
            (item if isinstance(item, str) else "")
        if not text.strip():
            continue
        out.measured += 1
        rung = rung_of(text)
        if rung is None:
            out.unverbed += 1
            continue
        out.by_rank[rung.rank] = out.by_rank.get(rung.rank, 0) + 1
        if out.top is None or rung.rank > out.top.rank:
            out.top = rung
            out.hardest_stem = text
    return out


# ── what each level has to reach ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Floor:
    level: str
    top: int
    distinct: int
    because: str

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "top": self.top, "distinct": self.distinct,
                "top_name": _BY_RANK[self.top].name, "because": self.because}


# Pre-Primary is asked to name, point at and say. That IS the outcome, so it
# has no floor: demanding an evaluation of a four-year-old is the same error as
# demanding brackets of them.
_FLOORS: dict[str, Floor] = {
    "Lower Primary": Floor(
        "Lower Primary", top=2, distinct=1,
        because="the designs' outcomes at this level are 'identify', 'name' "
                "and 'describe', so a set that never asks for a description "
                "has not reached the outcome"),
    "Upper Primary": Floor(
        "Upper Primary", top=3, distinct=2,
        because="the outcomes here apply what was learnt — 'use', 'draw', "
                "'work out' — and a rubric marking application cannot be "
                "answered by a set that only asks learners to name things"),
    "Junior School": Floor(
        "Junior School", top=4, distinct=3,
        because="the designs ask learners to compare, investigate and account "
                "for, and the rubrics' top level is written in those verbs"),
    "Senior School": Floor(
        "Senior School", top=5, distinct=3,
        because="pathway assessment marks judgement — 'evaluate', 'justify', "
                "'discuss' — and a set that never asks for one cannot "
                "discriminate at the top of the mark range"),
}
_FLOORS["Tertiary"] = _FLOORS["Senior School"]


def floor_for(grade: str | None) -> Floor | None:
    from .grade_order import GRADE_SEQUENCE, normalize_grade

    slug = normalize_grade(grade)
    level = next((lv for s, _l, lv in GRADE_SEQUENCE if s == slug), "")
    return _FLOORS.get(level)


@dataclass
class Report:
    level: str = ""
    floor: Floor | None = None
    spread: Spread = field(default_factory=Spread)
    misses: list[str] = field(default_factory=list)

    @property
    def below(self) -> bool:
        return bool(self.misses)

    def says(self) -> str:
        if not self.below:
            return ""
        top = self.spread.top
        reached = f"\"{top.name}\" ({top.verbs[0]})" if top else "no command word at all"
        return (f"Across {self.spread.measured} tasks the hardest thing asked "
                f"for is {reached}. " + "; ".join(self.misses) + ".")

    def fix(self) -> str:
        if not self.floor:
            return ""
        want = _BY_RANK[self.floor.top]
        return (f"{self.level} {self.floor.because}. Ask for {want.asks_for} — "
                f"a verb such as {', '.join(_suggestable(want))} — in at least one "
                f"task, and keep the easier ones as well.")

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "below": self.below,
                "floor": self.floor.to_dict() if self.floor else None,
                "spread": self.spread.to_dict(), "misses": self.misses,
                "says": self.says(), "fix": self.fix()}


def check_set(items: list[Any], grade: str | None,
              required: dict[str, Any] | None = None) -> Report:
    """Whether a set of tasks reaches the demand its level is assessed at.

    `required` is a generated per-sub-strand profile, and overrides the ladder
    where one exists: a design says what it asks for better than a general
    ladder can. It carries `top` and may carry `distinct`.
    """
    floor = floor_for(grade)
    if required:
        top = required.get("top") or required.get("top_rank")
        if isinstance(top, int) and 1 <= top <= 6:
            floor = Floor(
                level=(floor.level if floor else str(required.get("level") or "")),
                top=top,
                distinct=int(required.get("distinct") or (floor.distinct if floor else 1)),
                because=str(required.get("because")
                            or (floor.because if floor else "")))

    report = Report(level=floor.level if floor else "", floor=floor,
                    spread=spread(items))
    if floor is None or not report.spread.measured:
        return report

    reached = report.spread.top.rank if report.spread.top else 0
    if reached < floor.top:
        want = _BY_RANK[floor.top]
        report.misses.append(
            f"nothing in the set reaches \"{want.name}\", which is what this "
            f"level is assessed at")
    # A set of two items cannot spread across three rungs. Reporting that it
    # failed to is reporting arithmetic as a defect, and a gate that does it
    # once is a gate somebody turns off.
    if report.spread.measured >= floor.distinct \
            and report.spread.distinct < floor.distinct:
        report.misses.append(
            f"every task sits on {report.spread.distinct} rung"
            f"{'' if report.spread.distinct == 1 else 's'} of the ladder where "
            f"this level spreads across at least {floor.distinct}")
    return report


def block_for(grade: str | None) -> str:
    """The ladder as prompt text, for the grade being written for.

    Rendered rather than written out, so the words a generator is told to use
    are the same words the gate measures. Two lists that mean to agree and are
    maintained apart do not stay agreeing.
    """
    floor = floor_for(grade)
    if floor is None:
        return ""
    from .prompt_store import render

    lines = [f"  {r.rank}. {r.name.upper()} — {', '.join(_suggestable(r, 6))}"
             f"\n     asks for {r.asks_for}" for r in LADDER]
    want = _BY_RANK[floor.top]
    return render(
        "command-ladder", _LADDER_BLOCK,
        ladder="\n".join(lines),
        top=floor.top, top_name=want.name,
        distinct=floor.distinct,
        rungs="rung" if floor.distinct == 1 else "rungs",
        because=f"{floor.because[0].upper()}{floor.because[1:]}",
    )


# The ladder itself is DATA — the rungs and their verbs are what the gate
# measures, so they are rendered rather than retyped here. What is editable is
# the instruction wrapped around them.
_LADDER_BLOCK = """=== WHAT THE TASK ASKS FOR ===
Every question, activity and experiment is ranked by its command word:
{{ ladder }}

AT THIS LEVEL at least one task must reach rung {{ top }} ({{ top_name }}), and the set must spread across at least {{ distinct }} {{ rungs }}.
{{ because }}.
Keep the easy openers — a set needs them. What is wrong is a set whose HARDEST task never leaves the bottom of the ladder."""


def seed_prompts() -> dict[str, str]:
    return {"command-ladder": _LADDER_BLOCK}
