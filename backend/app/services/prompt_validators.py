"""Check a prompt before it is allowed to serve production traffic.

Every prompt carried all five labels, so `production` and `dev` always pointed
at the same version. There was no way to write a prompt, look at it, and only
then let it run — a bad edit was live the instant it was pushed, and the
version history recorded no moment at which anyone could have caught it.

So a push now lands on `latest`, `staging` and `dev`, these checks run, and
only a prompt that passes is promoted to `production` and `prod`. A prompt that
fails stays visible in staging while the previous version keeps serving, which
is the behaviour a failed deploy should have.

The checks are deliberately structural rather than editorial. Whether a prompt
teaches well is what the three review layers are for; whether it will render at
all, name the right variables, and avoid the defects this codebase has already
been bitten by, is decidable here and worth deciding before it runs.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-prompt-validators")

_PLACEHOLDER = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")

# A slot the template opened and never closed, or closed twice: "{{ foo }" and
# "{ foo }}" both render literally into the model's context.
_MALFORMED = re.compile(r"(?<!\{)\{[a-zA-Z_][a-zA-Z0-9_ ]*\}\}|\{\{\s*[a-zA-Z_][a-zA-Z0-9_ ]*\}(?!\})")

# Every authoring prompt must say who it is writing for. Without it the shared
# examples set the register, and a pre-primary sub-strand comes back demanding
# a flowchart from a child who cannot read.
_AUTHORING_AGENTS = frozenset({
    "note-generator", "strand-generator", "substrand-generator",
    "diagram-generator", "media-prompt-generator", "activity-generator",
    "question-generator", "rubric-generator", "simulation-generator",
})

# Agents that read a document rather than authoring from one. They need the
# source, not the register.
_EXTRACTION_AGENTS = frozenset({"curriculum-extractor", "grade-scope-extractor"})

# Subject-specific worked examples shown to every subject. A four-hour TVET
# agriculture module — soil pH titration, lime tonnage, agricultural GDP — was
# the model of what to produce for every grade and learning area, and it
# out-massed the level register by an order of magnitude.
_BLEED = (
    "soil ph", "agricultural lime", "caco3", "agroforestry", "agricultural gdp",
    "embu county", "push-pull technology", "universal soil loss",
    "napier grass", "desmodium",
)

# Values from another country's curriculum. The master context once listed
# "Care and Compassion" and "Understanding and Tolerance" — Australian values,
# not the Kenyan eight.
_KENYAN_VALUES = ("love", "responsibility", "respect", "unity", "peace",
                  "patriotism", "social justice", "integrity")
_FOREIGN_VALUES = ("care and compassion", "understanding and tolerance",
                   "doing your best", "fair go")


@dataclass(slots=True)
class Finding:
    severity: str          # "error" blocks promotion; "warning" does not
    check: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "check": self.check, "message": self.message}


@dataclass(slots=True)
class PromptReport:
    name: str
    findings: list[Finding] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def promotable(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "promotable": self.promotable,
            "variables": self.variables,
            "errors": [f.to_dict() for f in self.errors],
            "warnings": [f.to_dict() for f in self.warnings],
        }


def flat_name(name: str) -> str:
    """The name the CODE knows this prompt by.

    Every prompt is stored under two names — `note-generator` and its foldered
    twin `generate/lesson-plan` — but the bindings, and the list of prompts that
    author rather than extract, are keyed on the flat one. Validating the
    foldered name found no bindings and no authoring rules, so it passed every
    check by not being checked: `generate/lesson-plan` could lose
    {{ level_register }} and be promoted to production clean.
    """
    from .langfuse_context import langfuse_context_service

    if name in {"BECF", "cbc-master-context"}:
        return name
    for flat, foldered in langfuse_context_service.FOLDERS.items():
        if foldered == name:
            return flat
    return name


def _bound_variables(name: str) -> set[str]:
    """Which variables the code actually supplies to this agent.

    A prompt naming a variable nothing binds renders as an empty string, and the
    instruction that depended on it quietly disappears.
    """
    from .prompt_bindings import bindings_for

    return bindings_for(flat_name(name))


def validate(name: str, text: str) -> PromptReport:
    """Everything decidable about a prompt without running it."""
    report = PromptReport(name=name)
    lowered = text.lower()
    variables = sorted(set(_PLACEHOLDER.findall(text)))
    report.variables = variables

    def fail(check: str, message: str) -> None:
        report.findings.append(Finding("error", check, message))

    def warn(check: str, message: str) -> None:
        report.findings.append(Finding("warning", check, message))

    if not text.strip():
        fail("empty", "The prompt is empty.")
        return report

    if len(text) < 200:
        warn("length", f"Only {len(text)} characters — unusually short for an agent prompt.")

    for malformed in set(_MALFORMED.findall(text)):
        fail("malformed_placeholder",
             f"'{malformed}' is an unbalanced placeholder and will render literally "
             "into the model's context.")

    checked_as = flat_name(name)
    bound = _bound_variables(name)
    if bound:
        unbound = [v for v in variables if v not in bound]
        if unbound:
            fail("unbound_variable",
                 f"{', '.join(unbound)} — the prompt asks for {'these' if len(unbound) > 1 else 'this'} "
                 f"but the code never supplies {'them' if len(unbound) > 1 else 'it'}, so "
                 f"{'they' if len(unbound) > 1 else 'it'} will render as nothing and whatever "
                 "depended on it disappears.")
        unused = [v for v in bound if v not in variables]
        if unused:
            warn("unused_binding",
                 f"The code supplies {', '.join(sorted(unused))}, which this prompt "
                 "does not use. Either the prompt lost a slot or the binding is dead.")

    if checked_as in _AUTHORING_AGENTS:
        if "level_register" not in variables:
            fail("missing_register",
                 "An authoring prompt with no {{ level_register }} lets its own examples "
                 "set the register — this is how a pre-primary sub-strand came back "
                 "demanding a flowchart from a child who cannot read.")
        if "faith_scope" not in variables:
            fail("missing_faith_scope",
                 "Without {{ faith_scope }}, CRE, IRE and HRE are authored from one "
                 "undifferentiated pool and content from one faith reaches another.")
        if "master_context" not in variables and "grade" not in variables:
            warn("no_context",
                 "Neither {{ master_context }} nor {{ grade }} appears; the model is "
                 "authoring without knowing which curriculum it serves.")

    _SOURCE_SLOTS = ("source", "document", "raw_text", "text", "excerpt", "chunk")
    if checked_as in _EXTRACTION_AGENTS and not any(
        v.startswith(_SOURCE_SLOTS) for v in variables
    ):
        from .prompt_bindings import raw_fetched

        message = ("An extraction prompt with no source slot reports what it recalls "
                   "rather than what the document says — and reports it as grounded.")
        if checked_as in raw_fetched():
            # Fetched as text and framed by hand-built messages: the document is
            # appended as a message, which is a different shape, not a defect.
            warn("no_source_slot", message + " This one is framed in code instead.")
        else:
            fail("missing_source", message)

    for term in _BLEED:
        if term in lowered:
            fail("subject_bleed",
                 f"'{term}' appears. A worked example from one subject, shown to every "
                 "subject, steers unrelated learning areas toward it.")

    for foreign in _FOREIGN_VALUES:
        if foreign in lowered:
            fail("foreign_values",
                 f"'{foreign}' is not one of the Kenyan national values "
                 f"({', '.join(_KENYAN_VALUES)}).")

    if "json" in lowered and not re.search(r"return only valid json|valid json object|return the json", lowered):
        warn("json_discipline",
             "The prompt mentions JSON but never says to return ONLY JSON, so prose "
             "around the object will break parsing.")

    if re.search(r"\b4 hours\b", lowered) and "lesson" not in lowered:
        fail("hardcoded_hours",
             "'4 hours' is hardcoded. Pre-primary designs allocate lessons of 30 "
             "minutes, and a fabricated figure is indistinguishable afterwards from "
             "one KICD published.")

    return report


def validate_all(prompts: dict[str, str]) -> dict[str, PromptReport]:
    return {name: validate(name, text) for name, text in prompts.items()}
