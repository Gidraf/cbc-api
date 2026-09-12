"""Which outcome and which experience each lesson is for, decided before a word
is written.

Each per-lesson call was told "you are writing lesson 4 of 6" and what lesson
3 had done — and never which outcome lesson 4 was for. The model chose, and
it chose "work out combined operations" three times out of six and "appreciate
the use of integers in real-life situations" never. The cloned worked examples
followed from the cloned topics. The prompt said "deal the design's experiences
out across the lessons FIRST"; the model does not, so this does.

The deal is deterministic: one experience per lesson in the design's own
order, each matched to the outcome it most plainly serves, every outcome
covered at least once, lessons ordered so an outcome is introduced before it
is practised. The same design always deals the same way, so a regenerated
guide is written to the same plan as the one it replaces.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Words that say nothing about WHICH outcome an experience serves. Every
# experience in an Integers sub-strand says "integers"; matching on it would
# tie every experience to every outcome equally.
_EMPTY = frozenset({
    "the", "and", "a", "an", "of", "to", "in", "on", "by", "for", "with",
    "from", "at", "as", "or", "is", "are", "be", "it", "its", "this", "that",
    "their", "them", "they", "will", "can", "using", "use", "used", "all",
    "such", "other", "out", "carry", "work", "different", "various",
    "situations", "situation", "activities", "activity", "learners", "peers",
})


@dataclass(slots=True)
class Brief:
    """What one lesson is for."""

    lesson: int
    outcome_ref: str
    outcome: str
    experience_refs: list[str] = field(default_factory=list)
    experiences: list[str] = field(default_factory=list)
    # 1 of 3, 2 of 3: where this lesson sits among the lessons on its outcome.
    position: int = 1
    of: int = 1

    @property
    def role(self) -> str:
        if self.of <= 1:
            return "the one lesson on this outcome: introduce it and apply it"
        if self.position == 1:
            return "the FIRST lesson on this outcome: introduce it"
        if self.position == self.of:
            return "the LAST lesson on this outcome: apply it at full demand"
        return "a MIDDLE lesson on this outcome: practise it, harder than before"

    def to_dict(self) -> dict[str, Any]:
        return {"lesson": self.lesson, "outcome_ref": self.outcome_ref,
                "outcome": self.outcome, "experience_refs": list(self.experience_refs),
                "experiences": list(self.experiences),
                "position": self.position, "of": self.of}


def _stems(text: str) -> set[str]:
    out: set[str] = set()
    for word in re.findall(r"[a-z]+", str(text or "").lower()):
        if word in _EMPTY or len(word) < 3:
            continue
        for suffix in ("ing", "ies", "ed", "es", "s"):
            if len(word) > len(suffix) + 2 and word.endswith(suffix):
                word = word[: -len(suffix)]
                break
        out.add(word)
    return out


def _affinity(experience: str, outcome: str, common: set[str]) -> float:
    a, b = _stems(experience) - common, _stems(outcome) - common
    if not a or not b:
        return 0.0
    return len(a & b) / len(b)


def deal(row: dict[str, Any], lessons: int) -> list[Brief]:
    """The plan: which outcome and experience(s) each of `lessons` lessons is for."""
    from . import design_elements

    elements = design_elements.enumerate_for(row or {})
    outcomes = [e for e in elements if e.kind == "outcome"]
    experiences = [e for e in elements if e.kind == "experience"]
    if lessons < 1 or not outcomes:
        return []

    # Stems every outcome shares carry no signal about which one is meant.
    counts: dict[str, int] = {}
    for o in outcomes:
        for stem in _stems(o.text):
            counts[stem] = counts.get(stem, 0) + 1
    common = {s for s, n in counts.items() if len(outcomes) >= 2 and n >= len(outcomes)}

    # Each experience to the outcome it most plainly serves. One that matches
    # no outcome at all is left unhomed for now rather than tie-broken onto
    # the first outcome.
    homes: list[tuple[Any, int | None, float]] = []
    for exp in experiences:
        scores = [(_affinity(exp.text, o.text, common), i) for i, o in enumerate(outcomes)]
        best_score, best_i = max(scores, key=lambda s: (s[0], -s[1]))
        homes.append((exp, best_i if best_score > 0 else None, best_score))

    # Every outcome is funded. An outcome nobody's experience matched takes
    # an unhomed experience first, then the homed one with the least to lose
    # — so that "appreciate the use of integers" is somebody's lesson rather
    # than nobody's.
    covered = {i for _e, i, _s in homes if i is not None}
    for i, _o in enumerate(outcomes):
        if i in covered or not homes:
            continue
        unhomed = [k for k, (_e, home, _s) in enumerate(homes) if home is None]
        k = unhomed[0] if unhomed else min(
            range(len(homes)), key=lambda k: (homes[k][2], -k))
        exp, _old, _score = homes[k]
        homes[k] = (exp, i, 0.0)
        covered.add(i)
    # Anything still unhomed practises the first outcome.
    homes = [(exp, 0 if home is None else home, score) for exp, home, score in homes]

    # Lessons follow outcome order, and within an outcome the design's order.
    slots: list[tuple[int, list[Any]]] = []
    for i, _o in enumerate(outcomes):
        mine = [exp for exp, home, _s in homes if home == i]
        if not mine:
            slots.append((i, []))
            continue
        for exp in mine:
            slots.append((i, [exp]))

    # Fit to the funded count: fold the extra experiences into their
    # outcome's last lesson, or split an outcome's lesson to fill a gap.
    while len(slots) > lessons:
        # Fold the last slot whose outcome has more than one lesson.
        by_outcome: dict[int, int] = {}
        for i, _e in slots:
            by_outcome[i] = by_outcome.get(i, 0) + 1
        k = next((k for k in range(len(slots) - 1, -1, -1)
                  if by_outcome[slots[k][0]] > 1), None)
        if k is None:
            break
        i, exps = slots.pop(k)
        j = max(idx for idx, (o, _e) in enumerate(slots) if o == i)
        slots[j] = (i, slots[j][1] + exps)
    while len(slots) < lessons:
        # Another lesson on the outcome with the most experiences to practise.
        by_outcome = {}
        for i, _e in slots:
            by_outcome[i] = by_outcome.get(i, 0) + 1
        i = max(by_outcome, key=lambda o: (by_outcome[o], -o))
        j = max(idx for idx, (o, _e) in enumerate(slots) if o == i)
        slots.insert(j + 1, (i, []))

    briefs: list[Brief] = []
    for n, (i, exps) in enumerate(slots[:lessons], start=1):
        briefs.append(Brief(
            lesson=n, outcome_ref=outcomes[i].ref, outcome=outcomes[i].text,
            experience_refs=[e.ref for e in exps],
            experiences=[e.text for e in exps]))
    for brief in briefs:
        same = [b for b in briefs if b.outcome_ref == brief.outcome_ref]
        brief.of = len(same)
        brief.position = same.index(brief) + 1
    return briefs


def block(brief: Brief | None) -> str:
    """What one lesson's call is told, as prompt text."""
    if brief is None:
        return ""
    from .prompt_store import render

    if brief.experiences:
        via = "\n".join(f"  - {ref}: {text}"
                        for ref, text in zip(brief.experience_refs, brief.experiences))
    else:
        via = ("  (no unused suggested experience is left for this lesson: "
               "practise the outcome on harder material than the lesson before)")
    return render("lesson-brief", _BLOCK,
                  outcome_ref=brief.outcome_ref, outcome=brief.outcome,
                  via=via, role=brief.role)


def plan_text(briefs: list[Brief]) -> str:
    """The whole deal in one block, for a call that writes every lesson."""
    if not briefs:
        return ""
    lines = ["=== THE PLAN: WHAT EACH LESSON IS FOR (fixed — write to it) ==="]
    for b in briefs:
        exps = "; ".join(b.experience_refs) or "practise, harder than the lesson before"
        lines.append(f"  Lesson {b.lesson}: {b.outcome_ref} — {b.outcome} — via {exps} "
                     f"({b.role})")
    return "\n".join(lines)


_BLOCK = """=== WHAT THIS LESSON IS FOR (fixed — not yours to choose) ===
OUTCOME: {{ outcome_ref }} — {{ outcome }}
THROUGH THESE SUGGESTED EXPERIENCES, and no others:
{{ via }}
This lesson is {{ role }}.

The title, the objective, every activity and every worked example are about THIS outcome through THESE experiences. `serves` lists exactly these refs; `slos_covered` names this outcome in the design's words; `learning_experiences_used` names these experiences in the design's words — and the lesson then actually DOES them. A lesson about a different outcome, however good, takes the place of the one the design funded here."""


def seed_prompts() -> dict[str, str]:
    return {"lesson-brief": _BLOCK}
