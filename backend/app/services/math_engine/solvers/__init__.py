"""Modular Math Engine Domain Solvers.

Exposes domain-specific solvers across all CBC Mathematics domains:
- Arithmetic & Number Theory
- Fractions & Decimals
- Percentages
- Ratios & Proportions
- Algebra & Systems
- Geometry & Coordinate Geometry
- Trigonometry
- Measurement & Rates
- Statistics
- Probability
- Financial Mathematics
"""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Any, List, Optional

from ..latex_input import to_plain
from ..objects import SolutionStep, SolutionTrace
from .algebra import (
    solve_linear_equation,
    solve_quadratic_equation,
    solve_simultaneous_linear,
)
from .arithmetic import (
    prime_factorization,
    solve_gcd_lcm,
    solve_rounding,
)
from .financial import (
    solve_compound_interest,
    solve_profit_loss,
    solve_simple_interest,
)
from .fractions import solve_fraction_operation
from .integers import NotArithmetic, arithmetic_in, solve_integer_expression
from .geometry import (
    solve_circle_properties,
    solve_coordinate_distance_midpoint,
    solve_cuboid_volume_and_surface_area,
    solve_cylinder_volume_and_surface_area,
    solve_pythagoras,
    solve_rectangle_perimeter_and_area,
    solve_trapezium_area,
    solve_triangle_area,
)
from .measurement import (
    solve_density_mass_volume,
    solve_speed_distance_time,
    solve_unit_conversion,
)
from .percentages import (
    solve_percentage_change,
    solve_percentage_of_quantity,
)
from .probability import (
    solve_complementary_probability,
    solve_independent_events_probability,
    solve_simple_probability,
)
from .ratios import (
    solve_share_in_ratio,
    solve_simplify_ratio,
)
from .statistics import (
    solve_dataset_summary,
    solve_frequency_table_mean,
)
from .trigonometry import (
    solve_elevation_depression,
    solve_right_triangle_angle,
    solve_right_triangle_side,
)

__all__ = [
    # Arithmetic
    "solve_integer_expression",
    "arithmetic_in",
    "NotArithmetic",
    "prime_factorization",
    "solve_gcd_lcm",
    "solve_rounding",
    # Fractions
    "solve_fraction_operation",
    # Percentages
    "solve_percentage_of_quantity",
    "solve_percentage_change",
    # Ratios
    "solve_simplify_ratio",
    "solve_share_in_ratio",
    # Algebra
    "solve_linear_equation",
    "solve_simultaneous_linear",
    "solve_quadratic_equation",
    # Geometry
    "solve_triangle_area",
    "solve_rectangle_perimeter_and_area",
    "solve_circle_properties",
    "solve_trapezium_area",
    "solve_pythagoras",
    "solve_cylinder_volume_and_surface_area",
    "solve_cuboid_volume_and_surface_area",
    "solve_coordinate_distance_midpoint",
    # Trigonometry
    "solve_right_triangle_side",
    "solve_right_triangle_angle",
    "solve_elevation_depression",
    # Measurement
    "solve_unit_conversion",
    "solve_speed_distance_time",
    "solve_density_mass_volume",
    # Statistics
    "solve_dataset_summary",
    "solve_frequency_table_mean",
    # Probability
    "solve_simple_probability",
    "solve_complementary_probability",
    "solve_independent_events_probability",
    # Financial
    "solve_profit_loss",
    "solve_simple_interest",
    "solve_compound_interest",
    # Unified dispatcher
    "solve_problem",
]


# An equation inside a sentence. "Solve for x: 3x + 4 = 19" carries its own
# prose, and sympify chokes on the words — so take the longest run of
# mathematics around the "=" rather than handing over the whole line.
_EQUATION = re.compile(r"[0-9a-zA-Z.\^*/+\-()\s]*=[0-9a-zA-Z.\^*/+\-()\s]*")


def _equation_in(text: str) -> str:
    """The equation inside a sentence, or "" when there is not exactly one."""
    if "=" not in text:
        return ""
    best = ""
    for match in _EQUATION.finditer(text):
        candidate = match.group(0).strip(" :;,.")
        if candidate.count("=") != 1:
            continue
        lhs, rhs = candidate.split("=")
        # Both sides must carry a number or a variable, and neither may be
        # prose: "Solve for x" alone is not half of an equation.
        if not (lhs.strip() and rhs.strip()):
            continue
        # Drop leading words: keep the tail of the left side from the last word
        # that is not part of the expression.
        lhs = re.sub(r"^.*?(?=[0-9(]|\b[a-zA-Z]\b\s*[-+*/^=])", "", lhs, count=1)
        rebuilt = f"{lhs.strip()}={rhs.strip()}"
        if len(re.sub(r"\s", "", rebuilt)) > len(re.sub(r"\s", "", best)):
            best = rebuilt
    if not best:
        return ""
    # A residual multi-letter word means prose survived; refuse rather than
    # guess. Single letters are variables.
    if re.search(r"[a-zA-Z]{2,}", re.sub(r"\b(sqrt|pi|sin|cos|tan|log)\b", "", best)):
        return ""
    return best


def solve_problem(problem: str, domain: str = "auto") -> SolutionTrace:
    """Unified problem solving dispatcher across all mathematical domains.

    Returns a trace with ``unsolved=True`` when no pattern matches. That is the
    honest answer for most free text: this dispatcher recognises a fixed set of
    shapes, and a CBC word problem can be phrased a hundred ways. Saying so is
    useful; saying "Solved" over a step that is the question read back is not.
    """
    # Every caller hands us LaTeX, because that is what renders and prints. The
    # patterns below are written for plain text, so normalise once, here, and
    # never make each pattern carry its own LaTeX variant.
    clean = to_plain(problem)

    # 1. Fraction operations: e.g. "2/3 + 3/4", "5/6 * 2/3"
    frac_match = re.search(r"(\d+)\s*/\s*(\d+)\s*([+\-*/])\s*(\d+)\s*/\s*(\d+)", clean)
    if frac_match:
        n1, d1, op, n2, d2 = frac_match.groups()
        return solve_fraction_operation(int(n1), int(d1), int(n2), int(d2), op=op)

    # 2. Triangle area: "base = B, height = H" or "base of 8 cm and height of 6 cm"
    tri_match = re.search(
        r"base\s*(?:of|=|:)?\s*(\d+(?:\.\d+)?).*height\s*(?:of|=|:)?\s*(\d+(?:\.\d+)?)",
        clean,
        re.I,
    )
    if tri_match:
        b, h = map(float, tri_match.groups())
        return solve_triangle_area(b, h)

    # 3. Pythagoras theorem: "legs a = 3 and b = 4" or "hypotenuse"
    pyth_hyp = re.search(r"legs?\s*(?:a\s*=\s*)?(\d+(?:\.\d+)?)\s*(?:and|,)\s*(?:b\s*=\s*)?(\d+(?:\.\d+)?)", clean, re.I)
    if pyth_hyp and "pythagor" in clean.lower():
        a_val, b_val = map(float, pyth_hyp.groups())
        return solve_pythagoras(a=a_val, b=b_val)

    # 4. Dataset statistics: [1, 2, 3, 4]
    data_match = re.search(r"\[([\d\s,.]+)\]", clean)
    if data_match:
        vals = [float(x.strip()) for x in data_match.group(1).split(",") if x.strip()]
        if vals:
            return solve_dataset_summary(vals)

    # 5. Simple Interest: "principal of X at R% for T years"
    si_match = re.search(r"principal\s*(?:of|=|:)?\s*(\d+(?:\.\d+)?).*rate\s*(?:of|=|:)?\s*(\d+(?:\.\d+)?).*time\s*(?:of|=|:)?\s*(\d+(?:\.\d+)?)", clean, re.I)
    if si_match:
        p, r, t = map(float, si_match.groups())
        return solve_simple_interest(p, r, t)

    # 6. GCD / LCM: "GCD of 24 and 36"
    gcd_match = re.search(r"(?:gcd|lcm|hcf)\s*(?:of)?\s*(\d+)\s*(?:and|,)\s*(\d+)", clean, re.I)
    if gcd_match:
        a_int, b_int = map(int, gcd_match.groups())
        return solve_gcd_lcm(a_int, b_int)

    # 7. Percentage: "20% of 150"
    pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:of)\s*(\d+(?:\.\d+)?)", clean, re.I)
    if pct_match:
        pct_val, total_val = map(float, pct_match.groups())
        return solve_percentage_of_quantity(pct_val, total_val)

    # 8. Speed distance time: "distance = D, time = T"
    sdt_match = re.search(r"distance\s*(?:of|=|:)?\s*(\d+(?:\.\d+)?).*time\s*(?:of|=|:)?\s*(\d+(?:\.\d+)?)", clean, re.I)
    if sdt_match:
        d, t = map(float, sdt_match.groups())
        return solve_speed_distance_time(distance=d, time=t)

    # 9. Equations (linear or quadratic)
    equation = _equation_in(clean)
    if equation:
        eq_clean = re.sub(r"(\d)([a-zA-Z])", r"\1*\2", equation)
        eq_clean = re.sub(r"(\d)\(", r"\1*(", eq_clean)
        eq_clean = re.sub(r"\)([a-zA-Z0-9])", r")*\1", eq_clean)

        # Check for quadratic term x^2 or x**2
        if "x^2" in eq_clean or "x**2" in eq_clean or "x²" in eq_clean:
            try:
                norm_quad = eq_clean.replace("x²", "x**2").replace("^", "**")
                parts = norm_quad.split("=")
                import sympy as sp
                lhs = sp.sympify(parts[0]) - sp.sympify(parts[1])
                x_sym = sp.Symbol("x")
                a = float(lhs.coeff(x_sym, 2))
                b = float(lhs.coeff(x_sym, 1))
                c = float(lhs.coeff(x_sym, 0))
                return solve_quadratic_equation(a, b, c)
            except Exception:
                pass

        try:
            return solve_linear_equation(eq_clean)
        except Exception:
            pass

    # 10. A plain calculation. Last, so a fraction, an equation or an area is
    #     still worked by the solver that knows its formula — this takes only
    #     what nothing else claimed. Without it the whole Integers sub-strand
    #     had no worked solutions at all.
    expression = arithmetic_in(clean)
    if expression:
        try:
            return solve_integer_expression(expression)
        except NotArithmetic:
            pass

    # Nothing matched. Say so — do not invent a step.
    return SolutionTrace(
        problem=problem,
        final_answer="",
        steps=[],
        verified=False,
        unsolved=True,
        unsolved_reason=(
            "No deterministic solver recognises this problem. The engine solves a "
            "fixed set of shapes (fractions, linear and quadratic equations, area "
            "and perimeter, Pythagoras, statistics, percentages, ratios, interest, "
            "speed/distance/time, GCD/LCM, probability); anything else needs to be "
            "worked by hand or rephrased into one of them."
        ),
    )
