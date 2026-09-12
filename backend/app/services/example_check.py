"""Whether a worked example's ARITHMETIC actually models what it describes.

A reviewer found three faults in one Grade 9 guide and the maths engine
verified all three as correct:

    "temperature drops from 5°C to -3°C, so 5 + (-3) = 2"      5 + (-3) IS 2
    "a hiker climbs from 200 m to 50 m, so 200 + (-50) = 150"  200 + (-50) IS 150
    "-7 + 3 = -4, so adding a positive moves you closer to 0"  -7 + 3 IS -4

Every sum checks out. The change from 5°C to -3°C is a fall of 8, not 2; a
hiker going from 200 m to 50 m has descended, not climbed; and -2 + 10 = 8 is
further from zero, not closer. The arithmetic was never the problem — the
sentence saying what the arithmetic represents was.

A solver cannot catch this, because there is nothing wrong with the sum. What
CAN catch it is comparing the expression against the words around it:

  * a change "from A to B" is B - A, and an example that writes A + (-B)
    has modelled a different question;
  * "climbs", "rises", "gains" against a pair that falls is the story
    contradicting its own numbers;
  * "always", "results in", "any" is a claim about every case, and a claim
    about every case can be tested against cases.

None of these needs a model. All of them are the difference between a booklet
somebody buys and one they discard.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# "from 5°C to -3°C", "from 200 metres to 50 m", "from 10 to -2"
# Up to four words may sit between "from" and its number — "from an elevation
# of 200 metres to 50 metres" is the shape the reviewer found, and a pattern
# demanding the number immediately after "from" walked straight past it.
_FROM_TO = re.compile(
    r"\bfrom\s+(?:\w+\s+){0,4}?(-?\d+(?:\.\d+)?)\s*"
    r"(?:°?\s*[cCfF]\b|m\b|metres?\b|meters?\b|km\b|shillings?\b|KE?S?h?\b)?"
    r"\s*(?:down\s+to|up\s+to|to)\s+(?:\w+\s+){0,3}?(-?\d+(?:\.\d+)?)", re.I)

# The words that say which way it went.
_ROSE = re.compile(r"\b(rise[sn]?|rose|climb(s|ed|ing)?|increase[sd]?|gain(s|ed)?|"
                   r"up|warm(s|ed|er)?|ascend(s|ed|ing)?)\b", re.I)
_FELL = re.compile(r"\b(fall(s|en|ing)?|fell|drop(s|ped|ping)?|decrease[sd]?|"
                   r"lose[sd]?|lost|down|cool(s|ed|er)?|descend(s|ed|ing)?|"
                   r"below)\b", re.I)

# A claim about every case.
_UNIVERSAL = re.compile(
    r"\b(always|never|any\s+\w+|every\s+\w+|all\s+\w+|results?\s+in|"
    r"will\s+(?:be|always)|is\s+always)\b", re.I)

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class Finding:
    kind: str
    says: str
    fix: str = ""
    # Which lessons the finding is about, where it is about particular ones —
    # so a repair loop has something to rewrite rather than a sentence to parse.
    lessons: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "says": self.says, "fix": self.fix,
                "lessons": list(self.lessons)}


@dataclass
class Report:
    checked: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.findings

    @property
    def score(self) -> float:
        if not self.checked:
            return 0.0
        bad = len({f.says for f in self.findings})
        return round(max(0.0, 1 - bad / self.checked) * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {"checked": self.checked, "clean": self.clean,
                "score": self.score,
                "findings": [f.to_dict() for f in self.findings]}


_TEX_WRAP = re.compile(r"\\(?:text|mathrm|mbox)\s*\{([^{}]*)\}")
_TEX_NOISE = re.compile(r"\$|\\[,;!]|\^\s*\\circ|\\circ|\\degree|\\left|\\right")


def _text_of(example: dict[str, Any]) -> str:
    parts = [str(example.get("statement") or "")]
    for step in (example.get("steps") or []):
        if isinstance(step, dict):
            parts += [str(step.get("working") or ""), str(step.get("because") or "")]
    parts.append(str(example.get("answer") or ""))
    return " ".join(parts)


def _as_story(text: str) -> str:
    """The same text with the LaTeX dressing taken off, for the story checks.

    "from $5°C$ to $-3°C$" is the same story as "from 5°C to -3°C", and the
    story checks read it with a regex that a dollar sign stops dead. Example
    1.1 of a Grade 9 guide answered 2 for a change from 5 to −3 and was not
    caught, while example 3.1 — the same mistake written without dollars — was.
    """
    return _TEX_NOISE.sub("", _TEX_WRAP.sub(r"\1", text))


def _direction_fault(text: str) -> Finding | None:
    """A story that goes one way and numbers that go the other."""
    pair = _FROM_TO.search(text)
    if not pair:
        return None
    start, end = float(pair.group(1)), float(pair.group(2))
    if start == end:
        return None
    went_up = end > start
    said_up = bool(_ROSE.search(text))
    said_down = bool(_FELL.search(text))
    if went_up and said_down and not said_up:
        return Finding(
            "direction", f"It says the value falls, and goes from {pair.group(1)} "
            f"to {pair.group(2)}, which is a rise.",
            "Fix the wording or the numbers — a learner reading this learns the "
            "wrong sign.")
    if not went_up and said_up and not said_down:
        return Finding(
            "direction", f"It says the value rises, and goes from {pair.group(1)} "
            f"to {pair.group(2)}, which is a fall.",
            "A hiker going from 200 m to 50 m has descended, not climbed.")
    return None


def _change_fault(text: str) -> Finding | None:
    """A change from A to B is B - A, whatever the example writes down."""
    pair = _FROM_TO.search(text)
    if not pair:
        return None
    start, end = float(pair.group(1)), float(pair.group(2))
    change = end - start
    if not re.search(r"\bchange|\bdifference|\bdrop|\bfall|\brise|\bincrease|"
                     r"\bdecrease", text, re.I):
        return None

    # The answer the example actually gives.
    answer = str(_last_number(text) or "")
    if answer == "":
        return None
    try:
        given = float(answer)
    except ValueError:
        return None

    if abs(given - change) < 1e-9 or abs(given - abs(change)) < 1e-9:
        return None
    return Finding(
        "models_the_wrong_thing",
        f"The value goes from {pair.group(1)} to {pair.group(2)}, so the change "
        f"is {change:g}. This example answers {given:g}, which is a different "
        f"question — the arithmetic is right and it is not the arithmetic the "
        f"story asks for.",
        "Write the change as final minus initial and work that out.")


def _last_number(text: str) -> str | None:
    found = _NUMBER.findall(text)
    return found[-1] if found else None


def _too_easy(examples: list[Any], grade: str, subject: str,
              strand: str = "", sub_strand: str = "") -> Finding | None:
    """Arithmetic years below the grade the SET is printed for.

    "7 - 4 = 3" is not wrong, and it is not a Grade 9 revision question either.
    But a guide introducing the sign rule legitimately needs `-4 × 6 = -24` in
    it, so condemning that item on its own would be condemning the example the
    lesson is built around — and a gate that fails honest work gets switched
    off, after which it catches nothing at all.

    What the reviewer actually objected to was never one easy example. It was
    that the hardest thing in a whole Grade 9 booklet was `7 - 4`. So that is
    what is asked here: whether ANYTHING in the set reaches the grade.

    The measurement lives in `task_demand`, which counts what makes an
    expression hard — how many operations, how many KINDS of operation, whether
    anything is bracketed, whether the order of operations decides the answer —
    against the floor for the grade's own level. A set with no arithmetic in it
    is never flagged, which is how a floor written for Mathematics leaves a
    comprehension exercise alone.
    """
    from . import demand_profile

    judgement = demand_profile.judge(examples, grade=grade, subject=subject or "",
                                     strand=strand, sub_strand=sub_strand)

    # Only the ARITHMETIC half applies here. The command-word half asks what a
    # task demands OF THE LEARNER, and a worked example demands nothing of them
    # — it is the teacher showing a method. "Find its temperature after 2
    # hours" is a demonstration, and failing it for not saying "evaluate" would
    # fail every worked example in every guide in the system.
    #
    # That half is measured where it belongs, on the questions, activities and
    # experiments that do ask the learner something.
    if not judgement.numeric.below:
        return None
    return Finding("below_the_grade", judgement.numeric.says(),
                   judgement.numeric.fix())


def _duplicates(examples: list[Any], grade: str, subject: str) -> list[Finding]:
    """The same worked example printed twice in one guide.

    A Grade 9 integers guide taught `3 + 5 × 2` in Lesson 2 and taught it again,
    with the same two steps and the same answer, in Lesson 5. Nothing measured
    it: each copy is a full-length, correct, well-formed example, so a check
    that reads forwards sees two good lessons.

    Matched on the ARITHMETIC rather than the words, because a second copy is
    usually reworded — the tell is that the sums are identical.
    """
    from . import task_demand

    seen: dict[str, int] = {}
    findings: list[Finding] = []
    for index, example in enumerate(examples or [], start=1):
        if not isinstance(example, dict):
            continue
        demand = task_demand.measure_item(example)
        key = re.sub(r"\s+", "", demand.expression)
        if not key or demand.operations == 0:
            continue
        if key in seen:
            findings.append(Finding(
                "repeated_example",
                f"Example {index} works out \"{demand.expression}\", which "
                f"example {seen[key]} has already worked out. A learner "
                f"reaching it has been taught nothing new, and the lesson "
                f"holding it is a lesson the guide did not really write.",
                "Replace it, or move the second copy to where it is revision "
                "and say that is what it is."))
        else:
            seen[key] = index
    return findings


# ── the arithmetic, against the engine, step by step ─────────────────────────
#
# `worked_solutions.check` has existed for the whole of this work and was
# called from nowhere. It solves the EXERCISES a guide sets and never checked
# the guide's own worked examples, which is where two errors reached a page:
#
#   "-(-2) x (-4) = 2 x 4 = 8"      the term is -8; the minus was distributed
#                                   onto one factor and the sign flipped twice
#   "(-15/3 - (-2)(-4) + 6) / (-2(3) + (-4))  =  -7"
#                                   -7 is the NUMERATOR. The denominator was
#                                   worked out, written down, and never used.
#
# The same expression appeared in two lessons of one guide with two different
# answers, and neither was right. Every step is now solved on its own, because
# a fault at step 2 is worth naming at step 2 rather than as a wrong total.

_EQUATION = re.compile(r"^(?P<lhs>[^=]{2,120}?)\s*=\s*(?P<rhs>[^=]{1,60})$")

# Enough to catch a guide, bounded so a 500-item batch cannot spend a minute
# in the solver.
_MAX_CHECKED_EXAMPLES = 40
_MAX_CHECKED_STEPS = 12


def _arithmetic_faults(examples: list[Any]) -> list[Finding]:
    from . import worked_solutions

    findings: list[Finding] = []
    for index, example in enumerate(examples[:_MAX_CHECKED_EXAMPLES] or [],
                                    start=1):
        if not isinstance(example, dict):
            continue

        # Each step's own equation. A wrong step is worth naming where it is.
        steps = [s for s in (example.get("steps") or []) if isinstance(s, dict)]
        for number, step in enumerate(steps[:_MAX_CHECKED_STEPS], start=1):
            match = _EQUATION.match(str(step.get("working") or "").strip())
            if not match:
                continue
            verdict = worked_solutions.check(match.group("lhs"),
                                             match.group("rhs"))
            if verdict["checked"] and verdict["agrees"] is False:
                findings.append(Finding(
                    "step_is_wrong",
                    f"Example {index}, step {number}: "
                    f"\"{match.group('lhs').strip()}\" is "
                    f"{verdict['engine_answer']}, and the step says "
                    f"{match.group('rhs').strip()}.",
                    "Work the step again. Every step after this one inherits "
                    "it, and a learner imitating the guide will make the same "
                    "mistake in the same place."))

        # And the answer, against the WHOLE statement — which is the only thing
        # that catches an answer that solves part of the question.
        statement = str(example.get("statement") or "")
        answer = str(example.get("answer") or "")
        verdict = worked_solutions.check(statement, answer)
        if verdict["checked"] and verdict["agrees"] is False:
            findings.append(Finding(
                "answer_disagrees",
                f"Example {index} answers {answer.strip()}; the engine makes "
                f"it {verdict['engine_answer']}. If the steps are right, the "
                f"answer has stopped short of the whole expression — a "
                f"numerator reported as the value of a fraction is the "
                f"commonest form of this.",
                "Carry the working through to the end of the expression and "
                "state that as the answer."))
    return findings


# ── the order of operations, step by step ────────────────────────────────────
#
# The check that every step is a TRUE equation and the answer is RIGHT passes
# this, and what it teaches is illegal:
#
#     5 + (-3) - 2 × (-4)
#     = 5 - 3 - 2 × (-4)     "we perform addition and subtraction, left to right"
#     = 2 - 2 × (-4)         "5 - 3 = 2"          ← the multiplication is pending
#     = 2 - (-8)             "2 × (-4) = -8"
#     = 10
#
# Every line is true. The answer is 10 and 10 is correct — by luck, because the
# multiplication sat at the tail. A learner who applies the stated rule to
# 4 + 3 × 2 gets 14.
#
# Correct arithmetic reaching a correct answer by a method that would fail on
# the next question is the most dangerous thing a guide can contain, because
# nothing about the numbers gives it away.

_MUL_LEVEL = re.compile(r"[×÷*/]|\^")
_ADD_LEVEL_TOP = re.compile(r"^\s*-?[\d.]+\s*[+-]\s*[\d.]+\s*$")


def _outside_brackets(expression: str) -> str:
    """The expression with every bracketed group collapsed to a placeholder."""
    text = _as_symbols(expression)
    for _ in range(8):
        reduced = re.sub(r"\([^()]*\)", "N", text)
        if reduced == text:
            break
        text = reduced
    return text


def _out_of_order(example: dict[str, Any], index: int) -> Finding | None:
    """A step that adds or subtracts while a multiplication is still pending."""
    steps = [st for st in (example.get("steps") or []) if isinstance(st, dict)]
    running = _as_symbols(str(example.get("statement") or ""))

    for number, step in enumerate(steps, start=1):
        working = _as_symbols(str(step.get("working") or "").strip())
        match = _EQUATION.match(working)
        if not match:
            running = working or running
            continue
        lhs, rhs = match.group("lhs").strip(), match.group("rhs").strip()

        # A sub-expression inside brackets is SUPPOSED to go first.
        bracketed = re.search(r"\([^()]*" + re.escape(lhs) + r"[^()]*\)", running)
        if not bracketed and _ADD_LEVEL_TOP.match(lhs) \
                and _MUL_LEVEL.search(_outside_brackets(running)):
            return Finding(
                "out_of_order",
                f"Example {index}, step {number} works out \"{lhs}\" while "
                f"\"{running.strip()}\" still has a multiplication or division "
                f"waiting. The answer may still come out right — it does here, "
                f"because the product sits at the end — and the METHOD is the "
                f"one BODMAS forbids. A learner applying it to $4 + 3 "
                f"\\times 2$ gets 14.",
                "Work the multiplication and division first, then the addition "
                "and subtraction from left to right. Say that in the reason for "
                "the step, because the reason is what a learner copies.")
        running = rhs or running
    return None


def _order_faults(examples: list[Any]) -> list[Finding]:
    out: list[Finding] = []
    for index, example in enumerate(examples or [], start=1):
        if not isinstance(example, dict):
            continue
        found = _out_of_order(example, index)
        if found:
            out.append(found)
    return out


# The shape every worked example takes, so a learner meets one format.
_SHAPE_RULES: tuple[tuple[str, str], ...] = (
    ("statement", "the task it works, written out"),
    ("steps", "numbered steps"),
    ("answer", "final answer on its own line"),
)


def _shape_faults(examples: list[Any]) -> list[Finding]:
    """Whether every example is laid out the same way.

    A guide whose examples are each formatted differently is a guide a learner
    has to re-learn how to read on every page, and it is the difference between
    a booklet somebody prints and one somebody sells. The rule is deliberately
    plain: a task, numbered steps that each say WHY, and one final answer.
    """
    findings: list[Finding] = []
    for index, example in enumerate(examples or [], start=1):
        if not isinstance(example, dict):
            continue
        # An expression lifted out of teaching prose is not a worked example
        # and has no steps by construction. Reporting all ten of them as
        # badly laid out is the crying-wolf failure this check exists to
        # avoid — its subject is examples somebody actually authored.
        if example.get("from_prose"):
            continue
        missing = [what for key, what in _SHAPE_RULES if not example.get(key)]
        if missing:
            findings.append(Finding(
                "solution_not_uniform",
                f"Example {index} has no " + ", no ".join(missing) + ".",
                "Every worked example takes the same shape: the task, "
                "numbered steps, and one final answer."))
            continue
        steps = [s for s in (example.get("steps") or []) if isinstance(s, dict)]

        # Display maths inside a sentence breaks the sentence. A reason reading
        # "First, adding $$-5$$ and $$8$$ gives $$3$$" prints as prose and
        # centred numbers alternating down the page, one line each — which is
        # what a Grade 9 guide did to every reason in Example 5.1.
        staircase = [n for n, st in enumerate(steps, start=1)
                     if "$$" in str(st.get("because") or "")]
        if staircase:
            findings.append(Finding(
                "solution_not_uniform",
                f"Example {index} puts display maths inside the reason for "
                f"step(s) {', '.join(str(n) for n in staircase[:6])}. Each "
                f"expression takes a centred line of its own, so the sentence "
                f"prints as a staircase of numbers down the page.",
                "Use single dollars inside a sentence. Display maths belongs "
                "on the working line, not in the words explaining it."))

        unreasoned = [n for n, s in enumerate(steps, start=1)
                      if not str(s.get("because") or "").strip()]
        if unreasoned:
            findings.append(Finding(
                "solution_not_uniform",
                f"Example {index} has {len(unreasoned)} step(s) with no reason "
                f"given: {', '.join(str(n) for n in unreasoned[:6])}.",
                "Each step says WHY it is taken, not what it did. \"Make the "
                "denominators the same so the parts are the same size\", never "
                "\"now we rewrite the fractions\"."))
    return findings


def _missing_operations(items: list[Any], grade: str, subject: str,
                        strand: str, sub_strand: str) -> list[Finding]:
    """Operations the design names and the guide never uses.

    A Grade 9 integers guide came back with multiplication and division gone
    entirely — six lessons of adding and subtracting small positives — for a
    sub-strand whose design names all four operations by name.

    The demand floor happened to catch that set, because an expression with no
    multiplication-level operator can never make the order of operations
    matter. "Happened to catch" is not a check: what the design NAMES, the
    guide has to teach, and the design says so in words that can be read.
    """
    from . import design_elements, lesson_material, task_demand

    row = lesson_material._design_row(grade, subject, sub_strand, strand)
    if not row:
        # Nothing to read the requirement out of. Silence rather than a rule
        # invented from the sub-strand's title.
        return []
    wanted = design_elements.operations_named(row)
    if not wanted:
        return []

    used: set[str] = set()
    for item in (items or []):
        if isinstance(item, dict):
            used |= set(task_demand.measure_item(item).all_kinds
                        or task_demand.measure_item(item).kinds)
    if not used:
        return []

    findings: list[Finding] = []

    # A sub-strand about directed numbers whose expressions contain none.
    if design_elements.wants_negatives(row):
        signed = any(task_demand.measure_item(i).negatives
                     for i in (items or []) if isinstance(i, dict))
        if not signed:
            findings.append(Finding(
                "no_negative_numbers",
                "This sub-strand's design is about directed numbers, and not "
                "one expression in this content uses a negative number. "
                "`6 + 2 × (3 - 1)` clears the difficulty floor — three "
                "operations, a bracket, order of operations deciding the "
                "answer — and teaches nothing about signs.",
                "Work the examples on signed numbers: a negative operand, a "
                "negative result, or a subtraction that crosses zero."))

    missing = {sym: name for sym, name in wanted.items() if sym not in used}
    if not missing:
        return findings
    return findings + [Finding(
        "operation_never_taught",
        "The design for this sub-strand names "
        + ", ".join(sorted(missing.values()))
        + ", and no expression in this content uses "
        + ("it" if len(missing) == 1 else "them")
        + ". A learner is assessed on what the design names, not on what the "
          "guide found easiest to write.",
        "Teach and work examples on "
        + ", ".join(f"{name} ({sym})" for sym, name in sorted(missing.items(),
                                                              key=lambda kv: kv[1]))
        + ".")]


# Quantities that CANNOT be negative, and the words that name them.
#
# A reviewer found two of these in one guide: "in a survey, if more people
# prefer tea over coffee, we can represent this as a positive integer for tea
# and a negative for coffee", and "when cooking, if a recipe requires you to
# subtract KES 20 for ingredients you already have".
#
# There is no such thing as -15 people, and a recipe is measured in grams and
# millilitres rather than shillings. Both read as helpful real-life context and
# both teach a learner something false about what a negative number means —
# which is worse than a dry example, because the learner believes it.
#
# What is DELIBERATELY not here: temperature, elevation, altitude, balance,
# account, profit, score. Every one of those is genuinely signed, and they are
# the contexts the sub-strand exists to teach.
_CANNOT_BE_NEGATIVE: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("a count of people or things",
     re.compile(r"\b(surveys?|respondents?|frequenc\w+|tally|how many|"
                r"number of (?:people|learners|students|pupils|items|"
                r"responses|votes))\b", re.I),
     "counts and frequencies start at zero. There is no such thing as -15 "
     "people preferring coffee: a category is not a sign, and a learner told "
     "otherwise will write negative frequencies in a data-handling paper."),
    ("a pH reading",
     re.compile(r"\bpH\b", re.I),
     "the pH scale runs from 0 to 14 in school science and is read in "
     "decimals — blood is 7.4, lemon juice about 2.2. There is no negative pH "
     "at this level, so it is the wrong example for a directed number. "
     "Elevation above and below sea level, temperature either side of "
     "freezing, or a bank balance are the real ones."),
    ("a mass, length or volume",
     re.compile(r"\b(recipes?|ingredients?|cooking|grams?|kilograms?|"
                r"millilitres?|litres?|heights?|lengths?|widths?|masses|"
                r"weighs?|weight)\b", re.I),
     "a quantity of stuff starts at zero. A recipe is measured in grams and "
     "millilitres rather than shillings, and a plant is not -2 cm tall — what "
     "can be negative there is its POSITION relative to a mark, which is a "
     "different quantity with a different name. Use a context that is "
     "genuinely signed: temperature, altitude, or money owed."),
)

_GOES_NEGATIVE = re.compile(
    r"\bnegative\b|\bbelow zero\b|\bminus\b|\bsubtract\w*\b|"
    r"(?<![\d)])-\s?\d", re.I)


def _impossible_negative(examples: list[Any], what: str = "Example") -> list[Finding]:
    findings: list[Finding] = []
    for index, example in enumerate(examples or [], start=1):
        if not isinstance(example, dict):
            continue
        text = _text_of(example)
        if not _GOES_NEGATIVE.search(text):
            continue
        for kind, pattern, why in _CANNOT_BE_NEGATIVE:
            if pattern.search(text):
                findings.append(Finding(
                    "impossible_negative",
                    f"{what} {index} puts a negative value on {kind}: {why}",
                    "Move the example to a quantity that really is signed, or "
                    "drop it. A false real-life analogy is worse than a dry "
                    "example, because a learner believes it."))
                break
    return findings


# Notation that will print as it stands, and print as nonsense.
#
# The Grade 9 guide printed "$(6 + ×× 2$" and "$12×12× 2 - 3 + 1$" on the page
# a class reads. Both are what an unbalanced brace or a doubled command leaves
# behind, and the exercise beside them then answered "10 - 22 + 5 = 8", because
# the expression the solver was handed was not the expression on the page.
_MANGLED: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[+×÷*/^-]\s*[×÷*/^]"),
     "two operators in a row"),
    (re.compile(r"\d\s*[×÷]\s*\d+\s*[×÷]\s*\d+\s*[×÷]"),
     "a run of operators no expression has"),
    (re.compile(r"[+×÷*/^-]\s*\$"), "an expression that ends on an operator"),
    (re.compile(r"\\[a-zA-Z]+\s*\{[^}]*$"), "an unclosed LaTeX group"),
)


_LATEX_OP = re.compile(r"\\times|\\cdot|\\div|\\pm")


def _as_symbols(text: str) -> str:
    """LaTeX operators as the symbols they print, so one rule catches both."""
    return _LATEX_OP.sub(lambda m: {"\\times": "×", "\\cdot": "×",
                                    "\\div": "÷", "\\pm": "+"}[m.group(0)],
                         text or "")


def _mangled(examples: list[Any]) -> list[Finding]:
    findings: list[Finding] = []
    for index, example in enumerate(examples or [], start=1):
        if not isinstance(example, dict):
            continue
        text = _as_symbols(_text_of(example))
        if text.count("$") % 2:
            findings.append(Finding(
                "mangled_notation",
                f"Example {index} has an odd number of dollar signs, so the "
                f"maths and the words around it run together on the page.",
                "Close every $ … $ pair."))
        for pattern, what in _MANGLED:
            found = pattern.search(text)
            if found:
                findings.append(Finding(
                    "mangled_notation",
                    f"Example {index} contains {what}: "
                    f"\"{found.group(0).strip()}\". This prints exactly as it "
                    f"stands, in front of a class.",
                    "Write the expression again. A learner cannot answer what "
                    "nobody can read, and a solver given it computes something "
                    "else."))
                break
    return findings


# Claims about every case, and the counterexamples that break them.
_CLAIM_TESTS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"positive.{0,40}negative.{0,40}closer to zero", re.I),
     "-2 + 10 = 8",
     "adding a positive to a negative does not always move towards zero: "
     "-2 + 10 = 8 is further from zero than -2."),
    (re.compile(r"(?:sum|adding|addition).{0,30}two negatives?.{0,30}positive", re.I),
     "-2 + -3 = -5",
     "the sum of two negatives is negative, not positive."),
    (re.compile(r"subtract\w*.{0,40}(?:always|result\w*).{0,20}smaller", re.I),
     "5 - (-3) = 8",
     "subtracting does not always give something smaller: 5 - (-3) = 8."),
)


def _false_generalisation(text: str) -> Finding | None:
    if not _UNIVERSAL.search(text):
        return None
    for pattern, counter, why in _CLAIM_TESTS:
        if pattern.search(text):
            return Finding(
                "false_generalisation",
                f"It states a rule that does not hold: {why}",
                f"State the rule for the case it covers, or drop it. "
                f"Counterexample: {counter}.")
    return None


def check(examples: list[Any], *, grade: str = "", subject: str | None = None,
          strand: str = "", sub_strand: str = "") -> Report:
    """Every worked example, against the words around its arithmetic."""
    report = Report()
    for example in (examples or []):
        if not isinstance(example, dict):
            continue
        report.checked += 1
        text = _as_story(_text_of(example))
        for finding in (_direction_fault(text), _change_fault(text),
                        _false_generalisation(text)):
            if finding:
                # Which lesson wrote it, where the caller said. A story fault
                # with no lesson attached was a finding nothing could rewrite.
                lesson = example.get("_lesson")
                if isinstance(lesson, int) and lesson not in finding.lessons:
                    finding.lessons.append(lesson)
                report.findings.append(finding)

    # Difficulty is a property of the set, not of any one example in it.
    below = _too_easy(examples, grade, subject, strand, sub_strand)
    if below:
        report.findings.append(below)
    # And so is repetition: a second copy is only visible beside the first.
    report.findings += _duplicates(examples, grade, subject or "")
    report.findings += _mangled(examples)
    report.findings += _impossible_negative(examples)
    report.findings += _shape_faults(examples)
    report.findings += _arithmetic_faults(examples)
    report.findings += _order_faults(examples)
    report.findings += _missing_operations(examples, grade, subject or "",
                                           strand, sub_strand)
    return report


def check_material(material: dict[str, Any], *, grade: str = "",
                   subject: str | None = None, strand: str = "",
                   sub_strand: str = "") -> Report:
    """Every worked example in a lesson-material artifact."""
    examples: list[Any] = []
    for piece in (material.get("material") or []):
        if isinstance(piece, dict):
            examples += [e for e in (piece.get("worked_examples") or [])
                         if isinstance(e, dict)]
    return check(examples, grade=grade, subject=subject, strand=strand,
                 sub_strand=sub_strand)


# An equation stated in passing: "Division follows the same rules:
# $12 \times (-3) = -4$". Written as a multiplication it is false — the term is
# -36 — and the guide meant a division. Nothing looked at it, because the plan
# carries no worked examples and the prose scan only measured how HARD each
# expression was, never whether it was true.
# The bare-prose branch must not cross a `$`. It did, and spliced the tail of
# one expression onto the head of the next: from "(2 \times 4)$. Present the
# expression $5 + (3 - 2) \times 4" to "= 5" — an equation nobody wrote,
# reported as false, in text that made the checker look broken.
#
# And it must not stop in the MIDDLE of a chain. "5 + (3 - 2) \times 4 = 5 + 1
# \times 4 = 9" is true; reading it as "... = 5" is not. A chain belongs to the
# step checker, which walks it in order.
_PROSE_EQUATION = re.compile(
    r"\$([^$\n]{2,80}?=[^$\n]{1,40}?)\$|(?<![\w$])([-\d(][^=\n$]{1,60}?"
    r"=\s*-?[\d.]+)(?![\w$])(?!\s*[-+×÷*/^=])")


def _prose_equations(text: str) -> list[tuple[str, str]]:
    """Every `lhs = rhs` a passage asserts, as a pair to be checked."""
    out: list[tuple[str, str]] = []
    for match in _PROSE_EQUATION.finditer(text or ""):
        body = match.group(1) or match.group(2) or ""
        # A chained equation is checked step by step, not as a whole.
        if body.count("=") != 1:
            continue
        lhs, rhs = body.split("=")
        if lhs.strip() and rhs.strip():
            out.append((lhs.strip(), rhs.strip()))
    return out


def check_prose_arithmetic(texts: list[str]) -> list[Finding]:
    """Whether the equations a guide states in passing are true.

    The teacher's guide asserts its arithmetic in sentences rather than in
    worked examples, so the step-by-step checker never saw any of it. A guide
    that states a false equation in an aside teaches it exactly as effectively
    as one that states it in an example.
    """
    from . import worked_solutions

    findings: list[Finding] = []
    seen: set[str] = set()
    for text in texts:
        for lhs, rhs in _prose_equations(text)[:20]:
            key = re.sub(r"\s+", "", f"{lhs}={rhs}")
            if key in seen:
                continue
            seen.add(key)
            verdict = worked_solutions.check(lhs, rhs)
            if verdict["checked"] and verdict["agrees"] is False:
                findings.append(Finding(
                    "states_a_false_equation",
                    f"The guide states \"{lhs} = {rhs}\". The maths engine "
                    f"makes {lhs} equal {verdict['engine_answer']}.",
                    "Correct it. A false equation in an aside is taught as "
                    "effectively as one in a worked example, and a teacher "
                    "reads this aloud."))
    return findings


# A sentence that promises a problem and does not give one.
#
# "Present learners with real-life problems that require combined operations,
# such as calculating total expenses or profits." — what are the numbers? What
# are the expenses? A teacher who printed that guide still has to invent every
# problem in it, which is the work the guide exists to have done.
_PROMISES = re.compile(
    r"\b(present(?:s|ing)? (?:learners|them|the class) with"
    r"|work(?: through)? (?:some |a few |several )?(?:more )?examples"
    r"|solve (?:the following|these|expressions|problems)"
    r"|practise? (?:some|a few|several) (?:problems|expressions|examples)"
    r"|discuss(?:es|ing)? (?:some )?examples"
    r"|give (?:them )?(?:some )?(?:problems|examples)"
    r"|organi[sz]e a game|set (?:them )?(?:some )?(?:problems|questions)"
    # The ghost assessment: twenty minutes of class time allocated to "a mix
    # of multiple-choice questions and problem-solving tasks", and not one
    # question anywhere in the guide.
    r"|assessment activity|(?:sit|take|complete) (?:a |the )?(?:quiz|test)"
    r"|(?:a |the )?quiz (?:that|which|covering)"
    r"|multiple[- ]choice questions)\b",
    re.I)


def _promised_but_not_given(notes: dict[str, Any], grade: str, subject: str,
                            strand: str, sub_strand: str) -> list[Finding]:
    """A lesson that says it will present problems, and presents none."""
    from . import design_elements, lesson_material, task_demand

    row = lesson_material._design_row(grade, subject, sub_strand, strand)
    if not row or not design_elements.operations_named(row):
        return []

    empty: list[str] = []
    for number, module in enumerate(
            notes.get("modules") or notes.get("hour_modules") or [], start=1):
        if not isinstance(module, dict):
            continue
        lesson = int(module.get("module_number") or number)
        for segment in (module.get("exposition_segments") or []):
            if not isinstance(segment, dict):
                continue
            body = str(segment.get("body") or "")
            promise = _PROMISES.search(body)
            if not promise or task_demand.items_in_prose(body):
                continue
            empty.append(f"lesson {lesson}, \"{promise.group(0).strip()}\"")

    if not empty:
        return []
    shown = "; ".join(empty[:4])
    more = f" and {len(empty) - 4} more" if len(empty) > 4 else ""
    return [Finding(
        "promised_but_not_given",
        f"{len(empty)} passage(s) promise a problem and give none — {shown}"
        f"{more}. A teacher who printed this still has to invent every problem "
        f"in it, which is the work the guide exists to have done.",
        "Write the problem out: the numbers, the expression, and the answer. "
        "A description of an example is not an example.")]


def _lessons_without_maths(notes: dict[str, Any], grade: str, subject: str,
                          strand: str, sub_strand: str) -> list[Finding]:
    """A lesson in a mathematics sub-strand that contains no mathematics.

    Every check until now asked how HARD the expressions were and none asked
    whether there were any. So a guide came back with three expressions across
    six lessons — 240 minutes of instruction — and the demand gate looked at
    the three, found one of them adequate, and had nothing to say about the
    five lessons that contained none at all.

    A lesson that teaches an operation and shows none of it worked is a lesson
    that teaches nothing, and it is the reason the questions station has
    nothing to build a paper from.
    """
    from . import design_elements, lesson_material, task_demand

    row = lesson_material._design_row(grade, subject, sub_strand, strand)
    if not row or not design_elements.operations_named(row):
        # Not a sub-strand about operations — a lesson of prose is right here.
        return []

    empty: list[int] = []
    for number, module in enumerate(
            notes.get("modules") or notes.get("hour_modules") or [], start=1):
        if not isinstance(module, dict):
            continue
        text = str(module.get("teacher_exposition") or "")
        for segment in (module.get("exposition_segments") or []):
            if isinstance(segment, dict):
                text += " " + str(segment.get("body") or "")
        worked = module.get("worked_examples") or []
        if task_demand.items_in_prose(text) or worked:
            continue
        empty.append(int(module.get("module_number") or number))

    if not empty:
        return []
    return [Finding(
        "lesson_without_mathematics",
        f"Lesson{'' if len(empty) == 1 else 's'} "
        + ", ".join(str(n) for n in empty)
        + f" contain{'s' if len(empty) == 1 else ''} no mathematics at all — "
        f"not one expression, not one worked example. This sub-strand's design "
        f"is about "
        + ", ".join(sorted(design_elements.operations_named(row).values()))
        + ", and a lesson that teaches an operation and shows none of it "
          "worked is 40 minutes that teaches nothing.",
        "Put the arithmetic in. Every lesson works at least one expression "
        "through to its answer — that is also the only thing the questions "
        "station has to build a paper from.",
        lessons=list(empty))]


def _narrowed_objectives(notes: dict[str, Any], grade: str, subject: str,
                         strand: str, sub_strand: str) -> list[Finding]:
    """A lesson objective that asks for less than the outcome it cites.

    This is where multiplication and division actually went. A Grade 9 guide
    whose outcome reads "perform basic operations on Integers" wrote, as its
    own objective, "perform basic operations (ADDITION, SUBTRACTION) on
    integers" — and every station downstream then served that narrowed
    objective faithfully. Six lessons without a single product, decided by a
    parenthesis in one line, before a word of content was written.

    A generic outcome is not an invitation to pick two. What "basic
    operations" means for this sub-strand is what its own design says, and the
    design says so in words.
    """
    from . import design_elements, lesson_material

    row = lesson_material._design_row(grade, subject, sub_strand, strand)
    if not row:
        return []
    required = design_elements.operations_named(row)
    if len(required) < 2:
        return []

    findings: list[Finding] = []
    for number, module in enumerate(
            notes.get("modules") or notes.get("hour_modules") or [], start=1):
        if not isinstance(module, dict):
            continue
        objective = str(module.get("learning_intent") or "").strip()
        if not objective:
            continue
        named = design_elements.operations_named({"slos": [{"slo": objective}]})
        # Only where the objective ENUMERATES: an objective that names none is
        # generic, like the outcome, and is not narrowing anything.
        if not named or set(named) >= set(required):
            continue
        missing = {sym: name for sym, name in required.items() if sym not in named}
        findings.append(Finding(
            "objective_narrows_the_outcome",
            f"Lesson {number}'s objective names only "
            + ", ".join(sorted(named.values()))
            + ", and the design for this sub-strand requires "
            + ", ".join(sorted(required.values()))
            + f". Nothing downstream will teach "
            + ", ".join(sorted(missing.values()))
            + ", because the objective did not ask for it.",
            "Either widen the objective to what the outcome covers, or say in "
            "the plan which other lesson carries "
            + ", ".join(sorted(missing.values())) + "."))
    return findings


def _items_of(module: dict[str, Any]) -> list[dict[str, Any]]:
    """Every expression one lesson teaches from, wherever it is written."""
    from . import task_demand

    text = str(module.get("teacher_exposition") or "")
    for segment in (module.get("exposition_segments") or []):
        if isinstance(segment, dict):
            text += " " + str(segment.get("body") or "")
    items: list[dict[str, Any]] = list(task_demand.items_in_prose(text))
    items += [e for e in (module.get("worked_examples") or [])
              if isinstance(e, dict)]
    return items


def _lesson_by_lesson(notes: dict[str, Any], grade: str, subject: str,
                      strand: str, sub_strand: str) -> list[Finding]:
    """Each lesson against its own rung, instead of the guide against the floor.

    `check_set` pools every expression in the guide and asks whether the set
    reaches the grade. That is the right question for a question paper and the
    wrong one for a teacher's guide, because a class does not meet the set —
    it meets one lesson at a time. A guide whose lesson 2 works
    `-10 + 6 \times (-2)` carries the whole set over the floor while lessons 1,
    3 and 5 teach from single-operation arithmetic, and nothing says so.

    The rung comes from `lesson_handoff.ladder`, so an opening lesson is held
    to less than a closing one: what is enforced is that every lesson reaches
    SOMETHING at its own step, not that all six are equally hard.
    """
    from . import design_elements, lesson_handoff, lesson_material, task_demand

    modules = [m for m in (notes.get("modules") or notes.get("hour_modules") or [])
               if isinstance(m, dict)]
    floor = task_demand.floor_for(grade, subject)
    if not modules or floor is None:
        return []

    row = lesson_material._design_row(grade, subject, sub_strand, strand)
    signed_wanted = bool(row) and design_elements.wants_negatives(row)

    shallow: list[tuple[int, Any, Any]] = []
    unsigned: list[int] = []
    for module, step in zip(modules, lesson_handoff.ladder(len(modules), floor)):
        try:
            number = int(module.get("module_number") or step.lesson)
        except (TypeError, ValueError):
            number = step.lesson
        measured = [d for d in (task_demand.measure_item(i)
                                for i in _items_of(module)) if d.measurable]
        if not measured:
            # A lesson with no arithmetic at all is `_lessons_without_maths`.
            # Reporting it twice trains a reader to skim both.
            continue
        if not any(d.operations >= step.operations
                   and len(d.kinds) >= step.kinds
                   and d.depth >= step.depth
                   and (d.order_matters or not step.order_matters)
                   for d in measured):
            best = max(measured,
                       key=lambda d: (d.operations, len(d.kinds), d.depth))
            shallow.append((number, step, best))
        if signed_wanted and not any(d.negatives for d in measured):
            unsigned.append(number)

    findings: list[Finding] = []
    if shallow:
        worst = "; ".join(
            f"lesson {n} gets no further than `{d.expression}` "
            f"({d.operations} operation{'' if d.operations == 1 else 's'}, "
            f"{len(d.kinds)} kind{'' if len(d.kinds) == 1 else 's'}), where its "
            f"step asks for {s.operations} and {s.kinds}"
            for n, s, d in shallow[:4])
        findings.append(Finding(
            "lesson_below_its_own_step",
            f"{len(shallow)} lesson{'' if len(shallow) == 1 else 's'} never "
            f"reach the demand of their own position in the sub-strand: "
            f"{worst}. The guide as a whole can still clear the floor on one "
            f"hard expression in one lesson — but a class meets one lesson at "
            f"a time, and these ones are an easier grade for forty minutes.",
            "Work at least one expression per lesson at that lesson's step. "
            "Easier ones alongside it are the build-up and are wanted; what is "
            "not allowed is a lesson that never gets there.",
            lessons=[n for n, _s, _d in shallow]))
    if unsigned:
        findings.append(Finding(
            "lesson_without_negative_numbers",
            f"Lesson{'' if len(unsigned) == 1 else 's'} "
            + ", ".join(str(n) for n in unsigned)
            + f" work{'s' if len(unsigned) == 1 else ''} only on positive "
            f"numbers, in a sub-strand whose design is about directed ones. "
            f"The guide overall uses negatives, so the guide-wide check is "
            f"satisfied while these lessons teach none.",
            "Put a signed number in every lesson: a negative operand, a "
            "negative result, or a subtraction that crosses zero.",
            lessons=list(unsigned)))
    return findings


def check_notes(notes: dict[str, Any], *, grade: str = "",
                subject: str | None = None, strand: str = "",
                sub_strand: str = "") -> Report:
    """The teacher's guide, against the same floor its material is held to.

    The plan station receives the demand block and was never measured against
    it, so a plan could be built entirely from `3 + 5 = 8` and pass — and the
    material station then inherits those examples and writes them out. Checking
    the material and not the plan is checking the copy and not the original.
    """
    texts: list[str] = []
    for module in (notes.get("modules") or notes.get("hour_modules") or []):
        if not isinstance(module, dict):
            continue
        texts.append(str(module.get("teacher_exposition") or ""))
        for segment in (module.get("exposition_segments") or []):
            if isinstance(segment, dict):
                texts.append(str(segment.get("body") or ""))

    from . import task_demand

    items: list[Any] = []
    for text in texts:
        items += task_demand.items_in_prose(text)

    # Worked examples where a plan happens to carry them, judged in full, and
    # each one told which lesson it belongs to.
    for position, module in enumerate(
            notes.get("modules") or notes.get("hour_modules") or [], start=1):
        if isinstance(module, dict):
            try:
                number = int(module.get("module_number") or position)
            except (TypeError, ValueError):
                number = position
            items += [{**e, "_lesson": number}
                      for e in (module.get("worked_examples") or [])
                      if isinstance(e, dict)]

    report = check(items, grade=grade, subject=subject, strand=strand,
                   sub_strand=sub_strand)
    report.findings += check_prose_arithmetic(texts)
    report.findings += _narrowed_objectives(notes, grade, subject or "",
                                            strand, sub_strand)
    report.findings += _lessons_without_maths(notes, grade, subject or "",
                                              strand, sub_strand)
    report.findings += _lesson_by_lesson(notes, grade, subject or "",
                                         strand, sub_strand)
    report.findings += _promised_but_not_given(notes, grade, subject or "",
                                               strand, sub_strand)
    # The prose too, not only the worked examples. A plan states its false
    # analogy in a sentence — "integers represent data such as the pH levels of
    # substances" — and never writes it as an example, so a check that reads
    # only `worked_examples` never sees it.
    report.findings += _impossible_negative(
        [{"statement": t} for t in texts if t.strip()], what="Passage")
    return report
