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

    out["checked"] = True
    out["engine_answer"] = trace.final_answer
    try:
        out["agrees"] = bool(
            verify_solution(trace.final_answer, claimed_answer).get("verified"))
    except Exception:  # noqa: BLE001
        out["agrees"] = None
    return out
