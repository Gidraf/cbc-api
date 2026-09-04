from __future__ import annotations

import random
from typing import Any

from .context import CurriculumContext
from .simulation_builder import build_simulation_track
from .solver import (
    solve_fraction_addition,
    solve_linear_equation,
    solve_statistics_summary,
    solve_triangle_area,
)
from .verifier import verify_solution


def generate_math_question(
    context: CurriculumContext,
    template_id: str = "auto",
    difficulty: str = "standard",
    enable_simulation: bool = True,
) -> dict[str, Any]:
    """Generate a verified, curriculum-linked mathematical question with solution & simulation."""
    tid = template_id.lower().strip()

    # Auto-detect from context if template is 'auto'
    if tid == "auto":
        ss_lower = context.sub_strand_name.lower()
        if "fraction" in ss_lower:
            tid = "fraction_addition"
        elif "linear" in ss_lower or "equation" in ss_lower or "algebra" in ss_lower:
            tid = "linear_equation"
        elif "area" in ss_lower or "triangle" in ss_lower or "geometry" in ss_lower:
            tid = "triangle_area"
        elif "statistic" in ss_lower or "mean" in ss_lower or "data" in ss_lower:
            tid = "statistics_central"
        else:
            tid = "linear_equation"

    curriculum_link = context.to_dict()

    if tid == "fraction_addition":
        if difficulty == "basic":
            d1, d2 = random.choice([(2, 4), (3, 6), (2, 3), (4, 5)])
            n1 = random.randint(1, d1 - 1)
            n2 = random.randint(1, d2 - 1)
        else:
            d1 = random.choice([3, 4, 5, 6, 7])
            d2 = random.choice([2, 5, 8, 9])
            while d1 == d2:
                d2 = random.randint(2, 9)
            n1 = random.randint(1, d1 - 1)
            n2 = random.randint(1, d2 - 1)

        trace = solve_fraction_addition(n1, d1, n2, d2)
        question_text = f"Work out: $\\frac{{{n1}}}{{{d1}}} + \\frac{{{n2}}}{{{d2}}}$"
        marks = 3
        marking_scheme = (
            "1 mark for finding correct common denominator (LCM); "
            "1 mark for converting to equivalent fractions; "
            "1 mark for correct simplified sum."
        )

    elif tid == "triangle_area":
        if difficulty == "basic":
            b = float(random.choice([4, 6, 8, 10]))
            h = float(random.choice([3, 5, 7, 9]))
        else:
            b = float(random.choice([5.5, 7.2, 8.4, 12.0, 14.5]))
            h = float(random.choice([4.0, 6.5, 9.0, 11.2]))

        trace = solve_triangle_area(b, h)
        question_text = f"Find the area of a triangle with a base of ${b}\\text{{ cm}}$ and a perpendicular height of ${h}\\text{{ cm}}$."
        marks = 3
        marking_scheme = (
            "1 mark for stating the formula $A = \\frac{1}{2}bh$; "
            "1 mark for correct substitution; "
            "1 mark for correct answer with units $\\text{cm}^2$."
        )

    elif tid == "statistics_central":
        size = 5 if difficulty == "basic" else 7
        vals = [float(random.randint(5, 25)) for _ in range(size)]
        trace = solve_statistics_summary(vals)
        vals_str = ", ".join(str(int(v)) for v in vals)
        question_text = f"The following data represents test marks for a group of learners: $[{vals_str}]$. Calculate the mean, median, and mode."
        marks = 4
        marking_scheme = (
            "1 mark for ordering the dataset; "
            "1 mark for calculating correct mean; "
            "1 mark for identifying correct median; "
            "1 mark for stating the mode."
        )

    else:  # default linear_equation
        if difficulty == "basic":
            a = random.choice([2, 3, 4, 5])
            x_sol = random.choice([2, 3, 4, 5, 6])
            b = random.choice([1, 2, 3, 7])
            c = a * x_sol + b
            eq_str = f"{a}*x + {b} = {c}"
            question_text = f"Solve the equation: ${a}x + {b} = {c}$"
        else:
            k = random.choice([2, 3, 4])
            m = random.choice([2, 3])
            c_val = random.choice([1, 2])
            x_sol = random.choice([2, 3, 4, 5])
            rhs = k * (m * x_sol - c_val)
            eq_str = f"{k}*({m}*x - {c_val}) = {rhs}"
            question_text = f"Solve for $x$: ${k}({m}x - {c_val}) = {rhs}$"

        trace = solve_linear_equation(eq_str)
        marks = 3
        marking_scheme = (
            "1 mark for expanding or balancing brackets; "
            "1 mark for collecting like terms; "
            "1 mark for correct solution for the variable."
        )

    # Verification check. Default False: an unreadable answer is unverified,
    # not correct.
    ver_res = verify_solution(trace.problem, trace.final_answer)
    trace.verified = bool(ver_res.get("verified", False))

    sim_track = None
    if enable_simulation:
        sim_track = build_simulation_track(
            problem=question_text,
            solution_trace=trace,
            curriculum_link=curriculum_link,
            title=f"Question: {question_text[:50]}",
            source_type="question_solution",
        )

    return {
        "question_id": f"math_q_{random.randint(10000, 99999)}",
        "question_type": "constructed_response",
        "question_text": question_text,
        "marks": marks,
        "curriculum_link": curriculum_link,
        "solution_trace": trace.to_dict(),
        "final_answer": trace.final_answer,
        "marking_scheme": marking_scheme,
        "simulation": sim_track.to_dict() if sim_track else None,
        "verified": trace.verified,
        "verification": ver_res,
        "unsolved": trace.unsolved,
    }
