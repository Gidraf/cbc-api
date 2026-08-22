from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import PipelineStage
from ..errors import raise_api_error
from ..infra.db import execute, fetch_one, to_json
from ..models import GenerateRequest, PipelineResult, Provenance, StageRunResult, now_iso
from ..services.diagram_dedup import diagram_deduplicator
from ..services.langfuse_context import langfuse_context_service
from ..services.llm_client import llm_client
from ..services.metrics import metrics_service
from ..services.provider_router import ProviderRouter
from ..services.question_dna import question_dna_service
from ..services.targets import target_service
from ..services.validation import validate_grade_dataset, validate_question_batch


class PipelineService:
    def __init__(self, router: ProviderRouter) -> None:
        self.router = router

    def run(self, request: GenerateRequest) -> PipelineResult:
        start_time = time.time()
        grade_slug = validate_grade_dataset(request.curriculum.grade)
        subject = request.curriculum.subject
        idempotency_key = request.controls.idempotency_key

        # 1. Idempotency Cache Check
        if idempotency_key:
            cached = fetch_one(
                "SELECT result FROM idempotency_cache WHERE idempotency_key = :ikey AND expires_at > NOW()",
                {"ikey": idempotency_key},
            )
            if cached and cached.get("result"):
                return PipelineResult.model_validate(cached["result"])

        run_id = f"run_{request.request_id}"
        stage_runs: list[StageRunResult] = []

        # 2. Notes Generation Stage
        notes_stage = self._run_stage(
            PipelineStage.NOTES_GENERATION.value,
            request,
            lambda req, resolved: self._generate_notes(req, resolved, grade_slug, subject),
        )
        stage_runs.append(notes_stage)

        # 3. Diagram Generation Stage (with Vector Deduplication & Accessibility)
        diagram_stage = self._run_stage(
            PipelineStage.DIAGRAM_GENERATION.value,
            request,
            lambda req, resolved: self._generate_diagrams(req, resolved, grade_slug, subject, notes_stage.output),
        )
        stage_runs.append(diagram_stage)

        # 4. Activity Generation Stage
        activity_stage = self._run_stage(
            PipelineStage.ACTIVITY_GENERATION.value,
            request,
            lambda req, resolved: self._generate_activities(req, resolved, grade_slug, subject, notes_stage.output),
        )
        stage_runs.append(activity_stage)

        # 5. Question Generation Stage
        question_stage = self._run_stage(
            PipelineStage.QUESTION_GENERATION.value,
            request,
            lambda req, resolved: self._generate_questions(
                req, resolved, grade_slug, subject, notes_stage.output, diagram_stage.output, activity_stage.output
            ),
        )
        validate_question_batch(question_stage.output.get("questions", []))
        stage_runs.append(question_stage)

        # 6. Reviewer Panel Quality Audit
        review_stage = self._run_stage(
            PipelineStage.REVIEWER_PANEL.value,
            request,
            lambda req, resolved: self._run_reviewer_panel(req, resolved, grade_slug, subject, question_stage.output),
        )
        stage_runs.append(review_stage)

        # 7. Quality Gate Decision
        review_audit = review_stage.output
        is_approved = review_audit.get("status") == "approved"
        workflow_status = "published" if is_approved else "needs_human_review"

        # 8. Persist Individual Question DNA Lineage
        for q in question_stage.output.get("questions", []):
            qid = q.get("question_id", f"Q-{grade_slug}-{request.curriculum.slo_id}")
            question_dna_service.save_question(
                question_id=qid,
                universal_id=q.get("universal_id", request.curriculum.slo_id),
                curriculum_link=request.curriculum.model_dump(),
                pedagogical_dna=q.get("pedagogical_dna", {}),
                content=q.get("content", {}),
                provenance=question_stage.provenance.model_dump(),
                review_audit=review_audit,
                status="approved" if is_approved else "needs_review",
            )

        # 9. Assemble Sub-strand Resource Bundle
        bundle_id = f"res_{request.request_id[-12:].lower()}"
        bundle = {
            "bundle_id": bundle_id,
            "curriculum": request.curriculum.model_dump(),
            "notes": notes_stage.output,
            "diagrams": [diagram_stage.output],
            "activities": [activity_stage.output],
            "questions": question_stage.output.get("questions", []),
            "review_audit": review_audit,
            "status": workflow_status,
            "updated_at": now_iso(),
        }

        # Persist Sub-strand Resource Bundle to Database
        execute(
            """
            INSERT INTO substrand_resources (bundle_id, curriculum, notes, diagrams, activities, questions, review_audit, status, updated_at)
            VALUES (
                :bundle_id, CAST(:curriculum AS jsonb), CAST(:notes AS jsonb),
                CAST(:diagrams AS jsonb), CAST(:activities AS jsonb),
                CAST(:questions AS jsonb), CAST(:review_audit AS jsonb),
                :status, NOW()
            )
            ON CONFLICT (bundle_id) DO UPDATE SET
                curriculum = EXCLUDED.curriculum,
                notes = EXCLUDED.notes,
                diagrams = EXCLUDED.diagrams,
                activities = EXCLUDED.activities,
                questions = EXCLUDED.questions,
                review_audit = EXCLUDED.review_audit,
                status = EXCLUDED.status,
                updated_at = NOW()
            """,
            {
                "bundle_id": bundle_id,
                "curriculum": to_json(request.curriculum.model_dump()),
                "notes": to_json(notes_stage.output),
                "diagrams": to_json([diagram_stage.output]),
                "activities": to_json([activity_stage.output]),
                "questions": to_json(question_stage.output.get("questions", [])),
                "review_audit": to_json(review_audit),
                "status": workflow_status,
            },
        )

        # 10. Record Target Metrics
        target_service.record_generation(grade_slug, is_approved=is_approved)

        result = PipelineResult(run_id=run_id, stage_runs=stage_runs, published_bundle=bundle)

        # 11. Store in Idempotency Cache
        if idempotency_key:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
            execute(
                """
                INSERT INTO idempotency_cache (idempotency_key, status, result, expires_at)
                VALUES (:ikey, 'completed', CAST(:result AS jsonb), :expires)
                ON CONFLICT (idempotency_key) DO UPDATE SET
                    result = EXCLUDED.result,
                    expires_at = EXCLUDED.expires_at
                """,
                {
                    "ikey": idempotency_key,
                    "result": to_json(result.model_dump()),
                    "expires": expires_at,
                },
            )

        return result

    def _run_stage(self, stage: str, request: GenerateRequest, fn):
        start = time.time()
        resolved = self.router.resolve_for_stage(stage)
        output = fn(request, resolved)
        latency_ms = (time.time() - start) * 1000
        metrics_service.record_stage_latency(stage, latency_ms)

        provenance = Provenance(
            langfuse_prompt_name=stage,
            langfuse_prompt_version="v2.1",
            langfuse_prompt_label=request.controls.environment,
            prompt_hash_sha256=self.router.prompt_hash(stage, output),
            model_provider=resolved.provider,
            model_name=resolved.model,
            model_revision="2026-08",
            temperature=0.2,
            top_p=0.9,
            pipeline_stage=stage,
            resolved_model_provider=resolved.provider,
            resolved_model_name=resolved.model,
            resolved_base_url=resolved.resolved_base_url,
            credential_ref_id=resolved.credential_ref_id,
            created_at=now_iso(),
        )
        return StageRunResult(pipeline_stage=stage, output=output, provenance=provenance)

    def _generate_notes(self, request: GenerateRequest, resolved, grade_slug: str, subject: str) -> dict[str, Any]:
        context = langfuse_context_service.assemble_agent_context(
            agent_name="note-generator",
            grade_slug=grade_slug,
            subject=subject,
            template_vars={
                "level": request.curriculum.level,
                "strand": request.curriculum.strand,
                "sub_strand": request.curriculum.sub_strand,
                "slo_id": request.curriculum.slo_id,
            },
        )
        return llm_client.generate(resolved, context.messages, temperature=0.2)

    def _generate_diagrams(
        self,
        request: GenerateRequest,
        resolved,
        grade_slug: str,
        subject: str,
        notes_output: dict,
    ) -> dict[str, Any]:
        concept_name = f"{request.curriculum.sub_strand} visual model"
        context = langfuse_context_service.assemble_agent_context(
            agent_name="diagram-generator",
            grade_slug=grade_slug,
            subject=subject,
            template_vars={
                "concept": concept_name,
                "notes_title": notes_output.get("title", request.curriculum.sub_strand),
            },
        )
        raw_diagram = llm_client.generate(resolved, context.messages, temperature=0.1)

        svg_markup = raw_diagram.get("diagram_svg", "<svg xmlns='http://www.w3.org/2000/svg'></svg>")
        accessibility = raw_diagram.get("accessibility", {})

        # Execute SHA-256 Deduplication & MinIO Upload
        dedup_result = diagram_deduplicator.deduplicate_and_store(
            svg_str=svg_markup,
            diagram_title=raw_diagram.get("diagram_title", concept_name),
            alt_text=accessibility.get("alt_text", ""),
            tactile_description=accessibility.get("tactile_description", ""),
            metadata={"grade": grade_slug, "subject": subject, "strand": request.curriculum.strand},
        )

        metrics_service.record_diagram_dedup(reused=(dedup_result.dedup_status == "reused"))

        return {
            "diagram_id": dedup_result.diagram_id,
            "diagram_title": dedup_result.diagram_title,
            "diagram_svg": dedup_result.diagram_svg,
            "diagram_hash": dedup_result.diagram_hash,
            "storage_url": dedup_result.storage_url,
            "dedup_status": dedup_result.dedup_status,
            "accessibility": {
                "alt_text": dedup_result.alt_text,
                "tactile_description": dedup_result.tactile_description,
            },
        }

    def _generate_activities(
        self,
        request: GenerateRequest,
        resolved,
        grade_slug: str,
        subject: str,
        notes_output: dict,
    ) -> dict[str, Any]:
        context = langfuse_context_service.assemble_agent_context(
            agent_name="activity-generator",
            grade_slug=grade_slug,
            subject=subject,
            template_vars={
                "level": request.curriculum.level,
                "strand": request.curriculum.strand,
                "sub_strand": request.curriculum.sub_strand,
                "slo_id": request.curriculum.slo_id,
                "notes_title": notes_output.get("title", ""),
            },
        )
        return llm_client.generate(resolved, context.messages, temperature=0.3)

    def _generate_questions(
        self,
        request: GenerateRequest,
        resolved,
        grade_slug: str,
        subject: str,
        notes_output: dict,
        diagrams_output: dict,
        activities_output: dict,
    ) -> dict[str, Any]:
        _ = activities_output
        context = langfuse_context_service.assemble_agent_context(
            agent_name="question-generator",
            grade_slug=grade_slug,
            subject=subject,
            template_vars={
                "level": request.curriculum.level,
                "subject_code": request.curriculum.subject_code,
                "strand": request.curriculum.strand,
                "sub_strand": request.curriculum.sub_strand,
                "slo_id": request.curriculum.slo_id,
                "notes_title": notes_output.get("title", ""),
                "diagram_id": diagrams_output.get("diagram_id", ""),
                "difficulty": 0.5,
            },
        )
        return llm_client.generate(resolved, context.messages, temperature=0.2)

    def _run_reviewer_panel(
        self,
        request: GenerateRequest,
        resolved,
        grade_slug: str,
        subject: str,
        questions_output: dict,
    ) -> dict[str, Any]:
        context = langfuse_context_service.assemble_agent_context(
            agent_name="reviewer-panel",
            grade_slug=grade_slug,
            subject=subject,
            template_vars={
                "content_to_review": questions_output,
                "curriculum_reference": request.curriculum.model_dump(),
            },
        )
        return llm_client.generate(resolved, context.messages, temperature=0.1)
