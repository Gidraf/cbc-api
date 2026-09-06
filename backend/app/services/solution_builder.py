"""A worked solution for one question, not an answer key.

A marking scheme that says "B" teaches nobody anything, and a teacher marking
thirty scripts with it cannot award part marks. What a scheme has to carry is
the route: what was given, what was done to it, and why that step is allowed.

Three sources, in order of how much they can be trusted:

1. The MATHS ENGINE. Where the question is a calculation the engine can do, it
   is done here rather than by a model — the steps are derived, the answer is
   checked, and the reason attached to each step is the rule that licenses it.
   A model asked for "the working" produces plausible working; this produces
   correct working.
2. What the author already wrote — `marking_scheme`, `model_answer`, the
   per-part answers. Kept verbatim: it was reviewed as part of the item.
3. Nothing. A solution is not invented here to fill a gap; a question with no
   answer is reported as one, because a marking scheme that quietly makes an
   answer up is worse than a blank.

Multiple choice is a special case throughout. The option letter is the answer,
and it is never the whole answer: the scheme names the option AND shows why it
is right — and, where the author gave them, why the others are not.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-solutions")

# What a step is for, so the paper can set it differently: a calculation is set
# as mathematics, a reason is set as prose.
CALCULATION = "calculation"
REASON = "reason"
STATEMENT = "statement"


@dataclass
class Step:
    n: int
    text: str
    kind: str = STATEMENT
    why: str = ""
    marks: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"n": self.n, "text": self.text, "kind": self.kind,
                "why": self.why, "marks": self.marks}


@dataclass
class Solution:
    steps: list[Step] = field(default_factory=list)
    answer: str = ""
    # Which option is correct, and why each of the others is not.
    chosen: str = ""
    distractors: list[dict[str, str]] = field(default_factory=list)
    source: str = "none"          # engine | authored | none
    verified: bool = False        # only the engine can claim this
    note: str = ""

    @property
    def complete(self) -> bool:
        return bool(self.steps or self.answer)

    def to_dict(self) -> dict[str, Any]:
        return {"steps": [s.to_dict() for s in self.steps], "answer": self.answer,
                "chosen": self.chosen, "distractors": self.distractors,
                "source": self.source, "verified": self.verified,
                "note": self.note}


# A line of authored working, split off its own justification. Authors write
# "3 × 4 = 12 (a positive times a positive is positive)" and both halves are
# worth keeping, set differently.
_WHY = re.compile(r"^(?P<did>.+?)\s*[\(—–]\s*(?P<why>[^)]{4,})\)?\s*$")
# "1." / "Step 2:" / "b)" at the head of a line.
_NUMBERED = re.compile(r"^\s*(?:step\s*)?\(?\d+[.)]\s*|^\s*[a-z][.)]\s+", re.I)
_MARKS = re.compile(r"[\(\[]\s*(\d+(?:\.\d+)?)\s*(?:marks?|mks?|m)\s*[\)\]]", re.I)

_LOOKS_LIKE_SUMS = re.compile(r"[0-9]\s*[+\-×x*/÷=]\s*[0-9]|\\frac|\\times|\\div")


def _kind_of(line: str) -> str:
    if _LOOKS_LIKE_SUMS.search(line):
        return CALCULATION
    if re.match(r"^\s*(because|since|as|so that|this is)\b", line, re.I):
        return REASON
    return STATEMENT


def _from_engine(stem: str) -> Solution | None:
    """Solve it properly, if the engine can.

    The engine's dispatcher reads plain text, and questions arrive carrying
    LaTeX — so the stem is flattened first. That conversion is the whole
    reason the engine ever solves anything asked through this path.
    """
    try:
        from .math_engine.latex_input import to_plain
        from .math_engine.solver import solve_math_problem
    except Exception as exc:  # noqa: BLE001
        logger.debug("Maths engine unavailable: %s", exc)
        return None

    try:
        trace = solve_math_problem(to_plain(stem))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Engine declined %r: %s", stem[:60], exc)
        return None

    raw_steps = list(getattr(trace, "steps", None) or [])
    answer = str(getattr(trace, "final_answer", "") or "").strip()
    if not raw_steps or not answer:
        return None

    solution = Solution(answer=answer, source="engine",
                        verified=bool(getattr(trace, "verified", False)))
    for n, step in enumerate(raw_steps, start=1):
        # `SolutionStep` is (step_number, operation, expression_before,
        # expression_after, latex, explanation). The line a learner reads is
        # the rewriting — "-3 + 5 = 2" — and `explanation` is why it is
        # allowed, which is the half a marking scheme is usually missing.
        before = str(getattr(step, "expression_before", "") or "").strip()
        after = str(getattr(step, "expression_after", "") or "").strip()
        latex = str(getattr(step, "latex", "") or "").strip()
        if before and after:
            text = f"{before} = {after}"
        else:
            text = latex or before or after or str(getattr(step, "operation", "") or "")
        why = str(getattr(step, "explanation", "") or "").strip()
        if not text.strip():
            continue
        solution.steps.append(
            Step(n=n, text=text.strip(), kind=CALCULATION, why=why,
                 # The engine derives the route; it does not award marks.
                 marks=0.0))
    if not solution.steps:
        return None
    # An engine that says it could not solve this has not solved it, whatever
    # else it filled in.
    if getattr(trace, "unsolved", False):
        return None
    return solution


def _split_scheme(scheme: str) -> list[str]:
    """One step per line the author intended.

    Schemes are written three ways and a single set mixes them: one step per
    line, steps run together after full stops, and steps terminated by their
    own mark allocation. Splitting on newlines alone turned "Names respiration
    (1 mark). States ATP (1 mark)." into ONE step worth one mark, which loses
    both the second step and half the marks.
    """
    lines: list[str] = []
    for chunk in re.split(r"[\r\n]+", scheme):
        chunk = chunk.strip()
        if not chunk:
            continue
        # A mark allocation ends the step it belongs to, so anything after it
        # on the same line is the next one.
        pieces = [p for p in re.split(r"(?<=[\)\]])\s*[.;]?\s+", chunk)
                  if len(_MARKS.sub("", p).strip()) > 2] if _MARKS.search(chunk) else [chunk]
        for piece in pieces or [chunk]:
            piece = piece.strip(" .;")
            if len(piece) > 2:
                lines.append(piece)
    return lines


def _from_author(question: dict[str, Any]) -> Solution:
    """The scheme the author wrote, split into steps rather than reflowed.

    Kept as written. It was reviewed as part of the item, and rewriting it here
    would put words into a marking scheme that no reviewer has read.
    """
    solution = Solution(source="authored")
    scheme = str(question.get("marking_scheme") or "").strip()
    model = str(question.get("model_answer") or "").strip()

    for n, line in enumerate(_split_scheme(scheme), start=1):
        marks = 0.0
        found = _MARKS.search(line)
        if found:
            marks = float(found.group(1))
            line = _MARKS.sub("", line).strip(" -–—")
        line = _NUMBERED.sub("", line).strip()
        why = ""
        split = _WHY.match(line)
        if split and _LOOKS_LIKE_SUMS.search(split.group("did")):
            line, why = split.group("did").strip(), split.group("why").strip()
        if line:
            solution.steps.append(
                Step(n=n, text=line, kind=_kind_of(line), why=why, marks=marks))

    solution.answer = model or str(question.get("correct_answer") or "").strip()
    if not solution.steps and not solution.answer:
        solution.source = "none"
    return solution


def _multiple_choice(question: dict[str, Any], solution: Solution) -> None:
    """Name the option, and say why the others are not it.

    "B" is the answer and it is never the whole answer. A learner who chose C
    needs to know what C would have been the answer to.
    """
    options = [o for o in (question.get("options") or []) if isinstance(o, dict)]
    if not options:
        return
    correct = str(question.get("correct_answer") or "").strip()

    for option in options:
        oid = str(option.get("id") or "").strip()
        text = str(option.get("text") or "").strip()
        is_right = bool(option.get("is_correct")) or (correct and oid.lower() == correct.lower())
        if is_right:
            solution.chosen = f"{oid}. {text}" if oid else text
            continue
        why = str(option.get("rationale") or option.get("why_wrong")
                  or option.get("feedback") or "").strip()
        if why:
            solution.distractors.append({"option": oid, "text": text, "why": why})

    if not solution.chosen and correct:
        solution.chosen = correct


def build(question: dict[str, Any]) -> Solution:
    """The worked solution for one question."""
    stem = " ".join(str(question.get(k) or "") for k in
                    ("question_text", "stimulus_context")).strip()
    q_type = str(question.get("question_type") or "").strip().lower()

    solution = _from_engine(stem) if stem else None
    if solution is None:
        solution = _from_author(question)
    else:
        # The engine solved it; anything the author wrote about HOW to award
        # marks still belongs on the page beside the derivation.
        authored = _from_author(question)
        if authored.steps and not any(s.marks for s in solution.steps):
            for step in authored.steps:
                if step.marks:
                    solution.steps.append(
                        Step(n=len(solution.steps) + 1, text=step.text,
                             kind=step.kind, why=step.why, marks=step.marks))

    if q_type in ("multiple_choice", "mcq"):
        _multiple_choice(question, solution)
        # The letter is not working. A learner who chose another option is told
        # nothing by "B", so an option standing on its own is reported even
        # though the item technically has an answer on it.
        if solution.chosen and not solution.steps and not solution.distractors:
            solution.note = ("The option is recorded but no working was written "
                             "for it. A learner who chose another option is told "
                             "nothing by this.")

    if not solution.complete:
        solution.source = "none"
        solution.note = solution.note or (
            "This question has no model answer and no marking scheme. It "
            "cannot be marked as it stands.")
    return solution


def build_all(questions: list[dict[str, Any]]) -> list[Solution]:
    return [build(q if isinstance(q, dict) else {}) for q in (questions or [])]
