"""Canonical Mathematical AST Base Interfaces.

The Mathematical AST is the single authoritative source of truth for mathematical meaning.
Renderers (LaTeX, KaTeX, SVG, HTML, speech) and engines (solvers, verifiers) consume this AST.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class MathObject(ABC):
    """Abstract base class for all canonical mathematical objects."""

    @abstractmethod
    def to_latex(self) -> str:
        """Return canonical LaTeX representation."""
        pass

    @abstractmethod
    def to_plain(self) -> str:
        """Return human-readable plain text or speech-friendly form."""
        pass

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Serialize object to JSON-compatible structured dictionary."""
        pass

    def evaluate(self, **env: Any) -> Any:
        """Evaluate numeric value in context of variable environment."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support numeric evaluation.")

    def __str__(self) -> str:
        return self.to_plain()

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.to_plain()}>"


class Expression(MathObject):
    """Base class for mathematical expressions that can be evaluated or manipulated."""
    pass


class Relation(MathObject):
    """Base class for mathematical relations (equations, inequalities, congruences)."""
    pass


class GeometryObject(MathObject):
    """Base class for geometric entities (points, lines, shapes, angles)."""
    pass


class DatasetObject(MathObject):
    """Base class for statistical data structures."""
    pass
