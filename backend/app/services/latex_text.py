"""LaTeX as a person writes it on a board, and as a teacher says it aloud.

Questions are stored in LaTeX — `$\\frac{3}{4}$`, `$x^2$`, `$\\sqrt[3]{216}$`,
`$2x + 3 \\le 12$` — because that is what prints. The voice read it as
written ("backslash frac three four") and the whiteboard wrote `\\frac` in
chalk. Two readings of the same source:

* `to_unicode` — what a hand writes: 3/4, x², ∛216, 2x + 3 ≤ 12, 45°.
* `to_speech` — what a teacher says: "3/4" (said "3 quarters" by the
  narration's own fraction rule), "x squared", "the cube root of 216",
  "2x plus 3 is less than or equal to 12", "45 degrees".

Neither is a LaTeX parser; both handle what question writers actually use.
"""
from __future__ import annotations

import re

_SUP = str.maketrans("0123456789+-=()ni", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ")
_SUB = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
_GREEK = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "theta": "θ", "lambda": "λ", "mu": "μ",
          "pi": "π", "sigma": "σ", "phi": "φ", "omega": "ω", "Delta": "Δ", "Sigma": "Σ", "Omega": "Ω"}
_SYMBOLS = {"times": "×", "div": "÷", "cdot": "·", "pm": "±", "mp": "∓", "le": "≤", "leq": "≤", "ge": "≥",
            "geq": "≥", "ne": "≠", "neq": "≠", "approx": "≈", "infty": "∞", "angle": "∠", "triangle": "△",
            "degree": "°", "circ": "°", "cdots": "⋯", "ldots": "…", "dots": "…", "to": "→", "rightarrow": "→",
            "Rightarrow": "⇒", "iff": "⇔", "therefore": "∴", "perp": "⊥", "parallel": "∥", "sim": "~",
            "propto": "∝", "in": "∈", "cup": "∪", "cap": "∩", "%": "%", "$": "$", "{": "{", "}": "}",
            "sin": "sin", "cos": "cos", "tan": "tan", "log": "log", "ln": "ln", **_GREEK}
_SAY = {"times": " times ", "div": " divided by ", "cdot": " times ", "pm": " plus or minus ", "mp": " minus or plus ",
        "le": " is less than or equal to ", "leq": " is less than or equal to ",
        "ge": " is greater than or equal to ", "geq": " is greater than or equal to ",
        "ne": " is not equal to ", "neq": " is not equal to ", "approx": " is approximately ", "infty": " infinity ",
        "angle": " angle ", "triangle": " triangle ", "degree": " degrees", "circ": " degrees",
        "cdots": ", and so on, ", "ldots": ", and so on, ", "dots": ", and so on, ", "to": " to ",
        "rightarrow": " gives ", "Rightarrow": " which gives ", "iff": " if and only if ", "therefore": " therefore ",
        "perp": " is perpendicular to ", "parallel": " is parallel to ", "propto": " is proportional to ",
        "sin": " sine ", "cos": " cosine ", "tan": " tangent ", "log": " log ", "ln": " natural log ",
        "%": " percent", "$": "$", "{": "", "}": "", **{k: f" {k} " for k in _GREEK}}
_ORDINAL_POWER = {"2": "squared", "3": "cubed"}
_UNITS = {"mm", "cm", "dm", "m", "km", "ft", "in", "yd", "mi"}

_WRAPPERS = re.compile(r"\\(?:text|textbf|textit|mathrm|mathbf|mathit|operatorname|boxed|displaystyle)\s*\{([^{}]*)\}")
_FRAC = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_ROOT = re.compile(r"\\sqrt\s*(?:\[\s*([^\]]+?)\s*\])?\s*\{([^{}]*)\}")
_SPACING = re.compile(r"\\(?:left|right|big|Big|bigg|Bigg)(?![A-Za-z])|\\[,;:! ]|\\q?quad(?![A-Za-z])")


def _prepare(text: str) -> str:
    t = str(text or "").replace("{,}", ",")
    t = re.sub(r"\\\\(?=[A-Za-z{}()\[\],;:! %$])", r"\\", t)   # `\\frac` stored doubled
    t = t.replace("$$", " ").replace("$", " ").replace("\\(", " ").replace("\\)", " ")
    t = t.replace("\\[", " ").replace("\\]", " ")
    t = _SPACING.sub(" ", t)
    for _ in range(4):
        t = _WRAPPERS.sub(r"\1", t)
    # Braced powers first, so a fraction of powers has no braces inside it:
    # p^{11} is p^11, p^{7+4} is p^(7+4).
    t = re.sub(r"\^\s*\{\s*([^{}]*?)\s*\}",
               lambda m: "^" + (m.group(1) if re.fullmatch(r"-?\w+|\\circ", m.group(1)) else f"({m.group(1)})"), t)
    return t


def _simple(x: str) -> bool:
    """One term: 7, x, 2.5, or a single power such as 7^8 or x^{10}."""
    return bool(re.fullmatch(r"\s*-?[\w.]+(?:\s*\^\s*\{?\s*-?\w+\s*\}?)?\s*", x))


def _wrap(x: str) -> str:
    x = x.strip()
    return x if _simple(x) or re.fullmatch(r"[\w.^{}²³⁰-⁹]+", x) else f"({x})"


_OPERAND_L = r"(?<=[\w)\]%°²³])"
_OPERAND_R = r"(?=\s*[\w(\[√∛−-])"


def _ascii_maths(t: str) -> str:
    """Operators typed the computer way — 35 * 120, a <= b, sqrt(169) —
    written the way a learner writes them: 35 × 120, a ≤ b, √(169)."""
    t = re.sub(_OPERAND_L + r"\s*\*\s*" + _OPERAND_R, " × ", t)
    t = re.sub(r"\s*<=\s*", " ≤ ", t)
    t = re.sub(r"\s*>=\s*", " ≥ ", t)
    t = re.sub(r"\s*!=\s*", " ≠ ", t)
    t = re.sub(r"\bsqrt\s*\(", "√(", t)
    t = re.sub(r"\bcbrt\s*\(", "∛(", t)
    return t


def to_unicode(text: str) -> str:
    """LaTeX written as a hand writes it."""
    t = _prepare(text)
    for _ in range(6):
        new = _FRAC.sub(lambda m: f"{_wrap(m.group(1))}/{_wrap(m.group(2))}", t)
        new = _ROOT.sub(lambda m: {"3": "∛", "4": "∜"}.get((m.group(1) or "").strip(), (m.group(1) or "").translate(_SUP) + "√")
                        + (m.group(2).strip() if _simple(m.group(2)) else f"({m.group(2).strip()})"), new)
        if new == t:
            break
        t = new
    t = re.sub(r"\^\s*(?:\{\s*\\circ\s*\}|\\circ)", "°", t)

    def sup(m: re.Match) -> str:
        body = m.group(1) if m.group(1) is not None else m.group(2)
        body = body.strip()
        return body.translate(_SUP) if re.fullmatch(r"[0-9+\-=()ni]+", body) else f"^({body})" if len(body) > 1 else f"^{body}"

    def sub(m: re.Match) -> str:
        body = (m.group(1) if m.group(1) is not None else m.group(2)).strip()
        return body.translate(_SUB) if re.fullmatch(r"[0-9+\-=()]+", body) else f"_{body}"

    t = re.sub(r"\^\s*(?:\(([^()]*)\)|(-?\w+))", sup, t)
    t = re.sub(r"_\s*(?:\{([^{}]*)\}|(\w))", sub, t)
    t = re.sub(r"\\([A-Za-z]+|[%${}])", lambda m: _SYMBOLS.get(m.group(1), m.group(1)), t)
    t = t.replace("{", "").replace("}", "").replace("−", "-")
    t = _ascii_maths(t)
    t = re.sub(r"[ \t]+([.,;:?!])", r"\1", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def _power_words(base: str, power: str) -> str:
    power = power.strip()
    power = re.sub(r"(?<=\w)\s*-\s*(?=\w)", " minus ", re.sub(r"(?<=\w)\s*\+\s*(?=\w)", " plus ", power))
    if power in _ORDINAL_POWER:
        return f"{base} {_ORDINAL_POWER[power]}"
    if power.startswith("-"):
        return f"{base} to the power of negative {power[1:]}"
    return f"{base} to the power of {power}"


def _said_part(x: str, denominator: bool = False) -> str:
    x = x.strip()
    if _simple(x):
        return x
    return f"the quantity {x}," if denominator else f"{x}, all"


def to_speech(text: str) -> str:
    """LaTeX said as a teacher says it. Plain prose passes through."""
    raw = str(text or "")
    if not re.search(r"[\\^$_∛∜√²³*×÷=<>≤≥≠≈±+]|sqrt|cbrt|\s[−-]\s|(?<![\w)])[−-]\d", raw):
        return raw
    t = _ascii_maths(_prepare(raw))
    # Symbols a voice would otherwise read aloud as "star" or skip.
    t = re.sub(r"\s*[×*]\s*", " times ", t)
    t = re.sub(r"\s*÷\s*", " divided by ", t)
    t = re.sub(r"\s*≤\s*", " is less than or equal to ", t)
    t = re.sub(r"\s*≥\s*", " is greater than or equal to ", t)
    t = re.sub(r"\s*≠\s*", " is not equal to ", t)
    t = re.sub(r"\s*≈\s*", " is approximately ", t)
    t = re.sub(r"\s*±\s*", " plus or minus ", t)
    t = re.sub(r"\bapprox\.?(?=\s)", "approximately", t)
    t = re.sub(r"√\s*\(([^()]*)\)", r" the square root of \1 ", t)
    t = re.sub(r"∛\s*\(([^()]*)\)", r" the cube root of \1 ", t)
    # Unicode already in the text: ∛343, √16, 5³, x² (but "125 m³" is a unit,
    # said "cubic metres" by the narration's unit rule).
    t = re.sub(r"∛\s*(\(?[\w.]+\)?)", r" the cube root of \1 ", t)
    t = re.sub(r"∜\s*(\(?[\w.]+\)?)", r" the fourth root of \1 ", t)
    t = re.sub(r"√\s*(\(?[\w.]+\)?)", r" the square root of \1 ", t)
    t = re.sub(r"(\d|(?<!\d )(?<![\d])\b[a-zA-Z]|\))([²³])", lambda m: m.group(1) + (" squared" if m.group(2) == "²" else " cubed"), t)
    for _ in range(6):
        new = _FRAC.sub(lambda m: (f"{m.group(1).strip()}/{m.group(2).strip()}"
                                   if re.fullmatch(r"\s*-?\d+\s*", m.group(1)) and re.fullmatch(r"\s*\d+\s*", m.group(2))
                                   else f" {_said_part(m.group(1))} over {_said_part(m.group(2), True)} "), t)
        new = _ROOT.sub(lambda m: {"": " the square root of ", "2": " the square root of ", "3": " the cube root of ",
                                   "4": " the fourth root of "}.get((m.group(1) or "").strip(),
                                                                   f" the {(m.group(1) or '').strip()}th root of ")
                        + m.group(2).strip() + " ", new)
        if new == t:
            break
        t = new
    t = re.sub(r"\^\s*(?:\{\s*\\circ\s*\}|\\circ)", " degrees", t)
    t = re.sub(r"\\log\s*_\s*\{?\s*(\w+)\s*\}?", r" log to base \1 of ", t)
    def power(m: re.Match) -> str:
        # "8 cm^3" is a unit, said "cubic centimetres" by the unit rule.
        if m.group(1) in _UNITS and re.search(r"\d\s*$", t[:m.start()]):
            return m.group(0)
        return _power_words(m.group(1), m.group(2) if m.group(2) is not None else m.group(3))

    t = re.sub(r"([\w)]+)\s*\^\s*(?:\(([^()]*)\)|(-?\w+))", power, t)
    t = re.sub(r"(\w)\s*_\s*\{?\s*(\w+)\s*\}?", r"\1 \2", t)
    t = re.sub(r"\\([A-Za-z]+|[%${}])", lambda m: _SAY.get(m.group(1), f" {m.group(1)} "), t)
    t = t.replace("{", " ").replace("}", " ")
    t = re.sub(r"(?<=[\w)])\s*=\s*(?=[\w(-])", " equals ", t)
    t = re.sub(r"(?<=[\w)])\s*<\s*(?=[\w(-])", " is less than ", t)
    t = re.sub(r"(?<=[\w)])\s*>\s*(?=[\w(-])", " is greater than ", t)
    t = re.sub(r"(?<=[\w)])\s+[−-]\s+(?=[\w(])", " minus ", t)
    t = re.sub(r"(?<=[\w)])\s*\+\s*(?=[\w(])", " plus ", t)
    t = re.sub(r"(?<![\w)])[−-](?=\d)", "negative ", t)
    t = re.sub(r"\s+([.,;:?!])", r"\1", t)
    return re.sub(r"\s{2,}", " ", t).strip()
