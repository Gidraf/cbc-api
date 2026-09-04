"""Deterministic Percentage Operations Solver."""
from __future__ import annotations

from ..objects import SolutionStep, SolutionTrace


def solve_percentage_of_quantity(percent: float, total: float) -> SolutionTrace:
    """Calculate P% of Total."""
    result = (percent / 100.0) * total
    res_str = str(int(result)) if result.is_integer() else f"{result:.2f}"

    steps = [
        SolutionStep(
            step_number=1,
            operation="Convert percentage to fraction or decimal",
            expression_before=f"{percent}\\% \\text{{ of }} {total}",
            expression_after=f"\\frac{{{percent}}}{{100}} \\times {total}",
            latex=f"{percent}\\% = \\frac{{{percent}}}{{100}}",
            explanation="Express the percentage over 100.",
        ),
        SolutionStep(
            step_number=2,
            operation="Multiply by the total quantity",
            expression_before=f"\\frac{{{percent}}}{{100}} \\times {total}",
            expression_after=res_str,
            latex=f"\\frac{{{percent} \\times {total}}}{{100}} = {res_str}",
            explanation=f"Compute the product.",
        ),
    ]

    return SolutionTrace(
        problem=f"Calculate {percent}\\% of {total}",
        final_answer=res_str,
        steps=steps,
        verified=True,
        check_latex=f"\\frac{{{res_str}}}{{{total}}} \\times 100 = {percent}\\% \\checkmark",
    )


def solve_percentage_change(original: float, new_value: float) -> SolutionTrace:
    """Calculate percentage increase or decrease."""
    change = new_value - original
    is_increase = change >= 0
    pct = abs(change) / original * 100.0
    pct_str = f"{pct:.2f}%" if not pct.is_integer() else f"{int(pct)}%"
    kind = "increase" if is_increase else "decrease"

    steps = [
        SolutionStep(
            step_number=1,
            operation="Calculate absolute change",
            expression_before=f"\\text{{New}} - \\text{{Original}}",
            expression_after=f"{new_value} - {original} = {abs(change)}",
            latex=f"\\Delta = |{new_value} - {original}| = {abs(change)}",
            explanation=f"Find the difference between new and original values ({kind}).",
        ),
        SolutionStep(
            step_number=2,
            operation="Divide by original and multiply by 100%",
            expression_before=f"\\frac{{\\text{{Change}}}}{{\\text{{Original}}}} \\times 100\\%",
            expression_after=pct_str,
            latex=f"\\frac{{{abs(change)}}}{{{original}}} \\times 100\\% = {pct_str}",
            explanation="Express change as a fraction of original, then convert to percentage.",
        ),
    ]

    return SolutionTrace(
        problem=f"Find the percentage change from {original} to {new_value}",
        final_answer=f"{pct_str} {kind}",
        steps=steps,
        verified=True,
    )
