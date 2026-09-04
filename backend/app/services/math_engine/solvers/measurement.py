"""Deterministic Measurement and Rates Solver."""
from __future__ import annotations

from typing import Optional

from ..objects import SolutionStep, SolutionTrace
from ..units import Quantity, UnitRegistry


def solve_unit_conversion(value: float, from_unit: str, to_unit: str) -> SolutionTrace:
    """Convert a value from one unit to another using the UnitRegistry."""
    q_from = Quantity(value, from_unit)
    q_to = q_from.to_unit(to_unit)

    from_u = UnitRegistry.get(from_unit)
    to_u = UnitRegistry.get(to_unit)
    factor = from_u.conversion_factor / to_u.conversion_factor

    factor_str = str(int(factor)) if factor.is_integer() else (f"{factor:.4g}" if factor < 1 else f"{factor:.2f}")

    steps = [
        SolutionStep(
            step_number=1,
            operation=f"Determine conversion factor between {from_unit} and {to_unit}",
            expression_before=f"1\\text{{ {from_unit}}} = ?\\text{{ {to_unit}}}",
            expression_after=f"1\\text{{ {from_unit}}} = {factor_str}\\text{{ {to_unit}}}",
            latex=f"1\\text{{ {from_unit}}} = {factor_str}\\text{{ {to_unit}}}",
            explanation=f"Both units measure {from_u.dimension.value.capitalize()}. The conversion factor is {factor_str}.",
        ),
        SolutionStep(
            step_number=2,
            operation="Multiply given quantity by conversion factor",
            expression_before=f"{value}\\text{{ {from_unit}}}",
            expression_after=q_to.to_latex(),
            latex=f"{value} \\times {factor_str}\\text{{ {to_unit}}} = {q_to.to_latex()}",
            explanation=f"Convert by scaling with the factor: {value} * {factor_str}.",
        ),
    ]

    return SolutionTrace(
        problem=f"Convert {value} {from_unit} to {to_unit}",
        final_answer=q_to.to_latex(),
        steps=steps,
        verified=True,
        check_latex=f"{q_to.to_latex()} \\equiv {q_from.to_latex()} \\checkmark",
    )


def solve_speed_distance_time(
    distance: Optional[float] = None,
    time: Optional[float] = None,
    speed: Optional[float] = None,
    dist_unit: str = "km",
    time_unit: str = "h",
    speed_unit: str = "km/h",
) -> SolutionTrace:
    """Solve S = D / T given any 2 parameters."""
    if speed is None and distance is not None and time is not None:
        calc_speed = distance / time
        s_str = str(int(calc_speed)) if calc_speed.is_integer() else f"{calc_speed:.2f}"
        steps = [
            SolutionStep(
                step_number=1,
                operation="State formula: Speed = Distance / Time",
                expression_before="\\text{Speed} = \\frac{\\text{Distance}}{\\text{Time}}",
                expression_after=f"S = \\frac{{{distance}\\text{{ {dist_unit}}}}}{{{time}\\text{{ {time_unit}}}}}",
                latex="S = \\frac{D}{T}",
                explanation="Speed is rate of distance covered per unit time.",
            ),
            SolutionStep(
                step_number=2,
                operation="Compute Speed",
                expression_before=f"S = \\frac{{{distance}}}{{{time}}}",
                expression_after=f"S = {s_str}\\text{{ {speed_unit}}}",
                latex=f"S = \\frac{{{distance}}}{{{time}}} = {s_str}\\text{{ {speed_unit}}}",
                explanation=f"Divide distance ({distance}) by time ({time}).",
            ),
        ]
        return SolutionTrace(
            problem=f"Calculate speed for distance {distance} {dist_unit} in time {time} {time_unit}",
            final_answer=f"S = {s_str}\\text{{ {speed_unit}}}",
            steps=steps,
            verified=True,
            check_latex=f"{s_str} \\times {time} = {distance} \\checkmark",
        )

    elif distance is None and speed is not None and time is not None:
        calc_dist = speed * time
        d_str = str(int(calc_dist)) if calc_dist.is_integer() else f"{calc_dist:.2f}"
        steps = [
            SolutionStep(
                step_number=1,
                operation="State formula: Distance = Speed * Time",
                expression_before="D = S \\times T",
                expression_after=f"D = {speed}\\text{{ {speed_unit}}} \\times {time}\\text{{ {time_unit}}}",
                latex="D = S \\times T",
                explanation="Distance is the product of speed and elapsed time.",
            ),
            SolutionStep(
                step_number=2,
                operation="Compute Distance",
                expression_before=f"D = {speed} \\times {time}",
                expression_after=f"D = {d_str}\\text{{ {dist_unit}}}",
                latex=f"D = {speed} \\times {time} = {d_str}\\text{{ {dist_unit}}}",
                explanation=f"Multiply speed ({speed}) by time ({time}).",
            ),
        ]
        return SolutionTrace(
            problem=f"Calculate distance covered at speed {speed} {speed_unit} for {time} {time_unit}",
            final_answer=f"D = {d_str}\\text{{ {dist_unit}}}",
            steps=steps,
            verified=True,
            check_latex=f"\\frac{{{d_str}}}{{{time}}} = {speed} \\checkmark",
        )

    elif time is None and distance is not None and speed is not None:
        calc_time = distance / speed
        t_str = str(int(calc_time)) if calc_time.is_integer() else f"{calc_time:.2f}"
        steps = [
            SolutionStep(
                step_number=1,
                operation="State formula: Time = Distance / Speed",
                expression_before="T = \\frac{D}{S}",
                expression_after=f"T = \\frac{{{distance}\\text{{ {dist_unit}}}}}{{{speed}\\text{{ {speed_unit}}}}}",
                latex="T = \\frac{D}{S}",
                explanation="Time is distance divided by speed.",
            ),
            SolutionStep(
                step_number=2,
                operation="Compute Time",
                expression_before=f"T = \\frac{{{distance}}}{{{speed}}}",
                expression_after=f"T = {t_str}\\text{{ {time_unit}}}",
                latex=f"T = \\frac{{{distance}}}{{{speed}}} = {t_str}\\text{{ {time_unit}}}",
                explanation=f"Divide distance ({distance}) by speed ({speed}).",
            ),
        ]
        return SolutionTrace(
            problem=f"Calculate time to cover distance {distance} {dist_unit} at speed {speed} {speed_unit}",
            final_answer=f"T = {t_str}\\text{{ {time_unit}}}",
            steps=steps,
            verified=True,
            check_latex=f"{speed} \\times {t_str} = {distance} \\checkmark",
        )

    else:
        raise ValueError("Must provide exactly two of (distance, time, speed)")


def solve_density_mass_volume(
    mass: Optional[float] = None,
    volume: Optional[float] = None,
    density: Optional[float] = None,
    mass_unit: str = "g",
    vol_unit: str = "cm^3",
    density_unit: str = "g/cm^3",
) -> SolutionTrace:
    """Solve Density = Mass / Volume given any 2 parameters."""
    if density is None and mass is not None and volume is not None:
        calc_dens = mass / volume
        den_str = str(int(calc_dens)) if calc_dens.is_integer() else f"{calc_dens:.2f}"
        steps = [
            SolutionStep(
                step_number=1,
                operation="State formula: Density = Mass / Volume",
                expression_before="\\rho = \\frac{M}{V}",
                expression_after=f"\\rho = \\frac{{{mass}\\text{{ {mass_unit}}}}}{{{volume}\\text{{ {vol_unit}}}}}",
                latex="\\rho = \\frac{M}{V}",
                explanation="Density is mass per unit volume.",
            ),
            SolutionStep(
                step_number=2,
                operation="Compute Density",
                expression_before=f"\\rho = \\frac{{{mass}}}{{{volume}}}",
                expression_after=f"\\rho = {den_str}\\text{{ {density_unit}}}",
                latex=f"\\rho = \\frac{{{mass}}}{{{volume}}} = {den_str}\\text{{ {density_unit}}}",
                explanation=f"Divide mass ({mass}) by volume ({volume}).",
            ),
        ]
        return SolutionTrace(
            problem=f"Calculate density of an object with mass {mass} {mass_unit} and volume {volume} {vol_unit}",
            final_answer=f"\\rho = {den_str}\\text{{ {density_unit}}}",
            steps=steps,
            verified=True,
        )

    elif mass is None and density is not None and volume is not None:
        calc_m = density * volume
        m_str = str(int(calc_m)) if calc_m.is_integer() else f"{calc_m:.2f}"
        steps = [
            SolutionStep(
                step_number=1,
                operation="State formula: Mass = Density * Volume",
                expression_before="M = \\rho \\times V",
                expression_after=f"M = {density} \\times {volume}",
                latex="M = \\rho \\times V",
                explanation="Mass is the product of density and volume.",
            ),
            SolutionStep(
                step_number=2,
                operation="Compute Mass",
                expression_before=f"M = {density} \\times {volume}",
                expression_after=f"M = {m_str}\\text{{ {mass_unit}}}",
                latex=f"M = {density} \\times {volume} = {m_str}\\text{{ {mass_unit}}}",
                explanation=f"Multiply density ({density}) by volume ({volume}).",
            ),
        ]
        return SolutionTrace(
            problem=f"Calculate mass of an object with density {density} {density_unit} and volume {volume} {vol_unit}",
            final_answer=f"M = {m_str}\\text{{ {mass_unit}}}",
            steps=steps,
            verified=True,
        )

    else:
        raise ValueError("Must provide (mass, volume) or (density, volume)")
