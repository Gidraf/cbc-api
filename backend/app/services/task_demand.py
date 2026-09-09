"""How much a task actually DEMANDS, measured, against what the grade requires.

`example_check` catches a worked example whose words and arithmetic disagree.
This catches the other half of the same complaint: arithmetic that is perfectly
correct, perfectly described, and years below the grade it is printed for.

A reviewer put it plainly — a Grade 9 integers guide whose hardest line was
`7 - 4 = 3`. Nothing in it is wrong. A parent still closes the booklet, because
what Grade 9 is actually assessed on looks like this:

    Evaluate without using a calculator:

        (-15 ÷ 3 - (-2) × (-4) + 6) / (-2 × 3 + (-4))

That expression is not harder because the numbers are bigger. It is harder
because of its SHAPE: four different operations, so the order of operations
decides the answer; brackets, so precedence has to be read rather than assumed;
negatives multiplied together, which is the sign rule the grade is examined on;
and a fraction bar, which is a bracket the learner has to supply themselves.

Those are countable. So instead of asking a model to "make it challenging" — an
instruction with no failure condition — this measures the shape and states the
floor as numbers:

    operations, distinct kinds of operation, bracket depth, negative
    operands, and whether the order of operations changes the answer.

WHAT THIS DELIBERATELY DOES NOT DO. It never flags an item that contains no
expression. A comprehension question, a map exercise and a singing lesson are
measured as zero and compared against nothing, which is why a floor written for
Mathematics does not fail Creative Arts. And an item whose hardest single line
is modest still passes when the item as a WHOLE is several steps of real work —
a multi-step word problem is demanding in a way one line never shows. A check
that fails honest work gets switched off, and then it catches nothing at all.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── Reading an expression out of text ────────────────────────────────────────

# LaTeX is the house notation, so most real expressions arrive inside $...$.
_MATH_SPAN = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.S)

_SIMPLE_LATEX: tuple[tuple[str, str], ...] = (
    (r"\\left|\\right", ""),
    (r"\\times|\\cdot|\\ast", "×"),
    (r"\\div", "÷"),
    (r"\\pm|\\mp", "±"),
    (r"\\sqrt", "√"),
    (r"\\[,;:!]", ""),
    (r"\\quad|\\qquad", " "),
    (r"\\displaystyle|\\limits", " "),
)

# A unit or a word inside an expression is not an operand.
_TEXT_CMD = re.compile(r"\\(?:text|mathrm|mbox|operatorname)\s*\{[^{}]*\}")


def _braced(source: str, start: int) -> tuple[str, int]:
    """The content of the {...} beginning at `start`, and where it ends."""
    if start >= len(source) or source[start] != "{":
        return "", start
    depth, i = 0, start
    while i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1:i], i + 1
        i += 1
    return source[start + 1:], len(source)


_FRAC_ALIAS = re.compile(r"\\dfrac|\\tfrac")


def _expand_fractions(source: str) -> tuple[str, bool]:
    r"""`\frac{A}{B}` as `((A)÷(B))`, and whether any was a real fraction bar.

    The bar is a bracket the learner has to supply for themselves, which is
    exactly why it belongs in the measurement — but only when there is
    something to bracket. `\frac{1}{2}` is the number a half.
    """
    source = _FRAC_ALIAS.sub("\\\\frac", source)
    out, i, compound = [], 0, False
    while True:
        at = source.find("\\frac", i)
        if at < 0:
            out.append(source[i:])
            break
        out.append(source[i:at])
        top, after = _braced(source, at + len("\\frac"))
        bottom, after = _braced(source, after)
        if _OPERATOR.search(top) or _OPERATOR.search(bottom):
            compound = True
        out.append(f"(({top})÷({bottom}))")
        i = after
    return "".join(out), compound


_OPERATOR = re.compile(r"[+×÷^√±]|(?<=[\d)])\s*-")

_OPS = set("+-×÷^√±*/")
_NORMALISE = {"*": "×", "/": "÷", "±": "+"}

# A span is a run of tokens that are all numbers, operators, brackets or single
# letters. A unit ("kg") or a word ("and") is none of those, so it ends the
# span — which loses "5 kg + 3 kg" and gains never reading prose as algebra.
# A WORD is matched whole. Matching one letter at a time and then asking
# whether the token happened to be a single letter admitted "Work out 7 - 4"
# as seven variables multiplied together, and every prose statement with it.
_TOKEN = re.compile(r"\d+(?:\.\d+)?|[A-Za-z]+|[()\[\]]|[+\-×÷^√±*/]|=|\S")


def _spans(text: str) -> list[str]:
    """Every candidate expression in a piece of text, longest run first."""
    latex, compound = _expand_fractions(_TEXT_CMD.sub(" ", text or ""))
    for pattern, repl in _SIMPLE_LATEX:
        latex = re.sub(pattern, repl, latex)
    latex = latex.replace("$", " ").replace("\\", " ")
    latex = latex.replace("{", "(").replace("}", ")")

    runs: list[str] = []
    current: list[str] = []
    for token in _TOKEN.findall(latex):
        if (token[0].isdigit() or token in _OPS or token in "()[]="
                or (len(token) == 1 and token.isalpha())):
            current.append(token)
        else:
            if current:
                runs.append(" ".join(current))
            current = []
    if current:
        runs.append(" ".join(current))

    # An equation is two expressions; measure each side on its own.
    sides: list[str] = []
    for run in runs:
        sides += [part for part in run.split("=") if part.strip()]
    if compound:
        sides.append(text)  # so `fraction_bar` survives to the Demand below
    return sides


# ── What was measured ────────────────────────────────────────────────────────


@dataclass(slots=True)
class Demand:
    """The shape of the hardest expression in a piece of work."""

    operations: int = 0
    kinds: frozenset[str] = frozenset()
    depth: int = 0
    negatives: int = 0
    fraction_bar: bool = False
    # Across every step, not just the hardest one. A three-step word problem
    # whose hardest single line is one multiplication is still three kinds of
    # work, and judging it on that one line failed exactly the items the grade
    # wants most.
    total_operations: int = 0
    all_kinds: frozenset[str] = frozenset()
    steps: int = 0
    # Whether the item is set in words rather than given as a bare expression.
    # A word problem carries demand that counting operators cannot see; an
    # expression typed across two lines does not.
    word_problem: bool = False
    expression: str = ""

    @property
    def measurable(self) -> bool:
        """Whether there was any arithmetic here at all."""
        return self.operations > 0 or self.total_operations > 0

    @property
    def order_matters(self) -> bool:
        """Whether BODMAS changes the answer — an add-level op and a mul-level one."""
        return bool(self.kinds & {"+", "-"}) and bool(self.kinds & {"×", "÷", "^", "√"})

    def to_dict(self) -> dict[str, Any]:
        return {"operations": self.operations, "kinds": sorted(self.kinds),
                "depth": self.depth, "negatives": self.negatives,
                "fraction_bar": self.fraction_bar,
                "order_matters": self.order_matters,
                "total_operations": self.total_operations,
                "all_kinds": sorted(self.all_kinds or self.kinds),
                "steps": self.steps, "word_problem": self.word_problem,
                "expression": self.expression}


def _measure_one(expr: str) -> Demand:
    """One expression, tokenised. A leading `-` is a sign, not an operation."""
    ops, kinds, negatives = 0, set(), 0
    depth = deepest = 0
    prev: str | None = None
    for token in _TOKEN.findall(expr):
        if token[0].isdigit() or (len(token) == 1 and token.isalpha()):
            # `2(3+4)`, `(a)(b)` and `3x` are multiplications nobody wrote
            # down. Two bare numbers side by side are not: that is a thousands
            # space or a line break, and reading it as a product inflated the
            # demand of every figure with four digits in it.
            if prev == "closed" or (prev == "value" and token.isalpha()):
                ops += 1
                kinds.add("×")
            prev = "value"
        elif token in "([":
            if prev in ("value", "closed"):
                ops += 1
                kinds.add("×")
            depth += 1
            deepest = max(deepest, depth)
            prev = "open"
        elif token in ")]":
            depth = max(0, depth - 1)
            prev = "closed"
        elif token == "√":
            kinds.add("√")
            prev = "open"
        elif token in _OPS:
            symbol = _NORMALISE.get(token, token)
            if symbol in "+-" and prev in (None, "op", "open"):
                if symbol == "-":
                    negatives += 1
                prev = "open"          # a signed number is still an operand
            else:
                ops += 1
                kinds.add(symbol)
                prev = "op"
        else:
            prev = None
    return Demand(operations=ops, kinds=frozenset(kinds), depth=deepest,
                  negatives=negatives, expression=_tidy(expr))


def _tidy(expr: str) -> str:
    """The span as somebody would write it, not as the tokeniser split it."""
    text = re.sub(r"\(\s+", "(", expr.strip())
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\(\s*-\s*(\d)", r"(-\1", text)
    return re.sub(r"\s{2,}", " ", text)


def measure(text: str) -> Demand:
    """The hardest expression in `text`, plus what the whole of it adds up to."""
    hardest = Demand()
    total = 0
    kinds: set[str] = set()
    for span in _spans(text):
        if span is text:  # the fraction-bar marker appended by `_spans`
            continue
        one = _measure_one(span)
        if not one.operations:
            continue
        total += one.operations
        kinds |= set(one.kinds)
        if (one.operations, one.depth, len(one.kinds)) > \
                (hardest.operations, hardest.depth, len(hardest.kinds)):
            hardest = one
    hardest.total_operations = total
    hardest.all_kinds = frozenset(kinds)
    hardest.fraction_bar = "\\frac" in (text or "") or "\\dfrac" in (text or "")
    if hardest.fraction_bar:
        hardest.depth = max(hardest.depth, 1)
    return hardest


# A command word plus an expression is not prose. "Evaluate: 3 + 5 × 2" is an
# expression with an instruction in front of it; "A trader buys 3 crates of
# eggs at KSh 450 each" is a situation the learner has to model.
_PROSE_WORD = re.compile(r"[A-Za-z]{3,}")


def _is_prose(statement: str) -> bool:
    words = _PROSE_WORD.findall(statement or "")
    return len(words) >= 6


def measure_item(item: dict[str, Any]) -> Demand:
    """A worked example or a question, across its statement and every step."""
    lines = [str(item.get("statement") or item.get("stem") or
                 item.get("question") or "")]
    working = [str(s.get("working") or "") for s in (item.get("steps") or [])
               if isinstance(s, dict)]
    working += [str(s.get("working") or "") for s in (item.get("solution") or [])
                if isinstance(s, dict)]
    lines += working
    lines.append(str(item.get("answer") or ""))

    hardest = Demand()
    total, kinds = 0, set()
    for line in lines:
        one = measure(line)
        total += one.total_operations
        kinds |= set(one.kinds)
        if (one.operations, one.depth, len(one.kinds)) > \
                (hardest.operations, hardest.depth, len(hardest.kinds)):
            hardest = one
    hardest.total_operations = total
    hardest.all_kinds = frozenset(kinds)
    hardest.steps = len([w for w in working if w.strip()])
    hardest.word_problem = _is_prose(lines[0] if lines else "")
    if not hardest.kinds:
        hardest.kinds = frozenset(kinds)
    return hardest


# ── What the grade requires ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Floor:
    """The least demanding shape this level's own assessment would accept."""

    level: str
    operations: int
    kinds: int
    depth: int
    order_matters: bool
    exemplar: str
    because: str

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "operations": self.operations,
                "kinds": self.kinds, "depth": self.depth,
                "order_matters": self.order_matters,
                "exemplar": self.exemplar, "because": self.because}


# Pre-Primary and Lower Primary have NO floor. A six-year-old adding two
# single-digit numbers is doing the thing the design asks for, and a check that
# demands brackets of them is a check that is simply wrong.
_FLOORS: dict[str, Floor] = {
    "Upper Primary": Floor(
        level="Upper Primary",
        operations=2, kinds=2, depth=0, order_matters=True,
        exemplar="$1\\,250 - 3 \\times 240$",
        because="the designs assess the four operations together, so a single "
                "operation cannot show whether order of operations is known",
    ),
    "Junior School": Floor(
        level="Junior School",
        operations=2, kinds=2, depth=1, order_matters=True,
        exemplar="$\\dfrac{-15 \\div 3 - (-2) \\times (-4) + 6}{-2 \\times 3 + (-4)}$",
        because="the designs assess COMBINED operations at this level — "
                "brackets and a fraction bar deciding the order, and signs "
                "carried through — not one operation at a time",
    ),
    "Senior School": Floor(
        level="Senior School",
        operations=3, kinds=3, depth=1, order_matters=True,
        exemplar="$\\dfrac{2^{3} - \\sqrt{49}}{(-3)(4) + 15} + \\dfrac{1}{4}$",
        because="a pathway question combines indices, roots, brackets and "
                "fractions in one expression",
    ),
}
_FLOORS["Tertiary"] = _FLOORS["Senior School"]


# WHICH SUBJECTS HAVE A FLOOR AT ALL.
#
# This is the same list the prompt fragments carry, and it is one list on
# purpose. Gating a subject the generator was never given the rule for is
# crying wolf at a station that did exactly as it was told — a Grade 9
# Chemistry mole calculation was being failed for "one operation" while the
# chemistry prompt had never been shown a floor.
#
# Add a subject here and to `prompt_fragments` together, or not at all — a
# subject gated but not instructed is a station failed for doing as it was
# told, and a subject instructed but not gated is a rule nothing enforces.
# There is a test that these two lists are equal.
#
# The sciences are here because their calculations are arithmetic and are
# marked as arithmetic. What they are NOT judged on is the maths exemplar: a
# science calculation is demanding when it carries a formula, a substitution
# and a unit, which is what their own fragment asks for.
QUANTITATIVE: tuple[str, ...] = ("mathemat", "physic", "chemist",
                                 "integrated science")


def has_floor(subject: str | None) -> bool:
    """Whether demand is something this subject is measured on."""
    return any(re.search(rf"\b{stem}", subject or "", re.I)
               for stem in QUANTITATIVE)


def floor_for(grade: str | None, subject: str | None = None) -> Floor | None:
    """The floor for this grade, or None where there should not be one.

    `subject` defaults to unset, which means "do not ask the question" rather
    than "any subject": a caller that does not know the subject gets the
    level's floor. Callers that DO know it must pass it, so that a subject
    whose generator was never given the rule is never held to it.
    """
    from .grade_order import GRADE_SEQUENCE, normalize_grade

    if subject is not None and not has_floor(subject):
        return None
    slug = normalize_grade(grade)
    level = next((lv for s, _l, lv in GRADE_SEQUENCE if s == slug), "")
    return _FLOORS.get(level)


# Arithmetic so far below the grade that no teaching purpose reaches down to
# it. One operation, one kind of operation, no negative number, nothing
# bracketed, and every operand a single digit: `5 + 3`, `3 - 5`, `7 - 4`.
#
# This is NOT the grade floor, and the difference matters. A Grade 9 lesson
# introducing the sign rule legitimately needs `-4 × 6 = -24` — one operation,
# below the grade floor, and doing a job. Nothing at this grade needs `5 + 3`.
# It is Grade 2 work, six years down, and a set is not excused for containing
# it by containing something harder elsewhere.
def infant_arithmetic(demand: Demand) -> bool:
    if demand.operations != 1 or len(demand.kinds) != 1:
        return False
    if demand.negatives or demand.depth or demand.fraction_bar:
        return False
    return all(len(n.lstrip("-")) == 1 and "." not in n
               for n in _NUMBER.findall(demand.expression))


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class Shortfall:
    """What is missing, and what would fix it."""

    level: str
    misses: list[str] = field(default_factory=list)
    demand: Demand = field(default_factory=Demand)
    floor: Floor | None = None

    @property
    def below(self) -> bool:
        return bool(self.misses)

    def says(self) -> str:
        return (f"The hardest expression here is \"{self.demand.expression}\" — "
                + "; ".join(self.misses) + ".")

    def fix(self) -> str:
        if not self.floor:
            return ""
        return (f"{self.level} work {self.floor.because}. Write it at the shape "
                f"of {self.floor.exemplar}.")


def shortfall(demand: Demand, floor: Floor | None) -> Shortfall:
    """Every way this falls short of the floor. Empty when it does not."""
    if floor is None or not demand.measurable:
        return Shortfall(level=floor.level if floor else "", demand=demand,
                         floor=floor)

    # A modest single line is fine when the item as a whole is real work — a
    # multi-step WORD PROBLEM is demanding in a way one line never shows, and
    # failing it would be failing exactly the item the grade wants most.
    #
    # The escape is for word problems and nothing else. Without that condition
    # it let `Evaluate: 3 + 5 × 2` through, because writing the multiplication
    # on one line and the addition on the next made a two-step item out of an
    # expression with no brackets and no negative number in it — Grade 5 work,
    # counted as Grade 9 because it was typed on two lines.
    if demand.word_problem and demand.steps >= 2 \
            and demand.total_operations >= floor.operations \
            and len(demand.all_kinds or demand.kinds) >= floor.kinds:
        return Shortfall(level=floor.level, demand=demand, floor=floor)

    misses: list[str] = []
    if demand.operations < floor.operations:
        misses.append(f"it has {demand.operations} operation"
                      f"{'' if demand.operations == 1 else 's'} where this level "
                      f"works with at least {floor.operations}")
    if len(demand.kinds) < floor.kinds:
        seen = len(demand.kinds)
        misses.append(f"it uses {seen} kind{'' if seen == 1 else 's'} of "
                      f"operation where this level combines at least "
                      f"{floor.kinds}")
    if demand.depth < floor.depth and not demand.fraction_bar:
        misses.append("nothing is bracketed, so the order of operations is never "
                      "in question")
    if floor.order_matters and not demand.order_matters:
        misses.append("every operation is at the same level of precedence, so "
                      "BODMAS never decides the answer")
    return Shortfall(level=floor.level, misses=misses, demand=demand, floor=floor)


def check_item(item: dict[str, Any], grade: str | None,
               subject: str | None = None) -> Shortfall:
    """One worked example or question, against its grade's floor."""
    return shortfall(measure_item(item), floor_for(grade, subject))


# ── A whole set, which is the unit that actually matters ─────────────────────
#
# A per-item floor is wrong, and wrong in a way that would have made this
# useless. A guide introducing the sign rule NEEDS `-4 × 6 = -24` in it; an
# item-by-item gate condemns that example and the teacher turns the gate off.
#
# What the reviewer actually objected to was never one easy example. It was
# that the hardest thing in a whole Grade 9 booklet was `7 - 4`. So that is
# what is measured: whether ANYTHING in the set reaches the grade.


@dataclass
class SetReport:
    """Whether a set of items is as demanding as its grade, item by item.

    Judged on the TYPICAL item rather than the hardest one. Asking only
    "does anything reach the grade" was the mistake: a Grade 9 guide whose
    examples were 5 + 3, 3 - 5, 3 + 5 × 2, -4 + 6 × (-2), -300 + 300,
    3 + 5 × 2 again and -4 + 6 × (-2) - 3 passed that test on its last
    example. A learner reads all seven.
    """

    level: str = ""
    floor: Floor | None = None
    at_grade: int = 0
    measured: int = 0
    hardest: Demand = field(default_factory=Demand)
    shortfall: Shortfall | None = None
    # Items so far below the grade that nothing excuses them.
    far_below: list[str] = field(default_factory=list)

    @property
    def typical_below(self) -> bool:
        """Fewer than half the items reach the grade."""
        return bool(self.measured) and self.at_grade * 2 < self.measured

    @property
    def below(self) -> bool:
        if not self.measured or self.floor is None:
            return False
        return bool(self.far_below) or self.typical_below

    def says(self) -> str:
        if not self.below:
            return ""
        parts: list[str] = []
        if self.far_below:
            shown = ", ".join(f'"{e}"' for e in self.far_below[:4])
            more = (f" and {len(self.far_below) - 4} more"
                    if len(self.far_below) > 4 else "")
            parts.append(
                f"{len(self.far_below)} of these {self.measured} items are "
                f"single-digit arithmetic with no negative number and nothing "
                f"bracketed — {shown}{more}. That is primary-school work in a "
                f"{self.level} guide, and no example in the rest of the set "
                f"excuses it.")
        if self.typical_below:
            parts.append(
                f"Only {self.at_grade} of {self.measured} items reach "
                f"{self.level}, so the TYPICAL example here is below the "
                f"grade — a learner reads all of them, not only the hardest.")
            if self.shortfall and self.shortfall.misses:
                parts.append(self.shortfall.says())
        return " ".join(parts)

    def fix(self) -> str:
        return self.shortfall.fix() if self.shortfall else ""

    def to_dict(self) -> dict[str, Any]:
        return {"level": self.level, "at_grade": self.at_grade,
                "measured": self.measured, "below": self.below,
                "typical_below": self.typical_below,
                "far_below": self.far_below,
                "floor": self.floor.to_dict() if self.floor else None,
                "hardest": self.hardest.to_dict(),
                "says": self.says(), "fix": self.fix()}


def check_set(items: list[Any], grade: str | None,
              subject: str | None = None) -> SetReport:
    """Whether a set of examples or questions reaches its grade anywhere."""
    floor = floor_for(grade, subject)
    report = SetReport(level=floor.level if floor else "", floor=floor)
    hardest_short: Shortfall | None = None
    for item in (items or []):
        if not isinstance(item, dict):
            continue
        demand = measure_item(item)
        if not demand.measurable:
            continue
        report.measured += 1
        short = shortfall(demand, floor)
        if not short.below:
            report.at_grade += 1
        if infant_arithmetic(demand):
            report.far_below.append(demand.expression)
        if (demand.operations, demand.depth, len(demand.kinds)) > \
                (report.hardest.operations, report.hardest.depth,
                 len(report.hardest.kinds)):
            report.hardest = demand
            hardest_short = short
    report.shortfall = hardest_short
    return report


# The only single-letter words in English. Read as variables, "If I have +4
# and add +6 I get +10" yielded the expression "+ 6 I" — prose reported as
# arithmetic, and then reported as arithmetic below the grade.
_ENGLISH_LETTERS = frozenset({"i", "a"})


def items_in_prose(text: str) -> list[dict[str, Any]]:
    """Each expression a passage teaches from, as an item in its own right.

    The teacher's guide carries no `worked_examples` field: its arithmetic sits
    inside the exposition, in sentences like "For example, $3 + 5 = 8$ and
    $-3 + (-5) = -8$". So the plan station was told the demand floor and
    nothing measured whether it met it — which is how a Grade 9 plan came back
    teaching from twelve expressions of which one reached the grade.

    An expression IS the item here. There is no separate statement to compare
    it against, so only the arithmetic half applies; whether the words around
    it model the right thing is the material station's business, because that
    is where the words are written.
    """
    found: list[dict[str, Any]] = []
    for span in _spans(text or ""):
        if span is text:
            continue
        one = _measure_one(span)
        if not one.operations:
            continue
        # An expression whose only non-numeric operand is an English word is a
        # sentence, not algebra.
        letters = {t.lower() for t in _TOKEN.findall(one.expression)
                   if len(t) == 1 and t.isalpha()}
        if letters and letters <= _ENGLISH_LETTERS:
            continue
        found.append({"statement": one.expression, "from_prose": True})
    return found
