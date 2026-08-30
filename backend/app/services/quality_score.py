"""One number per generated item, from signals that were actually checked.

Auto mode needs a floor, and a floor needs a number. Every accuracy figure in
this project so far has been a person reading output against the KICD design.
That is the right way to judge a curriculum and the wrong way to gate a machine:
it does not exist until somebody does it.

So this scores what the pipeline already verifies, and nothing else. Every
component below is a measurement some validator performed on this item — not an
opinion, not a model asked how it did.

WHAT THIS DOES NOT KNOW. It cannot tell whether a rubric measures the right
thing, whether a note's Kiswahili is correct, or whether a lesson is any good.
It catches absence, contradiction and ungroundedness — the failures that made
content unusable in this project — and it will happily score a dull, accurate
guide at 100. A high score means "nothing measurable is wrong", which is the
most a gate should ever claim.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-quality-score")

# What each signal is worth. Grounding and completeness dominate because
# ungrounded and incomplete are the two ways this pipeline has actually failed.
WEIGHTS: dict[str, float] = {
    "grounded": 0.20,        # read from the design at all
    "lesson_coverage": 0.25, # every funded lesson planned, none of them thin
    "citations": 0.20,       # every page:line reference resolves
    "rubrics": 0.15,         # rubrics read from KICD rather than derived
    "gate": 0.20,            # the local reviewer and approvers
}


@dataclass(slots=True)
class Component:
    name: str
    score: float          # 0-100
    weight: float
    measured: bool
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "score": round(self.score, 1),
                "weight": self.weight, "measured": self.measured,
                "evidence": self.evidence}


@dataclass(slots=True)
class ItemScore:
    kind: str = ""
    sub_strand: str = ""
    components: list[Component] = field(default_factory=list)

    @property
    def measured(self) -> list[Component]:
        return [c for c in self.components if c.measured]

    @property
    def score(self) -> float:
        """Weighted over what was actually measured.

        An unmeasured signal is excluded rather than scored zero. Scoring it
        zero would punish a station for not having citations to check; scoring
        it full would let an unchecked item pass as a verified one.
        """
        rated = self.measured
        if not rated:
            return 0.0
        total = sum(c.weight for c in rated)
        return round(sum(c.score * c.weight for c in rated) / total, 1)

    @property
    def confidence(self) -> float:
        """How much of the scoring scheme this item could be judged against.

        An item scored on one signal out of five is not a 100, it is a 100 with
        almost nothing behind it — and an auto-run must be able to tell those
        apart before it decides to keep going.
        """
        possible = sum(WEIGHTS.values())
        return round(sum(c.weight for c in self.measured) / possible, 2) if possible else 0.0

    @property
    def weakest(self) -> str:
        rated = self.measured
        return min(rated, key=lambda c: c.score).name if rated else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "sub_strand": self.sub_strand,
            "score": self.score, "confidence": self.confidence,
            "weakest": self.weakest,
            "components": [c.to_dict() for c in self.components],
        }


def _pct(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, number))


def score(result: dict[str, Any], kind: str = "") -> ItemScore:
    """Score one station's result from what its own validators reported."""
    out = ItemScore(kind=kind)
    if not isinstance(result, dict):
        return out

    def add(name: str, value: float | None, evidence: str) -> None:
        out.components.append(Component(
            name=name, score=value if value is not None else 0.0,
            weight=WEIGHTS.get(name, 0.0), measured=value is not None,
            evidence=evidence,
        ))

    # ── grounded in the design at all ───────────────────────────────────────
    chars = result.get("source_material_length")
    if "grounded" in result or chars is not None:
        grounded = bool(result.get("grounded")) or bool(chars)
        add("grounded", 100.0 if grounded else 0.0,
            f"{int(chars or 0):,} characters of design read"
            if grounded else "generated without the design")
    else:
        add("grounded", None, "not reported by this station")

    # ── every funded lesson planned, and none of them too thin ──────────────
    coverage = result.get("lesson_coverage")
    if isinstance(coverage, dict) and coverage.get("modules_required"):
        pct = _pct(coverage.get("percentage"))
        thin = len(coverage.get("thin_modules") or [])
        add("lesson_coverage", pct,
            f"{coverage.get('modules_found')} of {coverage.get('modules_required')} "
            f"{coverage.get('unit') or 'lessons'} planned"
            + (f", {thin} too thin to teach from" if thin else ""))
    else:
        add("lesson_coverage", None, "this station does not plan lessons")

    # ── citations that resolve against the document ─────────────────────────
    citations = result.get("citations")
    if isinstance(citations, dict) and citations.get("total"):
        add("citations", _pct(citations.get("percentage")),
            f"{citations.get('verified')} of {citations.get('total')} "
            f"page references resolve")
    else:
        add("citations", None, "nothing cited")

    # ── rubrics read from KICD rather than derived from outcomes ────────────
    subs = result.get("sub_strands")
    if isinstance(subs, list) and subs:
        from_design = sum(
            1 for s in subs
            if isinstance(s, dict) and any(
                (r or {}).get("rubric_source") == "design"
                for r in (s.get("assessment_rubrics") or [])
                if isinstance(r, dict)
            )
        )
        add("rubrics", round(from_design / len(subs) * 100, 1),
            f"{from_design} of {len(subs)} sub-strands carry a rubric read from "
            f"the design rather than written from their outcomes")
    else:
        add("rubrics", None, "no sub-strands in this result")

    # ── the local reviewer and both approvers ───────────────────────────────
    gate = result.get("quality_gate")
    cycles = result.get("review_cycles")
    if isinstance(cycles, dict) and cycles.get("cycles_run"):
        add("gate", _pct(cycles.get("best_score")),
            f"best of {cycles.get('cycles_run')} review cycle(s); "
            f"{'passed' if cycles.get('final_passed') else 'did not pass'}")
    elif isinstance(gate, dict) and gate.get("overall_score") is not None:
        add("gate", _pct(gate.get("overall_score")),
            f"{'passed' if gate.get('passed') else 'needs revision'}")
    else:
        add("gate", None, "no gate ran")

    return out


@dataclass(slots=True)
class RunningAverage:
    """The rolling picture an auto-run decides on."""

    scores: list[float] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)

    def add(self, item: ItemScore) -> None:
        self.scores.append(item.score)
        self.confidences.append(item.confidence)

    @property
    def count(self) -> int:
        return len(self.scores)

    @property
    def average(self) -> float:
        return round(sum(self.scores) / len(self.scores), 1) if self.scores else 0.0

    @property
    def mean_confidence(self) -> float:
        return (round(sum(self.confidences) / len(self.confidences), 2)
                if self.confidences else 0.0)

    def recent(self, window: int) -> float:
        tail = self.scores[-window:]
        return round(sum(tail) / len(tail), 1) if tail else 0.0
