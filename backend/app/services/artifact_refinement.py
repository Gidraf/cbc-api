"""Review, fix, review again — until it is actually good, or until it stops.

A layer-2 review came back "pass at 83%" with four open issues: two lessons
that were the same lesson, a PCI never addressed, a nature walk that does not
fit the time, an abstraction a four-year-old cannot hold. Every one of them was
correct, specific and actionable. Nothing acted on any of them.

The pipeline had all the parts. `revision_directives` turns findings into
instructions; `regenerate_artifact` writes the next version from them; the
reviewer reads the diff. All three waited for somebody to press a button, and
"pass" made pressing it look unnecessary.

Two different bars were being confused. `decide()` returns "pass" at 80 overall
with no dimension under 70 — the bar for "this is not broken". That is the
right bar for a gate. It is the wrong bar for "stop working on it", and using
one number for both is why an 83 with four findings read as finished.

So the target is separate and higher, and the loop runs itself.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("cbc-artifact-refinement")

# What "good enough to stop" means, as distinct from "not broken". Both are
# needed: an average of 92 hiding a 60 is not a finished artifact.
TARGET_OVERALL = 90
TARGET_DIMENSION = 85

# Severities that keep the loop running however high the score. A HIGH finding
# beside a 94 is a 94 with something seriously wrong in it.
BLOCKING_SEVERITIES = ("high", "medium")

MAX_CYCLES = 3

# How much a cycle must gain to be worth another. Below this the model has read
# the findings and not acted on them, and reading them a third time costs the
# same as the pass that just failed to help.
MIN_GAIN = 3


@dataclass(slots=True)
class Cycle:
    number: int
    artifact_id: str = ""
    version: int = 0
    overall: int = 0
    weakest: str = ""
    weakest_score: int = 0
    verdict: str = ""
    open_issues: list[dict[str, Any]] = field(default_factory=list)
    regenerated_to: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.number, "artifact_id": self.artifact_id,
            "version": self.version, "overall": self.overall,
            "weakest": self.weakest, "weakest_score": self.weakest_score,
            "verdict": self.verdict,
            "open_issues": self.open_issues,
            "regenerated_to": self.regenerated_to, "error": self.error,
        }


@dataclass(slots=True)
class RefinementReport:
    started_from: str = ""
    best_artifact_id: str = ""
    best_overall: int = 0
    cycles: list[Cycle] = field(default_factory=list)
    stopped_because: str = ""
    met_target: bool = False
    target_overall: int = TARGET_OVERALL
    target_dimension: int = TARGET_DIMENSION

    @property
    def outstanding(self) -> list[dict[str, Any]]:
        return self.cycles[-1].open_issues if self.cycles else []

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_from": self.started_from,
            "best_artifact_id": self.best_artifact_id,
            "best_overall": self.best_overall,
            "met_target": self.met_target,
            "stopped_because": self.stopped_because,
            "target": {"overall": self.target_overall,
                       "dimension": self.target_dimension},
            "cycles_run": len(self.cycles),
            "outstanding": self.outstanding,
            "cycles": [c.to_dict() for c in self.cycles],
        }


def _dimensions(verdict: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = verdict.get("dimensions")
    if isinstance(raw, str):
        import json
        try:
            raw = json.loads(raw)
        except Exception:  # noqa: BLE001
            raw = {}
    return raw if isinstance(raw, dict) else {}


def weakest_of(verdict: dict[str, Any]) -> tuple[str, int]:
    """The dimension holding this review back, and its score."""
    scored = [
        (int(d.get("score") or 0), str(d.get("name") or name))
        for name, d in _dimensions(verdict).items()
        if isinstance(d, dict) and not d.get("not_applicable")
    ]
    if not scored:
        return "", 0
    score, name = min(scored)
    return name, score


def open_issues(verdict: dict[str, Any]) -> list[dict[str, Any]]:
    """Findings serious enough to keep working on."""
    return [
        i for i in (verdict.get("issues") or [])
        if isinstance(i, dict)
        and str(i.get("severity") or "").lower() in BLOCKING_SEVERITIES
    ]


def meets_target(verdict: dict[str, Any], *, overall_target: int = TARGET_OVERALL,
                 dimension_target: int = TARGET_DIMENSION) -> bool:
    """Whether this is finished, as opposed to merely not broken.

    All three conditions, because each hides a different failure: an average
    clears while one dimension is poor; every dimension clears while a HIGH
    issue stands; and a model that reports no dimensions at all would otherwise
    pass by having said nothing.
    """
    dimensions = _dimensions(verdict)
    if not dimensions:
        return False
    if int(verdict.get("overall_confidence") or 0) < overall_target:
        return False
    _, weakest = weakest_of(verdict)
    if weakest < dimension_target:
        return False
    return not open_issues(verdict)


def _why(verdict: dict[str, Any], *, overall_target: int,
         dimension_target: int) -> str:
    """What is still short, in the words an operator would use."""
    overall = int(verdict.get("overall_confidence") or 0)
    name, score = weakest_of(verdict)
    issues = open_issues(verdict)

    short: list[str] = []
    if overall < overall_target:
        short.append(f"{overall}/100 against a target of {overall_target}")
    if score < dimension_target:
        short.append(f"{name.replace('_', ' ')} at {score} against "
                     f"{dimension_target}")
    if issues:
        worst = issues[0]
        short.append(
            f"{len(issues)} open finding(s), the first being "
            f"[{worst.get('severity')}] {str(worst.get('what'))[:100]}"
        )
    return "; ".join(short) or "nothing outstanding"


def run(
    artifact_id: str,
    *,
    review: Callable[[str], dict[str, Any]],
    regenerate: Callable[[str], str],
    overall_target: int = TARGET_OVERALL,
    dimension_target: int = TARGET_DIMENSION,
    max_cycles: int = MAX_CYCLES,
    step: Callable[[str, str, str], None] | None = None,
) -> RefinementReport:
    """Review, regenerate from the findings, review again. Bounded.

    `review` returns the verdict for one version; `regenerate` writes the next
    version from that version's findings and returns its id. Both are passed in
    so this can be tested without a model and without a database.
    """
    def say(name: str, detail: str = "", status: str = "ok") -> None:
        if step:
            step(name, detail, status)

    report = RefinementReport(
        started_from=artifact_id, best_artifact_id=artifact_id,
        target_overall=overall_target, target_dimension=dimension_target,
    )
    current = artifact_id

    for number in range(1, max(1, max_cycles) + 1):
        cycle = Cycle(number=number, artifact_id=current)
        try:
            verdict = review(current) or {}
        except Exception as exc:  # noqa: BLE001
            cycle.error = f"{type(exc).__name__}: {exc}"
            report.cycles.append(cycle)
            report.stopped_because = "review_failed"
            say(f"Review {number}", cycle.error, "fail")
            break

        cycle.version = int(verdict.get("version") or 0)
        cycle.overall = int(verdict.get("overall_confidence") or 0)
        cycle.verdict = str(verdict.get("verdict") or "")
        cycle.weakest, cycle.weakest_score = weakest_of(verdict)
        cycle.open_issues = open_issues(verdict)
        report.cycles.append(cycle)

        if cycle.overall > report.best_overall:
            report.best_overall = cycle.overall
            report.best_artifact_id = current

        if meets_target(verdict, overall_target=overall_target,
                        dimension_target=dimension_target):
            report.met_target = True
            report.stopped_because = "met_target"
            say(f"Review {number}",
                f"{cycle.overall}/100, weakest {cycle.weakest} at "
                f"{cycle.weakest_score}, nothing outstanding — target met")
            break

        reason = _why(verdict, overall_target=overall_target,
                      dimension_target=dimension_target)
        say(f"Review {number}", f"{reason}", "warn")

        if number >= max_cycles:
            report.stopped_because = "max_cycles"
            break

        # A gain this small means it read the findings and did not act on them.
        if len(report.cycles) > 1:
            previous = report.cycles[-2]
            if cycle.overall < previous.overall + MIN_GAIN:
                report.stopped_because = "no_improvement"
                say(f"Stopped after {number}",
                    f"{previous.overall}/100 → {cycle.overall}/100; the "
                    f"findings were sent and did not move it", "warn")
                break

        try:
            nxt = regenerate(current)
        except Exception as exc:  # noqa: BLE001
            cycle.error = f"{type(exc).__name__}: {exc}"
            report.stopped_because = "regeneration_failed"
            say(f"Regenerate {number}", cycle.error, "fail")
            break
        if not nxt or nxt == current:
            report.stopped_because = "no_new_version"
            say(f"Regenerate {number}", "no new version was filed", "warn")
            break

        cycle.regenerated_to = nxt
        say(f"Regenerate {number}",
            f"filed a new version from {len(cycle.open_issues)} finding(s)")
        current = nxt

    if not report.stopped_because:
        report.stopped_because = "max_cycles"

    last = report.cycles[-1] if report.cycles else None
    say("Refinement finished",
        f"{len(report.cycles)} cycle(s), best {report.best_overall}/100"
        + (" — target met" if report.met_target
           else f" — {len(last.open_issues) if last else 0} finding(s) stand "
                f"({report.stopped_because})"),
        "ok" if report.met_target else "warn")
    return report
