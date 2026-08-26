from __future__ import annotations

import logging
from typing import Any

from ..errors import raise_api_error
from ..infra.db import execute, fetch_all, fetch_one, to_json
from ..models import now_iso
from .grade_order import grade_ordinal, normalize_grade
from .ids import mint_question_id, mint_universal_id, next_version_id

logger = logging.getLogger("cbc-question-dna")

# IDs minted by app.services.ids start with this prefix. Anything else arriving
# as a question_id is a model-supplied positional label ("Q1"), which must never
# become a primary key — every batch would collide with every other batch.
MINTED_PREFIX = "q-"


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
        version: int = 1,
        display_label: str = "",
    ) -> None:
        execute(
            """
            INSERT INTO question_dna (
                question_id, universal_id, curriculum_link, pedagogical_dna, content,
                provenance, review_audit, status, grade_ordinal, version, display_label,
                created_at, updated_at
            )
            VALUES (
                :question_id, :universal_id, CAST(:curriculum_link AS jsonb),
                CAST(:pedagogical_dna AS jsonb), CAST(:content AS jsonb),
                CAST(:provenance AS jsonb), CAST(:review_audit AS jsonb),
                :status, :grade_ordinal, :version, :display_label, NOW(), NOW()
            )
            ON CONFLICT (question_id) DO UPDATE SET
                curriculum_link = EXCLUDED.curriculum_link,
                pedagogical_dna = EXCLUDED.pedagogical_dna,
                content = EXCLUDED.content,
                provenance = EXCLUDED.provenance,
                review_audit = EXCLUDED.review_audit,
                status = EXCLUDED.status,
                grade_ordinal = EXCLUDED.grade_ordinal,
                version = EXCLUDED.version,
                display_label = EXCLUDED.display_label,
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
                "grade_ordinal": grade_ordinal(curriculum_link.get("grade")),
                "version": version,
                "display_label": display_label,
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
        sub_strand: str | None = None,
        question_type: str | None = None,
        status: str | None = None,
        slo_id: str | None = None,
        include_superseded: bool = False,
        limit: int = 50,
        offset: int = 0,
        order: str = "curriculum",
    ) -> list[dict[str, Any]]:
        """List questions, filtered in SQL and ordered low grade to high by default.

        ``order="curriculum"`` walks the CBC progression — PP1 first, Grade 12
        last — which is the order an exam builder and a printed paper both want.
        ``order="recent"`` is available for review queues.
        """
        conditions = ["1=1"]
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if grade:
            conditions.append("curriculum_link->>'grade' = :grade")
            params["grade"] = normalize_grade(grade)
        if subject:
            conditions.append("LOWER(curriculum_link->>'subject') = LOWER(:subject)")
            params["subject"] = subject.strip()
        if strand:
            conditions.append("LOWER(curriculum_link->>'strand') = LOWER(:strand)")
            params["strand"] = strand.strip()
        if sub_strand:
            conditions.append("LOWER(curriculum_link->>'sub_strand') LIKE LOWER(:sub_strand)")
            params["sub_strand"] = f"%{sub_strand.strip()}%"
        if slo_id:
            conditions.append("curriculum_link->>'slo_id' = :slo_id")
            params["slo_id"] = slo_id.strip()
        if question_type:
            conditions.append("content->>'question_type' = :qtype")
            params["qtype"] = question_type
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if not include_superseded:
            conditions.append("superseded_by IS NULL")

        if order == "recent":
            order_clause = "created_at DESC"
        else:
            order_clause = (
                "grade_ordinal ASC, "
                "curriculum_link->>'subject' ASC, "
                "curriculum_link->>'strand' ASC, "
                "curriculum_link->>'sub_strand' ASC, "
                "curriculum_link->>'slo_id' ASC, "
                "(pedagogical_dna->>'difficulty_index')::float ASC NULLS LAST, "
                "created_at ASC"
            )

        sql = f"""
            SELECT question_id, universal_id, display_label, version, curriculum_link,
                   pedagogical_dna, content, provenance, review_audit, status,
                   grade_ordinal, superseded_by, created_at, updated_at
            FROM question_dna
            WHERE {' AND '.join(conditions)}
            ORDER BY {order_clause}
            LIMIT :limit OFFSET :offset
        """
        return fetch_all(sql, params)

    def count_questions(self, **filters: Any) -> int:
        """Total matching rows, for pagination metadata."""
        rows = self.list_questions(limit=100000, offset=0, **filters)
        return len(rows)

    def action_recreate(self, question_id: str) -> dict[str, Any]:
        """Discards current item and generates a completely fresh question for the same SLO."""
        existing = self.get_question(question_id)
        return {
            "action": "re-create",
            "question_id": question_id,
            "status": "queued_for_recreation",
            "curriculum": existing.get("curriculum_link", {}),
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
        """Re-scores the item against the current metric set."""
        from .dna_scoring import score_question

        existing = self.get_question(question_id)
        content = existing.get("content", {}) or {}
        curriculum = existing.get("curriculum_link", {}) or {}

        scores = score_question(
            content,
            slo_text=str(curriculum.get("slo_text") or ""),
            grade_ordinal=grade_ordinal(curriculum.get("grade")),
        )

        audit = dict(existing.get("review_audit") or {})
        audit.update(
            {
                "re_reviewed_at": now_iso(),
                "scores": scores.values_only(),
                "score_detail": scores.detail(),
                "mean_score": scores.mean(),
                "weakest": scores.weakest(),
            }
        )

        execute(
            """
            UPDATE question_dna
            SET review_audit = CAST(:review_audit AS jsonb), updated_at = NOW()
            WHERE question_id = :qid
            """,
            {"qid": question_id, "review_audit": to_json(audit)},
        )
        return {"action": "re-review", "question_id": question_id, "review_audit": audit}

    def update_question(
        self,
        question_id: str,
        content: dict[str, Any],
        review_audit: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a question, versioning it if it has already been approved.

        An approved question may already have been printed onto a paper, so it is
        frozen: editing it mints ``…@v2`` and marks the original superseded. Draft
        questions are edited in place.
        """
        existing = self.get_question(question_id)
        audit = review_audit if review_audit is not None else dict(existing.get("review_audit") or {})
        audit["updated_at"] = now_iso()

        if existing.get("status") != "approved":
            execute(
                """
                UPDATE question_dna
                SET content = CAST(:content AS jsonb),
                    review_audit = CAST(:review_audit AS jsonb),
                    updated_at = NOW()
                WHERE question_id = :qid
                """,
                {"qid": question_id, "content": to_json(content), "review_audit": to_json(audit)},
            )
            return self.get_question(question_id)

        new_id, new_version = next_version_id(question_id)
        audit["supersedes"] = question_id
        self.save_question(
            question_id=new_id,
            universal_id=existing["universal_id"],
            curriculum_link=existing.get("curriculum_link", {}) or {},
            pedagogical_dna=existing.get("pedagogical_dna", {}) or {},
            content=content,
            provenance=existing.get("provenance", {}) or {},
            review_audit=audit,
            status="approved",
            version=new_version,
            display_label=existing.get("display_label", "") or "",
        )
        execute(
            "UPDATE question_dna SET superseded_by = :new_id, updated_at = NOW() WHERE question_id = :qid",
            {"new_id": new_id, "qid": question_id},
        )
        logger.info("Question %s was approved; edit created version %s", question_id, new_id)
        return self.get_question(new_id)

    def delete_question(self, question_id: str) -> dict[str, Any]:
        execute("DELETE FROM question_dna WHERE question_id = :qid", {"qid": question_id})
        return {"deleted": True, "question_id": question_id}

    def save_batch_questions(
        self,
        grade: str,
        subject: str,
        strand: str,
        sub_strand: str,
        questions: list[dict[str, Any]],
        status: str = "approved",
        gate_result: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Persist a reviewed batch with real audit data and unique IDs."""
        from .artifact_dna import artifact_dna_service
        from .dna_scoring import score_question

        grade_slug = normalize_grade(grade)
        saved: list[dict[str, Any]] = []

        for item in questions:
            curriculum_in = item.get("curriculum") or {}
            pedagogy_in = item.get("pedagogy") or {}
            slo = str(curriculum_in.get("slo_id") or item.get("target_slo") or "").strip()

            # Trust an ID only if this service minted it. Anything else is a
            # positional label from the model and would collide across batches.
            incoming_id = str(item.get("question_id") or "")
            question_id = (
                incoming_id
                if incoming_id.startswith(MINTED_PREFIX)
                else mint_question_id(grade_slug, subject, sub_strand, slo)
            )

            universal_id = str(item.get("universal_id") or "") or mint_universal_id(
                grade_slug, subject, strand, sub_strand, slo
            )

            curriculum_link = {
                "grade": grade_slug,
                "grade_ordinal": grade_ordinal(grade_slug),
                "level": curriculum_in.get("level", ""),
                "subject": subject,
                "subject_code": curriculum_in.get("subject_code", ""),
                "strand": strand,
                "sub_strand": sub_strand,
                "slo_id": slo,
                "slo_text": curriculum_in.get("slo_text", ""),
            }

            pedagogical_dna = {
                "bloom_level": pedagogy_in.get("bloom_level", item.get("bloom_level", "Application")),
                "difficulty_index": pedagogy_in.get("difficulty_index", item.get("difficulty_index", 0.5)),
                "question_type": item.get("question_type", "multiple_choice"),
                "family": item.get("family", ""),
                "max_marks": pedagogy_in.get("max_marks", item.get("max_marks", 1)),
                "estimated_time_mins": pedagogy_in.get("estimated_time_mins", 2),
                "micro_concept": pedagogy_in.get("micro_concept", ""),
                "core_competency": pedagogy_in.get("core_competency", ""),
                "constitutional_value": pedagogy_in.get("constitutional_value", ""),
                "source_hour": pedagogy_in.get("source_hour"),
                "source_hour_title": pedagogy_in.get("source_hour_title", ""),
            }

            content = {
                "question_type": item.get("question_type", "multiple_choice"),
                "question_text": item.get("question_text", ""),
                "stimulus_context": item.get("stimulus_context", ""),
                "options": item.get("options"),
                "correct_answer": item.get("correct_answer"),
                "structured_parts": item.get("structured_parts"),
                "diagram": item.get("diagram"),
                "model_answer": item.get("model_answer", ""),
                "marking_scheme": item.get("marking_scheme", ""),
                "rubric": item.get("rubric") or item.get("marking_guide") or {},
            }

            provenance = {
                "source_citations": item.get("provenance_citation", ""),
                "parent_substrand": sub_strand,
                "generated_by": "questions_factory",
                "verified_at": now_iso(),
            }

            # The measured result, not an assertion. Previously this row was
            # hardcoded to quality_score 1.0 regardless of what the gate found.
            scores = score_question(
                content,
                slo_text=curriculum_link["slo_text"],
                grade_ordinal=grade_ordinal(grade_slug),
            )
            review_audit: dict[str, Any] = {
                "status": status,
                "scores": scores.values_only(),
                "score_detail": scores.detail(),
                "mean_score": scores.mean(),
                "weakest": scores.weakest(),
                "approved_at": now_iso(),
            }
            if gate_result:
                review_audit["quality_gate"] = {
                    "passed": gate_result.get("passed"),
                    "overall_score": gate_result.get("overall_score"),
                    "summary": gate_result.get("summary_message"),
                    "risk_flags": (gate_result.get("reviewer") or {}).get("risk_flags", []),
                }

            self.save_question(
                question_id=question_id,
                universal_id=universal_id,
                curriculum_link=curriculum_link,
                pedagogical_dna=pedagogical_dna,
                content=content,
                provenance=provenance,
                review_audit=review_audit,
                status=status,
                version=int(item.get("version") or 1),
                display_label=str(item.get("display_label") or ""),
            )

            dna_id = ""
            try:
                cert = artifact_dna_service.generate_question_dna(
                    question_id=question_id,
                    curriculum=curriculum_link,
                    question_item={
                        "universal_id": universal_id,
                        "content": content,
                        "pedagogical_dna": pedagogical_dna,
                        "rubric": content["rubric"],
                    },
                    provenance=provenance,
                )
                dna_id = cert.dna_id
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not mint DNA certificate for %s: %s", question_id, exc)

            saved.append(
                {
                    "question_id": question_id,
                    "universal_id": universal_id,
                    "display_label": item.get("display_label", ""),
                    "dna_id": dna_id,
                    "mean_score": scores.mean(),
                    "status": status,
                }
            )

        return saved


question_dna_service = QuestionDnaService()
