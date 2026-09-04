"""Deterministic Ratios and Proportions Solver."""
from __future__ import annotations

import math
from functools import reduce
from typing import List

from ..objects import SolutionStep, SolutionTrace


def solve_simplify_ratio(terms: List[int]) -> SolutionTrace:
    """Simplify a ratio a : b : c... to lowest terms."""
    if not terms:
        raise ValueError("Ratio must contain at least two terms.")
    common_gcd = reduce(math.gcd, terms)
    simplified = [t // common_gcd for t in terms]

    orig_str = " : ".join(str(t) for t in terms)
    simp_str = " : ".join(str(t) for t in simplified)

    div_expr = " : ".join(f"\\frac{{{t}}}{{{common_gcd}}}" for t in terms)
    steps = [
        SolutionStep(
            step_number=1,
            operation="Find GCD of all terms",
            expression_before=orig_str,
            expression_after=f"\\text{{GCD}} = {common_gcd}",
            latex=f"\\text{{GCD}}({', '.join(str(t) for t in terms)}) = {common_gcd}",
            explanation=f"Find the greatest common factor of the ratio terms.",
        ),
        SolutionStep(
            step_number=2,
            operation="Divide each term by the GCD",
            expression_before=orig_str,
            expression_after=simp_str,
            latex=f"{div_expr} = {simp_str}",
            explanation="Reduce to simplest integer terms.",
        ),
    ]

    return SolutionTrace(
        problem=f"Simplify the ratio {orig_str}",
        final_answer=simp_str,
        steps=steps,
        verified=True,
    )


def solve_share_in_ratio(total_amount: float, ratio_terms: List[int]) -> SolutionTrace:
    """Divide a total quantity in a given ratio."""
    ratio_sum = sum(ratio_terms)
    unit_value = total_amount / ratio_sum
    shares = [round(t * unit_value, 2) for t in ratio_terms]

    ratio_str = " : ".join(str(t) for t in ratio_terms)
    shares_str = ", ".join(str(int(s)) if s.is_integer() else str(s) for s in shares)

    steps = [
        SolutionStep(
            step_number=1,
            operation="Find total number of ratio parts",
            expression_before=ratio_str,
            expression_after=f"\\text{{Total parts}} = {ratio_sum}",
            latex=f"\\sum \\text{{parts}} = {' + '.join(str(t) for t in ratio_terms)} = {ratio_sum}",
            explanation="Sum all parts of the ratio.",
        ),
        SolutionStep(
            step_number=2,
            operation="Calculate the value of one part",
            expression_before=f"\\frac{{\\text{{Total}}}}{{\\text{{Total parts}}}}",
            expression_after=f"\\frac{{{total_amount}}}{{{ratio_sum}}} = {unit_value}",
            latex=f"\\text{{One part}} = \\frac{{{total_amount}}}{{{ratio_sum}}} = {unit_value}",
            explanation=f"Divide the total {total_amount} by {ratio_sum} parts.",
        ),
        SolutionStep(
            step_number=3,
            operation="Calculate individual shares",
            expression_before=f"\\text{{Multiply each term by }} {unit_value}",
            expression_after=shares_str,
            latex=";\\ ".join(f"{t} \\times {unit_value} = {s}" for t, s in zip(ratio_terms, shares)),
            explanation="Multiply each ratio term by the value of one part.",
        ),
    ]

    return SolutionTrace(
        problem=f"Share {total_amount} in the ratio {ratio_str}",
        final_answer=shares_str,
        steps=steps,
        verified=math.isclose(sum(shares), total_amount, rel_tol=1e-5),
        check_latex=f"{' + '.join(str(s) for s in shares)} = {sum(shares)} = {total_amount} \\checkmark",
    )
