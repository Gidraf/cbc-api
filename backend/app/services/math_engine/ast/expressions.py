from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Union

from .base import Expression


@dataclass(slots=True)
class Constant(Expression):
    value: Union[int, float]

    def to_latex(self) -> str:
        if isinstance(self.value, float) and self.value.is_integer():
            return str(int(self.value))
        return str(self.value)

    def to_plain(self) -> str:
        return str(self.value)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "constant", "value": self.value, "latex": self.to_latex()}

    def evaluate(self, **env: Any) -> Union[int, float]:
        return self.value


@dataclass(slots=True)
class Variable(Expression):
    name: str

    def to_latex(self) -> str:
        return self.name

    def to_plain(self) -> str:
        return self.name

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "variable", "name": self.name, "latex": self.name}

    def evaluate(self, **env: Any) -> Any:
        if self.name in env:
            return env[self.name]
        raise ValueError(f"Variable '{self.name}' not provided in evaluation environment.")


@dataclass(slots=True)
class FractionExpr(Expression):
    numerator: int
    denominator: int

    def __post_init__(self):
        if self.denominator == 0:
            raise ZeroDivisionError("Fraction denominator cannot be zero.")

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "fraction",
            "numerator": self.numerator,
            "denominator": self.denominator,
            "latex": self.to_latex(),
            "plain": self.to_plain(),
        }

    def evaluate(self, **env: Any) -> float:
        return self.numerator / self.denominator


@dataclass(slots=True)
class Term(Expression):
    coefficient: Union[int, float] = 1
    variable: str = "x"
    power: Union[int, float] = 1

    def __init__(
        self,
        coefficient: Union[int, float, None] = None,
        variable: str = "x",
        power: Union[int, float] = 1,
        coeff: Union[int, float, None] = None,
    ):
        if coefficient is not None:
            self.coefficient = coefficient
        elif coeff is not None:
            self.coefficient = coeff
        else:
            self.coefficient = 1
        self.variable = variable
        self.power = power

    def to_latex(self) -> str:
        if self.coefficient == 0:
            return "0"
        coeff_str = ""
        if self.coefficient == -1 and self.power != 0:
            coeff_str = "-"
        elif self.coefficient != 1 or self.power == 0:
            coeff_str = str(int(self.coefficient)) if isinstance(self.coefficient, float) and self.coefficient.is_integer() else str(self.coefficient)

        if self.power == 0:
            return coeff_str or "1"
        if self.power == 1:
            return f"{coeff_str}{self.variable}"
        return f"{coeff_str}{self.variable}^{{{self.power}}}"

    def to_plain(self) -> str:
        if self.power == 0:
            return str(self.coefficient)
        if self.power == 1:
            return f"{self.coefficient}{self.variable}"
        return f"{self.coefficient}{self.variable}^{self.power}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "term",
            "coefficient": self.coefficient,
            "variable": self.variable,
            "power": self.power,
            "latex": self.to_latex(),
        }

    def evaluate(self, env_dict: Optional[Dict[str, Any]] = None, **env: Any) -> float:
        merged = dict(env_dict or {})
        merged.update(env)
        val = merged.get(self.variable, 0)
        return self.coefficient * (val ** self.power)


@dataclass(slots=True)
class Polynomial(Expression):
    terms: List[Term] = field(default_factory=list)
    constant: Union[int, float] = 0
    variable: str = "x"

    def to_latex(self) -> str:
        parts: List[str] = []
        for i, t in enumerate(self.terms):
            if t.coefficient == 0:
                continue
            t_lat = t.to_latex()
            if i > 0 and t.coefficient > 0:
                parts.append(f"+ {t_lat}")
            elif i > 0 and t.coefficient < 0:
                parts.append(f"- {t_lat.lstrip('-')}")
            else:
                parts.append(t_lat)

        if self.constant != 0 or not parts:
            c_str = str(int(self.constant)) if isinstance(self.constant, float) and self.constant.is_integer() else str(self.constant)
            if parts:
                if self.constant > 0:
                    parts.append(f"+ {c_str}")
                else:
                    parts.append(f"- {abs(self.constant)}")
            else:
                parts.append(c_str)

        return " ".join(parts) or "0"

    def to_plain(self) -> str:
        return self.to_latex().replace("{", "").replace("}", "")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "polynomial",
            "terms": [t.to_dict() for t in self.terms],
            "constant": self.constant,
            "latex": self.to_latex(),
        }

    @property
    def degree(self) -> int:
        if not self.terms:
            return 0
        return max(int(t.power) for t in self.terms)

    def evaluate(self, env_dict: Optional[Dict[str, Any]] = None, **env: Any) -> float:
        merged = dict(env_dict or {})
        merged.update(env)
        return sum(t.evaluate(merged) for t in self.terms) + self.constant


@dataclass(slots=True)
class Power(Expression):
    base: Expression
    exponent: Union[Expression, int, float]

    def to_latex(self) -> str:
        exp_str = self.exponent.to_latex() if isinstance(self.exponent, Expression) else str(self.exponent)
        base_str = self.base.to_latex()
        if isinstance(self.base, (Polynomial, BinaryOp)):
            base_str = f"\\left({base_str}\\right)"
        return f"{base_str}^{{{exp_str}}}"

    def to_plain(self) -> str:
        return f"({self.base.to_plain()})^({self.exponent})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "power",
            "base": self.base.to_dict(),
            "exponent": self.exponent.to_dict() if isinstance(self.exponent, Expression) else self.exponent,
            "latex": self.to_latex(),
        }

    def evaluate(self, **env: Any) -> float:
        b = self.base.evaluate(**env)
        e = self.exponent.evaluate(**env) if isinstance(self.exponent, Expression) else self.exponent
        return b ** e


@dataclass(slots=True)
class Radical(Expression):
    radicand: Expression
    index: int = 2

    def to_latex(self) -> str:
        if self.index == 2:
            return f"\\sqrt{{{self.radicand.to_latex()}}}"
        return f"\\sqrt[{self.index}]{{{self.radicand.to_latex()}}}"

    def to_plain(self) -> str:
        if self.index == 2:
            return f"sqrt({self.radicand.to_plain()})"
        return f"root({self.index}, {self.radicand.to_plain()})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "radical",
            "radicand": self.radicand.to_dict(),
            "index": self.index,
            "latex": self.to_latex(),
        }

    def evaluate(self, **env: Any) -> float:
        val = self.radicand.evaluate(**env)
        return val ** (1.0 / self.index)


@dataclass(slots=True)
class Logarithm(Expression):
    argument: Expression
    base: Union[Expression, int, float] = 10

    def to_latex(self) -> str:
        arg_lat = self.argument.to_latex()
        if self.base == 10:
            return f"\\log\\left({arg_lat}\\right)"
        if self.base == "e" or self.base == math.e:
            return f"\\ln\\left({arg_lat}\\right)"
        base_lat = self.base.to_latex() if isinstance(self.base, Expression) else str(self.base)
        return f"\\log_{{{base_lat}}}\\left({arg_lat}\\right)"

    def to_plain(self) -> str:
        return f"log_{self.base}({self.argument.to_plain()})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "logarithm",
            "argument": self.argument.to_dict(),
            "base": str(self.base),
            "latex": self.to_latex(),
        }

    def evaluate(self, **env: Any) -> float:
        val = self.argument.evaluate(**env)
        b = self.base.evaluate(**env) if isinstance(self.base, Expression) else (math.e if self.base == "e" else float(self.base))
        return math.log(val, b)


@dataclass(slots=True)
class BinaryOp(Expression):
    left: Expression
    op: str  # '+', '-', '*', '/'
    right: Expression

    def __init__(self, a: Any, b: Any, c: Any = None):
        if isinstance(a, str) and isinstance(b, Expression):
            self.op = a
            self.left = b
            self.right = c
        elif isinstance(b, str) and isinstance(a, Expression):
            self.left = a
            self.op = b
            self.right = c
        else:
            self.left = a
            self.op = str(b)
            self.right = c

    def to_latex(self) -> str:
        op_map = {"*": "\\times", "/": "\\div"}
        lat_op = op_map.get(self.op, self.op)
        if self.op == "/":
            return f"\\frac{{{self.left.to_latex()}}}{{{self.right.to_latex()}}}"
        return f"{self.left.to_latex()} {lat_op} {self.right.to_latex()}"

    def to_plain(self) -> str:
        return f"({self.left.to_plain()} {self.op} {self.right.to_plain()})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "binary_op",
            "op": self.op,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
            "latex": self.to_latex(),
        }

    def evaluate(self, **env: Any) -> float:
        l = self.left.evaluate(**env)
        r = self.right.evaluate(**env)
        if self.op == "+":
            return l + r
        if self.op == "-":
            return l - r
        if self.op == "*":
            return l * r
        if self.op == "/":
            if r == 0:
                raise ZeroDivisionError("Division by zero in expression evaluation.")
            return l / r
        raise ValueError(f"Unknown binary operator '{self.op}'")
