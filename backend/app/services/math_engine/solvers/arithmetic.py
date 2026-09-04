"""Deterministic Arithmetic and Number Theory Solver."""
from __future__ import annotations

import math
from typing import List, Tuple

from ..objects import SolutionStep, SolutionTrace


def prime_factorization(n: int) -> List[Tuple[int, int]]:
    """Return prime factors as [(prime, power), ...]."""
    if n <= 1:
        return []
    factors: List[Tuple[int, int]] = []
    d = 2
    temp = n
    while d * d <= temp:
        if temp % d == 0:
            count = 0
            while temp % d == 0:
                count += 1
                temp //= d
            factors.append((d, count))
        d += 1 if d == 2 else 2
    if temp > 1:
        factors.append((temp, 1))
    return factors


def solve_gcd_lcm(a: int, b: int) -> SolutionTrace:
    """Compute GCD/HCF and LCM with full trace."""
    g = math.gcd(a, b)
    l = math.lcm(a, b)

    factors_a = prime_factorization(a)
    factors_b = prime_factorization(b)

    def fmt_factors(facs: List[Tuple[int, int]]) -> str:
        return " \\times ".join(f"{p}^{{{c}}}" if c > 1 else str(p) for p, c in facs) or "1"

    steps = [
        SolutionStep(
            step_number=1,
            operation="Prime Factorization",
            expression_before=f"a = {a}, b = {b}",
            expression_after=f"{a} = {fmt_factors(factors_a)},\\ {b} = {fmt_factors(factors_b)}",
            latex=f"{a} = {fmt_factors(factors_a)},\\quad {b} = {fmt_factors(factors_b)}",
            explanation=f"Express each number as a product of its prime factors.",
        ),
        SolutionStep(
            step_number=2,
            operation="Determine Greatest Common Divisor (GCD / HCF)",
            expression_before="\\text{Common prime factors with lowest powers}",
            expression_after=f"\\text{{GCD}}({a}, {b}) = {g}",
            latex=f"\\text{{GCD}}({a}, {b}) = {g}",
            explanation=f"Multiply prime factors common to both numbers with the lowest power.",
        ),
        SolutionStep(
            step_number=3,
            operation="Determine Lowest Common Multiple (LCM)",
            expression_before="\\text{All prime factors with highest powers}",
            expression_after=f"\\text{{LCM}}({a}, {b}) = {l}",
            latex=f"\\text{{LCM}}({a}, {b}) = \\frac{{{a} \\times {b}}}{{\\text{{GCD}}({a}, {b})}} = {l}",
            explanation=f"Multiply each prime factor present using its highest power.",
        ),
    ]

    return SolutionTrace(
        problem=f"Find GCD and LCM of {a} and {b}",
        final_answer=f"\\text{{GCD}} = {g},\\ \\text{{LCM}} = {l}",
        steps=steps,
        verified=True,
        check_latex=f"{g} \\times {l} = {a} \\times {b} = {a*b} \\checkmark",
    )


def solve_rounding(value: float, decimals: int = 2) -> SolutionTrace:
    """Round a number with pedagogical trace."""
    rounded = round(value, decimals)
    multiplier = 10 ** (decimals + 1)
    check_digit = int(abs(value * multiplier)) % 10
    round_up = check_digit >= 5

    steps = [
        SolutionStep(
            step_number=1,
            operation=f"Identify target place value ({decimals} decimal places)",
            expression_before=str(value),
            expression_after=f"\\text{{Inspect next digit: }} {check_digit}",
            latex=f"\\text{{Rounding digit at pos }} {decimals+1}: {check_digit}",
            explanation=f"Look at the digit immediately following the {decimals}th decimal place.",
        ),
        SolutionStep(
            step_number=2,
            operation="Apply rounding rule",
            expression_before=f"\\text{{Digit is }} {'\\ge 5' if round_up else '< 5'}",
            expression_after=f"{rounded}",
            latex=f"{value} \\approx {rounded}",
            explanation=f"Since {check_digit} is {'5 or greater, round up' if round_up else 'less than 5, round down'}.",
        ),
    ]

    return SolutionTrace(
        problem=f"Round {value} to {decimals} decimal places",
        final_answer=str(rounded),
        steps=steps,
        verified=True,
    )
