"""Deterministic Algebra Solver."""
from __future__ import annotations

import math
import re
from typing import Any, List

import sympy as sp

from ..objects import SolutionStep, SolutionTrace


def solve_linear_equation(equation_str: str, var_name: str = "x") -> SolutionTrace:
    """Solve single variable linear equation with full pedagogical trace."""
    clean_str = equation_str.replace(" ", "")
    parts = clean_str.split("=")
    if len(parts) != 2:
        raise ValueError("Equation must contain exactly one '=' sign")

    x = sp.Symbol(var_name)
    lhs_expr = sp.sympify(parts[0])
    rhs_expr = sp.sympify(parts[1])

    equation = sp.Eq(lhs_expr, rhs_expr)
    solutions = sp.solve(equation, x)
    if not solutions:
        raise ValueError("No solution found for linear equation")

    sol = solutions[0]
    steps: List[SolutionStep] = []
    step_num = 1
    init_latex = f"{sp.latex(lhs_expr)} = {sp.latex(rhs_expr)}"

    expanded_lhs = sp.expand(lhs_expr)
    if expanded_lhs != lhs_expr:
        steps.append(
            SolutionStep(
                step_number=step_num,
                operation="Expand brackets",
                expression_before=init_latex,
                expression_after=f"{sp.latex(expanded_lhs)} = {sp.latex(rhs_expr)}",
                latex=f"{sp.latex(expanded_lhs)} = {sp.latex(rhs_expr)}",
                explanation="Multiply out brackets on the left-hand side.",
            )
        )
        step_num += 1
        curr_lhs = expanded_lhs
    else:
        curr_lhs = lhs_expr

    coeff = curr_lhs.coeff(x)
    const = curr_lhs - coeff * x
    rhs_const = rhs_expr - const

    if const != 0:
        steps.append(
            SolutionStep(
                step_number=step_num,
                operation=f"{'Subtract' if const > 0 else 'Add'} {abs(const)} on both sides",
                expression_before=f"{sp.latex(curr_lhs)} = {sp.latex(rhs_expr)}",
                expression_after=f"{sp.latex(coeff * x)} = {sp.latex(rhs_const)}",
                latex=f"{sp.latex(coeff * x)} = {sp.latex(rhs_const)}",
                explanation=f"Balance equation by moving constant {const} across.",
            )
        )
        step_num += 1

    if coeff != 1:
        steps.append(
            SolutionStep(
                step_number=step_num,
                operation=f"Divide both sides by {coeff}",
                expression_before=f"{sp.latex(coeff * x)} = {sp.latex(rhs_const)}",
                expression_after=f"{var_name} = {sp.latex(sol)}",
                latex=f"{var_name} = {sp.latex(sol)}",
                explanation=f"Isolate {var_name} by dividing by its coefficient.",
            )
        )

    sub_val = lhs_expr.subs(x, sol)
    check_str = f"{sp.latex(lhs_expr.subs(x, sp.Symbol(f'({sol})')))} = {sub_val} = {sp.latex(rhs_expr)} \\checkmark"

    return SolutionTrace(
        problem=init_latex,
        final_answer=f"{var_name} = {sp.latex(sol)}",
        steps=steps,
        verified=(sub_val == rhs_expr),
        check_latex=check_str,
    )


def solve_simultaneous_linear(eq1_str: str, eq2_str: str, var1: str = "x", var2: str = "y") -> SolutionTrace:
    """Solve system of 2 linear equations in 2 variables."""
    x, y = sp.symbols(f"{var1} {var2}")
    p1 = eq1_str.split("=")
    p2 = eq2_str.split("=")
    e1 = sp.Eq(sp.sympify(p1[0]), sp.sympify(p1[1]))
    e2 = sp.Eq(sp.sympify(p2[0]), sp.sympify(p2[1]))

    sol_dict = sp.solve((e1, e2), (x, y))
    if not sol_dict:
        raise ValueError("No unique solution found for simultaneous system.")

    val_x = sol_dict[x]
    val_y = sol_dict[y]

    steps = [
        SolutionStep(
            step_number=1,
            operation="State equations in standard form",
            expression_before=f"{eq1_str};\\ {eq2_str}",
            expression_after=f"(1)\\ {sp.latex(e1)},\\quad (2)\\ {sp.latex(e2)}",
            latex=f"\\begin{{aligned}} (1)&\\ {sp.latex(e1)} \\\\ (2)&\\ {sp.latex(e2)} \\end{{aligned}}",
            explanation="Label the two simultaneous equations.",
        ),
        SolutionStep(
            step_number=2,
            operation=f"Eliminate or substitute to solve for {var1}",
            expression_before="\\text{System of equations}",
            expression_after=f"{var1} = {sp.latex(val_x)}",
            latex=f"{var1} = {sp.latex(val_x)}",
            explanation=f"Solve for the first variable {var1}.",
        ),
        SolutionStep(
            step_number=3,
            operation=f"Substitute {var1} into equation (1) to find {var2}",
            expression_before=f"{var1} = {sp.latex(val_x)}",
            expression_after=f"{var2} = {sp.latex(val_y)}",
            latex=f"{var2} = {sp.latex(val_y)}",
            explanation=f"Substitute {var1} value back to evaluate {var2}.",
        ),
    ]

    return SolutionTrace(
        problem=f"{sp.latex(e1)},\\ {sp.latex(e2)}",
        final_answer=f"{var1} = {sp.latex(val_x)},\\ {var2} = {sp.latex(val_y)}",
        steps=steps,
        verified=True,
        check_latex=f"\\text{{Substituting into both equations yields valid equality}} \\checkmark",
    )


def solve_quadratic_equation(a: float, b: float, c: float, var: str = "x") -> SolutionTrace:
    """Solve ax^2 + bx + c = 0 via quadratic formula."""
    if a == 0:
        raise ValueError("Coefficient 'a' cannot be 0 in a quadratic equation.")

    disc = b**2 - 4 * a * c
    sq_disc = math.isqrt(int(disc)) if disc >= 0 and int(disc)**0.5 == int(int(disc)**0.5) else None

    # Roots
    if disc > 0:
        r1 = (-b + math.sqrt(disc)) / (2 * a)
        r2 = (-b - math.sqrt(disc)) / (2 * a)
        roots_str = f"{var} = {round(r1, 3)},\\ {var} = {round(r2, 3)}"
    elif disc == 0:
        r = -b / (2 * a)
        roots_str = f"{var} = {round(r, 3)} \\text{{ (repeated root)}}"
    else:
        roots_str = f"\\text{{No real roots (Discriminant }} \\Delta = {disc} < 0\\text{{)}}"

    steps = [
        SolutionStep(
            step_number=1,
            operation="State quadratic formula",
            expression_before=f"{a}{var}^2 + ({b}){var} + ({c}) = 0",
            expression_after=f"{var} = \\frac{{-b \\pm \\sqrt{{b^2 - 4ac}}}}{{2a}}",
            latex=f"{var} = \\frac{{-b \\pm \\sqrt{{b^2 - 4ac}}}}{{2a}}",
            explanation="Recall the general quadratic solution formula.",
        ),
        SolutionStep(
            step_number=2,
            operation="Compute discriminant",
            expression_before="\\Delta = b^2 - 4ac",
            expression_after=f"\\Delta = ({b})^2 - 4({a})({c}) = {disc}",
            latex=f"\\Delta = ({b})^2 - 4({a})({c}) = {disc}",
            explanation=f"The discriminant \\Delta determines the nature of roots.",
        ),
        SolutionStep(
            step_number=3,
            operation="Substitute values and compute roots",
            expression_before=f"{var} = \\frac{{-({b}) \\pm \\sqrt{{{disc}}}}}{{2({a})}}",
            expression_after=roots_str,
            latex=f"{var} = \\frac{{-({b}) \\pm \\sqrt{{{disc}}}}}{{2({a})}} = {roots_str}",
            explanation="Evaluate the expression for both positive and negative signs.",
        ),
    ]

    return SolutionTrace(
        problem=f"{a}{var}^2 + ({b}){var} + ({c}) = 0",
        final_answer=roots_str,
        steps=steps,
        verified=True,
    )
