"""Generate, save, review, revise — and do it again until it passes.

A station generated once, filed the version, ran the local reviewer and the two
local approvers, and returned whatever came out. When the gate said
"needs_revision at 76/100" that verdict went into the payload and no further.
The operator read it later, retyped the findings into the instructions box, and
clicked Generate again — by hand, per sub-strand, across a grade.

The findings are already structured, so the loop can close itself. This runs
the station, reads its gate, hands the gate's own next actions back to the
generator, and runs it again. Every cycle files a version, so nothing is lost
and the progression is on the record: cycle 1 at 76, cycle 2 at 88.

Two things it deliberately does NOT do.

It does not run for ever. Three cycles is the ceiling, and a cycle that fails to
improve on the one before it stops the loop then and there — a model that did
not get better with the findings in front of it will not get better on the third
reading of the same findings, and each pass costs money.

It does not promote. The cycles file versions; a human still approves one. An
automatic loop that also approved its own output would be a review with no
independent party in it, which is the thing the review layers exist to prevent.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("cbc-review-cycle")

# Three passes: the first generation, and two chances to act on findings. A
# fourth has never been the difference between usable and not, and it is a
# third of the bill again.
MAX_CYCLES = max(1, int(os.getenv("REVIEW_CYCLES", "3")))

# How much better a cycle must be to count as an improvement. Two points is
# sampling noise, not progress, and looping on noise is how a job spends an
# afternoon arriving where it started.
MIN_IMPROVEMENT = 3


@dataclass(slots=True)
class Cycle:
    cycle: int
    passed: bool = False
    score: int = 0
    weakest: str = ""
    summary: str = ""
    artifact_id: str = ""
    version: int = 0
    directives_sent: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle, "passed": self.passed, "score": self.score,
            "weakest": self.weakest, "summary": self.summary,
            "artifact_id": self.artifact_id, "version": self.version,
            "directives_sent": self.directives_sent, "error": self.error,
        }


@dataclass(slots=True)
class CycleReport:
    cycles: list[Cycle] = field(default_factory=list)
    stopped_because: str = ""
    best_cycle: int = 0
    best_score: int = 0
    final_passed: bool = False

    @property
    def latest_is_best(self) -> bool:
        return bool(self.cycles) and self.best_cycle == self.cycles[-1].cycle

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycles_run": len(self.cycles),
            "max_cycles": MAX_CYCLES,
            "stopped_because": self.stopped_because,
            "best_cycle": self.best_cycle,
            "best_score": self.best_score,
            "final_passed": self.final_passed,
            "latest_is_best": self.latest_is_best,
            # Said plainly, because the version a reader opens by default is the
            # latest one, and here that is not always the one to use.
            "note": (
                ""
                if self.latest_is_best
                else f"Cycle {self.best_cycle} scored {self.best_score} and the last "
                     f"cycle scored lower. The latest version is NOT the best one — "
                     f"open the versions and pick cycle {self.best_cycle}."
            ),
            "cycles": [c.to_dict() for c in self.cycles],
        }


def _gate_of(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    gate = result.get("quality_gate")
    return gate if isinstance(gate, dict) else {}


def _directives_from(gate: dict[str, Any]) -> list[str]:
    """What to tell the next generation, in the reviewer's own words.

    Paraphrasing the findings here would put a second opinion between the review
    and the fix, and the reviewer's phrasing is the one the next review will
    measure against.
    """
    actions = [str(a) for a in (gate.get("next_actions") or []) if str(a).strip()]
    flags = [
        str(f) for f in ((gate.get("reviewer") or {}).get("risk_flags") or [])
        if str(f).strip()
    ]
    # Hard invariants first: a risk flag blocks release however good the rest is.
    return (flags + actions)[:8]


def _instruction_block(cycle: int, gate: dict[str, Any], directives: list[str]) -> str:
    score = gate.get("overall_score") or 0
    return (
        f"=== REVISION {cycle - 1}: WHAT THE REVIEW FOUND ===\n"
        f"The previous version of this content scored {score}/100 and did not pass "
        f"the quality gate. {gate.get('summary_message') or ''}\n\n"
        f"Fix these, in this order:\n"
        + "\n".join(f"  {i}. {d}" for i, d in enumerate(directives, start=1))
        + "\n\nKEEP WHAT ALREADY PASSED. Rewriting the parts that were right loses "
          "them and makes the change impossible to read against the last version. "
          "Change what is named above and leave the rest as it stands.\n"
    )


def run(
    produce: Callable[[str], dict[str, Any]],
    *,
    label: str = "content",
    max_cycles: int = MAX_CYCLES,
    base_instructions: str = "",
) -> tuple[dict[str, Any], CycleReport]:
    """Run a station until its gate passes, it stops improving, or cycles run out.

    `produce` takes the instructions to generate with and returns the station's
    own result — which has already saved and versioned what it made. Returns the
    last result and the report.
    """
    report = CycleReport()
    result: dict[str, Any] = {}
    instructions = base_instructions
    directives: list[str] = []

    for number in range(1, max(1, max_cycles) + 1):
        cycle = Cycle(cycle=number, directives_sent=list(directives))
        try:
            result = produce(instructions)
        except Exception as exc:  # noqa: BLE001
            cycle.error = f"{type(exc).__name__}: {exc}"
            report.cycles.append(cycle)
            report.stopped_because = "generation_failed"
            logger.error("Review cycle %d for %s failed: %s", number, label, cycle.error)
            if number == 1:
                raise
            break

        gate = _gate_of(result)
        artifact = result.get("artifact") if isinstance(result, dict) else {}
        cycle.passed = bool(gate.get("passed"))
        cycle.score = int(gate.get("overall_score") or 0)
        cycle.summary = str(gate.get("summary_message") or "")
        cycle.artifact_id = str((artifact or {}).get("artifact_id") or "")
        cycle.version = int((artifact or {}).get("version") or 0)
        feedback = (gate.get("reviewer") or {}).get("feedback") or []
        if feedback:
            cycle.weakest = str(feedback[0].get("aspect") or "")
        report.cycles.append(cycle)

        if cycle.score > report.best_score:
            report.best_score = cycle.score
            report.best_cycle = number

        if cycle.passed:
            report.stopped_because = "approved"
            report.final_passed = True
            logger.info("%s passed the gate on cycle %d at %d/100.",
                        label, number, cycle.score)
            break

        if number >= max_cycles:
            report.stopped_because = "max_cycles"
            break

        previous = report.cycles[-2] if len(report.cycles) > 1 else None
        if previous and cycle.score < previous.score + MIN_IMPROVEMENT:
            # It read the findings and did not get better. Reading them a third
            # time will not change that, and the pass costs the same as the one
            # that just failed to help.
            report.stopped_because = "no_improvement"
            logger.info(
                "%s stopped after cycle %d: %d/100 against %d/100 last cycle.",
                label, number, cycle.score, previous.score,
            )
            break

        directives = _directives_from(gate)
        if not directives:
            # It failed the gate and the gate cannot say why. Regenerating with
            # nothing to act on is the same call again at the same price.
            report.stopped_because = "no_actionable_findings"
            break

        instructions = (
            f"{base_instructions}\n\n{_instruction_block(number + 1, gate, directives)}"
        ).strip()

    if not report.stopped_because:
        report.stopped_because = "max_cycles"
    return result, report
