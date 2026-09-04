from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class SimulationStep:
    index: int
    duration_ms: int
    latex: str
    plain: str
    narration: str
    audio_url: str | None = None
    svg_highlight: str = ""
    animation_type: str = "reveal"

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "duration_ms": self.duration_ms,
            "latex": self.latex,
            "plain": self.plain,
            "narration": self.narration,
            "audio_url": self.audio_url,
            "svg_highlight": self.svg_highlight,
            "animation_type": self.animation_type,
        }


@dataclass(slots=True)
class SimulationTrack:
    simulation_id: str
    curriculum_link: dict[str, Any]
    title: str
    total_duration_ms: int
    source_type: str = "question_solution"
    steps: list[SimulationStep] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulation_id": self.simulation_id,
            "curriculum_link": self.curriculum_link,
            "title": self.title,
            "total_duration_ms": self.total_duration_ms,
            "source_type": self.source_type,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
        }
