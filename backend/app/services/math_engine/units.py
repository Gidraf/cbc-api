"""Physical Quantities and Units Subsystem.

Provides dimensional analysis, unit conversion, and quantity arithmetic.
Designed as a permanent foundation for both Mathematics and future Science/Physics modules.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Dict, Optional, Tuple, Union


class Dimension(Enum):
    DIMENSIONLESS = "dimensionless"
    LENGTH = "length"
    MASS = "mass"
    TIME = "time"
    TEMPERATURE = "temperature"
    CURRENT = "current"
    AMOUNT = "amount"
    LUMINOUS_INTENSITY = "luminous_intensity"
    # Derived dimensions
    AREA = "area"
    VOLUME = "volume"
    SPEED = "speed"
    ACCELERATION = "acceleration"
    DENSITY = "density"
    FORCE = "force"
    PRESSURE = "pressure"
    ENERGY = "energy"
    POWER = "power"
    FREQUENCY = "frequency"
    MONEY = "money"


class DimensionalError(ValueError):
    """Raised when an operation is attempted on incompatible dimensions."""
    pass


@dataclass(frozen=True, slots=True)
class Unit:
    symbol: str
    name: str
    dimension: Dimension
    scale_to_base: float  # Multiply value by scale_to_base to convert to base unit
    offset_to_base: float = 0.0  # For temperature (e.g., Celsius to Kelvin)
    latex_symbol: str = ""

    def to_latex(self) -> str:
        return self.latex_symbol or f"\\text{{{self.symbol}}}"

    @property
    def conversion_factor(self) -> float:
        return self.scale_to_base

    def __str__(self) -> str:
        return self.symbol


# Canonical Unit Registry
_UNITS: Dict[str, Unit] = {
    # Dimensionless
    "": Unit("", "dimensionless", Dimension.DIMENSIONLESS, 1.0, latex_symbol=""),
    "%": Unit("%", "percent", Dimension.DIMENSIONLESS, 0.01, latex_symbol="\\%"),
    
    # Length (base: meter 'm')
    "mm": Unit("mm", "millimeter", Dimension.LENGTH, 0.001, latex_symbol="\\text{mm}"),
    "cm": Unit("cm", "centimeter", Dimension.LENGTH, 0.01, latex_symbol="\\text{cm}"),
    "dm": Unit("dm", "decimeter", Dimension.LENGTH, 0.1, latex_symbol="\\text{dm}"),
    "m": Unit("m", "meter", Dimension.LENGTH, 1.0, latex_symbol="\\text{m}"),
    "km": Unit("km", "kilometer", Dimension.LENGTH, 1000.0, latex_symbol="\\text{km}"),
    "in": Unit("in", "inch", Dimension.LENGTH, 0.0254, latex_symbol="\\text{in}"),
    "ft": Unit("ft", "foot", Dimension.LENGTH, 0.3048, latex_symbol="\\text{ft}"),
    "yd": Unit("yd", "yard", Dimension.LENGTH, 0.9144, latex_symbol="\\text{yd}"),
    "mi": Unit("mi", "mile", Dimension.LENGTH, 1609.344, latex_symbol="\\text{mi}"),

    # Area (base: square meter 'm^2')
    "mm^2": Unit("mm^2", "square millimeter", Dimension.AREA, 1e-6, latex_symbol="\\text{mm}^2"),
    "cm^2": Unit("cm^2", "square centimeter", Dimension.AREA, 1e-4, latex_symbol="\\text{cm}^2"),
    "m^2": Unit("m^2", "square meter", Dimension.AREA, 1.0, latex_symbol="\\text{m}^2"),
    "ha": Unit("ha", "hectare", Dimension.AREA, 10000.0, latex_symbol="\\text{ha}"),
    "km^2": Unit("km^2", "square kilometer", Dimension.AREA, 1e6, latex_symbol="\\text{km}^2"),

    # Volume & Capacity (base: cubic meter 'm^3')
    "mm^3": Unit("mm^3", "cubic millimeter", Dimension.VOLUME, 1e-9, latex_symbol="\\text{mm}^3"),
    "cm^3": Unit("cm^3", "cubic centimeter", Dimension.VOLUME, 1e-6, latex_symbol="\\text{cm}^3"),
    "mL": Unit("mL", "milliliter", Dimension.VOLUME, 1e-6, latex_symbol="\\text{mL}"),
    "L": Unit("L", "liter", Dimension.VOLUME, 1e-3, latex_symbol="\\text{L}"),
    "m^3": Unit("m^3", "cubic meter", Dimension.VOLUME, 1.0, latex_symbol="\\text{m}^3"),

    # Mass (base: kilogram 'kg')
    "mg": Unit("mg", "milligram", Dimension.MASS, 1e-6, latex_symbol="\\text{mg}"),
    "g": Unit("g", "gram", Dimension.MASS, 1e-3, latex_symbol="\\text{g}"),
    "kg": Unit("kg", "kilogram", Dimension.MASS, 1.0, latex_symbol="\\text{kg}"),
    "tonne": Unit("tonne", "metric ton", Dimension.MASS, 1000.0, latex_symbol="\\text{t}"),
    "t": Unit("t", "metric ton", Dimension.MASS, 1000.0, latex_symbol="\\text{t}"),

    # Time (base: second 's')
    "ms": Unit("ms", "millisecond", Dimension.TIME, 0.001, latex_symbol="\\text{ms}"),
    "s": Unit("s", "second", Dimension.TIME, 1.0, latex_symbol="\\text{s}"),
    "min": Unit("min", "minute", Dimension.TIME, 60.0, latex_symbol="\\text{min}"),
    "h": Unit("h", "hour", Dimension.TIME, 3600.0, latex_symbol="\\text{h}"),
    "hr": Unit("hr", "hour", Dimension.TIME, 3600.0, latex_symbol="\\text{h}"),
    "day": Unit("day", "day", Dimension.TIME, 86400.0, latex_symbol="\\text{day}"),

    # Speed (base: meter per second 'm/s')
    "m/s": Unit("m/s", "meter per second", Dimension.SPEED, 1.0, latex_symbol="\\text{m/s}"),
    "km/h": Unit("km/h", "kilometer per hour", Dimension.SPEED, 1.0 / 3.6, latex_symbol="\\text{km/h}"),
    "km/hr": Unit("km/hr", "kilometer per hour", Dimension.SPEED, 1.0 / 3.6, latex_symbol="\\text{km/h}"),

    # Density (base: kg/m^3)
    "kg/m^3": Unit("kg/m^3", "kilogram per cubic meter", Dimension.DENSITY, 1.0, latex_symbol="\\text{kg/m}^3"),
    "g/cm^3": Unit("g/cm^3", "gram per cubic centimeter", Dimension.DENSITY, 1000.0, latex_symbol="\\text{g/cm}^3"),

    # Temperature (base: Kelvin 'K')
    "K": Unit("K", "kelvin", Dimension.TEMPERATURE, 1.0, 0.0, latex_symbol="\\text{K}"),
    "degC": Unit("degC", "degree Celsius", Dimension.TEMPERATURE, 1.0, 273.15, latex_symbol="^{\\circ}\\text{C}"),
    "C": Unit("C", "degree Celsius", Dimension.TEMPERATURE, 1.0, 273.15, latex_symbol="^{\\circ}\\text{C}"),

    # Money / Currency
    "KES": Unit("KES", "Kenya Shilling", Dimension.MONEY, 1.0, latex_symbol="\\text{KES}"),
    "KSh": Unit("KSh", "Kenya Shilling", Dimension.MONEY, 1.0, latex_symbol="\\text{KSh}"),
    "USD": Unit("USD", "US Dollar", Dimension.MONEY, 130.0, latex_symbol="\\$"),
}


def get_unit(symbol: str | Unit) -> Unit:
    """Retrieve Unit from symbol string or return itself if already Unit."""
    if isinstance(symbol, Unit):
        return symbol
    clean = symbol.strip()
    if clean in _UNITS:
        return _UNITS[clean]
    # Check case-insensitive
    for k, u in _UNITS.items():
        if k.lower() == clean.lower():
            return u
    raise ValueError(f"Unknown unit symbol '{symbol}'. Known units: {list(_UNITS.keys())}")


class UnitRegistry:
    """Registry providing unit lookup, registration, and discovery."""

    @classmethod
    def get(cls, symbol: str | Unit) -> Unit:
        return get_unit(symbol)

    @classmethod
    def all_units(cls) -> Dict[str, Unit]:
        return dict(_UNITS)

    @classmethod
    def units_for_dimension(cls, dimension: Dimension) -> Dict[str, Unit]:
        return {k: u for k, u in _UNITS.items() if u.dimension == dimension}


@dataclass(slots=True)
class Quantity:
    """A numerical value combined with a physical unit.
    
    Supports arithmetic with dimensional validation and automatic unit conversion.
    """
    value: float | int
    unit: Unit = field(default_factory=lambda: _UNITS[""])

    def __init__(self, value: float | int, unit: str | Unit = ""):
        self.value = value
        self.unit = get_unit(unit) if isinstance(unit, str) else unit

    @property
    def dimension(self) -> Dimension:
        return self.unit.dimension

    def to_base_value(self) -> float:
        """Convert quantity value to standard SI base unit representation."""
        return float(self.value) * self.unit.scale_to_base + self.unit.offset_to_base

    def to_unit(self, target_unit: str | Unit) -> Quantity:
        """Convert this quantity to a compatible target unit."""
        target = get_unit(target_unit) if isinstance(target_unit, str) else target_unit
        if self.dimension != target.dimension:
            raise DimensionalError(
                f"Cannot convert {self.unit.name} ({self.dimension.value}) to "
                f"{target.name} ({target.dimension.value}): incompatible dimensions."
            )
        base_val = self.to_base_value()
        new_val = (base_val - target.offset_to_base) / target.scale_to_base
        if isinstance(self.value, int) and target.scale_to_base == self.unit.scale_to_base:
            return Quantity(int(new_val), target)
        return Quantity(round(new_val, 8) if not float(new_val).is_integer() else int(new_val), target)

    def __add__(self, other: Any) -> Quantity:
        if isinstance(other, (int, float)) and self.dimension == Dimension.DIMENSIONLESS:
            return Quantity(self.value + other, self.unit)
        if not isinstance(other, Quantity):
            raise TypeError(f"Cannot add Quantity and {type(other)}")
        if self.dimension != other.dimension:
            raise DimensionalError(
                f"Cannot add {self.unit} ({self.dimension.value}) and {other.unit} ({other.dimension.value})"
            )
        # Convert other to self's unit
        converted_other = other.to_unit(self.unit)
        return Quantity(self.value + converted_other.value, self.unit)

    def __sub__(self, other: Any) -> Quantity:
        if isinstance(other, (int, float)) and self.dimension == Dimension.DIMENSIONLESS:
            return Quantity(self.value - other, self.unit)
        if not isinstance(other, Quantity):
            raise TypeError(f"Cannot subtract Quantity and {type(other)}")
        if self.dimension != other.dimension:
            raise DimensionalError(
                f"Cannot subtract {other.unit} ({other.dimension.value}) from {self.unit} ({self.dimension.value})"
            )
        converted_other = other.to_unit(self.unit)
        return Quantity(self.value - converted_other.value, self.unit)

    def __mul__(self, other: Any) -> Quantity:
        if isinstance(other, (int, float)):
            return Quantity(self.value * other, self.unit)
        if not isinstance(other, Quantity):
            raise TypeError(f"Cannot multiply Quantity and {type(other)}")
        
        # Multiply units if specific derived pairs exist
        val = self.value * other.value
        # Length * Length -> Area
        if self.dimension == Dimension.LENGTH and other.dimension == Dimension.LENGTH:
            u1 = self.to_unit("m")
            u2 = other.to_unit("m")
            return Quantity(u1.value * u2.value, "m^2").to_unit(f"{self.unit.symbol}^2" if f"{self.unit.symbol}^2" in _UNITS else "m^2")
        # Speed * Time -> Length
        if self.dimension == Dimension.SPEED and other.dimension == Dimension.TIME:
            s_base = self.to_base_value()  # m/s
            t_base = other.to_base_value()  # s
            return Quantity(s_base * t_base, "m")
        if self.dimension == Dimension.TIME and other.dimension == Dimension.SPEED:
            return other * self

        # Default fallback
        return Quantity(val, f"{self.unit}*{other.unit}" if self.unit.symbol and other.unit.symbol else self.unit or other.unit)

    def __truediv__(self, other: Any) -> Quantity:
        if isinstance(other, (int, float)):
            if other == 0:
                raise ZeroDivisionError("Division by zero in quantity")
            return Quantity(self.value / other, self.unit)
        if not isinstance(other, Quantity):
            raise TypeError(f"Cannot divide Quantity by {type(other)}")
        
        if other.value == 0:
            raise ZeroDivisionError("Division by zero in quantity")

        # Same dimension ratio -> dimensionless
        if self.dimension == other.dimension:
            return Quantity(self.to_base_value() / other.to_base_value(), "")

        # Length / Time -> Speed
        if self.dimension == Dimension.LENGTH and other.dimension == Dimension.TIME:
            return Quantity(self.to_base_value() / other.to_base_value(), "m/s")

        # Mass / Volume -> Density
        if self.dimension == Dimension.MASS and other.dimension == Dimension.VOLUME:
            return Quantity(self.to_base_value() / other.to_base_value(), "kg/m^3")

        return Quantity(self.value / other.value, f"{self.unit}/{other.unit}")

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, (int, float)) and self.dimension == Dimension.DIMENSIONLESS:
            return math.isclose(self.value, other, rel_tol=1e-7, abs_tol=1e-9)
        if not isinstance(other, Quantity):
            return False
        if self.dimension != other.dimension:
            return False
        return math.isclose(self.to_base_value(), other.to_base_value(), rel_tol=1e-7, abs_tol=1e-9)

    def to_latex(self) -> str:
        val_str = str(int(self.value)) if isinstance(self.value, float) and self.value.is_integer() else str(self.value)
        unit_lat = self.unit.to_latex()
        if not unit_lat:
            return val_str
        return f"{val_str}\\ {unit_lat}"

    def to_plain(self) -> str:
        return f"{self.value} {self.unit.symbol}".strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit.symbol,
            "dimension": self.dimension.value,
            "latex": self.to_latex(),
            "plain": self.to_plain(),
        }

    def __repr__(self) -> str:
        return f"Quantity({self.value}, '{self.unit.symbol}')"
