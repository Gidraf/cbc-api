from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict

from .base import MathObject


@dataclass(slots=True)
class Money(MathObject):
    amount: float
    currency: str = "KES"

    def __add__(self, other: Any) -> Money:
        if isinstance(other, (int, float)):
            return Money(self.amount + other, self.currency)
        if isinstance(other, Money):
            if self.currency != other.currency:
                raise ValueError(f"Cannot add different currencies: {self.currency} and {other.currency}")
            return Money(self.amount + other.amount, self.currency)
        raise TypeError(f"Cannot add Money and {type(other)}")

    def __sub__(self, other: Any) -> Money:
        if isinstance(other, (int, float)):
            return Money(self.amount - other, self.currency)
        if isinstance(other, Money):
            if self.currency != other.currency:
                raise ValueError(f"Cannot subtract different currencies: {self.currency} and {other.currency}")
            return Money(self.amount - other.amount, self.currency)
        raise TypeError(f"Cannot subtract Money and {type(other)}")

    def __mul__(self, other: Any) -> Money:
        if isinstance(other, (int, float)):
            return Money(self.amount * other, self.currency)
        raise TypeError("Money can only be multiplied by scalar numbers.")

    def to_latex(self) -> str:
        formatted = f"{self.amount:,.2f}"
        return f"\\text{{{self.currency}}}\\ {formatted}"

    def to_plain(self) -> str:
        return f"{self.currency} {self.amount:,.2f}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "money",
            "amount": round(self.amount, 2),
            "currency": self.currency,
            "latex": self.to_latex(),
            "plain": self.to_plain(),
        }


@dataclass(slots=True)
class InterestModel(MathObject):
    principal: Money
    rate_percent: float
    time_years: float
    kind: str = "simple"  # simple or compound
    compounding_per_year: int = 1

    def interest(self) -> Money:
        p = self.principal.amount
        r = self.rate_percent / 100.0
        t = self.time_years
        if self.kind == "simple":
            return Money(p * r * t, self.principal.currency)
        # compound
        n = self.compounding_per_year
        amount = p * ((1.0 + r / n) ** (n * t))
        return Money(amount - p, self.principal.currency)

    def total_amount(self) -> Money:
        return self.principal + self.interest()

    def to_latex(self) -> str:
        if self.kind == "simple":
            return f"I = \\frac{{P \\times R \\times T}}{{100}} = \\frac{{{self.principal.amount} \\times {self.rate_percent} \\times {self.time_years}}}{{100}}"
        return f"A = P\\left(1 + \\frac{{r}}{{n}}\\right)^{{nt}}"

    def to_plain(self) -> str:
        return f"Interest({self.kind}): Principal {self.principal}, Rate {self.rate_percent}%, Time {self.time_years}yr"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "interest_model",
            "kind": self.kind,
            "principal": self.principal.to_dict(),
            "rate_percent": self.rate_percent,
            "time_years": self.time_years,
            "interest": self.interest().to_dict(),
            "total_amount": self.total_amount().to_dict(),
            "latex": self.to_latex(),
        }
