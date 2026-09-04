"""Core Math Engine Solver Interface.

Delegates to modular solvers in app.services.math_engine.solvers while maintaining
backward compatibility for existing endpoints and test suites.
"""
from __future__ import annotations

from typing import List, Optional

from .objects import SolutionStep, SolutionTrace
from .solvers import (
    prime_factorization,
    solve_circle_properties,
    solve_complementary_probability,
    solve_compound_interest,
    solve_coordinate_distance_midpoint,
    solve_cuboid_volume_and_surface_area,
    solve_cylinder_volume_and_surface_area,
    solve_dataset_summary,
    solve_density_mass_volume,
    solve_elevation_depression,
    solve_fraction_operation,
    solve_frequency_table_mean,
    solve_gcd_lcm,
    solve_independent_events_probability,
    solve_linear_equation,
    solve_percentage_change,
    solve_percentage_of_quantity,
    solve_problem,
    solve_profit_loss,
    solve_pythagoras,
    solve_quadratic_equation,
    solve_rectangle_perimeter_and_area,
    solve_right_triangle_angle,
    solve_right_triangle_side,
    solve_rounding,
    solve_share_in_ratio,
    solve_simple_interest,
    solve_simple_probability,
    solve_simplify_ratio,
    solve_simultaneous_linear,
    solve_speed_distance_time,
    solve_trapezium_area,
    solve_triangle_area,
    solve_unit_conversion,
)

__all__ = [
    "SolutionStep",
    "SolutionTrace",
    "solve_fraction_addition",
    "solve_fraction_operation",
    "solve_linear_equation",
    "solve_simultaneous_linear",
    "solve_quadratic_equation",
    "solve_triangle_area",
    "solve_rectangle_perimeter_and_area",
    "solve_circle_properties",
    "solve_trapezium_area",
    "solve_pythagoras",
    "solve_cylinder_volume_and_surface_area",
    "solve_cuboid_volume_and_surface_area",
    "solve_coordinate_distance_midpoint",
    "solve_statistics_summary",
    "solve_dataset_summary",
    "solve_frequency_table_mean",
    "solve_math_problem",
    "solve_simple_probability",
    "solve_complementary_probability",
    "solve_independent_events_probability",
    "solve_profit_loss",
    "solve_simple_interest",
    "solve_compound_interest",
    "solve_percentage_of_quantity",
    "solve_percentage_change",
    "solve_simplify_ratio",
    "solve_share_in_ratio",
    "solve_unit_conversion",
    "solve_speed_distance_time",
    "solve_density_mass_volume",
    "solve_gcd_lcm",
    "prime_factorization",
    "solve_rounding",
    "solve_right_triangle_side",
    "solve_right_triangle_angle",
    "solve_elevation_depression",
]


def solve_fraction_addition(num1: int, den1: int, num2: int, den2: int) -> SolutionTrace:
    """Backward-compatible fraction addition."""
    return solve_fraction_operation(num1, den1, num2, den2, op="+")


def solve_statistics_summary(values: List[float]) -> SolutionTrace:
    """Backward-compatible statistics summary."""
    return solve_dataset_summary(values)


def solve_math_problem(problem: str, problem_type: str = "auto") -> SolutionTrace:
    """Backward-compatible math problem solver dispatcher."""
    return solve_problem(problem, domain=problem_type)
