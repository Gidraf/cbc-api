"""Every question, playable.

A question in the bank already carries what a game needs: an expression the
engine can work (the writer's translation of the situation), a key the engine
has verified, distractors that each name a mistake. This turns that into a
PLAY SPEC — one of a handful of interaction kinds — and a WALKTHROUGH, the
narrated, animated explanation a teacher would give at the board.

The model chooses; the engine fills. A writer (a provider, Antigravity, a
local model) may say which kind suits an item — `"interaction": {"kind":
"number_line"}` — and may supply the data; every number in a spec comes from
the engine, so a spec cannot teach a wrong sum. An item with no hint gets the
kind its expression supports.

Kinds, for mathematics:

  choice        any multiple-choice item — the quiz race; a wrong pick shows
                the rationale of the distractor chosen
  bodmas        a calculation, one operation at a time — the learner taps the
                operation that comes next, then gives its value
  number_line   a chain of additions and subtractions of integers — start,
                jumps, landing point; temperatures, depths, balances
  balance       a linear equation in x — the learner does the same thing to
                both sides until x stands alone
  fraction_bar  the sum or difference of two fractions — bars cut into the
                denominators, then into the common denominator
"""
from __future__ import annotations

import logging
import math
import re
from fractions import Fraction
from typing import Any

logger = logging.getLogger("cbc-play-engine")

KINDS = ("choice", "bodmas", "number_line", "balance", "fraction_bar")


# ── reading an expression ───────────────────────────────────────────────────

def _clean(expression: str) -> str:
    text = str(expression or "").strip().strip("$")
    text = re.sub(r"\\(?:left|right)", "", text)
    text = text.replace("\\times", "*").replace("\\cdot", "*").replace("×", "*")
    text = text.replace("\\div", "/").replace("÷", "/").replace("−", "-").replace("–", "-")
    text = re.sub(r"\\[dt]?frac\{([^{}]+)\}\{([^{}]+)\}", r"((\1)/(\2))", text)
    text = text.replace("{", "(").replace("}", ")").replace("[", "(").replace("]", ")")
    return re.sub(r"\s+", " ", text).strip()


def _num(value: Fraction) -> int | float | str:
    """A value as the learner sees it: an integer, a decimal, or a/b."""
    if value.denominator == 1:
        return int(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _show(value: Fraction) -> str:
    return str(_num(value))


def structured_steps(expression: str, max_steps: int = 14) -> list[dict[str, Any]] | None:
    """The engine's board lines with what each one did, in a form a player
    can animate: the expression before, the operation (left, op, right),
    its result, the expression after, and the reason.

    Re-uses the integer solver's own rewriting, so the game's order of
    operations is the marking scheme's, step for step."""
    from .math_engine.solvers import integers as I

    try:
        tokens = I._tokenise(I._normalise(_clean(expression)).strip())
    except Exception:  # noqa: BLE001
        return None
    if not any(I._is_value(t) for t in tokens) or not any(t in "+-*/^" for t in tokens[1:]):
        return None
    out: list[dict[str, Any]] = []
    try:
        for _ in range(max_steps):
            found = I._next_operation(tokens)
            if found is None:
                break
            kind, where, close = found
            if kind == "unwrap":
                tokens = tokens[:where] + tokens[where + 1:close] + tokens[close + 1:]
                continue
            before = I._render(tokens)
            left_start = where - 1
            if left_start > 0 and tokens[left_start - 1] in "+-" and (
                    left_start - 1 == 0 or tokens[left_start - 2] in "+-*/("):
                left_start -= 1
            left, _ = I._signed(tokens, left_start)
            op = tokens[where]
            right, after = I._signed(tokens, where + 1)
            result = I._apply(left, op, right)
            replacement = [I._show(result)] if result >= 0 else ["-", I._show(abs(result))]
            tokens = tokens[:left_start] + replacement + tokens[after:]
            while True:
                spent = I._next_operation(tokens)
                if spent is not None and spent[0] == "unwrap":
                    _, a, b = spent
                    tokens = tokens[:a] + tokens[a + 1:b] + tokens[b + 1:]
                    continue
                break
            out.append({
                "before": before, "after": I._render(tokens),
                "left": _num(left), "op": {"*": "×", "/": "÷"}.get(op, op), "right": _num(right),
                "result": _num(result), "why": I._reason(left, op, right, result),
            })
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not structure %r: %s", expression, exc)
        return None
    return out or None


def value_of(expression: str) -> Fraction | None:
    steps = structured_steps(expression)
    if not steps:
        try:
            return Fraction(_clean(expression))
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return Fraction(str(steps[-1]["result"]))
    except (ValueError, ZeroDivisionError):
        return None


# ── kinds, derived from the expression ──────────────────────────────────────

_CHAIN = re.compile(r"^\s*\(?\s*[-+]?\s*\d+\s*\)?(\s*[-+]\s*\(?\s*[-+]?\s*\d+\s*\)?)+\s*$")


def number_line(expression: str) -> dict[str, Any] | None:
    """A chain of integers added and subtracted: −18 + 12 − 5 + 8."""
    text = _clean(expression)
    if not _CHAIN.match(text) or "*" in text or "/" in text:
        return None
    terms = re.findall(r"([-+]?)\s*\(?\s*([-+]?)\s*(\d+)\s*\)?", text)
    values: list[int] = []
    for n, (outer, inner, digits) in enumerate(terms):
        sign = -1 if (outer == "-") ^ (inner == "-") else 1
        values.append(sign * int(digits))
    if len(values) < 2:
        return None
    start, moves = values[0], values[1:]
    points = [start]
    for move in moves:
        points.append(points[-1] + move)
    lo, hi = min(points), max(points)
    pad = max(2, (hi - lo) // 6 or 2)
    step = 1 if hi - lo <= 24 else 5 if hi - lo <= 120 else 10
    return {"kind": "number_line", "start": start, "moves": moves, "points": points, "target": points[-1],
            "min": (lo - pad) // step * step, "max": -((-(hi + pad)) // step) * step, "tick": step}


def bodmas(expression: str) -> dict[str, Any] | None:
    steps = structured_steps(expression)
    if not steps or len(steps) < 2:
        return None
    return {"kind": "bodmas", "expression": steps[0]["before"], "steps": steps, "target": steps[-1]["result"]}


_FRAC_PAIR = re.compile(r"^\s*\(?\(?(\d+)\)?\s*/\s*\(?(\d+)\)?\)?\s*([-+])\s*\(?\(?(\d+)\)?\s*/\s*\(?(\d+)\)?\)?\s*$")


def fraction_bar(expression: str) -> dict[str, Any] | None:
    m = _FRAC_PAIR.match(_clean(expression))
    if not m:
        return None
    a, b, op, c, d = int(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4)), int(m.group(5))
    if not b or not d or b > 24 or d > 24:
        return None
    lcd = b * d // math.gcd(b, d)
    result = Fraction(a, b) + Fraction(c, d) if op == "+" else Fraction(a, b) - Fraction(c, d)
    return {"kind": "fraction_bar", "first": [a, b], "second": [c, d], "op": op, "common": lcd,
            "first_as": [a * lcd // b, lcd], "second_as": [c * lcd // d, lcd],
            "result": [result.numerator, result.denominator], "target": _num(result)}


def balance(expression: str) -> dict[str, Any] | None:
    """A linear equation in one unknown, solved by doing the same thing to
    both sides. Sympy reads it; each move is checked by substituting."""
    text = _clean(expression)
    if text.count("=") != 1:
        return None
    letters = sorted(set(re.findall(r"(?<![a-zA-Z])([a-zA-Z])(?![a-zA-Z])", text)))
    if len(letters) != 1:
        return None
    var = letters[0]
    try:
        import sympy as sp

        x = sp.Symbol(var)
        lhs_s, rhs_s = text.split("=")
        tr = (sp.parsing.sympy_parser.standard_transformations
              + (sp.parsing.sympy_parser.implicit_multiplication_application,))
        lhs = sp.parsing.sympy_parser.parse_expr(lhs_s, local_dict={var: x}, transformations=tr)
        rhs = sp.parsing.sympy_parser.parse_expr(rhs_s, local_dict={var: x}, transformations=tr)
        poly = sp.Poly(sp.expand(lhs - rhs), x)
        if poly.degree() != 1:
            return None
        solution = sp.solve(sp.Eq(lhs, rhs), x)
        if len(solution) != 1:
            return None
        root = sp.nsimplify(solution[0])
        a1, b1 = sp.Poly(sp.expand(lhs), x).all_coeffs() if sp.expand(lhs).has(x) else (0, sp.expand(lhs))
        a2, b2 = sp.Poly(sp.expand(rhs), x).all_coeffs() if sp.expand(rhs).has(x) else (0, sp.expand(rhs))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Not a linear equation %r: %s", expression, exc)
        return None

    def frac(v: Any) -> Fraction:
        return Fraction(str(sp.nsimplify(v)))

    a1, b1, a2, b2 = map(frac, (a1, b1, a2, b2))
    moves: list[dict[str, Any]] = []
    # x-terms to the left, numbers to the right, then divide.
    if a2:
        term = f"{'' if a2 == 1 else _show(a2)}{var}"
        moves.append({"op": "-", "value": term, "why": f"Take {term} from both sides."})
        a1, a2 = a1 - a2, Fraction(0)
    if b1:
        sign = "-" if b1 > 0 else "+"
        moves.append({"op": sign, "value": _show(abs(b1)),
                      "why": f"{'Take' if b1 > 0 else 'Add'} {_show(abs(b1))} {'from' if b1 > 0 else 'to'} both sides."})
        b2, b1 = b2 - b1, Fraction(0)
    if a1 != 1:
        moves.append({"op": "÷", "value": _show(a1), "why": f"Divide both sides by {_show(a1)}."})
    target = frac(root)
    return {"kind": "balance", "variable": var, "left": lhs_s.strip(), "right": rhs_s.strip(),
            "moves": moves, "target": _num(target)}


DERIVERS = {"number_line": number_line, "fraction_bar": fraction_bar, "balance": balance, "bodmas": bodmas}
# What an item with no hint becomes, first match wins: the most visual model
# the expression supports.
AUTO_ORDER = ("balance", "fraction_bar", "number_line", "bodmas")


def _expression_of(question: dict[str, Any]) -> str:
    expr = str(question.get("expression") or "").strip()
    if expr:
        return expr
    # A bare calculation item: "Work out $(-6) \\times (-4) + 8$" carries its
    # expression in the stem.
    stem = str(question.get("question_text") or "")
    spans = re.findall(r"\$([^$]+)\$", stem)
    return max(spans, key=len) if spans else ""


def _choice(question: dict[str, Any]) -> dict[str, Any] | None:
    options = [o for o in (question.get("options") or []) if isinstance(o, dict) and o.get("id")]
    if len(options) < 2 or sum(1 for o in options if o.get("is_correct")) != 1:
        return None
    return {"kind": "choice", "options": [
        {"id": o["id"], "text": str(o.get("text") or ""), "correct": bool(o.get("is_correct")),
         "why": str(o.get("distractor_rationale") or o.get("rationale") or "")} for o in options]}


def spec_for(question: dict[str, Any]) -> dict[str, Any]:
    """The play spec for one item: the writer's chosen kind where the engine
    can fill it, else the most visual kind the expression supports, plus the
    choice game for any multiple-choice item. Never raises."""
    hint = question.get("interaction") if isinstance(question.get("interaction"), dict) else {}
    wanted = str((hint or {}).get("kind") or "").strip().lower()
    expression = _expression_of(question)
    spec: dict[str, Any] | None = None
    note = ""
    if expression:
        if wanted in DERIVERS:
            spec = DERIVERS[wanted](expression)
            if spec is None:
                note = f"the writer asked for {wanted}, which this expression does not support"
        if spec is None:
            for kind in AUTO_ORDER:
                spec = DERIVERS[kind](expression)
                if spec is not None:
                    break
    choice = _choice(question)
    out: dict[str, Any] = {"primary": spec or choice, "choice": choice, "expression": expression}
    if note:
        out["note"] = note
    if spec is not None:
        out["key_agrees"] = _key_agrees(question, spec)
    return out


def _key_agrees(question: dict[str, Any], spec: dict[str, Any]) -> bool | None:
    """Whether the item's key is the value the spec arrives at. None where
    the item has no comparable key."""
    key = next((o for o in (question.get("options") or []) if isinstance(o, dict) and o.get("is_correct")), None)
    text = str((key or {}).get("text") or question.get("model_answer") or "")
    target = spec.get("target")
    if target is None or not text:
        return None
    nums = _values_in(text)
    try:
        want = Fraction(str(target))
    except (ValueError, ZeroDivisionError):
        return None
    return any(n == want for n in nums) if nums else None


def _values_in(text: str) -> list[Fraction]:
    """Every number a key states: $\\frac{7}{10}$, 0.7, −8°C, KSh 1,592."""
    t = str(text).replace("−", "-").replace("–", "-")
    t = re.sub(r"\\[dt]?frac\{\s*(-?\d+)\s*\}\{\s*(\d+)\s*\}", r"\1/\2", t)
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)
    out: list[Fraction] = []
    for n in re.findall(r"-?\d+(?:\.\d+)?(?:/\d+)?", t):
        try:
            out.append(Fraction(n))
        except (ValueError, ZeroDivisionError):
            continue
    return out


# ── checking a learner's move ───────────────────────────────────────────────

def check_answer(expected: Any, given: Any) -> bool:
    """Whether what the learner typed is the value: 3/4, 0.75 and 6/8 agree."""
    def read(v: Any) -> Fraction | None:
        text = _clean(str(v)).replace(" ", "")
        try:
            return Fraction(text)
        except (ValueError, ZeroDivisionError):
            got = value_of(text)
            return got
    a, b = read(expected), read(given)
    return a is not None and b is not None and a == b


# ── the walkthrough: a teacher at the board ─────────────────────────────────

def walkthrough(question: dict[str, Any], *, grade: str = "") -> dict[str, Any]:
    """Scenes for the animated, narrated explanation of one item.

    Every scene is a template the player knows how to animate, filled with
    the engine's numbers, and one or two sentences of narration a teacher
    would say. No model is called: the words come from the engine's reasons,
    so a walkthrough is instant and costs nothing.
    """
    play = spec_for(question)
    spec = play.get("primary") or {}
    stem = re.sub(r"\s+", " ", str(question.get("question_text") or "")).strip()
    situation = re.sub(r"\s+", " ", str(question.get("stimulus_context") or "")).strip()
    scenes: list[dict[str, Any]] = [{
        "scene": "title", "text": stem, "context": situation,
        "say": (situation + " " if situation else "") + _speakable(stem),
    }]
    kind = spec.get("kind")
    if play.get("expression") and kind != "choice" and str(question.get("expression") or ""):
        scenes.append({"scene": "setup", "expression": structured_steps(play["expression"])[0]["before"]
                       if structured_steps(play["expression"]) else play["expression"],
                       "say": "Let us write the situation as one calculation."})
    if kind == "number_line":
        scenes.append({"scene": "number_line_start", "spec": spec,
                       "say": f"We start at {_spoken(spec['start'])} on the number line."})
        position = spec["start"]
        for move in spec["moves"]:
            land = position + move
            scenes.append({"scene": "number_line_jump", "spec": spec, "from": position, "move": move, "to": land,
                           "say": f"{'Add' if move > 0 else 'Take away'} {abs(move)}: we move {abs(move)} "
                                  f"{'to the right' if move > 0 else 'to the left'} and land on {_spoken(land)}."})
            position = land
    elif kind == "balance":
        scenes.append({"scene": "balance_start", "spec": spec,
                       "say": f"The scale balances: {spec['left']} on one side, {spec['right']} on the other. "
                              f"Whatever we do to one side, we do to the other."})
        for move in spec["moves"]:
            scenes.append({"scene": "balance_move", "spec": spec, "move": move, "say": move["why"]})
        scenes.append({"scene": "balance_done", "spec": spec,
                       "say": f"{spec['variable']} stands alone: {spec['variable']} equals {_spoken(spec['target'])}."})
    elif kind == "fraction_bar":
        a, b = spec["first"]
        c, d = spec["second"]
        scenes.append({"scene": "fraction_bars", "spec": spec, "phase": "start",
                       "say": f"Here are {a} {_part(b, a)} and {c} {_part(d, c)}. The pieces are different sizes, "
                              f"so we cannot {'add' if spec['op'] == '+' else 'subtract'} them yet."})
        scenes.append({"scene": "fraction_bars", "spec": spec, "phase": "common",
                       "say": f"Cut both bars into {spec['common']} equal pieces. Now {a} {_part(b, a)} is "
                              f"{spec['first_as'][0]} {_part(spec['common'], spec['first_as'][0])}, and {c} {_part(d, c)} is "
                              f"{spec['second_as'][0]} {_part(spec['common'], spec['second_as'][0])}."})
        scenes.append({"scene": "fraction_bars", "spec": spec, "phase": "result",
                       "say": f"{'Together' if spec['op'] == '+' else 'The difference'}: "
                              f"{_spoken(spec['target'])}."})
    elif kind == "bodmas" or play.get("expression"):
        steps = (spec.get("steps") if kind == "bodmas" else structured_steps(play["expression"])) or []
        for n, step in enumerate(steps):
            first = n == 0
            scenes.append({"scene": "rewrite", "step": step,
                           "say": (f"{'First' if first else 'Next'}, {_spoken(step['left'])} {_spoken_op(step['op'])} "
                                   f"{_spoken(step['right'])} is {_spoken(step['result'])}. {step['why']}")})
    choice = play.get("choice")
    if choice:
        key = next((o for o in choice["options"] if o["correct"]), None)
        if key:
            scenes.append({"scene": "answer", "option": key["id"], "text": key["text"],
                           "say": f"So the answer is {key['id']}: {_speakable(key['text'])}. {key['why']}"})
        for wrong in [o for o in choice["options"] if not o["correct"] and o["why"]][:3]:
            scenes.append({"scene": "trap", "option": wrong["id"], "text": wrong["text"],
                           "say": f"If you chose {wrong['id']}: {wrong['why']}"})
    elif spec.get("target") is not None:
        scenes.append({"scene": "answer", "text": str(spec["target"]),
                       "say": f"So the answer is {_spoken(spec['target'])}."})
    return {"question_id": question.get("question_id"), "kind": kind, "scenes": scenes,
            "words": sum(len(s["say"].split()) for s in scenes)}


def _part(denominator: int, count: int) -> str:
    names = {2: "half", 3: "third", 4: "quarter", 5: "fifth", 6: "sixth", 8: "eighth", 10: "tenth", 12: "twelfth"}
    name = names.get(denominator, f"{denominator}th")
    plural = {"half": "halves"}.get(name, name + "s")
    return name if count == 1 else plural


def _spoken(value: Any) -> str:
    text = str(value)
    if text.startswith("-"):
        return "negative " + text[1:]
    if "/" in text:
        n, d = text.split("/", 1)
        return f"{n} over {d}"
    return text


def _spoken_op(op: str) -> str:
    return {"+": "plus", "-": "minus", "×": "times", "÷": "divided by", "^": "to the power"}.get(op, op)


def _speakable(text: str) -> str:
    t = re.sub(r"\$([^$]*)\$", r"\1", str(text))
    t = t.replace("\\times", " times ").replace("\\div", " divided by ").replace("−", "-")
    t = re.sub(r"\\[a-zA-Z]+", " ", t).replace("{", "").replace("}", "")
    t = re.sub(r"(?<![\w)])-(\d)", r"negative \1", t)
    return re.sub(r"\s+", " ", t).strip()


def _lower_first(text: str) -> str:
    text = text.strip()
    return text[:1].lower() + text[1:] if text else text


# ── a game round from the bank ──────────────────────────────────────────────

def session(questions: list[dict[str, Any]], *, mode: str = "mixed", count: int = 10) -> list[dict[str, Any]]:
    """Items for one round, each with its spec. `mode`: choice (the quiz race),
    one kind (number_line, balance, bodmas, fraction_bar), or mixed — the
    most visual kind each item supports, varied so a round is not one kind
    ten times."""
    out: list[dict[str, Any]] = []
    for q in questions:
        play = spec_for(q)
        if play.get("key_agrees") is False:
            continue  # the engine and the key disagree: not a game anyone should lose
        if mode == "choice":
            spec = play.get("choice")
        elif mode in KINDS:
            primary = play.get("primary") or {}
            spec = primary if primary.get("kind") == mode else None
        else:
            spec = play.get("primary")
        if spec:
            out.append({"question_id": q.get("question_id"), "question_text": q.get("question_text"),
                        "stimulus_context": q.get("stimulus_context") or "", "diagram": q.get("diagram"),
                        "spec": spec, "marks": (q.get("pedagogy") or {}).get("max_marks", 1)})
    if mode == "mixed":
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for item in out:
            by_kind.setdefault(item["spec"]["kind"], []).append(item)
        mixed: list[dict[str, Any]] = []
        while any(by_kind.values()) and len(mixed) < count:
            for kind in list(by_kind):
                if by_kind[kind]:
                    mixed.append(by_kind[kind].pop(0))
        return mixed[:count]
    return out[:count]


def prompt_block(subject: str = "") -> str:
    """The writer's contract for `interaction` — mathematics only for now."""
    from .langfuse_seed import SEED_PROMPT_BLOCKS
    from .prompt_store import render
    from .subject_checks import family_of

    if subject and family_of(subject) != "mathematics":
        return ""
    return render("question-interactions", SEED_PROMPT_BLOCKS["question-interactions"])
