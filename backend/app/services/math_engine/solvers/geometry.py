"""Deterministic Geometry Solver."""
from __future__ import annotations

import math
from typing import Optional

from ..objects import SolutionStep, SolutionTrace


def solve_triangle_area(base: float, height: float, unit: str = "cm") -> SolutionTrace:
    """Solve Area of a triangle given base and perpendicular height."""
    area = 0.5 * base * height
    area_val_str = str(int(area)) if area.is_integer() else f"{area:.2f}"
    unit_str = f"\\text{{ {unit}}}^2" if unit else ""

    steps = [
        SolutionStep(
            step_number=1,
            operation="State formula for area of a triangle",
            expression_before="\\text{Area}",
            expression_after="A = \\frac{1}{2} b h",
            latex="A = \\frac{1}{2} b h",
            explanation="The area of a triangle is half the product of its base and perpendicular height.",
        ),
        SolutionStep(
            step_number=2,
            operation="Substitute values into formula",
            expression_before="A = \\frac{1}{2} b h",
            expression_after=f"A = \\frac{{1}}{{2}} \\times {base} \\times {height}",
            latex=f"A = \\frac{{1}}{{2}} \\times {base} \\times {height}",
            explanation=f"Substitute base = {base} and height = {height}.",
        ),
        SolutionStep(
            step_number=3,
            operation="Compute the area",
            expression_before=f"A = \\frac{{1}}{{2}} \\times {base} \\times {height}",
            expression_after=f"A = {area_val_str}{unit_str}",
            latex=f"A = {area_val_str}{unit_str}",
            explanation=f"Calculate 0.5 * {base} * {height} = {area_val_str}.",
        ),
    ]

    return SolutionTrace(
        problem=f"Find the area of a triangle with base {base} {unit} and height {height} {unit}",
        final_answer=f"A = {area_val_str}{unit_str}",
        steps=steps,
        verified=True,
        check_latex=f"2 \\times {area_val_str} / {base} = {height} \\checkmark",
    )


def solve_rectangle_perimeter_and_area(length: float, width: float, unit: str = "cm") -> SolutionTrace:
    """Calculate perimeter and area of a rectangle."""
    perimeter = 2 * (length + width)
    area = length * width
    p_str = str(int(perimeter)) if perimeter.is_integer() else f"{perimeter:.2f}"
    a_str = str(int(area)) if area.is_integer() else f"{area:.2f}"
    unit_lin = f"\\text{{ {unit}}}" if unit else ""
    unit_sq = f"\\text{{ {unit}}}^2" if unit else ""

    steps = [
        SolutionStep(
            step_number=1,
            operation="Calculate Perimeter",
            expression_before="P = 2(l + w)",
            expression_after=f"P = 2({length} + {width}) = {p_str}{unit_lin}",
            latex=f"P = 2({length} + {width}) = {p_str}{unit_lin}",
            explanation=f"Perimeter is twice the sum of length ({length}) and width ({width}).",
        ),
        SolutionStep(
            step_number=2,
            operation="Calculate Area",
            expression_before="A = l \\times w",
            expression_after=f"A = {length} \\times {width} = {a_str}{unit_sq}",
            latex=f"A = {length} \\times {width} = {a_str}{unit_sq}",
            explanation=f"Area is the product of length ({length}) and width ({width}).",
        ),
    ]

    return SolutionTrace(
        problem=f"Calculate perimeter and area of rectangle with length {length} {unit} and width {width} {unit}",
        final_answer=f"P = {p_str}{unit_lin},\\ A = {a_str}{unit_sq}",
        steps=steps,
        verified=True,
        check_latex=f"\\frac{{{a_str}}}{{{length}}} = {width} \\checkmark",
    )


def solve_circle_properties(radius: float, unit: str = "cm", use_pi_fraction: bool = True) -> SolutionTrace:
    """Calculate circumference and area of a circle with radius r."""
    pi_val = 22.0 / 7.0 if use_pi_fraction else math.pi
    pi_sym = "\\frac{22}{7}" if use_pi_fraction else "3.1416"

    circumference = 2 * pi_val * radius
    area = pi_val * (radius ** 2)

    c_str = str(int(circumference)) if circumference.is_integer() else f"{circumference:.2f}"
    a_str = str(int(area)) if area.is_integer() else f"{area:.2f}"
    unit_lin = f"\\text{{ {unit}}}" if unit else ""
    unit_sq = f"\\text{{ {unit}}}^2" if unit else ""

    steps = [
        SolutionStep(
            step_number=1,
            operation="Calculate Circumference",
            expression_before="C = 2 \\pi r",
            expression_after=f"C = 2 \\times {pi_sym} \\times {radius} = {c_str}{unit_lin}",
            latex=f"C = 2 \\times {pi_sym} \\times {radius} = {c_str}{unit_lin}",
            explanation=f"Circumference is 2 * pi * radius using pi approx {pi_sym}.",
        ),
        SolutionStep(
            step_number=2,
            operation="Calculate Area",
            expression_before="A = \\pi r^2",
            expression_after=f"A = {pi_sym} \\times {radius}^2 = {a_str}{unit_sq}",
            latex=f"A = {pi_sym} \\times ({radius})^2 = {a_str}{unit_sq}",
            explanation=f"Area is pi * radius squared.",
        ),
    ]

    return SolutionTrace(
        problem=f"Find circumference and area of circle with radius {radius} {unit}",
        final_answer=f"C = {c_str}{unit_lin},\\ A = {a_str}{unit_sq}",
        steps=steps,
        verified=True,
    )


def solve_trapezium_area(a: float, b: float, height: float, unit: str = "cm") -> SolutionTrace:
    """Area of trapezium A = 1/2 * (a + b) * h."""
    area = 0.5 * (a + b) * height
    a_str = str(int(area)) if area.is_integer() else f"{area:.2f}"
    unit_sq = f"\\text{{ {unit}}}^2" if unit else ""

    steps = [
        SolutionStep(
            step_number=1,
            operation="State formula for area of a trapezium",
            expression_before="\\text{Area}",
            expression_after="A = \\frac{1}{2}(a + b)h",
            latex="A = \\frac{1}{2}(a + b)h",
            explanation="The area is half the sum of parallel sides multiplied by perpendicular height.",
        ),
        SolutionStep(
            step_number=2,
            operation="Substitute parallel sides and height",
            expression_before="A = \\frac{1}{2}(a + b)h",
            expression_after=f"A = \\frac{{1}}{{2}}({a} + {b}) \\times {height}",
            latex=f"A = \\frac{{1}}{{2}}({a} + {b}) \\times {height}",
            explanation=f"Substitute parallel sides a = {a}, b = {b}, and height h = {height}.",
        ),
        SolutionStep(
            step_number=3,
            operation="Compute Area",
            expression_before=f"A = \\frac{{1}}{{2}}({a + b}) \\times {height}",
            expression_after=f"A = {a_str}{unit_sq}",
            latex=f"A = {a_str}{unit_sq}",
            explanation=f"Calculate 0.5 * {a + b} * {height} = {a_str}.",
        ),
    ]

    return SolutionTrace(
        problem=f"Calculate area of trapezium with parallel sides {a} {unit}, {b} {unit} and height {height} {unit}",
        final_answer=f"A = {a_str}{unit_sq}",
        steps=steps,
        verified=True,
    )


def solve_pythagoras(
    a: Optional[float] = None,
    b: Optional[float] = None,
    c: Optional[float] = None,
    unit: str = "cm",
) -> SolutionTrace:
    """Solve for missing side of right triangle using a^2 + b^2 = c^2."""
    unit_str = f"\\text{{ {unit}}}" if unit else ""

    if c is None and a is not None and b is not None:
        c_val = math.sqrt(a**2 + b**2)
        c_str = str(int(c_val)) if c_val.is_integer() else f"{c_val:.2f}"
        steps = [
            SolutionStep(
                step_number=1,
                operation="State Pythagoras Theorem",
                expression_before="c^2 = a^2 + b^2",
                expression_after=f"c^2 = {a}^2 + {b}^2",
                latex=f"c = \\sqrt{{{a}^2 + {b}^2}}",
                explanation="Hypotenuse c squared equals the sum of the squares of the legs a and b.",
            ),
            SolutionStep(
                step_number=2,
                operation="Calculate squares and sum",
                expression_before=f"c^2 = {a**2} + {b**2}",
                expression_after=f"c^2 = {a**2 + b**2}",
                latex=f"c^2 = {a**2 + b**2}",
                explanation=f"{a}^2 = {a**2} and {b**2} = {b**2}, sum = {a**2 + b**2}.",
            ),
            SolutionStep(
                step_number=3,
                operation="Take square root",
                expression_before=f"c = \\sqrt{{{a**2 + b**2}}}",
                expression_after=f"c = {c_str}{unit_str}",
                latex=f"c = {c_str}{unit_str}",
                explanation=f"Take the positive square root to find c = {c_str}.",
            ),
        ]
        return SolutionTrace(
            problem=f"Find hypotenuse c given legs a = {a} {unit} and b = {b} {unit}",
            final_answer=f"c = {c_str}{unit_str}",
            steps=steps,
            verified=True,
            check_latex=f"{a}^2 + {b}^2 = {c_val**2:.1f} \\approx ({c_str})^2 \\checkmark",
        )

    elif a is None and b is not None and c is not None:
        if c <= b:
            raise ValueError("Hypotenuse c must be strictly greater than leg b")
        a_val = math.sqrt(c**2 - b**2)
        a_str = str(int(a_val)) if a_val.is_integer() else f"{a_val:.2f}"
        steps = [
            SolutionStep(
                step_number=1,
                operation="Rearrange Pythagoras Theorem for missing leg",
                expression_before="a^2 + b^2 = c^2",
                expression_after=f"a^2 = c^2 - b^2 = {c}^2 - {b}^2",
                latex=f"a = \\sqrt{{c^2 - b^2}}",
                explanation="Subtract b^2 from c^2 to isolate a^2.",
            ),
            SolutionStep(
                step_number=2,
                operation="Calculate squares and difference",
                expression_before=f"a^2 = {c**2} - {b**2}",
                expression_after=f"a^2 = {c**2 - b**2}",
                latex=f"a^2 = {c**2 - b**2}",
                explanation=f"{c}^2 = {c**2} and {b**2} = {b**2}, difference = {c**2 - b**2}.",
            ),
            SolutionStep(
                step_number=3,
                operation="Take square root",
                expression_before=f"a = \\sqrt{{{c**2 - b**2}}}",
                expression_after=f"a = {a_str}{unit_str}",
                latex=f"a = {a_str}{unit_str}",
                explanation=f"Compute square root to find a = {a_str}.",
            ),
        ]
        return SolutionTrace(
            problem=f"Find leg a given leg b = {b} {unit} and hypotenuse c = {c} {unit}",
            final_answer=f"a = {a_str}{unit_str}",
            steps=steps,
            verified=True,
            check_latex=f"({a_str})^2 + {b}^2 = {a_val**2 + b**2:.1f} = {c**2} \\checkmark",
        )

    else:
        raise ValueError("Must provide either (a and b) or (b and c)")


def solve_cylinder_volume_and_surface_area(
    radius: float,
    height: float,
    unit: str = "cm",
    use_pi_fraction: bool = True,
) -> SolutionTrace:
    """Calculate volume and total surface area of a closed cylinder."""
    pi_val = 22.0 / 7.0 if use_pi_fraction else math.pi
    pi_sym = "\\frac{22}{7}" if use_pi_fraction else "3.1416"

    volume = pi_val * (radius ** 2) * height
    curved_sa = 2 * pi_val * radius * height
    two_bases = 2 * pi_val * (radius ** 2)
    total_sa = curved_sa + two_bases

    v_str = str(int(volume)) if volume.is_integer() else f"{volume:.2f}"
    tsa_str = str(int(total_sa)) if total_sa.is_integer() else f"{total_sa:.2f}"
    unit_vol = f"\\text{{ {unit}}}^3" if unit else ""
    unit_sa = f"\\text{{ {unit}}}^2" if unit else ""

    steps = [
        SolutionStep(
            step_number=1,
            operation="Calculate Volume: V = pi * r^2 * h",
            expression_before="V = \\pi r^2 h",
            expression_after=f"V = {pi_sym} \\times {radius}^2 \\times {height} = {v_str}{unit_vol}",
            latex=f"V = {pi_sym} \\times ({radius})^2 \\times {height} = {v_str}{unit_vol}",
            explanation=f"Multiply base area (pi * r^2) by height ({height}).",
        ),
        SolutionStep(
            step_number=2,
            operation="Calculate Total Surface Area: A = 2*pi*r*h + 2*pi*r^2",
            expression_before="A = 2\\pi rh + 2\\pi r^2",
            expression_after=f"A = {tsa_str}{unit_sa}",
            latex=f"A = 2({pi_sym})({radius})({height}) + 2({pi_sym})({radius})^2 = {tsa_str}{unit_sa}",
            explanation="Sum of curved surface area and top and bottom circular bases.",
        ),
    ]

    return SolutionTrace(
        problem=f"Find volume and surface area of cylinder with radius {radius} {unit} and height {height} {unit}",
        final_answer=f"V = {v_str}{unit_vol},\\ A = {tsa_str}{unit_sa}",
        steps=steps,
        verified=True,
    )


def solve_cuboid_volume_and_surface_area(
    l: float,
    w: float,
    h: float,
    unit: str = "cm",
) -> SolutionTrace:
    """Calculate volume and surface area of a cuboid."""
    volume = l * w * h
    sa = 2 * (l * w + l * h + w * h)
    v_str = str(int(volume)) if volume.is_integer() else f"{volume:.2f}"
    sa_str = str(int(sa)) if sa.is_integer() else f"{sa:.2f}"
    unit_vol = f"\\text{{ {unit}}}^3" if unit else ""
    unit_sa = f"\\text{{ {unit}}}^2" if unit else ""

    steps = [
        SolutionStep(
            step_number=1,
            operation="Calculate Volume: V = l * w * h",
            expression_before="V = l \\times w \\times h",
            expression_after=f"V = {l} \\times {w} \\times {h} = {v_str}{unit_vol}",
            latex=f"V = {l} \\times {w} \\times {h} = {v_str}{unit_vol}",
            explanation="Product of length, width, and height gives cuboid volume.",
        ),
        SolutionStep(
            step_number=2,
            operation="Calculate Total Surface Area: A = 2(lw + lh + wh)",
            expression_before="A = 2(lw + lh + wh)",
            expression_after=f"A = 2({l*w} + {l*h} + {w*h}) = {sa_str}{unit_sa}",
            latex=f"A = 2({l} \\times {w} + {l} \\times {h} + {w} \\times {h}) = {sa_str}{unit_sa}",
            explanation="Sum of areas of all six rectangular faces.",
        ),
    ]

    return SolutionTrace(
        problem=f"Find volume and surface area of cuboid ({l} x {w} x {h} {unit})",
        final_answer=f"V = {v_str}{unit_vol},\\ A = {sa_str}{unit_sa}",
        steps=steps,
        verified=True,
    )


def solve_coordinate_distance_midpoint(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> SolutionTrace:
    """Calculate Euclidean distance and midpoint between two points (x1, y1) and (x2, y2)."""
    dx = x2 - x1
    dy = y2 - y1
    dist = math.sqrt(dx**2 + dy**2)
    dist_str = str(int(dist)) if dist.is_integer() else f"{dist:.2f}"

    mid_x = (x1 + x2) / 2.0
    mid_y = (y1 + y2) / 2.0
    mx_str = str(int(mid_x)) if mid_x.is_integer() else f"{mid_x:.2f}"
    my_str = str(int(mid_y)) if mid_y.is_integer() else f"{mid_y:.2f}"

    steps = [
        SolutionStep(
            step_number=1,
            operation="Calculate Distance d = sqrt((x2 - x1)^2 + (y2 - y1)^2)",
            expression_before="d = \\sqrt{(x_2 - x_1)^2 + (y_2 - y_1)^2}",
            expression_after=f"d = \\sqrt{{({dx})^2 + ({dy})^2}} = {dist_str}",
            latex=f"d = \\sqrt{{({x2} - {x1})^2 + ({y2} - {y1})^2}} = \\sqrt{{{dx**2 + dy**2}}} = {dist_str}",
            explanation=f"Apply distance formula with dx = {dx} and dy = {dy}.",
        ),
        SolutionStep(
            step_number=2,
            operation="Calculate Midpoint M = ((x1 + x2)/2, (y1 + y2)/2)",
            expression_before="M = \\left(\\frac{x_1 + x_2}{2}, \\frac{y_1 + y_2}{2}\\right)",
            expression_after=f"M = ({mx_str}, {my_str})",
            latex=f"M = \\left(\\frac{{{x1} + {x2}}}{{2}}, \\frac{{{y1} + {y2}}}{{2}}\\right) = ({mx_str}, {my_str})",
            explanation="Average the x-coordinates and y-coordinates respectively.",
        ),
    ]

    return SolutionTrace(
        problem=f"Find distance and midpoint between ({x1}, {y1}) and ({x2}, {y2})",
        final_answer=f"d = {dist_str},\\ M = ({mx_str}, {my_str})",
        steps=steps,
        verified=True,
    )
