from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .base import Expression, MathObject
from .geometry import Point


@dataclass(slots=True)
class TableOfValues(MathObject):
    x_values: List[float]
    y_values: List[float]
    x_label: str = "x"
    y_label: str = "y"

    def to_latex(self) -> str:
        headers = f"{self.x_label} & " + " & ".join(str(int(x)) if x.is_integer() else str(x) for x in self.x_values)
        vals = f"{self.y_label} & " + " & ".join(str(int(y)) if y.is_integer() else str(round(y, 2)) for y in self.y_values)
        col_spec = "|" + "c|" * (len(self.x_values) + 1)
        return f"\\begin{{array}}{{{col_spec}}}\n\\hline\n{headers} \\\\\n\\hline\n{vals} \\\\\n\\hline\n\\end{{array}}"

    def to_plain(self) -> str:
        pairs = ", ".join(f"({x}, {y})" for x, y in zip(self.x_values, self.y_values))
        return f"TableOfValues[{pairs}]"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "table_of_values",
            "x_label": self.x_label,
            "y_label": self.y_label,
            "x_values": self.x_values,
            "y_values": self.y_values,
            "points": [{"x": x, "y": y} for x, y in zip(self.x_values, self.y_values)],
        }


@dataclass(slots=True)
class MathFunction(MathObject):
    name: str = "f"
    variable: str = "x"
    expression: Optional[Expression] = None
    latex_def: str = ""

    def evaluate_at(self, x: float) -> float:
        if self.expression:
            return float(self.expression.evaluate(**{self.variable: x}))
        raise ValueError(f"Function {self.name} has no evaluatable expression.")

    def generate_table(self, x_values: List[float]) -> TableOfValues:
        y_vals = [self.evaluate_at(x) for x in x_values]
        return TableOfValues(x_values, y_vals, x_label=self.variable, y_label=f"{self.name}({self.variable})")

    def to_latex(self) -> str:
        if self.latex_def:
            return f"{self.name}\\left({self.variable}\\right) = {self.latex_def}"
        if self.expression:
            return f"{self.name}\\left({self.variable}\\right) = {self.expression.to_latex()}"
        return f"{self.name}\\left({self.variable}\\right)"

    def to_plain(self) -> str:
        return f"{self.name}({self.variable}) = {self.expression.to_plain() if self.expression else ''}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "variable": self.variable,
            "expression": self.expression.to_dict() if self.expression else None,
            "latex": self.to_latex(),
        }


@dataclass(slots=True)
class CoordinatePlane(MathObject):
    x_min: float = -10
    x_max: float = 10
    y_min: float = -10
    y_max: float = 10
    points: List[Point] = field(default_factory=list)
    functions: List[MathFunction] = field(default_factory=list)

    def to_latex(self) -> str:
        return f"\\text{{Cartesian Plane }}\\ [x: {self.x_min}\\dots {self.x_max}, y: {self.y_min}\\dots {self.y_max}]"

    def to_plain(self) -> str:
        return f"Plane[{self.x_min}..{self.x_max}, {self.y_min}..{self.y_max}]"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "coordinate_plane",
            "x_bounds": [self.x_min, self.x_max],
            "y_bounds": [self.y_min, self.y_max],
            "points": [p.to_dict() for p in self.points],
            "functions": [f.to_dict() for f in self.functions],
        }
