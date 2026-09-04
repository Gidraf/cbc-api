"""Plain mathematics out of the LaTeX the rest of the system speaks.

Every string that reaches the solver dispatcher was written for a reader, not
for a parser. Questions arrive as `Work out: $\\frac{2}{3} + \\frac{1}{4}$` and
formulas as `A = \\frac{1}{2}bh`, because that is what renders in the console
and prints on the paper.

The dispatcher's patterns were written against plain text — `2/3 + 1/4`,
`base of 8 cm`. Neither shape ever matched a real question: `\\frac{2}{3}` is
not `2/3`, and `base of $8\\text{ cm}$` is not `base of 8 cm`. So every call
fell through to a stub that echoed the question back and called it solved.

`to_plain` is the one place that gap is closed. It is deliberately lossy — it
is not a LaTeX parser and does not need to be. It produces something the
dispatcher's regexes can read, and nothing downstream renders its output.
"""
from __future__ import annotations

import re

# \frac{a}{b} -> (a)/(b). Innermost first, so nested fractions unwrap by
# repetition rather than by a recursive parser.
_FRAC = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_SQRT = re.compile(r"\\sqrt\s*\{([^{}]*)\}")
# \text{ cm}, \mathrm{kg}, \operatorname{...} — the wrapper carries no maths.
_WRAPPER = re.compile(r"\\(?:text|textbf|textit|mathrm|mathbf|operatorname)\s*\{([^{}]*)\}")

_SYMBOLS: tuple[tuple[str, str], ...] = (
    (r"\left", ""), (r"\right", ""),
    (r"\times", "*"), (r"\cdot", "*"), (r"\ast", "*"),
    (r"\div", "/"),
    (r"\pm", "+"),
    (r"\pi", "pi"),
    (r"\%", "%"),
    (r"\$", ""),
    (r"\,", " "), (r"\;", " "), (r"\:", " "), (r"\!", ""), (r"\ ", " "),
    (r"\\", " "),
    (r"^\circ", " degrees"),
    ("°", " degrees"),
    ("²", "^2"), ("³", "^3"),
    ("−", "-"), ("–", "-"),  # unicode minus and en dash, both seen from LLMs
    ("×", "*"), ("÷", "/"),
)


def to_plain(text: str) -> str:
    """The same problem, written so a regex can read it.

    >>> to_plain(r"Work out: $\\frac{2}{3} + \\frac{1}{4}$")
    'Work out: 2/3 + 1/4'
    >>> to_plain(r"a base of $8\\text{ cm}$")
    'a base of 8 cm'
    """
    if not text:
        return ""

    out = str(text)

    # Math delimiters first: the content inside them is the mathematics, and
    # the markers themselves are noise once it is extracted.
    out = out.replace("$$", " ").replace("$", " ")
    out = out.replace(r"\[", " ").replace(r"\]", " ")
    out = out.replace(r"\(", " ").replace(r"\)", " ")

    for _ in range(6):  # depth guard; real questions nest one or two deep
        new = _WRAPPER.sub(r"\1", out)
        new = _FRAC.sub(r"(\1)/(\2)", new)
        new = _SQRT.sub(r"sqrt(\1)", new)
        if new == out:
            break
        out = new

    for needle, replacement in _SYMBOLS:
        out = out.replace(needle, replacement)

    # A bare (2)/(3) reads better to the fraction pattern as 2/3, but only when
    # both sides are plain integers — anything else keeps its brackets.
    out = re.sub(r"\((\d+)\)\s*/\s*\((\d+)\)", r"\1/\2", out)

    # Any command that survived carried no value; drop the backslash and keep
    # the word, so \alpha becomes alpha rather than vanishing mid-expression.
    out = re.sub(r"\\([a-zA-Z]+)", r"\1", out)
    out = out.replace("{", " ").replace("}", " ")

    return re.sub(r"\s+", " ", out).strip()
