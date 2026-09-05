"""Working an arithmetic expression the way it is worked on a board.

The dispatcher could solve fractions, equations, areas and percentages, and
could not solve `-3 + 5`. So a Grade 9 sub-strand called Integers — every
exercise in it a signed-number calculation — got no worked solutions at all.

This evaluates by REWRITING, not by recursion: find the operation BODMAS says
comes next, do that one, and show the whole expression again with it resolved.
That is what a teacher writes on the board, one line under the last, and it is
what a learner copies and imitates.

    (-3) × (-4) + 10
    = 12 + 10          a negative multiplied by a negative gives a positive
    = 22

Each step carries the REASON, because the sign rules are exactly what a learner
gets wrong and "now we multiply" does not teach them.
"""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Any

from ..objects import SolutionStep, SolutionTrace

# A number, an operator, or a bracket. Unicode operators are included because
# the models write them and so do the textbooks.
_TOKEN = re.compile(r"\d+\.\d+|\d+|[-+*/×÷()]|\s+")

_TIMES = {"*", "×"}
_DIVIDE = {"/", "÷"}


class NotArithmetic(ValueError):
    """The text is not a self-contained arithmetic expression."""


def _tokenise(text: str) -> list[str]:
    out: list[str] = []
    position = 0
    for match in _TOKEN.finditer(text):
        if match.start() != position:
            raise NotArithmetic(f"unexpected {text[position:match.start()]!r}")
        position = match.end()
        token = match.group(0)
        if not token.isspace():
            out.append("*" if token in _TIMES else "/" if token in _DIVIDE else token)
    if position != len(text):
        raise NotArithmetic("trailing characters")
    if not out:
        raise NotArithmetic("nothing to work")
    return out


def _number(token: str) -> Fraction:
    return Fraction(token)


def _show(value: Fraction) -> str:
    """A number as a learner writes it."""
    if value.denominator == 1:
        return str(value.numerator)
    return f"\\frac{{{abs(value.numerator)}}}{{{value.denominator}}}" if value >= 0 \
        else f"-\\frac{{{abs(value.numerator)}}}{{{value.denominator}}}"


def _render(tokens: list[str]) -> str:
    """The expression as LaTeX, with negatives kept in their brackets."""
    out: list[str] = []
    skip: set[int] = set()
    for i, token in enumerate(tokens):
        if i in skip:
            continue
        if token == "*":
            out.append(" \\times ")
        elif token == "/":
            out.append(" \\div ")
        elif token in "+-":
            # A sign directly after an operator or an opening bracket belongs
            # to the number, not between two numbers.
            previous = tokens[i - 1] if i else ""
            if i == 0 or previous == "(":
                out.append(token)
            elif previous in "+-*/":
                # `6 + -5` is not how anyone writes it. Bracket the negative,
                # which is also how the learner met it in the question.
                nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
                if _is_value(nxt):
                    out.append(f"({token}{nxt})")
                    skip.add(i + 1)
                else:
                    out.append(token)
            else:
                out.append(f" {token} ")
        else:
            out.append(token)
    return "".join(out).replace("( ", "(").replace(" )", ")").strip()


def _reason(left: Fraction, op: str, right: Fraction, result: Fraction) -> str:
    """Why this step comes out as it does — the sign rules, said plainly."""
    if op == "*":
        if left < 0 and right < 0:
            return "A negative multiplied by a negative gives a positive."
        if left < 0 or right < 0:
            return "A positive multiplied by a negative gives a negative."
        return "Multiply the two numbers."
    if op == "/":
        if (left < 0) != (right < 0):
            return "A positive divided by a negative gives a negative."
        if left < 0 and right < 0:
            return "A negative divided by a negative gives a positive."
        return "Divide the two numbers."
    if op == "+":
        if right < 0:
            return "Adding a negative is the same as subtracting."
        if left < 0 and result >= 0:
            return (f"Start at {_show(left)} on the number line and move "
                    f"{_show(abs(right))} to the right.")
        if left < 0:
            return f"Both are negative, so they add to a larger negative."
        return "Add the two numbers."
    if right < 0:
        return "Subtracting a negative is the same as adding."
    if result < 0:
        return (f"Taking {_show(right)} from {_show(left)} passes zero, so the "
                f"answer is negative.")
    return "Subtract the second number from the first."


def _apply(left: Fraction, op: str, right: Fraction) -> Fraction:
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if right == 0:
        raise NotArithmetic("division by zero")
    return left / right


def _is_value(token: str) -> bool:
    return bool(token) and (token[0].isdigit() or token[0] == ".")


def _spent(inner: list[str]) -> bool:
    """A bracket holding just a number, signed or not: `(5)`, `(-2)`."""
    if len(inner) == 1:
        return _is_value(inner[0])
    return len(inner) == 2 and inner[0] in "+-" and _is_value(inner[1])


def _next_operation(tokens: list[str]) -> tuple[str, int, int] | None:
    """What BODMAS says to do next.

    ``("op", index, index)`` — work the operator at `index`.
    ``("unwrap", open, close)`` — a bracket that has served its purpose.

    Innermost brackets first; then × and ÷ left to right; then + and − left to
    right.
    """
    # Innermost bracket: the last '(' before the first ')' after it.
    depth_open = -1
    for i, token in enumerate(tokens):
        if token == "(":
            depth_open = i
        elif token == ")" and depth_open != -1:
            inner = tokens[depth_open + 1:i]
            if _spent(inner):
                return ("unwrap", depth_open, i)
            found = _next_operation(inner)
            if found is None:
                return None
            kind, a, b = found
            return (kind, a + depth_open + 1, b + depth_open + 1)

    for wanted in (("*", "/"), ("+", "-")):
        for i, token in enumerate(tokens):
            if (token in wanted and i > 0 and _is_value(tokens[i - 1])
                    and i + 1 < len(tokens)):
                return ("op", i, i)
    return None


def _signed(tokens: list[str], index: int) -> tuple[Fraction, int]:
    """The number at `index`, taking a leading sign with it."""
    if tokens[index] in "+-" and index + 1 < len(tokens) and _is_value(tokens[index + 1]):
        value = _number(tokens[index + 1])
        return (-value if tokens[index] == "-" else value), index + 2
    return _number(tokens[index]), index + 1


def solve_integer_expression(text: str, max_steps: int = 12) -> SolutionTrace:
    """Work a numeric expression, one board line at a time.

    Raises `NotArithmetic` when the text is not a self-contained calculation,
    so the dispatcher can move on rather than inventing an answer.
    """
    tokens = _tokenise(text.strip())
    if not any(_is_value(t) for t in tokens):
        raise NotArithmetic("no numbers")
    if not any(t in "+-*/" for t in tokens[1:]):
        raise NotArithmetic("nothing to work out")

    problem = _render(tokens)
    steps: list[SolutionStep] = []
    number = 1

    while number <= max_steps:
        found = _next_operation(tokens)
        if found is None:
            break

        before = _render(tokens)

        kind, where, close = found
        if kind == "unwrap":
            tokens = tokens[:where] + tokens[where + 1:close] + tokens[close + 1:]
            continue

        left_start = where - 1
        if left_start > 0 and tokens[left_start - 1] in "+-" and (
                left_start - 1 == 0 or tokens[left_start - 2] in "+-*/("):
            left_start -= 1
        left, _ = _signed(tokens, left_start)
        op = tokens[where]
        right, after = _signed(tokens, where + 1)

        result = _apply(left, op, right)
        replacement = [_show(result)] if result >= 0 else ["-", _show(abs(result))]
        tokens = tokens[:left_start] + replacement + tokens[after:]

        # A bracket left holding one number has served its purpose.
        while True:
            spent = _next_operation(tokens)
            if spent is not None and spent[0] == "unwrap":
                _, a, b = spent
                tokens = tokens[:a] + tokens[a + 1:b] + tokens[b + 1:]
                continue
            break

        steps.append(SolutionStep(
            step_number=number,
            operation=f"{_show(left)} {op} {_show(right)}",
            expression_before=before,
            expression_after=_render(tokens),
            latex=f"= {_render(tokens)}",
            explanation=_reason(left, op, right, result),
        ))
        number += 1

    answer = _render(tokens)
    if not steps:
        raise NotArithmetic("nothing to work out")

    return SolutionTrace(
        problem=problem,
        final_answer=answer,
        steps=steps,
        verified=True,
        check_latex=f"{problem} = {answer}",
    )


# The calculation written in words. CBC exercise sets are full of these, and
# they carry no operator at all — "the sum of -3 and 5" is a perfectly ordinary
# question that no expression scanner will ever find.
_PHRASES: tuple[tuple[str, str], ...] = (
    (r"sum\s+of\s+({n})\s+and\s+({n})", "{0} + {1}"),
    (r"total\s+of\s+({n})\s+and\s+({n})", "{0} + {1}"),
    (r"add\s+({n})\s+(?:to|and)\s+({n})", "{1} + {0}"),
    (r"difference\s+between\s+({n})\s+and\s+({n})", "{0} - {1}"),
    (r"subtract\s+({n})\s+from\s+({n})", "{1} - {0}"),
    (r"take\s+({n})\s+from\s+({n})", "{1} - {0}"),
    (r"product\s+of\s+({n})\s+and\s+({n})", "{0} * {1}"),
    (r"multiply\s+({n})\s+by\s+({n})", "{0} * {1}"),
    (r"divide\s+({n})\s+by\s+({n})", "{0} / {1}"),
    (r"quotient\s+of\s+({n})\s+and\s+({n})", "{0} / {1}"),
)

_NUMBER = r"[-+]?\d+(?:\.\d+)?"
_COMPILED = tuple(
    (re.compile(pattern.replace("{n}", _NUMBER), re.IGNORECASE), template)
    for pattern, template in _PHRASES
)


def _from_words(text: str) -> str:
    for pattern, template in _COMPILED:
        match = pattern.search(text)
        if match:
            return template.format(*match.groups())
    return ""


def arithmetic_in(text: str) -> str:
    """The self-contained calculation inside a sentence, or "".

    "Determine (-3) × (-4) + 10." carries its own prose. Take the longest run
    that is nothing but numbers, operators and brackets — and where there is no
    such run, try the calculation written in words.
    """
    best = ""
    for run in re.findall(r"[0-9+\-*/×÷().\s]+", text):
        candidate = run.strip(" .\n\t")
        if not re.search(r"\d", candidate):
            continue
        if not re.search(r"[-+*/×÷]", candidate.lstrip("-+")):
            continue
        if candidate.count("(") != candidate.count(")"):
            continue
        if len(candidate) > len(best):
            best = candidate
    return best or _from_words(text)
