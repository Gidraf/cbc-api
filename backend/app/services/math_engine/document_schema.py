from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class DocumentBlock:
    block_type: str  # "heading" | "paragraph" | "formula" | "worked_example" | "diagram" | "question" | "answer_space"
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"block_type": self.block_type, "payload": self.payload}


@dataclass(slots=True)
class EducationalDocument:
    document_id: str
    title: str
    curriculum: dict[str, Any]
    blocks: list[DocumentBlock] = field(default_factory=list)
    audience: str = "student"  # "student" | "teacher"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "curriculum": self.curriculum,
            "blocks": [b.to_dict() for b in self.blocks],
            "audience": self.audience,
            "created_at": self.created_at,
        }
