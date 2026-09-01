"""What to do about it, attached to the error that said it went wrong.

An error in this system usually has exactly one sensible next move, and until
now the operator had to know what it was. "MISSING_PARENT_CONTEXT: no approved
lesson plan" means: go to the board, find the grade, find the learning area,
find the lesson plan stage, run it, wait, review it, approve it, come back. Six
navigations to act on one sentence, in a console with fifteen grades and nine
stages — and every one of them is a chance to act on the wrong row.

So an error carries its remedy: the label of the thing to do, and enough to do
it from wherever the error appeared.

Three shapes, because there are three kinds of next move:

*   `run` — queue work that is missing. The common case, and the one worth
    carrying a COUNT: "three stages have to run before this one can" is a
    different decision from "one does", and finding that out one failure at a
    time is how an afternoon goes.
*   `set` — a value is wrong or absent and can be typed. A model id that does
    not exist at the provider is not a workflow problem; it is a text field.
*   `open` — the fix needs judgement, so it takes you to where the judgement is
    made rather than pretending a button can decide it. Approval is the example:
    a person signs, and no error should offer to sign for them.

A remedy is a SUGGESTION with a handle on it, never an automatic action. The
one thing worse than an error with no remedy is an error whose remedy quietly
did something else.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The stages that must be finished before another can start, in order. Read off
# the same chain the board draws, so a remedy cannot propose a route the board
# would not.
CHAIN: tuple[str, ...] = (
    "ingest", "strands", "substrands", "notes", "material",
    "diagram", "media", "simulation", "activity", "questions",
)

LABELS: dict[str, str] = {
    "ingest": "Read the design",
    "strands": "Strands",
    "substrands": "Sub-strands",
    "notes": "Lesson plan",
    "material": "Lesson material",
    "diagram": "Diagrams",
    "media": "Photos & videos",
    "simulation": "Simulations",
    "activity": "Activities & experiments",
    "questions": "Questions",
}


@dataclass(slots=True)
class Remedy:
    """One thing that would move this forward."""

    kind: str                       # run | set | open
    label: str                      # what the button says
    why: str = ""                   # one line: why this is the next move
    stage: str = ""
    grade: str = ""
    subject: str = ""
    # `run` only: how many of these there are, and whether order matters. A
    # remedy that says "3 stages" and runs them at once produces three
    # failures, because each needs the one before it.
    steps: list[dict[str, str]] = field(default_factory=list)
    sequential: bool = True
    # `set` only: which field, where it is set, and what it holds now.
    field_name: str = ""
    current: str = ""
    options: list[str] = field(default_factory=list)
    # `open` only.
    href: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "label": self.label, "why": self.why}
        for name in ("stage", "grade", "subject", "field_name", "current", "href"):
            value = getattr(self, name)
            if value:
                out[name] = value
        if self.steps:
            out["steps"] = self.steps
            out["sequential"] = self.sequential
        if self.options:
            out["options"] = self.options
        return out


def missing_upstream(grade: str, subject: str, stage: str, *, have: set[str] | None = None) -> Remedy:
    """Everything that has to run before `stage` can, in the order it must run.

    Offered as ONE remedy with several steps rather than several remedies: they
    are not alternatives, and presenting them as a list of buttons invites
    pressing the last one — which fails, because it is the one furthest from
    being possible.
    """
    have = have or set()
    try:
        upto = CHAIN.index(stage)
    except ValueError:
        upto = len(CHAIN)
    needed = [s for s in CHAIN[:upto] if s not in have]
    steps = [{"stage": s, "label": LABELS.get(s, s)} for s in needed]
    if len(steps) == 1:
        label = f"Run {steps[0]['label'].lower()}"
        why = f"{LABELS.get(stage, stage)} is built from it, so it has to exist first."
    else:
        label = f"Run the {len(steps)} stages this needs"
        why = (
            "In order — each one is built from the one before it, so running "
            "them together fails all but the first."
        )
    return Remedy(
        kind="run", label=label, why=why,
        grade=grade, subject=subject, stage=stage,
        steps=steps, sequential=True,
    )


def import_the_design(grade: str) -> Remedy:
    """Nothing has been read for this grade, so nothing downstream can exist."""
    return Remedy(
        kind="open",
        label="Import the design",
        why=(
            "The whole chain is built from the KICD design. Until the dataset "
            "is imported and read, every stage below it has nothing to work from."
        ),
        grade=grade,
        href=f"/datasets?grade={grade}",
    )


def set_the_model(stage: str, current: str = "", options: list[str] | None = None) -> Remedy:
    """A model id the provider does not recognise. Not a workflow problem."""
    return Remedy(
        kind="set",
        label="Set the model for this station",
        why=(
            "The station is bound to a model the provider does not have. Any "
            "generation at this station fails identically until it is changed — "
            "retrying will not help."
        ),
        stage=stage,
        field_name="model",
        current=current,
        options=options or [],
    )


def approve_first(grade: str, subject: str, stage: str) -> Remedy:
    """Deliberately `open`, not `run`: a person signs this."""
    return Remedy(
        kind="open",
        label=f"Open the {LABELS.get(stage, stage).lower()} to approve it",
        why=(
            "Approval is a person's decision and stays one — this takes you to "
            "the versions and what each still needs, it does not sign for you."
        ),
        grade=grade, subject=subject, stage=stage,
        href=f"/pipelines?grade={grade}&subject={subject}&stage={stage}",
    )


def run_this_stage(grade: str, subject: str, stage: str) -> Remedy:
    """Nothing is built here yet, and building it is one press."""
    label = LABELS.get(stage, stage)
    return Remedy(
        kind="run", label=f"Run {label.lower()}", grade=grade, subject=subject,
        stage=stage, steps=[{"stage": stage, "label": label}],
        why="Nothing has been built at this stage yet.",
    )


def as_payload(remedies: list[Remedy] | Remedy | None) -> list[dict[str, Any]]:
    if remedies is None:
        return []
    if isinstance(remedies, Remedy):
        remedies = [remedies]
    return [r.to_dict() for r in remedies]
