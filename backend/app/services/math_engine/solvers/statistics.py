"""Deterministic Statistics Solver."""
from __future__ import annotations

import statistics
from typing import Any, Dict, List

from ..objects import SolutionStep, SolutionTrace


def solve_dataset_summary(values: List[float]) -> SolutionTrace:
    """Calculate mean, median, mode, range, quartiles (Q1, Q2, Q3) and IQR."""
    if not values:
        raise ValueError("Dataset cannot be empty")

    n = len(values)
    sorted_vals = sorted(values)
    total = sum(values)
    mean_val = round(total / n, 2)
    median_val = statistics.median(sorted_vals)

    try:
        mode_val = statistics.mode(values)
    except statistics.StatisticsError:
        mode_val = sorted_vals[0]

    range_val = sorted_vals[-1] - sorted_vals[0]

    # Calculate quartiles
    # Lower half and upper half for Q1 and Q3
    mid = n // 2
    if n % 2 == 0:
        lower_half = sorted_vals[:mid]
        upper_half = sorted_vals[mid:]
    else:
        lower_half = sorted_vals[:mid]
        upper_half = sorted_vals[mid + 1:]

    q1 = statistics.median(lower_half) if lower_half else sorted_vals[0]
    q3 = statistics.median(upper_half) if upper_half else sorted_vals[-1]
    iqr = round(q3 - q1, 2)

    steps = [
        SolutionStep(
            step_number=1,
            operation="Order dataset ascending",
            expression_before=str(values),
            expression_after=str(sorted_vals),
            latex=f"\\text{{Ordered: }}[{', '.join(str(v) for v in sorted_vals)}]",
            explanation=f"Arrange all {n} values in ascending order.",
        ),
        SolutionStep(
            step_number=2,
            operation="Calculate Mean (average)",
            expression_before="\\bar{x} = \\frac{\\sum x}{n}",
            expression_after=f"\\bar{{x}} = \\frac{{{total}}}{{{n}}} = {mean_val}",
            latex=f"\\bar{{x}} = \\frac{{{total}}}{{{n}}} = {mean_val}",
            explanation=f"Sum of values ({total}) divided by count ({n}).",
        ),
        SolutionStep(
            step_number=3,
            operation="Find Median (Q2)",
            expression_before="\\text{Median}",
            expression_after=f"Q_2 = {median_val}",
            latex=f"\\text{{Median}} (Q_2) = {median_val}",
            explanation=f"The central value of the ordered set is {median_val}.",
        ),
        SolutionStep(
            step_number=4,
            operation="Calculate Quartiles and Interquartile Range (IQR)",
            expression_before="\\text{IQR} = Q_3 - Q_1",
            expression_after=f"Q_1 = {q1},\\ Q_3 = {q3},\\ \\text{{IQR}} = {q3} - {q1} = {iqr}",
            latex=f"Q_1 = {q1},\\quad Q_3 = {q3},\\quad \\text{{IQR}} = {q3} - {q1} = {iqr}",
            explanation=f"Lower quartile Q1 is {q1}, upper quartile Q3 is {q3}, giving IQR = {iqr}.",
        ),
        SolutionStep(
            step_number=5,
            operation="Identify Mode and Range",
            expression_before="\\text{Mode and Range}",
            expression_after=f"\\text{{Mode}} = {mode_val},\\ \\text{{Range}} = {range_val}",
            latex=f"\\text{{Mode}} = {mode_val},\\quad \\text{{Range}} = {sorted_vals[-1]} - {sorted_vals[0]} = {range_val}",
            explanation=f"Mode is most frequent value ({mode_val}), Range is max - min ({range_val}).",
        ),
    ]

    return SolutionTrace(
        problem=f"Calculate statistical summary for dataset: {values}",
        final_answer=(
            f"\\bar{{x}} = {mean_val},\\ \\text{{Median}} = {median_val},\\ "
            f"\\text{{Mode}} = {mode_val},\\ Q_1 = {q1},\\ Q_3 = {q3},\\ \\text{{IQR}} = {iqr}"
        ),
        steps=steps,
        verified=True,
        check_latex=f"{mean_val} \\times {n} \\approx {total} \\checkmark",
    )


def solve_frequency_table_mean(table: List[Dict[str, float]]) -> SolutionTrace:
    """Calculate mean from frequency distribution table: [{'value': x, 'freq': f}, ...]."""
    total_f = sum(row["freq"] for row in table)
    sum_fx = sum(row["value"] * row["freq"] for row in table)
    mean_val = round(sum_fx / total_f, 2)

    # Modal value
    max_f = max(row["freq"] for row in table)
    modal_vals = [row["value"] for row in table if row["freq"] == max_f]
    modal_str = ", ".join(str(v) for v in modal_vals)

    fx_terms = " + ".join(f"({r['value']} \\times {r['freq']})" for r in table)

    steps = [
        SolutionStep(
            step_number=1,
            operation="Calculate total frequency N = sum(f)",
            expression_before="\\sum f",
            expression_after=f"\\sum f = {total_f}",
            latex=f"N = \\sum f = {' + '.join(str(r['freq']) for r in table)} = {total_f}",
            explanation=f"Sum of all frequencies is {total_f}.",
        ),
        SolutionStep(
            step_number=2,
            operation="Calculate sum of fx: sum(f * x)",
            expression_before="\\sum fx",
            expression_after=f"\\sum fx = {sum_fx}",
            latex=f"\\sum fx = {fx_terms} = {sum_fx}",
            explanation="Multiply each value by its frequency and take the sum.",
        ),
        SolutionStep(
            step_number=3,
            operation="Calculate Mean: bar{x} = sum(fx) / sum(f)",
            expression_before="\\bar{x} = \\frac{\\sum fx}{\\sum f}",
            expression_after=f"\\bar{{x}} = \\frac{{{sum_fx}}}{{{total_f}}} = {mean_val}",
            latex=f"\\bar{{x}} = \\frac{{{sum_fx}}}{{{total_f}}} = {mean_val}",
            explanation=f"Divide total sum ({sum_fx}) by total frequency ({total_f}).",
        ),
    ]

    return SolutionTrace(
        problem=f"Find mean from frequency table with {len(table)} classes (total freq = {total_f})",
        final_answer=f"\\bar{{x}} = {mean_val},\\ \\text{{Modal value}} = {modal_str}",
        steps=steps,
        verified=True,
    )
