"""Deterministic Trigonometry Solver."""
from __future__ import annotations

import math
from typing import Literal

from ..objects import SolutionStep, SolutionTrace


def solve_right_triangle_side(
    angle_deg: float,
    known_length: float,
    ratio: Literal["sin", "cos", "tan"],
    find_part: Literal["numerator", "denominator"],
    unit: str = "cm",
) -> SolutionTrace:
    """Solve for unknown side of right triangle using sin, cos, or tan.
    
    If ratio == 'sin' (opp/hyp):
      - find_part == 'numerator': find opp = hyp * sin(theta)
      - find_part == 'denominator': find hyp = opp / sin(theta)
    If ratio == 'cos' (adj/hyp):
      - find_part == 'numerator': find adj = hyp * cos(theta)
      - find_part == 'denominator': find hyp = adj / cos(theta)
    If ratio == 'tan' (opp/adj):
      - find_part == 'numerator': find opp = adj * tan(theta)
      - find_part == 'denominator': find adj = opp / tan(theta)
    """
    rad = math.radians(angle_deg)
    ratio_labels = {
        "sin": ("\\sin(\\theta)", "\\frac{\\text{opposite}}{\\text{hypotenuse}}", "opposite", "hypotenuse"),
        "cos": ("\\cos(\\theta)", "\\frac{\\text{adjacent}}{\\text{hypotenuse}}", "adjacent", "hypotenuse"),
        "tan": ("\\tan(\\theta)", "\\frac{\\text{opposite}}{\\text{adjacent}}", "opposite", "adjacent"),
    }
    sym, frac_sym, num_name, den_name = ratio_labels[ratio]

    trig_val = math.sin(rad) if ratio == "sin" else (math.cos(rad) if ratio == "cos" else math.tan(rad))
    trig_str = f"{trig_val:.4f}"

    if find_part == "numerator":
        unknown_name = num_name
        known_name = den_name
        res = known_length * trig_val
        formula_sub = f"\\frac{{{unknown_name}}}{{{known_length}}}"
        calc_step = f"{unknown_name} = {known_length} \\times {trig_str}"
    else:
        unknown_name = den_name
        known_name = num_name
        res = known_length / trig_val
        formula_sub = f"\\frac{{{known_length}}}{{{unknown_name}}}"
        calc_step = f"{unknown_name} = \\frac{{{known_length}}}{{{trig_str}}}"

    res_str = str(int(res)) if res.is_integer() else f"{res:.2f}"
    unit_str = f"\\text{{ {unit}}}" if unit else ""

    steps = [
        SolutionStep(
            step_number=1,
            operation=f"Select trigonometric ratio ({ratio})",
            expression_before=sym,
            expression_after=frac_sym,
            latex=f"\\{ratio}({angle_deg}^\\circ) = {frac_sym}",
            explanation=f"Use definition of {ratio}: ratio of {num_name} to {den_name}.",
        ),
        SolutionStep(
            step_number=2,
            operation="Substitute known values into equation",
            expression_before=f"\\{ratio}({angle_deg}^\\circ) = {frac_sym}",
            expression_after=f"{trig_str} = {formula_sub}",
            latex=f"{trig_str} = {formula_sub}",
            explanation=f"Evaluate \\{ratio}({angle_deg}^\\circ) \\approx {trig_str} and substitute {known_name} = {known_length}.",
        ),
        SolutionStep(
            step_number=3,
            operation=f"Isolate and calculate unknown side ({unknown_name})",
            expression_before=calc_step,
            expression_after=f"{unknown_name} = {res_str}{unit_str}",
            latex=f"{unknown_name} = {res_str}{unit_str}",
            explanation=f"Rearrange to solve for {unknown_name}.",
        ),
    ]

    return SolutionTrace(
        problem=f"Find {unknown_name} given angle = {angle_deg}° and {known_name} = {known_length} {unit} using {ratio}",
        final_answer=f"{unknown_name} = {res_str}{unit_str}",
        steps=steps,
        verified=True,
    )


def solve_right_triangle_angle(
    opposite: float,
    adjacent: float,
) -> SolutionTrace:
    """Find acute angle theta given opposite and adjacent sides using tan(theta)."""
    ratio_val = opposite / adjacent
    rad = math.atan(ratio_val)
    deg = math.degrees(rad)
    deg_str = f"{deg:.1f}^\\circ"

    steps = [
        SolutionStep(
            step_number=1,
            operation="Apply tangent ratio formula",
            expression_before="\\tan(\\theta) = \\frac{\\text{opp}}{\\text{adj}}",
            expression_after=f"\\tan(\\theta) = \\frac{{{opposite}}}{{{adjacent}}} = {ratio_val:.4f}",
            latex=f"\\tan(\\theta) = \\frac{{{opposite}}}{{{adjacent}}} = {ratio_val:.4f}",
            explanation="Tangent of the angle is opposite side over adjacent side.",
        ),
        SolutionStep(
            step_number=2,
            operation="Take inverse tangent (arctan)",
            expression_before=f"\\theta = \\arctan({ratio_val:.4f})",
            expression_after=f"\\theta = {deg_str}",
            latex=f"\\theta = \\arctan\\left({ratio_val:.4f}\\right) = {deg_str}",
            explanation=f"Calculate the inverse tangent to find angle theta.",
        ),
    ]

    return SolutionTrace(
        problem=f"Find angle theta in right triangle with opposite = {opposite} and adjacent = {adjacent}",
        final_answer=f"\\theta = {deg_str}",
        steps=steps,
        verified=True,
    )


def solve_elevation_depression(
    height: float,
    distance: float,
    is_elevation: bool = True,
    unit: str = "m",
) -> SolutionTrace:
    """Solve for angle of elevation or depression."""
    kind = "elevation" if is_elevation else "depression"
    trace = solve_right_triangle_angle(opposite=height, adjacent=distance)

    deg = math.degrees(math.atan(height / distance))
    deg_str = f"{deg:.1f}^\\circ"

    steps = [
        SolutionStep(
            step_number=1,
            operation="Model problem as right-angled triangle",
            expression_before=f"\\text{{Height}} = {height}\\text{{ {unit}}},\\ \\text{{Distance}} = {distance}\\text{{ {unit}}}",
            expression_after=f"\\tan(\\theta) = \\frac{{\\text{{Height}}}}{{\\text{{Distance}}}}",
            latex=f"\\tan(\\theta) = \\frac{{{height}}}{{{distance}}}",
            explanation=f"The line of sight forms a right triangle where opposite side is height ({height} {unit}) and adjacent side is horizontal distance ({distance} {unit}).",
        ),
        SolutionStep(
            step_number=2,
            operation=f"Calculate angle of {kind}",
            expression_before=f"\\theta = \\arctan\\left(\\frac{{{height}}}{{{distance}}}\\right)",
            expression_after=f"\\theta = {deg_str}",
            latex=f"\\theta = \\arctan\\left(\\frac{{{height}}}{{{distance}}}\\right) = {deg_str}",
            explanation=f"Evaluate arctan to determine the angle of {kind}.",
        ),
    ]

    return SolutionTrace(
        problem=f"Find angle of {kind} to a point of height {height} {unit} at a horizontal distance of {distance} {unit}",
        final_answer=f"\\text{{Angle of {kind}}} = {deg_str}",
        steps=steps,
        verified=True,
    )
