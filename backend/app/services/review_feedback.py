"""A reviewer's own words, and what has to be rebuilt because of them.

A model reviewer scores dimensions. A person reads the thing and knows why it
is wrong: "the worked example uses litres where the design says millilitres",
"lesson 4 teaches a parable the design does not carry". Until now that had
nowhere to go except a conversation, so a systematic fault had to be described
to whoever runs the console rather than to the pipeline.

Two halves, and the second is the one that matters:

1. The comment is filed against the version, where the next approver reads it.
2. Everything BUILT FROM that version is marked stale — because a lesson plan
   that was wrong did not only produce a wrong plan. It produced the material
   said aloud from it, the diagrams drawn against it, the activities, the
   experiments and the questions written from all of those. Regenerating the
   plan and leaving them alone is how a sub-strand ends up internally
   inconsistent in a way nobody can see from any single screen.

Staleness is recorded, never enforced by deletion. The old version is what a
teacher may already be holding, and throwing it away because its parent changed
would take content out of circulation on a guess.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-review-feedback")

# What is built from a lesson plan, in the order the board runs them. Taken
# from `review_layers.DRAWN_FROM_PLAN` plus the questions written from all of
# it — a question is downstream of everything.
from .review_layers import DRAWN_FROM_PLAN

DOWNSTREAM_OF_PLAN: tuple[str, ...] = tuple(DRAWN_FROM_PLAN) + ("question",)

# The material is said aloud from the plan; assets illustrate the plan, not the
# material. So a comment on the MATERIAL invalidates less than one on the plan.
DOWNSTREAM_OF_MATERIAL: tuple[str, ...] = ("question",)

DOWNSTREAM: dict[str, tuple[str, ...]] = {
    "notes": DOWNSTREAM_OF_PLAN,
    "material": DOWNSTREAM_OF_MATERIAL,
    "diagram": ("question",),
    "activity": ("question",),
    "experiment": ("question",),
    "simulation": ("question",),
}

# What a comment is asking for. A reviewer saying "this is wrong" and a
# reviewer saying "this is thin" want different things from a regeneration.
REWRITE = "rewrite"        # regenerate this version from its own parents
AMEND = "amend"            # keep it, fix what the comment names
NOTE_ONLY = "note"         # recorded, nothing to rebuild


@dataclass
class Stale:
    artifact_id: str
    kind: str
    version: int
    sub_strand: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"artifact_id": self.artifact_id, "kind": self.kind,
                "version": self.version, "sub_strand": self.sub_strand}


@dataclass
class Feedback:
    artifact_id: str = ""
    kind: str = ""
    action: str = NOTE_ONLY
    body: str = ""
    author: str = ""
    stale: list[Stale] = field(default_factory=list)
    comment: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"artifact_id": self.artifact_id, "kind": self.kind,
                "action": self.action, "author": self.author,
                "stale": [s.to_dict() for s in self.stale],
                "stale_count": len(self.stale),
                "comment": self.comment,
                "says": self.summary()}

    def summary(self) -> str:
        if self.action == NOTE_ONLY:
            return "Recorded against this version. Nothing was marked for rebuilding."
        if not self.stale:
            return (f"Recorded, and this {self.kind} is marked for a "
                    f"{self.action}. Nothing downstream was built from it yet.")
        kinds: dict[str, int] = {}
        for item in self.stale:
            kinds[item.kind] = kinds.get(item.kind, 0) + 1
        listed = ", ".join(f"{n} {kind}" for kind, n in sorted(kinds.items()))
        return (f"Recorded, and this {self.kind} is marked for a {self.action}. "
                f"{len(self.stale)} version(s) built from it are now stale: "
                f"{listed}. They are marked, not deleted — the old copy may be "
                f"in a classroom already.")


def downstream_kinds(kind: str) -> tuple[str, ...]:
    """What has to be rebuilt when this kind is regenerated.

    A comment on the MATERIAL does not invalidate the diagrams: they illustrate
    the plan, not the words said aloud from it. Getting this wrong in the
    generous direction marks a sub-strand's whole output stale over a typo.
    """
    return DOWNSTREAM.get(str(kind or "").lower(), ())


def find_stale(artifact: Any, kinds: tuple[str, ...]) -> list[Stale]:
    """Versions built from this one, by scope rather than by parent id.

    Parent ids only link a regeneration to the version it replaced; a diagram
    drawn against lesson plan v2 carries no pointer to it. What they share is
    the sub-strand, which is the unit the whole board works in.
    """
    if not kinds:
        return []
    from . import artifact_registry

    out: list[Stale] = []
    for kind in kinds:
        try:
            rows = artifact_registry.search(
                grade=getattr(artifact, "grade", ""),
                subject=getattr(artifact, "subject", ""),
                sub_strand=getattr(artifact, "sub_strand_name", ""),
                kind=kind) or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not look for %s built from %s: %s",
                           kind, getattr(artifact, "artifact_id", ""), exc)
            continue
        for row in rows:
            artifact_id = str(row.get("artifact_id") or "")
            if not artifact_id or artifact_id == getattr(artifact, "artifact_id", ""):
                continue
            out.append(Stale(
                artifact_id=artifact_id, kind=kind,
                version=int(row.get("version") or 0),
                sub_strand=str(row.get("sub_strand_name") or "")))
    return out


def _mark(item: Stale, because: str, by: str) -> bool:
    """Say on the stale version itself why it is stale.

    Recorded as a comment rather than a status flag: a person opening that
    version needs the reviewer's actual words, not a boolean.
    """
    from . import artifact_registry

    try:
        artifact_registry.add_comment(
            item.artifact_id,
            f"Marked stale. The {because} this was built from was sent back by "
            f"a reviewer, so this version rests on a parent that is being "
            f"changed. Regenerate it after the {because} is remade.",
            author=by, dimension="stale")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not mark %s stale: %s", item.artifact_id, exc)
        return False


def submit(artifact_id: str, body: str, *, action: str = REWRITE,
           author: str = "") -> Feedback:
    """File a reviewer's note, and mark what it invalidates.

    Never deletes and never regenerates on its own. Regeneration costs money
    and takes a station out of service; what to rebuild and when is a decision,
    and this makes the decision visible rather than making it.
    """
    from ..errors import raise_api_error
    from . import artifact_registry

    if not str(body or "").strip():
        raise_api_error("VALIDATION_FAILED",
                        "A reviewer's note needs a body. What is wrong with it?")
    if action not in (REWRITE, AMEND, NOTE_ONLY):
        raise_api_error("VALIDATION_FAILED",
                        f"'{action}' is not an action. Known: {REWRITE}, "
                        f"{AMEND}, {NOTE_ONLY}.")

    artifact = artifact_registry.get(artifact_id)
    kind = str(getattr(artifact, "kind", ""))

    comment = artifact_registry.add_comment(
        artifact_id, body, author=author,
        dimension="reviewer" if action == NOTE_ONLY else f"reviewer:{action}")

    feedback = Feedback(artifact_id=artifact_id, kind=kind, action=action,
                        body=body, author=author, comment=comment)

    if action == NOTE_ONLY:
        return feedback

    feedback.stale = [s for s in find_stale(artifact, downstream_kinds(kind))
                      if _mark(s, kind, author)]
    return feedback


def directives_for(artifact_id: str) -> list[str]:
    """The reviewer notes a regeneration of this version must answer.

    A regeneration that does not read them repeats the fault the reviewer
    described, and the next reviewer writes the same note again.
    """
    from . import artifact_registry

    try:
        artifact = artifact_registry.get(artifact_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("No artifact %s to read notes from: %s", artifact_id, exc)
        return []

    out: list[str] = []
    for comment in (getattr(artifact, "comments", None) or []):
        if not isinstance(comment, dict):
            continue
        dimension = str(comment.get("dimension") or "")
        if not dimension.startswith("reviewer"):
            continue
        body = str(comment.get("body") or comment.get("comment") or "").strip()
        if body:
            out.append(body)
    return out


def as_instruction(notes: list[str]) -> str:
    """The notes, as something a generation prompt can carry."""
    if not notes:
        return ""
    lines = [
        "=== WHAT A REVIEWER SENT THIS BACK FOR ===",
        "A person read the previous version and wrote these. They are not "
        "suggestions: the version was rejected for them, and a regeneration "
        "that does not answer them will be rejected again.",
        "",
    ]
    lines += [f"  {i}. {note}" for i, note in enumerate(notes, start=1)]
    lines += ["", "Fix each one. Keep everything the reviewer did not object to."]
    return "\n".join(lines)
