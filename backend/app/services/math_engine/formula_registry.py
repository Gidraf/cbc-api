"""Canonical CBC Mathematics Formula Registry.

Contains 50+ standardized mathematical formulas across all CBC domains:
1. Number & Operations
2. Algebra
3. Geometry (2D)
4. Trigonometry
5. Coordinate Geometry
6. Measurement & 3D Mensuration
7. Rates & Physical Quantities
8. Financial Mathematics
9. Statistics
10. Probability
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..grade_order import normalize_grade


@dataclass(slots=True)
class MathFormula:
    id: str
    name: str
    latex: str
    variables: Dict[str, str]
    domain: str
    topics: List[str]
    grades: List[str]
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "latex": self.latex,
            "variables": self.variables,
            "domain": self.domain,
            "topics": self.topics,
            "grades": self.grades,
            "description": self.description,
        }


FORMULA_REGISTRY: List[MathFormula] = [
    # ══════════════════════════════════════════════════════════════════════
    # 1. NUMBER & OPERATIONS (7 formulas)
    # ══════════════════════════════════════════════════════════════════════
    MathFormula(
        id="fraction_add",
        name="Addition of Fractions",
        latex=r"\frac{a}{b} + \frac{c}{d} = \frac{ad + bc}{bd}",
        variables={"a, c": "numerators", "b, d": "denominators"},
        domain="arithmetic",
        topics=["number", "fractions", "addition"],
        grades=["grade-4", "grade-5", "grade-6", "grade-7", "grade-8"],
        description="Add two fractions using a common denominator.",
    ),
    MathFormula(
        id="fraction_mult",
        name="Multiplication of Fractions",
        latex=r"\frac{a}{b} \times \frac{c}{d} = \frac{a \times c}{b \times d}",
        variables={"a, c": "numerators", "b, d": "denominators"},
        domain="arithmetic",
        topics=["number", "fractions", "multiplication"],
        grades=["grade-5", "grade-6", "grade-7", "grade-8"],
        description="Multiply numerators and denominators.",
    ),
    MathFormula(
        id="fraction_div",
        name="Division of Fractions",
        latex=r"\frac{a}{b} \div \frac{c}{d} = \frac{a}{b} \times \frac{d}{c} = \frac{ad}{bc}",
        variables={"a, c": "numerators", "b, d": "denominators"},
        domain="arithmetic",
        topics=["number", "fractions", "division"],
        grades=["grade-6", "grade-7", "grade-8"],
        description="Multiply by the reciprocal of the divisor fraction.",
    ),
    MathFormula(
        id="percentage_formula",
        name="Percentage Calculation",
        latex=r"P = \frac{\text{Part}}{\text{Whole}} \times 100\%",
        variables={"P": "percentage", "Part": "given portion", "Whole": "total value"},
        domain="arithmetic",
        topics=["number", "percentages"],
        grades=["grade-5", "grade-6", "grade-7", "grade-8"],
        description="Express part of a quantity as a percentage of the total.",
    ),
    MathFormula(
        id="percentage_change",
        name="Percentage Change",
        latex=r"\%\Delta = \frac{|\text{New} - \text{Original}|}{\text{Original}} \times 100\%",
        variables={"New": "new value", "Original": "initial value"},
        domain="arithmetic",
        topics=["number", "percentages", "change"],
        grades=["grade-6", "grade-7", "grade-8", "grade-9"],
        description="Calculate percentage increase or decrease relative to initial value.",
    ),
    MathFormula(
        id="ratio_sharing",
        name="Ratio Sharing",
        latex=r"\text{Share} = \frac{\text{Part}}{\sum \text{Parts}} \times \text{Total}",
        variables={"Part": "individual ratio term", "Total": "total quantity being shared"},
        domain="arithmetic",
        topics=["number", "ratios", "proportion"],
        grades=["grade-6", "grade-7", "grade-8", "grade-9"],
        description="Divide a quantity proportionally according to a given ratio.",
    ),
    MathFormula(
        id="gcd_lcm_relation",
        name="Product of Two Numbers and Their GCD/LCM",
        latex=r"a \times b = \text{GCD}(a, b) \times \text{LCM}(a, b)",
        variables={"a, b": "positive integers", "GCD": "greatest common divisor", "LCM": "least common multiple"},
        domain="arithmetic",
        topics=["number", "gcd", "lcm", "factors"],
        grades=["grade-6", "grade-7", "grade-8"],
        description="Fundamental relation between two integers and their common divisors/multiples.",
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 2. ALGEBRA (9 formulas)
    # ══════════════════════════════════════════════════════════════════════
    MathFormula(
        id="linear_equation",
        name="Linear Equation in One Unknown",
        latex=r"ax + b = c \implies x = \frac{c - b}{a}",
        variables={"a": "coefficient", "b, c": "constants", "x": "unknown variable"},
        domain="algebra",
        topics=["algebra", "equations", "linear"],
        grades=["grade-7", "grade-8", "grade-9"],
        description="Solve a single-variable first-degree linear equation.",
    ),
    MathFormula(
        id="quadratic_formula",
        name="Quadratic Formula",
        latex=r"x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}",
        variables={"a, b, c": "coefficients (a != 0)", "x": "roots"},
        domain="algebra",
        topics=["algebra", "quadratic", "equations"],
        grades=["grade-9", "grade-10", "grade-11", "grade-12"],
        description="General solution for roots of ax^2 + bx + c = 0.",
    ),
    MathFormula(
        id="quadratic_discriminant",
        name="Quadratic Discriminant",
        latex=r"\Delta = b^2 - 4ac",
        variables={"a, b, c": "coefficients", r"\Delta": "discriminant"},
        domain="algebra",
        topics=["algebra", "quadratic", "discriminant"],
        grades=["grade-9", "grade-10", "grade-11", "grade-12"],
        description="Determines nature of roots: real distinct, real repeated, or complex.",
    ),
    MathFormula(
        id="difference_of_squares",
        name="Difference of Two Squares",
        latex=r"a^2 - b^2 = (a - b)(a + b)",
        variables={"a, b": "algebraic expressions"},
        domain="algebra",
        topics=["algebra", "factorization", "identities"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Factorization identity for difference of squares.",
    ),
    MathFormula(
        id="perfect_square_expansion",
        name="Expansion of Perfect Squares",
        latex=r"(a \pm b)^2 = a^2 \pm 2ab + b^2",
        variables={"a, b": "terms"},
        domain="algebra",
        topics=["algebra", "expansion", "identities"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Binomial square expansion formula.",
    ),
    MathFormula(
        id="laws_of_indices_mult",
        name="Product Law of Indices",
        latex=r"a^m \times a^n = a^{m+n}",
        variables={"a": "base", "m, n": "powers"},
        domain="algebra",
        topics=["algebra", "indices", "powers"],
        grades=["grade-7", "grade-8", "grade-9"],
        description="Add exponents when multiplying terms with equal bases.",
    ),
    MathFormula(
        id="laws_of_indices_div",
        name="Quotient Law of Indices",
        latex=r"\frac{a^m}{a^n} = a^{m-n}",
        variables={"a": "base", "m, n": "powers"},
        domain="algebra",
        topics=["algebra", "indices", "powers"],
        grades=["grade-7", "grade-8", "grade-9"],
        description="Subtract exponents when dividing terms with equal bases.",
    ),
    MathFormula(
        id="arithmetic_progression_nth_term",
        name="Arithmetic Progression (AP) n-th Term",
        latex=r"T_n = a + (n - 1)d",
        variables={"T_n": "nth term", "a": "first term", "n": "term position", "d": "common difference"},
        domain="algebra",
        topics=["algebra", "sequences", "ap"],
        grades=["grade-10", "grade-11", "grade-12"],
        description="Find any term of an arithmetic progression.",
    ),
    MathFormula(
        id="arithmetic_progression_sum",
        name="Sum of First n Terms of AP",
        latex=r"S_n = \frac{n}{2}[2a + (n - 1)d] = \frac{n}{2}(a + L)",
        variables={"S_n": "sum of n terms", "a": "first term", "L": "last term", "d": "common difference"},
        domain="algebra",
        topics=["algebra", "sequences", "ap", "series"],
        grades=["grade-10", "grade-11", "grade-12"],
        description="Total sum of terms in an arithmetic sequence.",
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 3. GEOMETRY (2D) (9 formulas)
    # ══════════════════════════════════════════════════════════════════════
    MathFormula(
        id="triangle_area",
        name="Area of a Triangle",
        latex=r"A = \frac{1}{2} b h",
        variables={"A": "area", "b": "base length", "h": "perpendicular height"},
        domain="geometry",
        topics=["geometry", "area", "triangles"],
        grades=["grade-5", "grade-6", "grade-7", "grade-8", "grade-9"],
        description="Half base times perpendicular height.",
    ),
    MathFormula(
        id="herons_formula",
        name="Heron's Formula for Triangle Area",
        latex=r"A = \sqrt{s(s-a)(s-b)(s-c)},\quad s = \frac{a+b+c}{2}",
        variables={"a, b, c": "side lengths", "s": "semi-perimeter", "A": "area"},
        domain="geometry",
        topics=["geometry", "triangles", "area", "heron"],
        grades=["grade-9", "grade-10", "grade-11"],
        description="Calculate triangle area given all three side lengths.",
    ),
    MathFormula(
        id="rectangle_area",
        name="Area of a Rectangle",
        latex=r"A = l \times w",
        variables={"A": "area", "l": "length", "w": "width"},
        domain="geometry",
        topics=["geometry", "area", "quadrilaterals"],
        grades=["grade-3", "grade-4", "grade-5", "grade-6"],
        description="Length times width.",
    ),
    MathFormula(
        id="rectangle_perimeter",
        name="Perimeter of a Rectangle",
        latex=r"P = 2(l + w)",
        variables={"P": "perimeter", "l": "length", "w": "width"},
        domain="geometry",
        topics=["geometry", "perimeter", "quadrilaterals"],
        grades=["grade-3", "grade-4", "grade-5", "grade-6"],
        description="Total boundary length of a rectangle.",
    ),
    MathFormula(
        id="parallelogram_area",
        name="Area of a Parallelogram",
        latex=r"A = b \times h",
        variables={"A": "area", "b": "base", "h": "perpendicular height"},
        domain="geometry",
        topics=["geometry", "area", "parallelogram"],
        grades=["grade-6", "grade-7", "grade-8"],
        description="Base times perpendicular height.",
    ),
    MathFormula(
        id="trapezoid_area",
        name="Area of a Trapezium",
        latex=r"A = \frac{1}{2}(a + b)h",
        variables={"a, b": "parallel sides", "h": "perpendicular height"},
        domain="geometry",
        topics=["geometry", "area", "trapezium"],
        grades=["grade-7", "grade-8", "grade-9"],
        description="Average of parallel sides multiplied by height.",
    ),
    MathFormula(
        id="circle_area",
        name="Area of a Circle",
        latex=r"A = \pi r^2",
        variables={"A": "area", "r": "radius", r"\pi": "pi constant"},
        domain="geometry",
        topics=["geometry", "circles", "area"],
        grades=["grade-7", "grade-8", "grade-9"],
        description="Area enclosed by a circle of radius r.",
    ),
    MathFormula(
        id="circle_circumference",
        name="Circumference of a Circle",
        latex=r"C = 2 \pi r = \pi d",
        variables={"C": "circumference", "r": "radius", "d": "diameter"},
        domain="geometry",
        topics=["geometry", "circles", "perimeter"],
        grades=["grade-7", "grade-8", "grade-9"],
        description="Perimeter of a circle.",
    ),
    MathFormula(
        id="sector_area",
        name="Area of a Circular Sector",
        latex=r"A = \frac{\theta}{360^\circ} \pi r^2",
        variables={"A": "sector area", r"\theta": "central angle in degrees", "r": "radius"},
        domain="geometry",
        topics=["geometry", "circles", "sectors", "area"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Fractional area of a circle subtended by angle theta.",
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 4. TRIGONOMETRY (6 formulas)
    # ══════════════════════════════════════════════════════════════════════
    MathFormula(
        id="pythagoras_theorem",
        name="Pythagoras Theorem",
        latex=r"a^2 + b^2 = c^2",
        variables={"a, b": "perpendicular legs", "c": "hypotenuse"},
        domain="trigonometry",
        topics=["geometry", "trigonometry", "pythagoras", "triangles"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Hypotenuse squared equals sum of squares of perpendicular legs.",
    ),
    MathFormula(
        id="trig_ratios_sohcahtoa",
        name="Basic Trigonometric Ratios (SOH CAH TOA)",
        latex=r"\sin\theta = \frac{\text{opp}}{\text{hyp}},\quad \cos\theta = \frac{\text{adj}}{\text{hyp}},\quad \tan\theta = \frac{\text{opp}}{\text{adj}}",
        variables={"opp": "opposite side", "adj": "adjacent side", "hyp": "hypotenuse"},
        domain="trigonometry",
        topics=["trigonometry", "ratios", "angles"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Fundamental trigonometric definitions for right-angled triangles.",
    ),
    MathFormula(
        id="sine_rule",
        name="Sine Rule",
        latex=r"\frac{a}{\sin A} = \frac{b}{\sin B} = \frac{c}{\sin C} = 2R",
        variables={"a, b, c": "side lengths", "A, B, C": "opposite angles", "R": "circumradius"},
        domain="trigonometry",
        topics=["trigonometry", "triangles", "sine_rule"],
        grades=["grade-10", "grade-11", "grade-12"],
        description="Relates sides and angles of any non-right triangle.",
    ),
    MathFormula(
        id="cosine_rule",
        name="Cosine Rule",
        latex=r"a^2 = b^2 + c^2 - 2bc \cos A",
        variables={"a, b, c": "sides", "A": "angle opposite to side a"},
        domain="trigonometry",
        topics=["trigonometry", "triangles", "cosine_rule"],
        grades=["grade-10", "grade-11", "grade-12"],
        description="Generalization of Pythagoras theorem for non-right triangles.",
    ),
    MathFormula(
        id="triangle_area_sine",
        name="Triangle Area Using Sine",
        latex=r"A = \frac{1}{2} a b \sin C",
        variables={"A": "area", "a, b": "adjacent sides", "C": "included angle"},
        domain="trigonometry",
        topics=["trigonometry", "area", "triangles"],
        grades=["grade-9", "grade-10", "grade-11"],
        description="Area of triangle given two sides and the included angle.",
    ),
    MathFormula(
        id="pythagorean_trig_identity",
        name="Pythagorean Trigonometric Identity",
        latex=r"\sin^2\theta + \cos^2\theta = 1",
        variables={r"\theta": "angle"},
        domain="trigonometry",
        topics=["trigonometry", "identities"],
        grades=["grade-10", "grade-11", "grade-12"],
        description="Fundamental identity relating sine and cosine.",
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 5. COORDINATE GEOMETRY (5 formulas)
    # ══════════════════════════════════════════════════════════════════════
    MathFormula(
        id="coordinate_distance",
        name="Distance Between Two Points",
        latex=r"d = \sqrt{(x_2 - x_1)^2 + (y_2 - y_1)^2}",
        variables={"d": "distance", "(x1, y1), (x2, y2)": "coordinates"},
        domain="geometry",
        topics=["coordinate_geometry", "distance"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Euclidean distance between two Cartesian coordinates.",
    ),
    MathFormula(
        id="coordinate_midpoint",
        name="Midpoint of a Line Segment",
        latex=r"M = \left(\frac{x_1 + x_2}{2}, \frac{y_1 + y_2}{2}\right)",
        variables={"M": "midpoint", "(x1, y1), (x2, y2)": "endpoints"},
        domain="geometry",
        topics=["coordinate_geometry", "midpoint"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Coordinates of the central point of a line segment.",
    ),
    MathFormula(
        id="line_gradient",
        name="Gradient (Slope) of a Straight Line",
        latex=r"m = \frac{y_2 - y_1}{x_2 - x_1} = \frac{\Delta y}{\Delta x}",
        variables={"m": "gradient", "(x1, y1), (x2, y2)": "points on the line"},
        domain="geometry",
        topics=["coordinate_geometry", "gradient", "slope"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Vertical rise divided by horizontal run.",
    ),
    MathFormula(
        id="line_equation_slope_intercept",
        name="Equation of a Straight Line (Slope-Intercept Form)",
        latex=r"y = mx + c",
        variables={"m": "gradient", "c": "y-intercept"},
        domain="geometry",
        topics=["coordinate_geometry", "linear_equations", "lines"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Canonical slope-intercept equation of a straight line.",
    ),
    MathFormula(
        id="perpendicular_lines_gradient",
        name="Condition for Perpendicular Lines",
        latex=r"m_1 \times m_2 = -1 \implies m_2 = -\frac{1}{m_1}",
        variables={"m1, m2": "gradients of perpendicular lines"},
        domain="geometry",
        topics=["coordinate_geometry", "perpendicular", "gradients"],
        grades=["grade-9", "grade-10", "grade-11"],
        description="Product of slopes of perpendicular lines equals -1.",
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 6. MEASUREMENT & 3D MENSURATION (6 formulas)
    # ══════════════════════════════════════════════════════════════════════
    MathFormula(
        id="cylinder_volume",
        name="Volume of a Cylinder",
        latex=r"V = \pi r^2 h",
        variables={"V": "volume", "r": "base radius", "h": "height"},
        domain="measurement",
        topics=["measurement", "volume", "solids", "cylinder"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Base circular area times height.",
    ),
    MathFormula(
        id="cylinder_surface_area",
        name="Total Surface Area of a Closed Cylinder",
        latex=r"A = 2\pi rh + 2\pi r^2 = 2\pi r(h + r)",
        variables={"A": "surface area", "r": "radius", "h": "height"},
        domain="measurement",
        topics=["measurement", "surface_area", "solids", "cylinder"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Curved surface area plus two circular end faces.",
    ),
    MathFormula(
        id="cuboid_volume",
        name="Volume of a Cuboid",
        latex=r"V = l \times w \times h",
        variables={"V": "volume", "l": "length", "w": "width", "h": "height"},
        domain="measurement",
        topics=["measurement", "volume", "solids", "cuboid"],
        grades=["grade-5", "grade-6", "grade-7", "grade-8"],
        description="Product of length, width, and height.",
    ),
    MathFormula(
        id="cone_volume",
        name="Volume of a Cone",
        latex=r"V = \frac{1}{3}\pi r^2 h",
        variables={"V": "volume", "r": "base radius", "h": "vertical height"},
        domain="measurement",
        topics=["measurement", "volume", "cone"],
        grades=["grade-9", "grade-10", "grade-11"],
        description="One-third volume of corresponding cylinder.",
    ),
    MathFormula(
        id="sphere_volume",
        name="Volume of a Sphere",
        latex=r"V = \frac{4}{3}\pi r^3",
        variables={"V": "volume", "r": "radius"},
        domain="measurement",
        topics=["measurement", "volume", "sphere"],
        grades=["grade-9", "grade-10", "grade-11"],
        description="Volume enclosed by a sphere of radius r.",
    ),
    MathFormula(
        id="sphere_surface_area",
        name="Surface Area of a Sphere",
        latex=r"A = 4\pi r^2",
        variables={"A": "surface area", "r": "radius"},
        domain="measurement",
        topics=["measurement", "surface_area", "sphere"],
        grades=["grade-9", "grade-10", "grade-11"],
        description="Total outer surface area of a sphere.",
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 7. RATES & PHYSICAL QUANTITIES (4 formulas)
    # ══════════════════════════════════════════════════════════════════════
    MathFormula(
        id="speed_distance_time",
        name="Speed, Distance and Time",
        latex=r"S = \frac{D}{T}",
        variables={"S": "speed", "D": "distance", "T": "time"},
        domain="measurement",
        topics=["measurement", "speed", "rates"],
        grades=["grade-6", "grade-7", "grade-8"],
        description="Rate of change of distance with respect to time.",
    ),
    MathFormula(
        id="average_speed",
        name="Average Speed",
        latex=r"\bar{S} = \frac{\text{Total Distance}}{\text{Total Time}}",
        variables={r"\bar{S}": "average speed"},
        domain="measurement",
        topics=["measurement", "speed", "rates"],
        grades=["grade-7", "grade-8", "grade-9"],
        description="Total journey distance divided by total elapsed duration.",
    ),
    MathFormula(
        id="density_mass_volume",
        name="Density, Mass and Volume",
        latex=r"\rho = \frac{M}{V}",
        variables={r"\rho": "density", "M": "mass", "V": "volume"},
        domain="measurement",
        topics=["measurement", "density", "rates"],
        grades=["grade-7", "grade-8", "grade-9"],
        description="Mass per unit volume of a substance.",
    ),
    MathFormula(
        id="pressure_force_area",
        name="Pressure, Force and Area",
        latex=r"P = \frac{F}{A}",
        variables={"P": "pressure", "F": "perpendicular force", "A": "contact area"},
        domain="measurement",
        topics=["measurement", "pressure", "physics"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Force applied perpendicularly per unit contact surface area.",
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 8. FINANCIAL MATHEMATICS (5 formulas)
    # ══════════════════════════════════════════════════════════════════════
    MathFormula(
        id="profit_formula",
        name="Profit and Percentage Profit",
        latex=r"\text{Profit} = \text{SP} - \text{CP},\quad \%\text{Profit} = \frac{\text{Profit}}{\text{CP}} \times 100\%",
        variables={"SP": "selling price", "CP": "cost price"},
        domain="financial",
        topics=["financial", "business", "profit", "commercial"],
        grades=["grade-6", "grade-7", "grade-8"],
        description="Difference between selling and cost price expressed in currency and percentage.",
    ),
    MathFormula(
        id="simple_interest",
        name="Simple Interest",
        latex=r"I = \frac{P \times R \times T}{100},\quad A = P + I",
        variables={"I": "interest", "P": "principal", "R": "rate (% p.a.)", "T": "time (years)", "A": "total amount"},
        domain="financial",
        topics=["financial", "business", "interest"],
        grades=["grade-7", "grade-8", "grade-9"],
        description="Linear interest earned on initial principal.",
    ),
    MathFormula(
        id="compound_interest",
        name="Compound Interest",
        latex=r"A = P\left(1 + \frac{r}{n}\right)^{nt},\quad CI = A - P",
        variables={"A": "accumulated amount", "P": "principal", "r": "annual rate (decimal)", "n": "compounding periods/year", "t": "years"},
        domain="financial",
        topics=["financial", "compound_interest", "business"],
        grades=["grade-9", "grade-10", "grade-11", "grade-12"],
        description="Exponential interest calculation where interest earns further interest.",
    ),
    MathFormula(
        id="depreciation_formula",
        name="Depreciation (Reducing Balance)",
        latex=r"V = P(1 - r)^t",
        variables={"V": "depreciated value", "P": "original cost", "r": "depreciation rate", "t": "time in years"},
        domain="financial",
        topics=["financial", "depreciation", "business"],
        grades=["grade-9", "grade-10", "grade-11"],
        description="Calculates asset value reduction over elapsed years.",
    ),
    MathFormula(
        id="hire_purchase",
        name="Hire Purchase Total Cost",
        latex=r"\text{Total HP} = \text{Deposit} + (\text{Number of Installments} \times \text{Monthly Amount})",
        variables={"Deposit": "upfront payment", "Installments": "monthly recurring payments"},
        domain="financial",
        topics=["financial", "hire_purchase", "business"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Total cost of acquiring an item on credit/hire purchase terms.",
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 9. STATISTICS (5 formulas)
    # ══════════════════════════════════════════════════════════════════════
    MathFormula(
        id="mean_formula",
        name="Arithmetic Mean",
        latex=r"\bar{x} = \frac{\sum x}{n}",
        variables={r"\bar{x}": "mean", r"\sum x": "sum of values", "n": "number of values"},
        domain="statistics",
        topics=["statistics", "averages", "mean"],
        grades=["grade-7", "grade-8", "grade-9"],
        description="Sum of all observations divided by observation count.",
    ),
    MathFormula(
        id="frequency_table_mean",
        name="Mean from Frequency Distribution",
        latex=r"\bar{x} = \frac{\sum f x}{\sum f}",
        variables={r"\bar{x}": "mean", "f": "frequency", "x": "class midpoint/value"},
        domain="statistics",
        topics=["statistics", "frequency", "mean"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Weighted mean where each value is weighted by its class frequency.",
    ),
    MathFormula(
        id="variance_formula",
        name="Population and Sample Variance",
        latex=r"\sigma^2 = \frac{\sum (x - \bar{x})^2}{n}",
        variables={r"\sigma^2": "variance", r"\bar{x}": "mean", "n": "count"},
        domain="statistics",
        topics=["statistics", "dispersion", "variance"],
        grades=["grade-10", "grade-11", "grade-12"],
        description="Measure of how far dataset values spread out from the mean.",
    ),
    MathFormula(
        id="standard_deviation",
        name="Standard Deviation",
        latex=r"\sigma = \sqrt{\frac{\sum (x - \bar{x})^2}{n}}",
        variables={r"\sigma": "standard deviation", r"\bar{x}": "mean"},
        domain="statistics",
        topics=["statistics", "dispersion", "std_dev"],
        grades=["grade-10", "grade-11", "grade-12"],
        description="Square root of variance, in the same physical units as original data.",
    ),
    MathFormula(
        id="interquartile_range",
        name="Interquartile Range (IQR)",
        latex=r"\text{IQR} = Q_3 - Q_1",
        variables={"Q1": "lower quartile (25th percentile)", "Q3": "upper quartile (75th percentile)"},
        domain="statistics",
        topics=["statistics", "quartiles", "iqr"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Spread of the middle 50% of the data distribution.",
    ),

    # ══════════════════════════════════════════════════════════════════════
    # 10. PROBABILITY (5 formulas)
    # ══════════════════════════════════════════════════════════════════════
    MathFormula(
        id="probability_event",
        name="Probability of an Event",
        latex=r"P(A) = \frac{n(A)}{n(S)}",
        variables={"P(A)": "probability of event A", "n(A)": "favourable outcomes", "n(S)": "total sample space outcomes"},
        domain="probability",
        topics=["probability", "chance"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Ratio of favourable outcomes to total possible equally-likely outcomes.",
    ),
    MathFormula(
        id="complementary_probability",
        name="Complementary Probability Rule",
        latex=r"P(A') = 1 - P(A)",
        variables={"P(A')": "probability of event A not occurring"},
        domain="probability",
        topics=["probability", "complement"],
        grades=["grade-8", "grade-9", "grade-10"],
        description="Probability that an event does not happen.",
    ),
    MathFormula(
        id="mutually_exclusive_addition",
        name="Addition Rule for Mutually Exclusive Events",
        latex=r"P(A \cup B) = P(A) + P(B)",
        variables={"P(A union B)": "probability of A or B occurring"},
        domain="probability",
        topics=["probability", "addition_rule", "mutually_exclusive"],
        grades=["grade-9", "grade-10", "grade-11"],
        description="Sum of probabilities when events cannot occur simultaneously.",
    ),
    MathFormula(
        id="independent_events_multiplication",
        name="Multiplication Rule for Independent Events",
        latex=r"P(A \cap B) = P(A) \times P(B)",
        variables={"P(A intersect B)": "probability of both A and B occurring"},
        domain="probability",
        topics=["probability", "multiplication_rule", "independent"],
        grades=["grade-9", "grade-10", "grade-11"],
        description="Product of probabilities when the outcome of one event does not affect the other.",
    ),
    MathFormula(
        id="conditional_probability",
        name="Conditional Probability",
        latex=r"P(A|B) = \frac{P(A \cap B)}{P(B)},\quad P(B) > 0",
        variables={"P(A|B)": "probability of A given B has occurred"},
        domain="probability",
        topics=["probability", "conditional"],
        grades=["grade-11", "grade-12"],
        description="Probability of event A occurring given prior knowledge that event B has occurred.",
    ),
]


def search_formulas(
    query: str = "",
    grade: str = "",
    strand: str = "",
    topic: str = "",
    domain: str = "",
) -> List[Dict[str, Any]]:
    """Search and filter the 50+ canonical formulas by domain, grade, topic, or keyword."""
    norm_q = query.lower().strip()
    # Substring matching here put the quadratic formula in front of Grade 1
    # learners: "grade-1" is a substring of "grade-10", "grade-11", "grade-12".
    # Normalise both sides and compare exactly, the way `grade_sql.clause`
    # does for the database.
    norm_g = normalize_grade(grade)
    norm_s = strand.lower().strip()
    norm_t = topic.lower().strip()
    norm_d = domain.lower().strip()

    results: List[Dict[str, Any]] = []

    for f in FORMULA_REGISTRY:
        if norm_d and f.domain.lower() != norm_d:
            continue
        if norm_g and norm_g not in {normalize_grade(g) for g in f.grades}:
            continue
        if norm_t and not any(norm_t in t.lower() for t in f.topics):
            continue
        if norm_s and not any(norm_s in t.lower() for t in f.topics) and norm_s not in f.domain.lower():
            continue
        if norm_q:
            combined = f"{f.name} {f.description} {' '.join(f.topics)} {f.latex}".lower()
            if norm_q not in combined:
                continue

        results.append(f.to_dict())

    return results


def get_formulas_for_context(
    grade: str = "",
    topic: str = "",
) -> List[Dict[str, Any]]:
    """The formulas for this grade and topic — and nothing else.

    This used to fall back to the ENTIRE registry when the filter matched
    nothing, which is exactly what every real request did: the console sends
    "Grade 6" and "grade-pp1", neither of which matched the "grade-6" spelling
    in the tags. A PP1 lesson was offered compound interest and the quadratic
    formula. An empty filter result means there are no formulas for that grade,
    and that is the correct answer to give.
    """
    res = search_formulas(grade=grade, topic=topic)
    if not res and topic:
        # The topic may simply be phrased differently; the grade is not
        # negotiable, so widen on topic alone rather than on everything.
        res = search_formulas(grade=grade)
    return res
