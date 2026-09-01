"""How a subject writes the things it cannot write in words.

A fraction typed as "3/4", an angle as "45 degrees" and an equation as "x
squared plus 2x minus 3 equals 0" all survive the trip through JSON and all
arrive at a Kenyan learner as something they have never seen in a textbook.
Worse, they cannot be marked: "3/4" and "0.75" and "three quarters" are the
same answer written three ways, and a marking scheme that expects one of them
fails the other two.

Mathematics has notation for exactly this reason. So does chemistry, so does
physics. This says which notation a subject uses, in a form a model will
actually follow, and — more importantly — says it the same way to the notes,
the questions and the diagrams, so a fraction written one way in a lesson is
not written another way in the question about it.

GEOMETRY IS DIFFERENT and gets its own block. A triangle described in prose
cannot be drawn twice the same way; a triangle given as three labelled points
and three segments can be drawn identically for ever, measured, and asked
about. The difference between those two is the difference between a diagram
that can carry a question and one that can only decorate a page.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("cbc-notation")

# Subjects that need mathematical notation, matched loosely because a design
# calls it "Mathematical Activities" at PP1 and "Mathematics" at Grade 9.
# Stems, not whole words: a design calls it "Mathematical Activities" at PP1
# and "Mathematics" at Grade 9, and a trailing word boundary matches neither.
_MATHEMATICAL = re.compile(
    r"\b(mathematic|math|algebra|geometr|calculus|statistic|numerac)", re.I)
# "Home Science" is cookery and hygiene, not stoichiometry. Matching it on
# "science" gave it two pages of prompt about balancing equations.
_SCIENTIFIC = re.compile(
    r"\b(physic|chemist|biolog|agricultur|(?<!home )science)", re.I)
# Where a figure has to be constructible rather than described.
_GEOMETRIC = re.compile(
    r"\b(mathematic|math|geometr|technical drawing|physic)", re.I)

LATEX_BLOCK = """=== HOW TO WRITE MATHEMATICS ===
Write every mathematical expression in LaTeX, inline between single dollar
signs and displayed between double: $\\frac{3}{4}$, $$x^2 + 2x - 3 = 0$$.

This is not decoration. "3/4", "0.75" and "three quarters" are the same answer
written three ways, and a marking scheme that expects one of them fails the
other two. One notation is what makes an answer markable.

  fractions        $\\frac{3}{4}$        not 3/4 and not "three quarters"
  powers           $x^2$, $10^{-3}$      not x2, not "x squared"
  roots            $\\sqrt{16}$          not "the square root of 16"
  multiplication   $3 \\times 4$         not 3*4 and not 3x4
  division         $12 \\div 4$          not 12/4 where division is meant
  angles           $45^\\circ$            not "45 degrees"
  units            $12\\ \\text{cm}$      the unit upright, with a space
  ratios           $3 : 4$
  inequalities     $x \\geq 5$
  pi               $\\pi$

PROSE STAYS PROSE. A sentence explaining what a fraction IS should read like a
sentence — put the notation in it where the notation belongs, and nowhere else.
"Cut the orange into $4$ equal parts" is worse than "cut the orange into four
equal parts"; "each part is $\\frac{1}{4}$ of the orange" is right.

AT THIS LEVEL, USE ONLY WHAT THE LEARNER HAS MET. A child counting to ten has
not met a fraction bar, and writing one teaches them nothing. Where the
register above says the learner works with concrete objects, the notation
belongs in the teacher's own notes and not in what the child sees."""

CHEMISTRY_BLOCK = """=== HOW TO WRITE FORMULAE AND EQUATIONS ===
Chemical formulae carry subscripts and charges, and lose their meaning without
them. Write them in LaTeX: $H_2O$, $CO_2$, $SO_4^{2-}$, $Ca(OH)_2$.

Equations balance, and an unbalanced one printed in a guide is taught as
correct:
  $$2H_2 + O_2 \\rightarrow 2H_2O$$
State conditions above the arrow where they matter, and phases after each
species: $(s)$, $(l)$, $(g)$, $(aq)$.

Check every equation balances before you write it. A learner marking their own
work against an unbalanced equation learns that chemistry does not have to."""

PHYSICS_BLOCK = """=== HOW TO WRITE QUANTITIES ===
A number without a unit is not an answer. Write quantities in LaTeX with the
unit upright and spaced: $9.8\\ \\text{m/s}^2$, $12\\ \\text{N}$,
$3.0 \\times 10^8\\ \\text{m/s}$.

Use SI units and the symbols a Kenyan paper uses. Give a formula before you use
it — $v = u + at$ — and say what each symbol is, once, in the lesson that first
needs it."""

GEOMETRY_BLOCK = """=== HOW TO SPECIFY A FIGURE ===
A figure described in prose cannot be drawn twice the same way. "A triangle
with a right angle at B" leaves every length, every position and every label
to whoever draws it — and the question asked about it then does not match the
picture printed beside it.

So give a figure as a CONSTRUCTION, not a description. In the asset's `scene`,
alongside the labelled parts, add `construction`:

  "construction": {
    "kind": "triangle | quadrilateral | circle | angle | line | coordinate_plane | solid",
    "points": [{"name": "A", "x": 0, "y": 0}, {"name": "B", "x": 6, "y": 0},
               {"name": "C", "x": 6, "y": 4}],
    "segments": [{"from": "A", "to": "B", "label": "6 cm"},
                 {"from": "B", "to": "C", "label": "4 cm"},
                 {"from": "C", "to": "A", "label": ""}],
    "angles": [{"at": "B", "between": ["A", "C"], "measure": "90^\\circ",
                "mark": "right"}],
    "labels": [{"at": "A", "text": "A", "position": "below-left"}],
    "units": "cm",
    "not_to_scale": false
  }

Rules that make it constructible:
  - Coordinates in the figure's own units, with the origin bottom-left.
  - Every point named once, in capitals, and every segment referring to those
    names — never to coordinates.
  - State a measurement ONCE. A length written on the segment and again in the
    prose is two places to be wrong.
  - Where a figure is deliberately not to scale, say so with `not_to_scale`
    rather than by drawing it wrongly.
  - Mark what is given and leave what is asked for unmarked. A diagram that
    labels the answer has asked nothing."""


def block_for(subject: str, *, grade: str = "") -> str:
    """The notation rules this subject needs, or nothing.

    Nothing is the right answer for most subjects. A CRE guide with a block
    about balancing equations in it has a page of prompt spent on something it
    will never use, and every irrelevant instruction makes the relevant ones
    harder to find.
    """
    name = subject or ""
    parts: list[str] = []

    if _MATHEMATICAL.search(name):
        parts.append(LATEX_BLOCK)
    if _SCIENTIFIC.search(name):
        if not parts:
            parts.append(LATEX_BLOCK)
        if re.search(r"\b(chemist|integrated science|science)", name, re.I):
            parts.append(CHEMISTRY_BLOCK)
        if re.search(r"\b(physic|integrated science|science)", name, re.I):
            parts.append(PHYSICS_BLOCK)
    return "\n\n".join(parts)


def geometry_block(subject: str) -> str:
    """The construction spec, for subjects whose figures must be drawn exactly."""
    return GEOMETRY_BLOCK if _GEOMETRIC.search(subject or "") else ""


def uses_notation(subject: str) -> bool:
    return bool(block_for(subject))


# ── checking what came back ─────────────────────────────────────────────────

# Mathematics written the way it is spoken rather than the way it is written.
_UNMARKED: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("fraction", re.compile(r"(?<![\\\w$])\b\d+\s*/\s*\d+\b(?![^$]*\$)"),
     "a fraction as digits and a slash"),
    ("power", re.compile(r"\b\w+\s+squared\b|\b\w+\s+cubed\b", re.I),
     "a power written in words"),
    ("degrees", re.compile(r"\b\d+\s*degrees\b", re.I),
     "an angle written in words"),
    ("root", re.compile(r"\bsquare root of\b", re.I),
     "a root written in words"),
    ("times", re.compile(r"(?<![\\\w])\d+\s*[x*]\s*\d+(?![^$]*\$)"),
     "multiplication as x or *"),
)


def unmarked_in(text: str) -> list[dict[str, str]]:
    """Mathematics written as speech rather than as notation.

    Reported, not corrected. "3/4" inside a date, a ratio a teacher deliberately
    reads aloud, and a genuine fraction all look alike from here, and rewriting
    a guide's prose on a regular expression is how a lesson acquires a fraction
    it never had.
    """
    found: list[dict[str, str]] = []
    for name, pattern, why in _UNMARKED:
        match = pattern.search(text or "")
        if match:
            found.append({"kind": name, "example": match.group(0)[:60],
                          "why": why})
    return found


def check(content: Any, subject: str) -> dict[str, Any]:
    """Whether this content writes its mathematics the way its subject does."""
    if not uses_notation(subject):
        return {"checked": False, "reason": f"{subject} does not use notation."}

    import json

    text = json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content
    findings = unmarked_in(text)
    has_latex = bool(re.search(r"\$[^$]{1,200}\$", text))
    return {
        "checked": True,
        "uses_latex": has_latex,
        "findings": findings,
        "clean": has_latex and not findings,
        "score": 100.0 if (has_latex and not findings) else
                 60.0 if has_latex else
                 40.0 if not findings else 20.0,
    }
