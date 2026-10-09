"""An item's level and difficulty, worked out from the item itself.

The writer's own labels were not a measurement. All seventeen of qwen3:14b's
first items carried difficulty 0.65 — the batch's requested level, copied on
to every item — and about half claimed a Bloom level above what they asked:
"which of these is a simple sentence?" filed as Application. So the platform
reads the level off the task and builds the difficulty from what the item
makes a learner do; the writer's claim is kept beside it for comparison.

    level       the highest command word in the stem and its parts, on the
                platform's ladder (recall … create). An item with no verb —
                "Which of the following …" — is recall for a selected
                response and understanding for a written one.
    difficulty  0–1: a base from the level, raised for each further part,
                each walk-through step past two, a figure to read, marks past
                two, and each arithmetic operation past one.

It is a model of difficulty, not a measured facility. Facility comes from
learners' answers (`item_discrimination` waits on field data); until then
this is consistent, explained and the same for every writer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BLOOM = {1: "Recall", 2: "Understanding", 3: "Application", 4: "Analysis", 5: "Evaluation", 6: "Creation"}
_BASE = {1: 0.20, 2: 0.35, 3: 0.50, 4: 0.62, 5: 0.74, 6: 0.84}
_SELECTED = ("multiple_choice", "mcq", "true_false", "assertion_reason", "matching")
_SUM = __import__("re").compile(r"\d\s*[-+×x*/÷=]\s*\(?-?\d")


@dataclass
class Measured:
    rank: int
    bloom: str
    difficulty: float
    basis: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"rank": self.rank, "bloom": self.bloom, "difficulty": self.difficulty, "basis": self.basis}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def measure(item: dict[str, Any]) -> Measured:
    """The level and difficulty of one item, with the reasons."""
    from . import command_words

    parts = [p for p in (item.get("structured_parts") or []) if isinstance(p, dict)]
    task = " ".join([_text(item.get("question_text"))] + [_text(p.get("sub_question")) for p in parts])
    rung = command_words.rung_of(task)
    q_type = str(item.get("question_type") or "").lower()
    if rung is not None:
        rank, source = rung.rank, f"command word ({rung.name})"
    else:
        rank = 1 if q_type in _SELECTED else 2
        source = "no command word: " + ("a selected response is recall" if rank == 1
                                        else "a written answer is understanding")

    steps = [w for w in (item.get("worked_solution") or [])
             if (isinstance(w, dict) and _text(w.get("step"))) or (isinstance(w, str) and w.strip())]
    # Working a calculation is applying a procedure, whatever the stem's verb:
    # "what is the mass number?" over 14 protons and 16 neutrons has no verb
    # and is still 14 + 16.
    calculates = (q_type == "quantitative_calculation" or bool(_text(item.get("expression")))
                  or any(_SUM.search(_text(w.get("step") if isinstance(w, dict) else w)) for w in steps))
    if calculates and rank < 3:
        rank, source = 3, "a calculation is application"
    has_figure = bool(item.get("figure") or item.get("diagram") or q_type == "diagram_based")
    try:
        marks = int(float((item.get("pedagogy") or {}).get("max_marks") or item.get("max_marks") or 0))
    except (TypeError, ValueError):
        marks = 0
    operations = _operations(item)

    lift = {
        "parts": min(0.12, 0.04 * max(0, len(parts) - 1)),
        "walk_through": min(0.12, 0.03 * max(0, len(steps) - 2)),
        "figure": 0.05 if has_figure else 0.0,
        "marks": min(0.08, 0.02 * max(0, marks - 2)),
        "arithmetic": min(0.09, 0.03 * max(0, operations - 1)),
    }
    difficulty = round(min(0.95, max(0.1, _BASE[rank] + sum(lift.values()))), 2)
    basis = {"level": source, "parts": len(parts), "walk_through_steps": len(steps),
             "figure": has_figure, "marks": marks, "operations": operations,
             "lift": {k: round(v, 2) for k, v in lift.items() if v}}
    return Measured(rank=rank, bloom=BLOOM[rank], difficulty=difficulty, basis=basis)


def _operations(item: dict[str, Any]) -> int:
    """Arithmetic operations in the item's calculation, where it has one."""
    try:
        from . import task_demand

        text = _text(item.get("expression")) or _text(item.get("question_text"))
        demand = task_demand.measure_item({"statement": text})
        return int(max(demand.operations, getattr(demand, "total_operations", 0) or 0))
    except Exception:  # noqa: BLE001
        return 0
