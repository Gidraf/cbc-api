"""Check a simulation brief for the things that make it unbuildable or wrong.

Two failures matter here and they are different in kind.

A brief that is too thin is merely unbuildable: "show Newton's second law with a
spring" is a title, and a developer handed it will invent the model, the ranges
and the units. That wastes a build.

A brief whose stated model is absent or hand-waved is worse. A simulation that
is subtly wrong teaches the wrong thing far more convincingly than a wrong
sentence does — the learner watched it happen. So the equation, the constants
and the acceptance criteria are required, and a brief that only describes what
the screen looks like is refused.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-simulation-validators")

CHARS_PER_TOKEN = 4

# Enough to build from without further research.
MIN_BUILD_PROMPT_TOKENS = 800

# The stacks a Kenyan school device can actually run offline.
KNOWN_STACKS = ("css", "vanilla", "javascript", "js", "gsap", "canvas", "three")


@dataclass(slots=True)
class SimFinding:
    severity: str
    simulation: str
    check: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "simulation": self.simulation,
                "check": self.check, "message": self.message}


@dataclass(slots=True)
class SimulationReport:
    count: int = 0
    findings: list[SimFinding] = field(default_factory=list)
    build_tokens: list[int] = field(default_factory=list)

    @property
    def errors(self) -> list[SimFinding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def sound(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "sound": self.sound, "count": self.count,
            "build_tokens": self.build_tokens,
            "errors": [f.to_dict() for f in self.errors],
            "warnings": [f.to_dict() for f in self.findings if f.severity == "warning"],
        }


def check(simulations: list[dict[str, Any]]) -> SimulationReport:
    """Measure each brief for buildability and for a stated, checkable model."""
    report = SimulationReport(count=len(simulations))

    def fail(name: str, check_name: str, message: str) -> None:
        report.findings.append(SimFinding("error", name, check_name, message))

    def warn(name: str, check_name: str, message: str) -> None:
        report.findings.append(SimFinding("warning", name, check_name, message))

    for simulation in simulations:
        name = str(simulation.get("title") or "untitled")

        build = str(simulation.get("build_prompt") or "")
        tokens = len(build) // CHARS_PER_TOKEN
        report.build_tokens.append(tokens)
        if tokens < MIN_BUILD_PROMPT_TOKENS:
            fail(name, "too_short",
                 f"{tokens} tokens; at least {MIN_BUILD_PROMPT_TOKENS} are needed. "
                 "A developer handed less will invent the model, the ranges and the "
                 "units, and the build is wasted.")

        model = simulation.get("concept_model")
        if not isinstance(model, dict) or not str(model.get("explanation") or "").strip():
            fail(name, "no_model",
                 "No concept model. A simulation that is subtly wrong teaches the "
                 "wrong thing more convincingly than a wrong sentence, because the "
                 "learner watched it happen.")
        else:
            if not (model.get("equations") or []):
                fail(name, "no_equations",
                     "No equation stated, so the developer must derive the model "
                     "and a reviewer cannot check it.")
            if not (model.get("assumptions") or []):
                warn(name, "no_assumptions",
                     "Nothing says what is simplified away, so nobody can judge "
                     "whether the simplification matters at this level.")

        controls = simulation.get("learner_controls") or []
        if not controls:
            fail(name, "no_controls",
                 "Nothing for the learner to change. If nothing changes it is a "
                 "diagram, and a diagram costs far less to build.")
        for control in controls:
            if not isinstance(control, dict):
                continue
            label = str(control.get("label") or control.get("parameter") or "?")
            if not str(control.get("range") or "").strip():
                warn(name, "no_range",
                     f"Control '{label}' has no range, so its limits are guesswork.")
            if not str(control.get("unit") or "").strip():
                warn(name, "no_unit", f"Control '{label}' has no unit.")

        if not (simulation.get("acceptance_criteria") or []):
            fail(name, "no_acceptance_criteria",
                 "Nothing states what a correct build produces, so nobody can tell "
                 "a working simulation from a plausible-looking one.")

        if not str(simulation.get("predict_step") or "").strip():
            warn(name, "no_predict_step",
                 "The learner can act before predicting. A simulation that is only "
                 "a toy produces delight and no learning.")

        stack = str((simulation.get("technology") or {}).get("stack") or "").lower()
        if not any(known in stack for known in KNOWN_STACKS):
            warn(name, "unknown_stack",
                 f"Stack '{stack or 'unstated'}' is not one that runs offline in a "
                 "single file on the devices these schools have.")
        elif "three" in stack:
            warn(name, "heavy_stack",
                 "Three.js is heavy and most Kenyan school devices are not. Use it "
                 "only where the concept genuinely needs three dimensions.")

        accessibility = simulation.get("accessibility") or {}
        if not str(accessibility.get("text_alternative") or "").strip():
            warn(name, "no_text_alternative",
                 "A learner who cannot use the simulation has no way to reach the "
                 "same conclusion.")

    if report.errors:
        logger.warning(
            "%d simulation brief(s) are not buildable: %s", len(report.errors),
            "; ".join(f"{f.simulation}: {f.check}" for f in report.errors[:4]),
        )
    return report
