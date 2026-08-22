from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..infra.db import fetch_all, fetch_one


@dataclass(slots=True)
class PipelineMetrics:
    total_generations: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    stage_latencies: dict[str, list[float]] = field(default_factory=dict)
    diagram_dedup_hits: int = 0
    diagram_dedup_misses: int = 0


class MetricsService:
    def __init__(self) -> None:
        self._in_memory = PipelineMetrics()

    def record_stage_latency(self, stage: str, latency_ms: float) -> None:
        if stage not in self._in_memory.stage_latencies:
            self._in_memory.stage_latencies[stage] = []
        self._in_memory.stage_latencies[stage].append(latency_ms)
        # Keep last 100 entries per stage
        if len(self._in_memory.stage_latencies[stage]) > 100:
            self._in_memory.stage_latencies[stage].pop(0)

    def record_diagram_dedup(self, reused: bool) -> None:
        if reused:
            self._in_memory.diagram_dedup_hits += 1
        else:
            self._in_memory.diagram_dedup_misses += 1

    def get_system_metrics(self) -> dict[str, Any]:
        # Fetch run counts from DB
        runs_summary = fetch_one(
            """
            SELECT 
                COUNT(*) as total_runs,
                COUNT(*) FILTER (WHERE workflow_state = 'production_ready') as published_count,
                COUNT(*) FILTER (WHERE workflow_state = 'rejected') as rejected_count,
                COUNT(*) FILTER (WHERE workflow_state LIKE '%queue%') as in_progress_count
            FROM pipeline_runs
            """
        ) or {}

        diagrams_count = fetch_one("SELECT COUNT(*) as total FROM diagram_registry") or {"total": 0}
        questions_count = fetch_one("SELECT COUNT(*) as total FROM question_dna") or {"total": 0}

        avg_latencies = {}
        for stage, lat_list in self._in_memory.stage_latencies.items():
            if lat_list:
                avg_latencies[stage] = round(sum(lat_list) / len(lat_list), 2)

        total_dedup_checks = self._in_memory.diagram_dedup_hits + self._in_memory.diagram_dedup_misses
        hit_ratio = (
            round((self._in_memory.diagram_dedup_hits / total_dedup_checks) * 100.0, 2)
            if total_dedup_checks > 0
            else 0.0
        )

        return {
            "pipeline_runs": {
                "total": runs_summary.get("total_runs", 0),
                "published": runs_summary.get("published_count", 0),
                "rejected": runs_summary.get("rejected_count", 0),
                "in_progress": runs_summary.get("in_progress_count", 0),
            },
            "catalog": {
                "diagrams_registered": diagrams_count.get("total", 0),
                "questions_in_dna_bank": questions_count.get("total", 0),
            },
            "performance": {
                "avg_stage_latencies_ms": avg_latencies,
                "diagram_dedup_hit_ratio_percent": hit_ratio,
            },
            "timestamp": time.time(),
        }


metrics_service = MetricsService()
