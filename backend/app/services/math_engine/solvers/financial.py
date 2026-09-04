"""Deterministic Financial Mathematics Solver."""
from __future__ import annotations

import math
from typing import Optional

from ..objects import SolutionStep, SolutionTrace


def solve_profit_loss(
    cost_price: float,
    selling_price: float,
    currency: str = "KES",
) -> SolutionTrace:
    """Calculate profit or loss and percentage profit/loss."""
    diff = selling_price - cost_price
    is_profit = diff >= 0
    kind = "Profit" if is_profit else "Loss"
    abs_diff = abs(diff)

    pct = (abs_diff / cost_price) * 100.0 if cost_price > 0 else 0.0
    pct_str = f"{pct:.2f}\\%" if not pct.is_integer() else f"{int(pct)}\\%"

    diff_str = str(int(abs_diff)) if abs_diff.is_integer() else f"{abs_diff:.2f}"
    cp_str = str(int(cost_price)) if cost_price.is_integer() else f"{cost_price:.2f}"
    sp_str = str(int(selling_price)) if selling_price.is_integer() else f"{selling_price:.2f}"

    steps = [
        SolutionStep(
            step_number=1,
            operation=f"Determine {kind}",
            expression_before=f"\\text{{{kind}}} = |\\text{{SP}} - \\text{{CP}}|",
            expression_after=f"|{sp_str} - {cp_str}| = {currency}\\ {diff_str}",
            latex=f"\\text{{{kind}}} = {sp_str} - {cp_str} = {currency}\\ {diff_str}",
            explanation=f"Selling price is {'greater' if is_profit else 'less'} than cost price, resulting in a {kind.lower()}.",
        ),
        SolutionStep(
            step_number=2,
            operation=f"Calculate Percentage {kind}",
            expression_before=f"\\%\\text{{{kind}}} = \\frac{{\\text{{{kind}}}}}{{\\text{{CP}}}} \\times 100\\%",
            expression_after=f"\\frac{{{diff_str}}}{{{cp_str}}} \\times 100\\% = {pct_str}",
            latex=f"\\frac{{{diff_str}}}{{{cp_str}}} \\times 100\\% = {pct_str}",
            explanation=f"Express the {kind.lower()} as a percentage of the original cost price ({currency} {cp_str}).",
        ),
    ]

    return SolutionTrace(
        problem=f"Calculate {kind.lower()} and percentage {kind.lower()} for CP = {currency} {cp_str} and SP = {currency} {sp_str}",
        final_answer=f"\\text{{{kind}}} = {currency}\\ {diff_str}\\ ({pct_str})",
        steps=steps,
        verified=True,
    )


def solve_simple_interest(
    principal: float,
    rate_percent: float,
    time_years: float,
    currency: str = "KES",
) -> SolutionTrace:
    """Calculate simple interest I = (P * R * T) / 100 and total amount A = P + I."""
    interest = (principal * rate_percent * time_years) / 100.0
    total_amount = principal + interest

    i_str = str(int(interest)) if interest.is_integer() else f"{interest:.2f}"
    a_str = str(int(total_amount)) if total_amount.is_integer() else f"{total_amount:.2f}"
    p_str = str(int(principal)) if principal.is_integer() else f"{principal:.2f}"

    steps = [
        SolutionStep(
            step_number=1,
            operation="State formula: I = (P * R * T) / 100",
            expression_before="I = \\frac{P \\times R \\times T}{100}",
            expression_after=f"I = \\frac{{{p_str} \\times {rate_percent} \\times {time_years}}}{{100}}",
            latex="I = \\frac{P \\times R \\times T}{100}",
            explanation="Simple interest depends directly on principal, annual rate, and duration in years.",
        ),
        SolutionStep(
            step_number=2,
            operation="Compute Interest",
            expression_before=f"I = \\frac{{{principal * rate_percent * time_years}}}{{100}}",
            expression_after=f"I = {currency}\\ {i_str}",
            latex=f"I = {currency}\\ {i_str}",
            explanation=f"Multiply and divide by 100 to obtain interest of {currency} {i_str}.",
        ),
        SolutionStep(
            step_number=3,
            operation="Calculate Total Amount: A = P + I",
            expression_before="A = P + I",
            expression_after=f"A = {p_str} + {i_str} = {currency}\\ {a_str}",
            latex=f"A = {p_str} + {i_str} = {currency}\\ {a_str}",
            explanation="The total amount due is principal plus accrued interest.",
        ),
    ]

    return SolutionTrace(
        problem=f"Calculate simple interest and total amount on {currency} {p_str} at {rate_percent}% p.a. for {time_years} years",
        final_answer=f"I = {currency}\\ {i_str},\\ A = {currency}\\ {a_str}",
        steps=steps,
        verified=True,
        check_latex=f"\\frac{{{i_str} \\times 100}}{{{p_str} \\times {time_years}}} = {rate_percent}\\% \\checkmark",
    )


def solve_compound_interest(
    principal: float,
    rate_percent: float,
    time_years: float,
    compounds_per_year: int = 1,
    currency: str = "KES",
) -> SolutionTrace:
    """Calculate compound interest: A = P(1 + r/n)^(nt) and CI = A - P."""
    r = rate_percent / 100.0
    n = compounds_per_year
    t = time_years
    amount = principal * ((1.0 + (r / n)) ** (n * t))
    interest = amount - principal

    a_str = f"{amount:.2f}"
    i_str = f"{interest:.2f}"
    p_str = str(int(principal)) if principal.is_integer() else f"{principal:.2f}"

    steps = [
        SolutionStep(
            step_number=1,
            operation="State formula: A = P(1 + r/n)^(nt)",
            expression_before="A = P\\left(1 + \\frac{r}{n}\\right)^{nt}",
            expression_after=f"A = {p_str}\\left(1 + \\frac{{{r}}}{{{n}}}\\right)^{{{int(n * t)}}}",
            latex=f"A = P\\left(1 + \\frac{{r}}{{n}}\\right)^{{nt}}",
            explanation=f"Compound interest formula with principal {p_str}, rate {rate_percent}%, compounded {n} time(s) per year for {t} years.",
        ),
        SolutionStep(
            step_number=2,
            operation="Calculate Accumulated Amount A",
            expression_before=f"A = {p_str} \\times ({(1.0 + r/n):.4f})^{{{int(n * t)}}}",
            expression_after=f"A = {currency}\\ {a_str}",
            latex=f"A = {currency}\\ {a_str}",
            explanation=f"Evaluate compound multiplier and scale by principal.",
        ),
        SolutionStep(
            step_number=3,
            operation="Calculate Compound Interest: CI = A - P",
            expression_before="CI = A - P",
            expression_after=f"CI = {a_str} - {p_str} = {currency}\\ {i_str}",
            latex=f"CI = {a_str} - {p_str} = {currency}\\ {i_str}",
            explanation=f"Subtract principal from accumulated amount to find compound interest.",
        ),
    ]

    return SolutionTrace(
        problem=f"Calculate compound amount and interest on {currency} {p_str} at {rate_percent}% p.a. for {time_years} years (compounded {n}x/yr)",
        final_answer=f"A = {currency}\\ {a_str},\\ CI = {currency}\\ {i_str}",
        steps=steps,
        verified=True,
    )
