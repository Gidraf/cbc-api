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
    # A boolean precondition — was the design read at all. Worth less than it
    # looks, because `citations` already measures whether it was actually USED,
    # and an ungrounded run fails that far more informatively.
    "grounded": 0.12,
    # Coverage counts lessons; `distinct` checks they are different lessons.
    # It used to carry both jobs and did the second one badly: a guide that
    # plans seven lessons by copying one of them four times scores 100 here,
    # because each copy is a full-length lesson. The weight it gave up went to
    # `distinct`; the rest of the rebalance came from `grounded` and `rubrics`,
    # so that seven thin lessons still score below the auto-run floor.
    "lesson_coverage": 0.20, # every funded lesson planned, none of them thin
    "citations": 0.14,       # every page:line reference resolves
    "rubrics": 0.08,         # rubrics read from KICD rather than derived
    "gate": 0.10,            # the local reviewer and approvers
    # Invented claims. Weighted like the gate because a fabricated scripture
    # reference in a religious education guide is not a small defect, and it is
    # the one failure a reader cannot detect by reading.
    "no_invention": 0.14,
    # Lessons that are copies of each other — the half of coverage that
    # counting could never do. A guide that plans seven lessons and teaches
    # four is 40% short of what the design funds, and unlike a thin lesson a
    # duplicated one clears every length check there is.
    "distinct": 0.12,
    # The guide disagreeing with itself: an slo_map naming lessons that do not
    # carry those outcomes, a learning experience the design never suggested.
    # Cheap to check and impossible to argue with, because both halves are the
    # guide's own words.
    "consistent": 0.10,
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

    # ── claims the design does not support ──────────────────────────────────
    fabrication = result.get("fabrication")
    if isinstance(fabrication, dict) and fabrication.get("checked_chars"):
        findings = fabrication.get("findings") or []
        add("no_invention", _pct(fabrication.get("score")),
            "nothing invented" if not findings else
            f"{len(findings)} invented claim(s): "
            + "; ".join(str(f.get("kind")) for f in findings[:3]))
    else:
        add("no_invention", None, "not checked for this station")

    # ── lessons that are copies of each other ───────────────────────────────
    repetition = result.get("repetition")
    if isinstance(repetition, dict) and repetition.get("checked"):
        findings = repetition.get("findings") or []
        add("distinct", _pct(repetition.get("score")),
            "no lesson repeats another" if not findings else
            f"{len(findings)} repetition(s): {findings[0]}")
    else:
        add("distinct", None, "no lessons to compare")

    # ── a guide that contradicts itself ─────────────────────────────────────
    integrity = result.get("integrity")
    if isinstance(integrity, dict) and integrity.get("checked"):
        findings = integrity.get("findings") or []
        add("consistent", _pct(integrity.get("score")),
            "the guide agrees with itself" if not findings else
            f"{len(findings)} contradiction(s): {findings[0]}")
    else:
        add("consistent", None, "not checked for this station")

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
