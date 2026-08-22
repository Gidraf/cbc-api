from __future__ import annotations

from dataclasses import dataclass

from ..errors import raise_api_error
from ..models import now_iso


@dataclass(slots=True)
class DecisionResult:
    run_id: str
    state: str
    updated_at: str


class WorkflowService:
    def __init__(self, state) -> None:
        self.state = state

    def review_queue(self) -> list[dict]:
        items = []
        for run_id, entry in self.state.run_registry.items():
            if entry.get("workflow_state") == "reviewer_queue":
                items.append({"run_id": run_id, **entry})
        return items

    def human_review_queue(self) -> list[dict]:
        items = []
        for run_id, entry in self.state.run_registry.items():
            if entry.get("workflow_state") == "human_review_queue":
                items.append({"run_id": run_id, **entry})
        return items

    def production_ready(self) -> list[dict]:
        items = []
        for run_id, entry in self.state.run_registry.items():
            if entry.get("workflow_state") == "production_ready":
                items.append({"run_id": run_id, **entry})
        return items

    def review_decision(self, run_id: str, decision: str) -> DecisionResult:
        entry = self.state.run_registry.get(run_id)
        if not entry:
            raise_api_error("DATASET_ITEM_NOT_FOUND", f"Run not found: {run_id}")

        if decision == "approve_to_human_review":
            entry["workflow_state"] = "human_review_queue"
        elif decision == "return_for_regeneration":
            entry["workflow_state"] = "regeneration_queue"
        elif decision == "reject":
            entry["workflow_state"] = "rejected"
        else:
            raise_api_error("SCHEMA_VALIDATION_FAILED", f"Unknown review decision: {decision}")

        entry["updated_at"] = now_iso()
        return DecisionResult(run_id=run_id, state=entry["workflow_state"], updated_at=entry["updated_at"])

    def human_review_decision(self, run_id: str, decision: str) -> DecisionResult:
        entry = self.state.run_registry.get(run_id)
        if not entry:
            raise_api_error("DATASET_ITEM_NOT_FOUND", f"Run not found: {run_id}")

        if decision == "approve":
            entry["workflow_state"] = "production_ready"
        elif decision == "reject":
            entry["workflow_state"] = "rejected"
        else:
            raise_api_error("SCHEMA_VALIDATION_FAILED", f"Unknown human review decision: {decision}")

        entry["updated_at"] = now_iso()
        return DecisionResult(run_id=run_id, state=entry["workflow_state"], updated_at=entry["updated_at"])
