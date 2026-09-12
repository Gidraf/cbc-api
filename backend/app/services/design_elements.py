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
import re
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


def block_for(row: dict[str, Any], unit: str = "question") -> str:
    """The numbered list a generator records `serves` against.

    Empty when the design states nothing, so a sub-strand nobody has extracted
    yet asks for no citation rather than inviting an invented one.

    `unit` picks the wording. The block was written for questions and only
    ever reached the questions station; the notes station — which writes the
    teacher's guide — was never asked to cite, and so never did. Six guides in
    a row printed "this lesson names no design element" under every lesson,
    and the model had done nothing wrong: nobody had told it.
    """
    elements = enumerate_for(row)
    if not elements:
        return ""

    from .prompt_store import render

    lines = [f"  [{e.ref}] {e.text}" for e in elements]
    if unit == "lesson":
        return render("design-elements-lesson", _LESSON_BLOCK,
                      elements="\n".join(lines))
    return render("design-elements", _BLOCK, elements="\n".join(lines))


_BLOCK = """=== WHAT THIS DESIGN ASKS FOR, ELEMENT BY ELEMENT ===
Every question you write must record which of these it serves, in a `serves` list of refs, exactly as written in the brackets:
{{ elements }}

RULES FOR `serves`:
  - Use the ref EXACTLY as it appears in brackets. A ref that is not on this list is discarded, and the question then counts as serving nothing.
  - List every element the question genuinely serves, and no others. A question tagged with six refs to look thorough makes six elements read as covered when one was assessed, which is worse than an untagged question — an untagged one is visibly missing, and a wrongly tagged one is invisibly wrong.
  - Where a question serves none of them, return an empty list and say why in `provenance_citation`. That is a real answer; an invented ref is not.
  - A set of questions should between them cover EVERY ref above. An element with no question against it is a promise the design makes and this content does not keep."""


_LESSON_BLOCK = """=== WHAT THIS DESIGN ASKS FOR, ELEMENT BY ELEMENT ===
Every lesson you write must record which of these it realises, in a `serves` list of refs on the module, exactly as written in the brackets:
{{ elements }}

RULES FOR `serves`:
  - Use the ref EXACTLY as it appears in brackets. A ref that is not on this list is discarded, and the lesson then counts as serving nothing.
  - A lesson usually realises ONE or TWO outcomes and the experiences and inquiry questions that go with them. List what the lesson genuinely teaches and nothing else: a lesson tagged with every ref to look thorough makes the whole design read as covered by one lesson, and then nobody can see that lessons 4, 5 and 6 taught the same outcome again.
  - The lessons should between them cover EVERY ref above. An outcome with no lesson against it is a promise the design makes that this guide does not keep, and a head of department checking the scheme of work against the design will find it.
  - This is what makes the guide a curriculum document rather than an essay about the subject: each lesson's `serves` is printed on the page as "Where this comes from", in the design's own words, so a teacher challenged on a lesson can open the design and the BECF and point."""


def seed_prompts() -> dict[str, str]:
    return {"design-elements": _BLOCK, "design-elements-lesson": _LESSON_BLOCK}


_BRACKETED = re.compile(r"\[([^\[\]]{1,80})\]")


def harvest_serves(module: dict[str, Any], row: dict[str, Any]) -> list[str]:
    """The design refs a lesson names, wherever it put them.

    The module skeleton's placeholder for `slos_covered` read "the SLO(s) this
    lesson SERVES", so when the design-elements block asked for "which of these
    it serves", the model put the refs there — bracketed, exactly as asked,
    every one of them valid — and the page said the lesson named nothing. A
    lesson that cites correctly in the wrong field has cited.

    Bracketed refs in `slos_covered` are moved into `serves` and removed from
    `slos_covered`, so the header stops reading "[grade-9-Mat-1.1-1] · [inquiry
    1] · perform basic operations…". Only refs the design carries move; a
    bracketed phrase that is not a ref stays where it was.
    """
    if not isinstance(module, dict):
        return []
    known = refs(row)
    found: list[str] = []

    claimed = module.get("serves") or []
    if isinstance(claimed, str):
        claimed = [claimed]
    for item in claimed:
        text = str(item).strip().strip("[]").strip()
        if text and text not in found:
            found.append(text)

    slos = module.get("slos_covered")
    if isinstance(slos, list):
        kept_slos: list[Any] = []
        for entry in slos:
            text = str(entry).strip()
            bracketed = _BRACKETED.findall(text)
            inner = [b.strip() for b in bracketed if b.strip() in known]
            if inner and _BRACKETED.sub("", text).strip(" ·-") == "":
                # The whole entry was refs: it moves, and the entry goes.
                for ref in inner:
                    if ref not in found:
                        found.append(ref)
                continue
            for ref in inner:
                if ref not in found:
                    found.append(ref)
            kept_slos.append(entry)
        if len(kept_slos) != len(slos):
            module["slos_covered"] = kept_slos

    module["serves"] = [r for r in found if r in known]
    return module["serves"]


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


# ── which operations a sub-strand's own design asks for ─────────────────────
#
# The demand floor asks how HARD an expression is and never asks which
# operations it uses. A reviewer found a Grade 9 integers guide in which
# multiplication and division had vanished entirely — every expression across
# six lessons was addition and subtraction of small positives — and the design
# for that sub-strand names all four operations by name.
#
# The floor happens to catch that set, because an expression with no
# multiplication-level operator can never make the order of operations matter.
# But "happens to catch" is not a check. What the design NAMES, the guide has
# to teach, and the design says so in words that can be read.
_OPERATION_WORDS: tuple[tuple[str, str, str], ...] = (
    ("+", "addition", r"add(?:ition|ing|s)?\b|sum\b|plus\b"),
    ("-", "subtraction", r"subtract\w*|minus\b|difference\b|take away"),
    ("×", "multiplication", r"multipl\w+|product\b|times\b"),
    ("÷", "division", r"divi(?:de|sion|ding|sor)\w*|quotient\b|share\w* equally"),
    ("^", "indices", r"indice\w*|index\b|power\w*|squar\w+|cub\w+|exponent\w*"),
    ("√", "roots", r"square root\w*|surd\w*|\broots?\b"),
)


def operations_named(row: dict[str, Any]) -> dict[str, str]:
    """The operations this sub-strand's design asks for, by symbol.

    Read out of the design's own outcomes, experiences and rubric — never
    assumed from the sub-strand's title. A design that names only addition and
    subtraction asks for only those, and demanding a product of it would be
    demanding content the curriculum did not fund.
    """
    text = " ".join(e.text for e in enumerate_for(row))
    for extra in ("sub_strand_name", "strand_name", "pedagogical_guidance"):
        value = row.get(extra)
        if isinstance(value, str):
            text += " " + value
    found: dict[str, str] = {}
    for symbol, name, pattern in _OPERATION_WORDS:
        if re.search(pattern, text, re.I):
            found[symbol] = name
    return found


# A sub-strand about DIRECTED numbers, in the design's own words.
_DIRECTED = re.compile(
    r"\binteger\w*|\bdirected number\w*|\bnegative\w*|\bpositive and negative"
    r"|\bsigned number\w*", re.I)


def wants_negatives(row: dict[str, Any]) -> bool:
    """Whether this sub-strand's own design is about signed numbers.

    The demand floor counts operations, kinds and brackets and never asks
    whether a single number is negative — so `6 + 2 \times (3 - 1)` cleared the
    Grade 9 floor as the peak of a guide on INTEGERS. Three operations, three
    kinds, a bracket, order of operations deciding the answer, and not one
    directed number in it.

    Read from the design rather than from the sub-strand's title, so a
    sub-strand on whole numbers is never asked for a negative it does not
    teach.
    """
    text = " ".join(e.text for e in enumerate_for(row))
    for extra in ("sub_strand_name", "strand_name"):
        value = row.get(extra)
        if isinstance(value, str):
            text += " " + value
    return bool(_DIRECTED.search(text))
