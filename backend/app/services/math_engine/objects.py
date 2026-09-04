from __future__ import annotations

from dataclasses import dataclass, field
import statistics
from typing import Any


@dataclass(slots=True)
class MathNumber:
    value: int | float

    def to_latex(self) -> str:
        if isinstance(self.value, float) and self.value.is_integer():
            return str(int(self.value))
        return str(self.value)

    def to_plain(self) -> str:
        return str(self.value)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "number", "value": self.value, "latex": self.to_latex()}


@dataclass(slots=True)
class MathFraction:
    numerator: int
    denominator: int

    def to_latex(self) -> str:
        if self.denominator == 1:
            return str(self.numerator)
        if abs(self.numerator) >= self.denominator and self.denominator > 0:
            whole = self.numerator // self.denominator
            rem = abs(self.numerator) % self.denominator
            if rem == 0:
                return str(whole)
            return f"{whole}\\frac{{{rem}}}{{{self.denominator}}}"
        return f"\\frac{{{self.numerator}}}{{{self.denominator}}}"

    def to_plain(self) -> str:
        return f"{self.numerator}/{self.denominator}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "fraction",
            "numerator": self.numerator,
            "denominator": self.denominator,
            "latex": self.to_latex(),
            "plain": self.to_plain(),
        }


@dataclass(slots=True)
class MathPercentage:
    value: float | int

    def to_latex(self) -> str:
        val_str = str(int(self.value)) if isinstance(self.value, float) and self.value.is_integer() else str(self.value)
        return f"{val_str}\\%"

    def to_plain(self) -> str:
        return f"{self.value}%"

    def to_dict(self) -> dict[str, Any]:
        return {"type": "percentage", "value": self.value, "latex": self.to_latex()}


@dataclass(slots=True)
class MathRatio:
    terms: list[int]

    def to_latex(self) -> str:
        return " : ".join(str(t) for t in self.terms)

    def to_plain(self) -> str:
        return ":".join(str(t) for t in self.terms)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "ratio", "terms": self.terms, "latex": self.to_latex()}


@dataclass(slots=True)
class MathVariable:
    symbol: str

    def to_latex(self) -> str:
        return self.symbol

    def to_plain(self) -> str:
        return self.symbol


@dataclass(slots=True)
class MathExpression:
    raw: str
    latex: str

    def to_latex(self) -> str:
        return self.latex

    def to_plain(self) -> str:
        return self.raw


@dataclass(slots=True)
class MathEquation:
    lhs: str
    rhs: str
    variable: str = "x"

    def to_latex(self) -> str:
        return f"{self.lhs} = {self.rhs}"

    def to_plain(self) -> str:
        return f"{self.lhs} = {self.rhs}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "equation",
            "lhs": self.lhs,
            "rhs": self.rhs,
            "variable": self.variable,
            "latex": self.to_latex(),
        }


@dataclass(slots=True)
class MathPoint:
    name: str
    x: float
    y: float

    def to_latex(self) -> str:
        return f"{self.name}({self.x}, {self.y})"


@dataclass(slots=True)
class MathTriangle:
    a: MathPoint
    b: MathPoint
    c: MathPoint
    base: float
    height: float

    def area(self) -> float:
        return 0.5 * self.base * self.height

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "triangle",
            "points": [
                {"name": self.a.name, "x": self.a.x, "y": self.a.y},
                {"name": self.b.name, "x": self.b.x, "y": self.b.y},
                {"name": self.c.name, "x": self.c.x, "y": self.c.y},
            ],
            "base": self.base,
            "height": self.height,
            "area": self.area(),
            "latex_area": f"A = \\frac{{1}}{{2}} \\times {self.base} \\times {self.height} = {self.area()}",
        }


@dataclass(slots=True)
class MathDataset:
    values: list[float]

    def mean(self) -> float:
        return sum(self.values) / len(self.values) if self.values else 0.0

    def median(self) -> float:
        return statistics.median(self.values) if self.values else 0.0

    def mode(self) -> float:
        try:
            return statistics.mode(self.values)
        except statistics.StatisticsError:
            return self.values[0] if self.values else 0.0

    def to_latex_summary(self) -> str:
        m = round(self.mean(), 2)
        med = self.median()
        mo = self.mode()
        return f"\\bar{{x}} = {m},\\ \\text{{Median}} = {med},\\ \\text{{Mode}} = {mo}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "dataset",
            "values": self.values,
            "mean": round(self.mean(), 2),
            "median": self.median(),
            "mode": self.mode(),
            "latex": self.to_latex_summary(),
        }


@dataclass(slots=True)
class SolutionStep:
    step_number: int
    operation: str
    expression_before: str
    expression_after: str
    latex: str
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "operation": self.operation,
            "expression_before": self.expression_before,
            "expression_after": self.expression_after,
            "latex": self.latex,
            "explanation": self.explanation,
        }


@dataclass(slots=True)
class SolutionTrace:
    problem: str
    final_answer: str
    steps: list[SolutionStep] = field(default_factory=list)
    verified: bool = False
    check_latex: str = ""
    # No solver recognised the problem. Distinct from `verified=False`, which
    # means it was solved and the check did not confirm it.
    unsolved: bool = False
    unsolved_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "problem": self.problem,
            "final_answer": self.final_answer,
            "steps": [s.to_dict() for s in self.steps],
            "verified": self.verified,
            "check_latex": self.check_latex,
            "unsolved": self.unsolved,
            "unsolved_reason": self.unsolved_reason,
        }
