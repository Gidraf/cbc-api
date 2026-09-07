"""Every element a KICD design asks for, numbered once.

`design_coverage` needs a stable name for each thing a design asks for, so it
can say "outcome g9-mat-02 has no question against it". The question generator
needs the SAME names, so it can record which one each question serves.

If those two lists were built in two places they would drift, and the drift
would be silent: a generator recording `experience 3` against a report that
numbered the same experience `experience 4` produces a coverage report where
everything is served and nothing matches. So they are built here, once, and
both sides import this.

WHY REFS AND NOT FREE TEXT. A question that says it serves "the outcome about
integers" cannot be matched against a design that words it differently, which
is exactly the word-overlap matching this replaces. A ref is either in the
design's own numbered list or it is not, and one that is not is a fabrication
worth reporting rather than a near-miss worth accepting.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# The design fields this reads, the kind of element each holds, and the
# dimension `design_coverage` files it under. Order is the order a generator
# sees them in, so it is the order of the design itself.
SOURCES: tuple[tuple[str, str, str], ...] = (
    ("slos", "outcome", "outcomes"),
    ("key_inquiry_questions", "inquiry", "inquiry_questions"),
    ("learning_experiences", "experience", "learning_experiences"),
    ("core_competencies", "competency", "core_competencies"),
    ("values", "value", "values"),
    ("required_diagrams", "diagram", "required_diagrams"),
    ("experiments", "experiment", "experiments"),
)

_TEXT_KEYS = ("slo", "outcome", "text", "name", "title", "description",
              "question", "experience", "value", "competency", "activity_name")


@dataclass(frozen=True, slots=True)
class Element:
    kind: str
    ref: str
    text: str
    dimension: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ref": self.ref, "text": self.text,
                "dimension": self.dimension}


def _listed(row: dict[str, Any], key: str) -> list[Any]:
    value = row.get(key)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return [value] if value.strip() else []
    return value if isinstance(value, list) else []


def _text_of(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in _TEXT_KEYS:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return " ".join(str(v) for v in item.values()
                        if isinstance(v, str) and v.strip()).strip()
    return str(item).strip()


def _ref_for(kind: str, item: Any, index: int) -> str:
    """An outcome keeps the design's own id; everything else is numbered.

    An outcome's id is written in the design and already carried on every
    question, so using it means questions generated before any of this still
    match. Nothing else in a design has an id, so position is the only stable
    name available — which is why the numbering lives in one place.
    """
    if kind == "outcome" and isinstance(item, dict):
        given = str(item.get("slo_id") or item.get("id") or "").strip()
        if given:
            return given
    return f"{kind} {index}"


def enumerate_for(row: dict[str, Any]) -> list[Element]:
    """Every element this sub-strand's design asks for, in the design's order."""
    out: list[Element] = []
    for key, kind, dimension in SOURCES:
        for index, item in enumerate(_listed(row, key), start=1):
            text = _text_of(item)
            if not text:
                continue
            out.append(Element(kind, _ref_for(kind, item, index), text, dimension))
    return out


def refs(row: dict[str, Any]) -> set[str]:
    """The refs a question is allowed to claim to serve."""
    return {e.ref for e in enumerate_for(row)}


def by_dimension(row: dict[str, Any], dimension: str) -> list[Element]:
    return [e for e in enumerate_for(row) if e.dimension == dimension]


# ── what the generator is shown ──────────────────────────────────────────────


def block_for(row: dict[str, Any]) -> str:
    """The numbered list a generator records `serves` against.

    Empty when the design states nothing, so a sub-strand nobody has extracted
    yet asks for no citation rather than inviting an invented one.
    """
    elements = enumerate_for(row)
    if not elements:
        return ""

    from .prompt_store import render

    lines = [f"  [{e.ref}] {e.text}" for e in elements]
    return render("design-elements", _BLOCK, elements="\n".join(lines))


_BLOCK = """=== WHAT THIS DESIGN ASKS FOR, ELEMENT BY ELEMENT ===
Every question you write must record which of these it serves, in a `serves` list of refs, exactly as written in the brackets:
{{ elements }}

RULES FOR `serves`:
  - Use the ref EXACTLY as it appears in brackets. A ref that is not on this list is discarded, and the question then counts as serving nothing.
  - List every element the question genuinely serves, and no others. A question tagged with six refs to look thorough makes six elements read as covered when one was assessed, which is worse than an untagged question — an untagged one is visibly missing, and a wrongly tagged one is invisibly wrong.
  - Where a question serves none of them, return an empty list and say why in `provenance_citation`. That is a real answer; an invented ref is not.
  - A set of questions should between them cover EVERY ref above. An element with no question against it is a promise the design makes and this content does not keep."""


def seed_prompts() -> dict[str, str]:
    return {"design-elements": _BLOCK}


def valid_serves(claimed: Any, row: dict[str, Any]) -> tuple[list[str], list[str]]:
    """The refs a question may keep, and the ones it invented.

    Invented refs are removed rather than kept-and-flagged. A coverage report
    is read as a statement of fact, and one element reading covered because a
    question claimed a ref that does not exist is the single most expensive
    error this whole report could make.
    """
    allowed = refs(row)
    keep, invented = [], []
    for item in (claimed or []):
        ref = str(item).strip()
        if not ref:
            continue
        if ref in allowed:
            if ref not in keep:
                keep.append(ref)
        else:
            invented.append(ref)
    return keep, invented
