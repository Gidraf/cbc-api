from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .base import DatasetObject


@dataclass(slots=True)
class Dataset(DatasetObject):
    values: List[float]

    def count(self) -> int:
        return len(self.values)

    def total(self) -> float:
        return sum(self.values)

    def mean(self) -> float:
        return self.total() / self.count() if self.values else 0.0

    def median(self) -> float:
        return statistics.median(self.values) if self.values else 0.0

    def mode(self) -> float:
        try:
            return statistics.mode(self.values)
        except statistics.StatisticsError:
            return self.values[0] if self.values else 0.0

    def range(self) -> float:
        if not self.values:
            return 0.0
        return max(self.values) - min(self.values)

    def quartiles(self) -> Tuple[float, float, float]:
        """Return (Q1, Q2/median, Q3)."""
        if not self.values:
            return (0.0, 0.0, 0.0)
        sorted_v = sorted(self.values)
        med = self.median()
        n = len(sorted_v)
        if n == 1:
            return (sorted_v[0], sorted_v[0], sorted_v[0])
        half = n // 2
        lower = sorted_v[:half]
        upper = sorted_v[half + (1 if n % 2 != 0 else 0):]
        q1 = statistics.median(lower) if lower else med
        q3 = statistics.median(upper) if upper else med
        return (q1, med, q3)

    def iqr(self) -> float:
        q1, _, q3 = self.quartiles()
        return q3 - q1

    def variance(self) -> float:
        return statistics.variance(self.values) if len(self.values) > 1 else 0.0

    def std_dev(self) -> float:
        return statistics.stdev(self.values) if len(self.values) > 1 else 0.0

    def to_latex(self) -> str:
        vals = ", ".join(str(int(v)) if v.is_integer() else str(v) for v in self.values[:8])
        if len(self.values) > 8:
            vals += ", \\dots"
        return f"\\left\\{{ {vals} \\right\\}}"

    def to_plain(self) -> str:
        return f"Dataset({self.values})"

    def to_dict(self) -> Dict[str, Any]:
        q1, med, q3 = self.quartiles()
        return {
            "type": "dataset",
            "count": self.count(),
            "values": self.values,
            "mean": round(self.mean(), 3),
            "median": round(med, 3),
            "mode": round(self.mode(), 3),
            "range": round(self.range(), 3),
            "q1": round(q1, 3),
            "q3": round(q3, 3),
            "iqr": round(self.iqr(), 3),
            "std_dev": round(self.std_dev(), 3),
        }


@dataclass(slots=True)
class FrequencyTable(DatasetObject):
    categories: List[str]
    frequencies: List[int]

    def total_frequency(self) -> int:
        return sum(self.frequencies)

    def modal_category(self) -> str:
        if not self.frequencies:
            return ""
        max_f = max(self.frequencies)
        idx = self.frequencies.index(max_f)
        return self.categories[idx]

    def to_latex(self) -> str:
        rows = " \\\\\n".join(f"{c} & {f}" for c, f in zip(self.categories, self.frequencies))
        return f"\\begin{{array}}{{|c|c|}}\n\\hline\n\\text{{Category}} & \\text{{Frequency}} \\\\\n\\hline\n{rows} \\\\\n\\hline\n\\end{{array}}"

    def to_plain(self) -> str:
        return "; ".join(f"{c}: {f}" for c, f in zip(self.categories, self.frequencies))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "frequency_table",
            "categories": self.categories,
            "frequencies": self.frequencies,
            "total_frequency": self.total_frequency(),
            "modal_category": self.modal_category(),
        }
