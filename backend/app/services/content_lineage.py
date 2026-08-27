"""What each generation stage is allowed to see, and where its content came from.

The design is only read once, at the top. Strands are extracted from it with
page citations; sub-strands are extracted from the strand and the pages it names;
and from there nothing sends the document again. Each stage takes its parent's
*output* as context and inherits its *citations*, so an hour's notes carry the
design pages they descend from without carrying the design.

That is what keeps the prompts small — notes need a sub-strand, not 140,000
characters of syllabus — and it is what makes the chain auditable: every
artefact can name the pages it ultimately rests on, whatever else it also
draws on.

The layers per stage:

    sub-strands  design pages + strand                          (2)
    notes        strand + sub-strand + skill                    (3)
    diagram      strand + sub-strand + ONE hour's notes + skill (4)
    activity     strand + sub-strand + ONE hour's notes + skill (4)
    questions    strand + sub-strand + notes + assets + skill   (5)

Diagrams take a single hour, not the whole sub-strand's notes: the visual
belongs to that hour, and sending the rest both bloats the prompt and invites
the model to illustrate the wrong lesson.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

logger = logging.getLogger("cbc-content-lineage")

DESIGN = "design"
STRAND = "strand"
SUBSTRAND = "substrand"
HOUR_NOTE = "hour_note"
DIAGRAM = "diagram"
ACTIVITY = "activity"
QUESTION = "question"
# Planning assets across a sub-strand is a different shape from rendering one
# hour's asset: the planner needs every hour to decide what belongs where.
ASSET_PLAN = "asset_plan"

# What each stage may see. Anything not listed is deliberately withheld.
STAGE_LAYERS: dict[str, tuple[str, ...]] = {
    SUBSTRAND: ("design_pages", "strand"),
    HOUR_NOTE: ("strand", "substrand", "skill"),
    DIAGRAM: ("strand", "substrand", "hour_note", "skill"),
    ACTIVITY: ("strand", "substrand", "hour_note", "skill"),
    ASSET_PLAN: ("strand", "substrand", "notes", "skill"),
    QUESTION: ("strand", "substrand", "notes", "assets", "skill"),
}

# A skill changes how content is written; the rest determine what it can be
# about. Generating without an ancestor means inventing whatever it would have
# said, which is the failure mode this pipeline exists to prevent — so a stage
# missing one refuses rather than producing something that reads fine and rests
# on nothing.
OPTIONAL_LAYERS = frozenset({"skill"})


def required_layers(stage: str) -> tuple[str, ...]:
    return tuple(l for l in STAGE_LAYERS.get(stage, ()) if l not in OPTIONAL_LAYERS)


class MissingParentContext(RuntimeError):
    """A stage was asked to generate without an ancestor it depends on."""

    def __init__(self, stage: str, missing: list[str]):
        self.stage = stage
        self.missing = missing
        super().__init__(
            f"Cannot generate {stage}: {', '.join(missing)} "
            f"{'is' if len(missing) == 1 else 'are'} missing. "
            f"{_remedy(stage, missing)}"
        )


def _remedy(stage: str, missing: list[str]) -> str:
    """Say what to do, not just what is wrong."""
    steps = {
        "design_pages": "Ingest the curriculum design and attach its source document.",
        "strand": "Generate the strands for this subject first.",
        "substrand": "Generate the sub-strands for this strand first.",
        "hour_note": "Generate the lesson notes for this sub-strand first — assets belong to an hour.",
        "notes": "Generate the lesson notes for this sub-strand first.",
        "assets": "Generate this sub-strand's diagrams and activities first.",
    }
    return " ".join(steps[m] for m in missing if m in steps)


@dataclass(slots=True)
class Citation:
    """A place in the published design."""
    code: str
    page: int
    line: int
    quote: str = ""

    @property
    def ref(self) -> str:
        return f"{self.code} {self.page}:{self.line}".strip()

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ref": self.ref}


@dataclass(slots=True)
class Artifact:
    """One generated thing, and what it descends from."""
    kind: str
    id: str
    title: str = ""
    content: dict[str, Any] = field(default_factory=dict)
    parents: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    hour: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "id": self.id, "title": self.title,
            "hour": self.hour, "parents": list(self.parents),
            "citations": [c.to_dict() for c in self.citations],
            "content": self.content,
        }


def inherit_citations(parents: Iterable[Artifact]) -> list[Citation]:
    """The design references an artefact inherits from what produced it.

    Deduplicated by address: a sub-strand and its strand often cite the same
    page, and a question descending from both should not list it twice.
    """
    seen: dict[str, Citation] = {}
    for parent in parents:
        for citation in parent.citations:
            seen.setdefault(citation.ref, citation)
    return list(seen.values())


def descend(
    kind: str,
    artifact_id: str,
    parents: list[Artifact],
    *,
    title: str = "",
    content: dict[str, Any] | None = None,
    hour: int | None = None,
    own_citations: list[Citation] | None = None,
) -> Artifact:
    """Create an artefact that carries its parents' provenance forward."""
    citations = inherit_citations(parents)
    for citation in own_citations or []:
        if citation.ref not in {c.ref for c in citations}:
            citations.append(citation)

    if not citations:
        logger.info(
            "%s '%s' has no design citation: nothing in its ancestry cited the "
            "published design, so it cannot be traced back to one.",
            kind, artifact_id,
        )

    return Artifact(
        kind=kind, id=artifact_id, title=title,
        content=content or {}, parents=[p.id for p in parents],
        citations=citations, hour=hour,
    )


def _summarise(artifact: Artifact, limit: int = 1400) -> str:
    body = artifact.content.get("summary") or artifact.content.get("description") or ""
    if not body:
        parts = [f"{k}: {v}" for k, v in artifact.content.items() if isinstance(v, (str, int, float))]
        body = "; ".join(parts)
    return str(body)[:limit]


def build_context(
    stage: str,
    *,
    strand: Artifact | None = None,
    substrand: Artifact | None = None,
    hour_note: Artifact | None = None,
    notes: list[Artifact] | None = None,
    assets: list[Artifact] | None = None,
    skill: Any = None,
    design_pages: str = "",
    strict: bool = True,
) -> dict[str, Any]:
    """Assemble exactly the layers this stage is allowed, and say what was used.

    The manifest matters as much as the context: it records which layers were
    present, which were expected and missing, and how large the result is — so
    a prompt that came out wrong can be diagnosed from its inputs.
    """
    allowed = STAGE_LAYERS.get(stage)
    if allowed is None:
        raise ValueError(f"unknown generation stage '{stage}'")

    available: dict[str, Any] = {
        "design_pages": design_pages,
        "strand": strand,
        "substrand": substrand,
        "hour_note": hour_note,
        "notes": notes or [],
        "assets": assets or [],
        "skill": skill,
    }

    sections: list[str] = []
    used: list[str] = []
    missing: list[str] = []
    ancestors: list[Artifact] = []

    for layer in allowed:
        value = available.get(layer)
        if not value:
            missing.append(layer)
            continue
        used.append(layer)

        if layer == "design_pages":
            sections.append(f"=== CURRICULUM DESIGN (pages {design_pages}) ===")
        elif layer == "skill":
            persona = getattr(value, "persona", "") or ""
            sections.append(f"=== TEACHING SKILL ===\n{persona}")
        elif layer in ("notes", "assets"):
            for item in value:
                ancestors.append(item)
                label = f"{item.kind.upper()}{f' (hour {item.hour})' if item.hour else ''}"
                sections.append(f"=== {label}: {item.title} ===\n{_summarise(item)}")
        else:
            ancestors.append(value)
            label = value.kind.upper() + (f" (hour {value.hour})" if value.hour else "")
            sections.append(f"=== {label}: {value.title} ===\n{_summarise(value)}")

    blocking = [m for m in missing if m not in OPTIONAL_LAYERS]
    if strict and blocking:
        raise MissingParentContext(stage, blocking)

    body = "\n\n".join(sections)
    citations = inherit_citations(ancestors)

    return {
        "stage": stage,
        "context": body,
        "citations": [c.to_dict() for c in citations],
        "manifest": {
            "layers_expected": list(allowed),
            "layers_required": list(required_layers(stage)),
            "layers_used": used,
            "layers_missing": missing,
            "layers_missing_optional": [m for m in missing if m in OPTIONAL_LAYERS],
            "ancestors": [a.id for a in ancestors],
            "chars": len(body),
            "estimated_tokens": len(body) // 4,
        },
    }


def trace_to_design(artifact: Artifact, by_id: dict[str, Artifact]) -> list[dict[str, Any]]:
    """The chain from an artefact back to the design, parent by parent."""
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    frontier = [artifact]

    while frontier:
        current = frontier.pop(0)
        if current.id in seen:
            continue
        seen.add(current.id)
        chain.append({
            "kind": current.kind, "id": current.id, "title": current.title,
            "hour": current.hour,
            "citations": [c.ref for c in current.citations],
        })
        for parent_id in current.parents:
            parent = by_id.get(parent_id)
            if parent:
                frontier.append(parent)
    return chain
