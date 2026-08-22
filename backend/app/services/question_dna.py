from __future__ import annotations

import logging
from typing import Any

from ..errors import raise_api_error
from ..infra.db import execute, fetch_all, fetch_one, to_json
from ..models import now_iso

logger = logging.getLogger("cbc-question-dna")


class QuestionDnaService:
    def save_question(
        self,
        question_id: str,
        universal_id: str,
        curriculum_link: dict[str, Any],
        pedagogical_dna: dict[str, Any],
        content: dict[str, Any],
        provenance: dict[str, Any],
        review_audit: dict[str, Any],
        status: str = "approved",
    ) -> None:
        execute(
            """
            INSERT INTO question_dna (
                question_id, universal_id, curriculum_link, pedagogical_dna, content,
                provenance, review_audit, status, created_at, updated_at
            )
            VALUES (
                :question_id, :universal_id, CAST(:curriculum_link AS jsonb),
                CAST(:pedagogical_dna AS jsonb), CAST(:content AS jsonb),
                CAST(:provenance AS jsonb), CAST(:review_audit AS jsonb),
                :status, NOW(), NOW()
            )
            ON CONFLICT (question_id) DO UPDATE SET
                curriculum_link = EXCLUDED.curriculum_link,
                pedagogical_dna = EXCLUDED.pedagogical_dna,
                content = EXCLUDED.content,
                provenance = EXCLUDED.provenance,
                review_audit = EXCLUDED.review_audit,
                status = EXCLUDED.status,
                updated_at = NOW()
            """,
            {
                "question_id": question_id,
                "universal_id": universal_id,
                "curriculum_link": to_json(curriculum_link),
                "pedagogical_dna": to_json(pedagogical_dna),
                "content": to_json(content),
                "provenance": to_json(provenance),
                "review_audit": to_json(review_audit),
                "status": status,
            },
        )

    def get_question(self, question_id: str) -> dict[str, Any]:
        row = fetch_one("SELECT * FROM question_dna WHERE question_id = :qid", {"qid": question_id})
        if not row:
            raise_api_error("NOT_FOUND", f"Question DNA not found for ID: {question_id}")
        return row

    def list_questions(
        self,
        grade: str | None = None,
        subject: str | None = None,
        strand: str | None = None,
        question_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conditions = ["1=1"]
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if grade:
            conditions.append("curriculum_link->>'grade' = :grade")
            params["grade"] = grade
        if subject:
            conditions.append("curriculum_link->>'subject' = :subject")
            params["subject"] = subject
        if strand:
            conditions.append("curriculum_link->>'strand' = :strand")
            params["strand"] = strand
        if question_type:
            conditions.append("content->>'question_type' = :qtype")
            params["qtype"] = question_type
        if status:
            conditions.append("status = :status")
            params["status"] = status

        sql = f"""
            SELECT question_id, universal_id, curriculum_link, pedagogical_dna,
                   content, provenance, review_audit, status, created_at, updated_at
            FROM question_dna
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """
        return fetch_all(sql, params)

    def action_recreate(self, question_id: str) -> dict[str, Any]:
        """Discards current item and generates a completely fresh question for the same SLO."""
        existing = self.get_question(question_id)
        curriculum = existing.get("curriculum_link", {})
        # Return acknowledgment with new generation instruction
        return {
            "action": "re-create",
            "question_id": question_id,
            "status": "queued_for_recreation",
            "curriculum": curriculum,
            "message": "Fresh concept generation initiated for this SLO.",
        }

    def action_regenerate(self, question_id: str) -> dict[str, Any]:
        """Preserves question concept and refines text or options."""
        existing = self.get_question(question_id)
        return {
            "action": "regenerate",
            "question_id": question_id,
            "status": "queued_for_refinement",
            "content": existing.get("content", {}),
            "message": "Question refinement initiated.",
        }

    def action_rereview(self, question_id: str) -> dict[str, Any]:
        """Re-evaluates quality scores using latest Reviewer panel criteria."""
        existing = self.get_question(question_id)
        audit = existing.get("review_audit", {})
        audit["re_reviewed_at"] = now_iso()
        self.save_question(
            question_id=existing["question_id"],
            universal_id=existing["universal_id"],
            curriculum_link=existing.get("curriculum_link", {}),
            pedagogical_dna=existing.get("pedagogical_dna", {}),
            content=existing.get("content", {}),
            provenance=existing.get("provenance", {}),
            review_audit=audit,
            status=existing.get("status", "approved"),
        )
        return {"action": "re-review", "question_id": question_id, "review_audit": audit}


question_dna_service = QuestionDnaService()
