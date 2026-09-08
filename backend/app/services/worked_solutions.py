"""Worked solutions for a booklet, computed rather than asserted.

An exercise set with no worked solutions is a page a learner cannot revise
from: they can find out that they got it wrong and not why. Asking a model for
the working brings the opposite problem — the working is fluent, it is
sometimes wrong, and nothing checks it.

So the working comes from the deterministic solvers. Where they recognise the
question, every line is computed and every reason is the sign rule that
produced it; where they do not, this returns nothing at all rather than an
invented walkthrough. A booklet with solutions to eight of eleven exercises,
honestly marked, is worth more than one with eleven of eleven and three wrong.
"""
from __future__ import annotations

import re

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-worked-solutions")


@dataclass(slots=True)
class Line:
    """One line of board working."""

    latex: str
    because: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"latex": self.latex, "because": self.because}


@dataclass(slots=True)
class Solution:
    """One exercise, worked."""

    question: str
    solved: bool = False
    statement: str = ""
    lines: list[Line] = field(default_factory=list)
    answer: str = ""
    verified: bool = False
    why_not: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "solved": self.solved,
                "statement": self.statement,
                "lines": [line.to_dict() for line in self.lines],
                "answer": self.answer, "verified": self.verified,
                "why_not": self.why_not}


def solve(question: str) -> Solution:
    """Work one exercise, or say plainly that this engine cannot."""
    text = str(question or "").strip()
    if not text:
        return Solution(question=text, why_not="empty question")

    try:
        from .math_engine import solve_math_problem, verify_solution
    except Exception as exc:  # noqa: BLE001
        logger.warning("Maths engine unavailable: %s", exc)
        return Solution(question=text, why_not="the maths engine is unavailable")

    try:
        trace = solve_math_problem(text)
    except Exception as exc:  # noqa: BLE001
        # A solver raising is not a booklet failure. The exercise simply
        # prints without working, as it did before any of this existed.
        logger.info("Could not work %r: %s", text[:60], exc)
        return Solution(question=text, why_not=f"{type(exc).__name__}: {exc}"[:160])

    if trace.unsolved or not trace.steps:
        return Solution(question=text,
                        why_not=trace.unsolved_reason or "no solver recognised it")

    verified = bool(trace.verified)
    if not verified:
        try:
            verified = bool(verify_solution(trace.problem, trace.final_answer)
                            .get("verified"))
        except Exception:  # noqa: BLE001
            verified = False

    return Solution(
        question=text,
        solved=True,
        statement=trace.problem,
        lines=[Line(latex=step.latex, because=step.explanation)
               for step in trace.steps],
        answer=trace.final_answer,
        verified=verified,
    )


def solve_all(questions: list[str]) -> list[Solution]:
    return [solve(q) for q in questions]


# Units, currency and the dollars the schema itself asks for. The material
# prompt says `"answer": "<the answer, in $…$>"`, so the generator writes `$1$`
# — and comparing `$1$` against the engine's `1` reported EVERY correct answer
# as a disagreement. A key whose right answers are marked wrong is worse than
# no key: the first thing a reader does is stop believing the badge.
_NOT_THE_VALUE = re.compile(
    r"\$|\\[()\[\]]|\\text\s*\{[^}]*\}|\b(?:KES|KSh|Ksh|shillings?|"
    r"marks?|points?|cm|mm|m|km|kg|g|ml|l|°?C|degrees?)\b", re.I)


# A number, a fraction, or a fraction written in LaTeX — nothing else.
_A_VALUE = re.compile(
    r"^\s*-?\s*(?:\\d?frac\s*\{-?\d+(?:\.\d+)?\}\s*\{-?\d+(?:\.\d+)?\}"
    r"|\d+(?:\.\d+)?(?:\s*/\s*-?\d+(?:\.\d+)?)?)\s*$")


def _is_a_value(answer: str) -> bool:
    return bool(_A_VALUE.match(str(answer or "")))


def _comparable(answer: str) -> str:
    """An answer with everything that is not its value taken off."""
    return _NOT_THE_VALUE.sub(" ", str(answer or "")).strip(" .,;:") or str(answer or "")


def check(statement: str, claimed_answer: str) -> dict[str, Any]:
    """Whether an answer somebody else wrote is right.

    Used on the model's own worked examples: a booklet that prints an example
    the engine disagrees with should say so on the page rather than leave a
    learner to imitate it.
    """
    from .math_engine import solve_math_problem, verify_solution

    out: dict[str, Any] = {"checked": False, "agrees": None, "engine_answer": ""}
    if not statement or not claimed_answer:
        return out

    try:
        trace = solve_math_problem(statement)
    except Exception:  # noqa: BLE001
        return out
    if trace.unsolved or not trace.final_answer:
        return out

    # An "answer" that is not a value is not an answer.
    #
    # Handed a statement it could not parse cleanly, the engine returned the
    # fragment `\times 2) \div (-2` and reported it as the final answer — and
    # a checker that trusts that condemns a CORRECT example for disagreeing
    # with nonsense. A false failure on good work is exactly the error that
    # gets a checker switched off, so silence is the safe answer here.
    if not _is_a_value(trace.final_answer):
        return out

    out["checked"] = True
    out["engine_answer"] = trace.final_answer
    try:
        out["agrees"] = bool(
            verify_solution(trace.final_answer,
                            _comparable(claimed_answer)).get("verified"))
    except Exception:  # noqa: BLE001
        out["agrees"] = None
    return out


def rebuild(example: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """A worked example with the ENGINE's working in place of a wrong one.

    Checking the model's arithmetic and then printing it anyway was only ever
    half a fix. A guide came back with one expression worked sixteen times and
    nine of them wrong, and six of those nine were the SAME mistake:

        the term  -(-2) x (-4)  is  -8,
        and the numerator  -5 - 8 + 6  was written  -5 - (-8) + 6

    — the sign counted twice, because the value substituted back already
    carried it. That is a notation trap, not a gap in the model's reasoning,
    and no instruction reliably prevents it: the model is doing arithmetic in
    prose with no way to check itself.

    The engine has no such trouble, and it has been sitting here producing
    exactly this working, step by step with the sign rule named at each line,
    for the EXERCISES. So it writes the examples too. The model keeps the part
    it is good at — the statement, the words, the context — and stops being
    asked to do the part it cannot.

    Returns the example unchanged, and "", when there is nothing to correct.
    """
    statement = str(example.get("statement") or "")
    answer = str(example.get("answer") or "")
    verdict = check(statement, answer)
    if not verdict["checked"] or verdict["agrees"] is not False:
        return example, ""

    solved = solve_all([statement])
    trace = solved[0] if solved else None
    if trace is None or not trace.solved or not trace.verified or not trace.lines:
        return example, ""

    rebuilt = dict(example)
    rebuilt["steps"] = [{"working": line.latex, "because": line.because}
                        for line in trace.lines]
    rebuilt["answer"] = trace.answer
    # Kept, not discarded: a systematic fault that is silently corrected is a
    # systematic fault nobody fixes.
    rebuilt["replaced"] = {"answer": answer, "steps": example.get("steps") or []}
    return rebuilt, (f"the guide answered {answer}; the maths engine works it "
                     f"to {trace.answer}")
