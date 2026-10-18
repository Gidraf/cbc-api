"""The LaTeX of the engine's steps — shared by the Manim clips (app/manim_board.py)
and the browser's preview animation (whiteboard.js, with KaTeX).

Pure functions: no Manim, no model. `scene_tex` gives each scene the lines it
shows, worked out once here, so both animate the same thing.
"""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Any


def tex_of(text: str) -> str:
    """A learner's line as LaTeX: ÷ ×, a/b as a fraction, * as ×."""
    t = str(text).replace("÷", r"\div ").replace("×", r"\times ").replace("*", r"\times ").replace("−", "-")
    t = re.sub(r"(?<![\\\w])(\d+)\s*/\s*(\d+)", r"\\frac{\1}{\2}", t)
    return t


def mixed_tex(text: str) -> str:
    """Words and maths, as the item writes them ("Division: $18 \\div (-3)$"):
    the words as text, the maths between the dollars as maths."""
    out = []
    for k, part in enumerate(str(text).split("$")):
        if not part:
            continue
        if k % 2:
            out.append(tex_of(part))
        else:
            safe = re.sub(r"([#%&_{}])", r"\\\1", part).replace("~", " ").replace("^", " ")
            safe = safe.replace("÷", r"$\div$").replace("×", r"$\times$").replace("−", "-")
            out.append(r"\text{" + safe + "}")
    return " ".join(out) or r"\text{}"


def num_tex(v) -> str:
    """A number as the board writes it: -6, 3/4 as a fraction."""
    try:
        f = Fraction(str(v))
    except (ValueError, ZeroDivisionError):
        return tex_of(str(v))
    if f.denominator == 1:
        return str(f.numerator)
    sign = "-" if f < 0 else ""
    return f"{sign}\\frac{{{abs(f.numerator)}}}{{{f.denominator}}}"


def op_tex(op: str) -> str:
    return {"÷": r"\div", "×": r"\times", "*": r"\times", "/": r"\div"}.get(op, op)


def split_on(before: str, left, op: str, right) -> tuple[str, str, str] | None:
    """`before` as (what comes first, the part done now, what follows) — the
    part found however the engine spaced or bracketed its numbers."""
    def term(v) -> str:
        s = re.escape(str(v)).replace("\\-", "-")
        if str(v).startswith("-"):
            return rf"(?:\(\s*{s}\s*\)|{s})"
        return rf"(?:\(\s*{s}\s*\)|{s})"
    pat = rf"{term(left)}\s*{re.escape(op_tex(op))}\s*{term(right)}"
    m = re.search(pat, before)
    if not m:
        return None
    return before[:m.start()], before[m.start():m.end()], before[m.end():]


def side_tex(step: dict[str, Any]) -> str:
    right = num_tex(step["right"])
    right = f"({right})" if str(step["right"]).startswith("-") else right
    return f"{num_tex(step['left'])} {op_tex(step['op'])} {right} = {num_tex(step['result'])}"


def result_tex(step: dict[str, Any], pre: str) -> str:
    res = num_tex(step["result"])
    if str(step["result"]).startswith("-") and pre.rstrip().endswith(("+", "-", r"\times", r"\div")):
        res = f"({res})"
    return res


def answer_tex(text: str, option: str = "") -> str:
    plain = str(text).strip()
    tex = (num_tex(plain) if re.fullmatch(r"-?\d+(/\d+)?", plain)
           else mixed_tex(plain) if "$" in plain or re.search(r"[A-Za-z]{2,}", plain) else tex_of(plain))
    return (rf"\text{{{option}}}:\ " + tex) if option else tex


COLOUR = {r"\times": "blue", r"\div": "blue", "+": "green", "-": "red"}


def scene_tex(scenes: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
    """For each scene the browser animates with KaTeX, the lines it shows; None for the rest."""
    out: list[dict[str, Any] | None] = []
    balance_k = 0
    for sc in scenes:
        kind = sc.get("scene")
        try:
            if kind == "setup" and sc.get("expression"):
                out.append({"line": tex_of(sc["expression"])})
            elif kind == "rewrite":
                step = sc["step"]
                parts = split_on(step["before"], step["left"], step["op"], step["right"])
                out.append({"before": step["before"], "after": step["after"], "side": side_tex(step),
                            "colour": COLOUR.get(op_tex(step["op"]), "amber"),
                            "parts": list(parts) if parts else None,
                            "res": result_tex(step, parts[0]) if parts else None})
            elif kind == "balance_start":
                sp = sc["spec"]
                balance_k = 0
                out.append({"line": f"{tex_of(sp['left'])} = {tex_of(sp['right'])}"})
            elif kind == "balance_move":
                sp, move = sc["spec"], sc["move"]
                cur = sp["states"][balance_k - 1] if balance_k > 0 else [sp["left"], sp["right"]]
                op = op_tex(move["op"])
                nxt = sp["states"][balance_k]
                out.append({"both": [tex_of(cur[0]), f"{op} {tex_of(move['value'])}", tex_of(cur[1]),
                                     f"{op} {tex_of(move['value'])}"],
                            "next": f"{tex_of(nxt[0])} = {tex_of(nxt[1])}", "colour": COLOUR.get(op, "amber")})
                balance_k += 1
            elif kind == "balance_done":
                out.append({"done": True})
            elif kind == "answer":
                out.append({"line": answer_tex(sc.get("text") or "", sc.get("option") or "")})
            else:
                out.append(None)
        except (KeyError, IndexError, TypeError):
            out.append(None)
    return out
