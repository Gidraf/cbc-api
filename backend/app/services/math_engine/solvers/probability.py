"""Deterministic Probability Solver."""
from __future__ import annotations

import math
from fractions import Fraction
from typing import Optional

from ..objects import SolutionStep, SolutionTrace


def solve_simple_probability(favourable: int, total: int, event_name: str = "A") -> SolutionTrace:
    """Solve P(A) = n(A) / n(S) with fraction reduction and percentage."""
    if total <= 0:
        raise ValueError("Total sample space outcomes n(S) must be strictly positive")
    if favourable < 0 or favourable > total:
        raise ValueError("Favourable outcomes must be between 0 and total outcomes")

    frac = Fraction(favourable, total)
    frac_latex = f"\\frac{{{frac.numerator}}}{{{frac.denominator}}}" if frac.denominator != 1 else str(frac.numerator)
    pct = (favourable / total) * 100.0
    pct_str = f"{pct:.1f}\\%" if not pct.is_integer() else f"{int(pct)}\\%"

    steps = [
        SolutionStep(
            step_number=1,
            operation="State probability formula: P(E) = n(E) / n(S)",
            expression_before=f"P({event_name})",
            expression_after=f"P({event_name}) = \\frac{{n({event_name})}}{{n(S)}}",
            latex=f"P({event_name}) = \\frac{{n({event_name})}}{{n(S)}}",
            explanation="Probability of an event is number of favourable outcomes divided by total outcomes.",
        ),
        SolutionStep(
            step_number=2,
            operation="Substitute outcomes into formula",
            expression_before=f"P({event_name}) = \\frac{{n({event_name})}}{{n(S)}}",
            expression_after=f"P({event_name}) = \\frac{{{favourable}}}{{{total}}}",
            latex=f"P({event_name}) = \\frac{{{favourable}}}{{{total}}}",
            explanation=f"Favourable outcomes n({event_name}) = {favourable}, total sample space n(S) = {total}.",
        ),
    ]

    if frac.numerator != favourable or frac.denominator != total:
        steps.append(
            SolutionStep(
                step_number=3,
                operation="Simplify fraction to lowest terms",
                expression_before=f"\\frac{{{favourable}}}{{{total}}}",
                expression_after=frac_latex,
                latex=f"\\frac{{{favourable}}}{{{total}}} = {frac_latex}",
                explanation=f"Divide numerator and denominator by GCD = {math.gcd(favourable, total)}.",
            )
        )

    return SolutionTrace(
        problem=f"Find probability of event {event_name} with {favourable} favourable out of {total} total outcomes",
        final_answer=f"P({event_name}) = {frac_latex} = {pct_str}",
        steps=steps,
        verified=True,
        check_latex=f"0 \\le {frac_latex} \\le 1 \\checkmark",
    )


def solve_complementary_probability(prob_a: Fraction, event_name: str = "A") -> SolutionTrace:
    """Solve P(not A) = 1 - P(A)."""
    p_comp = 1 - prob_a
    comp_latex = f"\\frac{{{p_comp.numerator}}}{{{p_comp.denominator}}}" if p_comp.denominator != 1 else str(p_comp.numerator)
    a_latex = f"\\frac{{{prob_a.numerator}}}{{{prob_a.denominator}}}" if prob_a.denominator != 1 else str(prob_a.numerator)

    steps = [
        SolutionStep(
            step_number=1,
            operation="State complement rule: P(not A) = 1 - P(A)",
            expression_before=f"P({event_name}')",
            expression_after=f"P({event_name}') = 1 - P({event_name})",
            latex=f"P({event_name}') = 1 - P({event_name})",
            explanation="The sum of probabilities of an event and its complement is always 1.",
        ),
        SolutionStep(
            step_number=2,
            operation="Subtract P(A) from 1",
            expression_before=f"1 - {a_latex}",
            expression_after=comp_latex,
            latex=f"1 - {a_latex} = {comp_latex}",
            explanation=f"Compute complement fraction: {p_comp.numerator}/{p_comp.denominator}.",
        ),
    ]

    return SolutionTrace(
        problem=f"Find probability of not {event_name} given P({event_name}) = {a_latex}",
        final_answer=f"P({event_name}') = {comp_latex}",
        steps=steps,
        verified=True,
        check_latex=f"{a_latex} + {comp_latex} = 1 \\checkmark",
    )


def solve_independent_events_probability(
    p_a: Fraction,
    p_b: Fraction,
    name_a: str = "A",
    name_b: str = "B",
) -> SolutionTrace:
    """Solve P(A and B) = P(A) * P(B) for independent events."""
    p_inter = p_a * p_b
    p_a_str = f"\\frac{{{p_a.numerator}}}{{{p_a.denominator}}}" if p_a.denominator != 1 else str(p_a.numerator)
    p_b_str = f"\\frac{{{p_b.numerator}}}{{{p_b.denominator}}}" if p_b.denominator != 1 else str(p_b.numerator)
    res_str = f"\\frac{{{p_inter.numerator}}}{{{p_inter.denominator}}}" if p_inter.denominator != 1 else str(p_inter.numerator)

    steps = [
        SolutionStep(
            step_number=1,
            operation="State multiplication rule for independent events",
            expression_before=f"P({name_a} \\cap {name_b})",
            expression_after=f"P({name_a}) \\times P({name_b})",
            latex=f"P({name_a} \\text{{ and }} {name_b}) = P({name_a}) \\times P({name_b})",
            explanation="For independent events, the joint probability is the product of their separate probabilities.",
        ),
        SolutionStep(
            step_number=2,
            operation="Multiply fractions",
            expression_before=f"{p_a_str} \\times {p_b_str}",
            expression_after=res_str,
            latex=f"{p_a_str} \\times {p_b_str} = {res_str}",
            explanation="Multiply numerators and denominators and simplify to lowest terms.",
        ),
    ]

    return SolutionTrace(
        problem=f"Find P({name_a} and {name_b}) where P({name_a}) = {p_a_str} and P({name_b}) = {p_b_str}",
        final_answer=f"P({name_a} \\cap {name_b}) = {res_str}",
        steps=steps,
        verified=True,
    )
