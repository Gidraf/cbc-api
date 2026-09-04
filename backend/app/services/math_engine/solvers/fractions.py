"""Deterministic Fractions Operations Solver."""
from __future__ import annotations

import math
from fractions import Fraction
from typing import Any

from ..objects import SolutionStep, SolutionTrace


def solve_fraction_operation(
    n1: int,
    d1: int,
    a: Any,
    b: Any,
    c: Any = None,
    op: str = "+",
) -> SolutionTrace:
    """Solve fraction addition, subtraction, multiplication, or division."""
    if isinstance(a, str):
        op_sym = a.strip()
        n2 = int(b)
        d2 = int(c)
    else:
        n2 = int(a)
        d2 = int(b)
        op_sym = str(c).strip() if c is not None else op.strip()

    if d1 == 0 or d2 == 0:
        raise ZeroDivisionError("Fraction denominator cannot be zero.")
    if op_sym in ("+", "add"):
        lcm = math.lcm(d1, d2)
        m1 = lcm // d1
        m2 = lcm // d2
        res_num = n1 * m1 + n2 * m2
        ans_frac = Fraction(res_num, lcm)
        ans_latex = f"\\frac{{{ans_frac.numerator}}}{{{ans_frac.denominator}}}" if ans_frac.denominator != 1 else str(ans_frac.numerator)

        steps = [
            SolutionStep(
                step_number=1,
                operation="Find LCM of denominators",
                expression_before=f"\\frac{{{n1}}}{{{d1}}} + \\frac{{{n2}}}{{{d2}}}",
                expression_after=f"\\text{{LCM}}({d1}, {d2}) = {lcm}",
                latex=f"\\text{{LCM}}({d1}, {d2}) = {lcm}",
                explanation=f"Find the lowest common multiple of {d1} and {d2}.",
            ),
            SolutionStep(
                step_number=2,
                operation="Convert to equivalent fractions",
                expression_before=f"\\frac{{{n1}}}{{{d1}}} + \\frac{{{n2}}}{{{d2}}}",
                expression_after=f"\\frac{{{n1*m1}}}{{{lcm}}} + \\frac{{{n2*m2}}}{{{lcm}}}",
                latex=f"\\frac{{{n1} \\times {m1}}}{{{d1} \\times {m1}}} + \\frac{{{n2} \\times {m2}}}{{{d2} \\times {m2}}} = \\frac{{{n1*m1}}}{{{lcm}}} + \\frac{{{n2*m2}}}{{{lcm}}}",
                explanation=f"Express each fraction with common denominator {lcm}.",
            ),
            SolutionStep(
                step_number=3,
                operation="Add numerators",
                expression_before=f"\\frac{{{n1*m1}}}{{{lcm}}} + \\frac{{{n2*m2}}}{{{lcm}}}",
                expression_after=f"\\frac{{{res_num}}}{{{lcm}}}",
                latex=f"\\frac{{{n1*m1} + {n2*m2}}}{{{lcm}}} = \\frac{{{res_num}}}{{{lcm}}}",
                explanation=f"Add numerators while retaining the common denominator.",
            ),
        ]
        if res_num != ans_frac.numerator:
            steps.append(
                SolutionStep(
                    step_number=4,
                    operation="Simplify to lowest terms",
                    expression_before=f"\\frac{{{res_num}}}{{{lcm}}}",
                    expression_after=ans_latex,
                    latex=f"\\frac{{{res_num}}}{{{lcm}}} = {ans_latex}",
                    explanation="Divide numerator and denominator by their greatest common divisor.",
                )
            )
        return SolutionTrace(
            problem=f"\\frac{{{n1}}}{{{d1}}} + \\frac{{{n2}}}{{{d2}}}",
            final_answer=ans_latex,
            steps=steps,
            verified=True,
            check_latex=f"{ans_latex} - \\frac{{{n2}}}{{{d2}}} = \\frac{{{n1}}}{{{d1}}} \\checkmark",
        )

    elif op_sym in ("-", "sub", "subtract"):
        lcm = math.lcm(d1, d2)
        m1 = lcm // d1
        m2 = lcm // d2
        res_num = n1 * m1 - n2 * m2
        ans_frac = Fraction(res_num, lcm)
        ans_latex = f"\\frac{{{ans_frac.numerator}}}{{{ans_frac.denominator}}}" if ans_frac.denominator != 1 else str(ans_frac.numerator)

        steps = [
            SolutionStep(
                step_number=1,
                operation="Find common denominator (LCM)",
                expression_before=f"\\frac{{{n1}}}{{{d1}}} - \\frac{{{n2}}}{{{d2}}}",
                expression_after=f"\\text{{LCM}}({d1}, {d2}) = {lcm}",
                latex=f"\\text{{LCM}}({d1}, {d2}) = {lcm}",
                explanation=f"The lowest common denominator is {lcm}.",
            ),
            SolutionStep(
                step_number=2,
                operation="Subtract equivalent numerators",
                expression_before=f"\\frac{{{n1*m1}}}{{{lcm}}} - \\frac{{{n2*m2}}}{{{lcm}}}",
                expression_after=f"\\frac{{{res_num}}}{{{lcm}}}",
                latex=f"\\frac{{{n1*m1} - {n2*m2}}}{{{lcm}}} = \\frac{{{res_num}}}{{{lcm}}}",
                explanation="Subtract the numerators.",
            ),
        ]
        if res_num != ans_frac.numerator:
            steps.append(
                SolutionStep(
                    step_number=3,
                    operation="Simplify fraction",
                    expression_before=f"\\frac{{{res_num}}}{{{lcm}}}",
                    expression_after=ans_latex,
                    latex=f"\\frac{{{res_num}}}{{{lcm}}} = {ans_latex}",
                    explanation="Reduce to simplest form.",
                )
            )
        return SolutionTrace(
            problem=f"\\frac{{{n1}}}{{{d1}}} - \\frac{{{n2}}}{{{d2}}}",
            final_answer=ans_latex,
            steps=steps,
            verified=True,
        )

    elif op_sym in ("*", "x", "mult", "multiply"):
        res_num = n1 * n2
        res_den = d1 * d2
        ans_frac = Fraction(res_num, res_den)
        ans_latex = f"\\frac{{{ans_frac.numerator}}}{{{ans_frac.denominator}}}" if ans_frac.denominator != 1 else str(ans_frac.numerator)

        steps = [
            SolutionStep(
                step_number=1,
                operation="Multiply numerators and denominators",
                expression_before=f"\\frac{{{n1}}}{{{d1}}} \\times \\frac{{{n2}}}{{{d2}}}",
                expression_after=f"\\frac{{{res_num}}}{{{res_den}}}",
                latex=f"\\frac{{{n1} \\times {n2}}}{{{d1} \\times {d2}}} = \\frac{{{res_num}}}{{{res_den}}}",
                explanation="Multiply the top numbers together and the bottom numbers together.",
            ),
        ]
        if res_num != ans_frac.numerator:
            steps.append(
                SolutionStep(
                    step_number=2,
                    operation="Simplify to lowest terms",
                    expression_before=f"\\frac{{{res_num}}}{{{res_den}}}",
                    expression_after=ans_latex,
                    latex=f"\\frac{{{res_num}}}{{{res_den}}} = {ans_latex}",
                    explanation="Divide numerator and denominator by common factors.",
                )
            )
        return SolutionTrace(
            problem=f"\\frac{{{n1}}}{{{d1}}} \\times \\frac{{{n2}}}{{{d2}}}",
            final_answer=ans_latex,
            steps=steps,
            verified=True,
        )

    elif op_sym in ("/", "div", "divide"):
        if n2 == 0:
            raise ZeroDivisionError("Cannot divide by fraction with numerator 0.")
        # Multiply by reciprocal
        res_num = n1 * d2
        res_den = d1 * n2
        ans_frac = Fraction(res_num, res_den)
        ans_latex = f"\\frac{{{ans_frac.numerator}}}{{{ans_frac.denominator}}}" if ans_frac.denominator != 1 else str(ans_frac.numerator)

        steps = [
            SolutionStep(
                step_number=1,
                operation="Multiply by the reciprocal of the divisor",
                expression_before=f"\\frac{{{n1}}}{{{d1}}} \\div \\frac{{{n2}}}{{{d2}}}",
                expression_after=f"\\frac{{{n1}}}{{{d1}}} \\times \\frac{{{d2}}}{{{n2}}}",
                latex=f"\\frac{{{n1}}}{{{d1}}} \\div \\frac{{{n2}}}{{{d2}}} = \\frac{{{n1}}}{{{d1}}} \\times \\frac{{{d2}}}{{{n2}}}",
                explanation="Invert the second fraction and multiply.",
            ),
            SolutionStep(
                step_number=2,
                operation="Compute product and simplify",
                expression_before=f"\\frac{{{n1*d2}}}{{{d1*n2}}}",
                expression_after=ans_latex,
                latex=f"\\frac{{{n1} \\times {d2}}}{{{d1} \\times {n2}}} = {ans_latex}",
                explanation="Multiply and reduce to lowest terms.",
            ),
        ]
        return SolutionTrace(
            problem=f"\\frac{{{n1}}}{{{d1}}} \\div \\frac{{{n2}}}{{{d2}}}",
            final_answer=ans_latex,
            steps=steps,
            verified=True,
        )

    raise ValueError(f"Unknown fraction operator '{op}'")
