from __future__ import annotations

import logging
from datetime import date
from typing import Any

from ..infra.db import execute, fetch_one, to_json
from ..services.notifications import notification_service

logger = logging.getLogger("cbc-targets")


class TargetService:
    def get_or_create_daily_target(self, target_date: date | None = None) -> dict[str, Any]:
        today = target_date or date.today()
        row = fetch_one(
            "SELECT * FROM generation_targets WHERE target_date = :tdate",
            {"tdate": today},
        )

        if not row:
            execute(
                """
                INSERT INTO generation_targets (target_date, target_count, completed_count, approved_count, rejected_count, grade_breakdown)
                VALUES (:tdate, 100, 0, 0, 0, '{}'::jsonb)
                ON CONFLICT (target_date) DO NOTHING
                """,
                {"tdate": today},
            )
            row = fetch_one(
                "SELECT * FROM generation_targets WHERE target_date = :tdate",
                {"tdate": today},
            )

        return row or {"target_date": str(today), "target_count": 100, "completed_count": 0, "approved_count": 0, "rejected_count": 0}

    def configure_target(self, target_date: date, target_count: int, grade_breakdown: dict[str, int] | None = None) -> dict[str, Any]:
        execute(
            """
            INSERT INTO generation_targets (target_date, target_count, grade_breakdown, updated_at)
            VALUES (:tdate, :tcount, CAST(:breakdown AS jsonb), NOW())
            ON CONFLICT (target_date) DO UPDATE SET
                target_count = EXCLUDED.target_count,
                grade_breakdown = EXCLUDED.grade_breakdown,
                updated_at = NOW()
            """,
            {
                "tdate": target_date,
                "tcount": target_count,
                "breakdown": to_json(grade_breakdown or {}),
            },
        )
        return self.get_or_create_daily_target(target_date)

    def record_generation(self, grade: str, is_approved: bool = True) -> None:
        today = date.today()
        target = self.get_or_create_daily_target(today)

        completed = target.get("completed_count", 0) + 1
        approved = target.get("approved_count", 0) + (1 if is_approved else 0)
        rejected = target.get("rejected_count", 0) + (0 if is_approved else 1)

        breakdown = target.get("grade_breakdown") or {}
        if isinstance(breakdown, str):
            import json

            try:
                breakdown = json.loads(breakdown)
            except Exception:  # noqa: BLE001
                breakdown = {}

        breakdown[grade] = breakdown.get(grade, 0) + 1

        execute(
            """
            UPDATE generation_targets
            SET completed_count = :completed,
                approved_count = :approved,
                rejected_count = :rejected,
                grade_breakdown = CAST(:breakdown AS jsonb),
                updated_at = NOW()
            WHERE target_date = :tdate
            """,
            {
                "completed": completed,
                "approved": approved,
                "rejected": rejected,
                "breakdown": to_json(breakdown),
                "tdate": today,
            },
        )

        self._check_and_emit_milestones(today, completed, target.get("target_count", 100), approved, breakdown)

    def _check_and_emit_milestones(
        self,
        today: date,
        completed: int,
        target: int,
        approved: int,
        breakdown: dict[str, Any],
    ) -> None:
        if target <= 0:
            return

        percentage = (completed / target) * 100.0
        milestones = [
            ("25%", 25.0),
            ("50%", 50.0),
            ("75%", 75.0),
            ("100%", 100.0),
        ]

        for tier, threshold in milestones:
            if percentage >= threshold:
                existing = fetch_one(
                    "SELECT id FROM milestone_events WHERE target_date = :tdate AND tier = :tier",
                    {"tdate": today, "tier": tier},
                )
                if not existing:
                    event_data = {
                        "date": str(today),
                        "milestone_tier": tier,
                        "target_count": target,
                        "completed_count": completed,
                        "approved_count": approved,
                        "grade_breakdown": breakdown,
                    }
                    execute(
                        """
                        INSERT INTO milestone_events (target_date, tier, event_data, sent_at)
                        VALUES (:tdate, :tier, CAST(:event_data AS jsonb), NOW())
                        ON CONFLICT (target_date, tier) DO NOTHING
                        """,
                        {
                            "tdate": today,
                            "tier": tier,
                            "event_data": to_json(event_data),
                        },
                    )
                    notification_service.send_milestone_email(event_data)


target_service = TargetService()
