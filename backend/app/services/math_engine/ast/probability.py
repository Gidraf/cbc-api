from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Dict, List

from .base import MathObject


@dataclass(slots=True)
class SampleSpace(MathObject):
    outcomes: List[Any] = field(default_factory=list)

    def size(self) -> int:
        return len(self.outcomes)

    def to_latex(self) -> str:
        items = ", ".join(str(o) for o in self.outcomes[:10])
        return f"S = \\left\\{{ {items} \\right\\}}"

    def to_plain(self) -> str:
        return f"SampleSpace({self.outcomes})"

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "sample_space", "size": self.size(), "outcomes": self.outcomes}


@dataclass(slots=True)
class ProbabilityValue(MathObject):
    favorable: int
    total: int

    def __post_init__(self):
        if self.total <= 0:
            raise ValueError("Total outcomes in probability must be strictly positive.")
        if self.favorable < 0 or self.favorable > self.total:
            raise ValueError(f"Favorable outcomes {self.favorable} must be between 0 and total {self.total}.")

    def as_fraction(self) -> Fraction:
        return Fraction(self.favorable, self.total)

    def as_decimal(self) -> float:
        return round(self.favorable / self.total, 4)

    def as_percentage(self) -> float:
        return round((self.favorable / self.total) * 100, 2)

    def to_latex(self) -> str:
        fr = self.as_fraction()
        if fr.denominator == 1:
            return str(fr.numerator)
        return f"\\frac{{{fr.numerator}}}{{{fr.denominator}}}"

    def to_plain(self) -> str:
        fr = self.as_fraction()
        return f"{fr.numerator}/{fr.denominator} ({self.as_percentage()}%)"

    def to_dict(self) -> Dict[str, Any]:
        fr = self.as_fraction()
        return {
            "type": "probability_value",
            "favorable": self.favorable,
            "total": self.total,
            "fraction_latex": self.to_latex(),
            "decimal": self.as_decimal(),
            "percentage": self.as_percentage(),
        }


@dataclass(slots=True)
class Event(MathObject):
    name: str
    favorable_outcomes: List[Any]
    sample_space: SampleSpace

    def probability(self) -> ProbabilityValue:
        return ProbabilityValue(len(self.favorable_outcomes), self.sample_space.size())

    def complementary_probability(self) -> ProbabilityValue:
        comp_count = self.sample_space.size() - len(self.favorable_outcomes)
        return ProbabilityValue(comp_count, self.sample_space.size())

    def to_latex(self) -> str:
        p = self.probability()
        return f"P\\left({self.name}\\right) = {p.to_latex()}"

    def to_plain(self) -> str:
        p = self.probability()
        return f"P({self.name}) = {p.to_plain()}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "event",
            "name": self.name,
            "probability": self.probability().to_dict(),
            "complementary_probability": self.complementary_probability().to_dict(),
        }
