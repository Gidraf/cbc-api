from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .base import Expression, Relation


@dataclass(slots=True)
class Equation(Relation):
    lhs: Expression
    rhs: Expression

    def to_latex(self) -> str:
        return f"{self.lhs.to_latex()} = {self.rhs.to_latex()}"

    def to_plain(self) -> str:
        return f"{self.lhs.to_plain()} = {self.rhs.to_plain()}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "equation",
            "lhs": self.lhs.to_dict(),
            "rhs": self.rhs.to_dict(),
            "latex": self.to_latex(),
            "plain": self.to_plain(),
        }

    def is_satisfied(self, **env: Any) -> bool:
        """Check whether LHS == RHS under given variable assignment."""
        try:
            import math
            l_val = self.lhs.evaluate(**env)
            r_val = self.rhs.evaluate(**env)
            return math.isclose(float(l_val), float(r_val), rel_tol=1e-6, abs_tol=1e-8)
        except Exception:
            return False


@dataclass(slots=True)
class Inequality(Relation):
    lhs: Expression
    op: str  # '<', '<=', '>', '>=', '!='
    rhs: Expression

    def to_latex(self) -> str:
        op_map = {
            "<=": "\\le",
            ">=": "\\ge",
            "!=": "\\neq",
            "<": "<",
            ">": ">",
        }
        return f"{self.lhs.to_latex()} {op_map.get(self.op, self.op)} {self.rhs.to_latex()}"

    def to_plain(self) -> str:
        return f"{self.lhs.to_plain()} {self.op} {self.rhs.to_plain()}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "inequality",
            "op": self.op,
            "lhs": self.lhs.to_dict(),
            "rhs": self.rhs.to_dict(),
            "latex": self.to_latex(),
            "plain": self.to_plain(),
        }

    def is_satisfied(self, **env: Any) -> bool:
        l_val = float(self.lhs.evaluate(**env))
        r_val = float(self.rhs.evaluate(**env))
        if self.op == "<":
            return l_val < r_val
        if self.op == "<=":
            return l_val <= r_val
        if self.op == ">":
            return l_val > r_val
        if self.op == ">=":
            return l_val >= r_val
        if self.op == "!=":
            return l_val != r_val
        return False


@dataclass(slots=True)
class SystemOfEquations(Relation):
    equations: List[Equation] = field(default_factory=list)
    variables: List[str] = field(default_factory=list)

    def to_latex(self) -> str:
        rows = " \\\\\n".join(eq.to_latex() for eq in self.equations)
        return f"\\begin{{cases}}\n{rows}\n\\end{{cases}}"

    def to_plain(self) -> str:
        return "; ".join(eq.to_plain() for eq in self.equations)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "system_of_equations",
            "equations": [eq.to_dict() for eq in self.equations],
            "variables": self.variables,
            "latex": self.to_latex(),
        }
