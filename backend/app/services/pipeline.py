from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import PipelineStage
from ..errors import raise_api_error
from ..infra.db import execute, fetch_all, fetch_one, to_json
from ..models import GenerateRequest, PipelineResult, Provenance, StageRunResult, now_iso
from ..services.artifact_dna import artifact_dna_service
from ..services.cost_tracker import CostResult, calculate_cost, format_cost_summary, persist_stage_cost
from ..services.diagram_dedup import diagram_deduplicator
from ..services.faith_scope import prompt_block as faith_prompt_block
from ..services import notation, prompt_fragments
from ..services.level_register import register_block
from ..services.langfuse_context import langfuse_context_service
from ..services.llm_client import LlmResponse, llm_client
from ..services.metrics import metrics_service
from ..services.provider_router import ProviderRouter, ResolvedModelConfig
from ..services.question_dna import question_dna_service
from ..services.targets import target_service
from ..services.validation import validate_grade_dataset, validate_question_batch

logger = logging.getLogger("cbc-pipeline")


class PipelineService:
    def __init__(self, router: ProviderRouter) -> None:
        self.router = router

    def run_full_pipeline(self, request: GenerateRequest) -> PipelineResult:
        """Executes the full pipeline:
        Dataset Blueprint -> Notes -> SVG Diagrams -> Experiments & Activities (Safety Checked) ->
        Derived Questions -> Strict Reviewer Hazard Audit -> Dual-Agent Approver Deliberation ->
        Human Review Queue."""
        start_time = time.time()

        # 1. Check Idempotency Cache
        idempotency_key = request.controls.idempotency_key
        if idempotency_key:
            cached_row = fetch_one(
                "SELECT result FROM idempotency_cache WHERE idempotency_key = :ikey AND expires_at > NOW()",
                {"ikey": idempotency_key},
            )
            if cached_row and cached_row.get("result"):
                logger.info("Returning cached result for idempotency_key: %s", idempotency_key)
                return PipelineResult(**cached_row["result"])

        grade_slug = validate_grade_dataset(request.curriculum.grade)
        subject = request.curriculum.subject
        sub_strand = request.curriculum.sub_strand
        run_id = f"run_{request.request_id}"
        stage_runs: list[StageRunResult] = []
        stage_costs: list[CostResult] = []

        # 2. Fetch Sub-strand Blueprint & Dynamic Prompt Package from Database
        substrand_record = fetch_one(
            """
            SELECT strand_name, sub_strand_id, sub_strand_name, allocated_hours, slos,
                   learning_experiences, key_inquiry_questions, required_diagrams,
                   experiments, prompt_context
            FROM curriculum_substrands
            WHERE grade = :grade AND LOWER(subject) = LOWER(:subject) AND (
                LOWER(sub_strand_name) LIKE LOWER(:sub) OR LOWER(sub_strand_id) = LOWER(:sub)
            )
            LIMIT 1
            """,
            {
                "grade": grade_slug,
                "subject": subject,
                "sub": f"%{sub_strand}%",
            },
        )

        blueprint = substrand_record or {}
        parent_substrand_dna_id = (blueprint.get("prompt_context") or {}).get("substrand_dna_id")

        # 3. Stage 1: Notes Generation Stage
        notes_stage, notes_cost = self._run_stage(
            PipelineStage.NOTES_GENERATION.value,
            run_id,
            request,
            lambda req, resolved: self._generate_notes(req, resolved, grade_slug, subject, blueprint),
        )
        stage_runs.append(notes_stage)
        stage_costs.append(notes_cost)

        # 4. Stage 2: Diagram Generation Stage (Vector Deduplication & Accessibility)
        diagram_stage, diagram_cost = self._run_stage(
            PipelineStage.DIAGRAM_GENERATION.value,
            run_id,
            request,
            lambda req, resolved: self._generate_diagrams(req, resolved, grade_slug, subject, notes_stage.output, blueprint),
        )
        stage_runs.append(diagram_stage)
        stage_costs.append(diagram_cost)

        # 5. Stage 3: Real Experiments & Learning Activities Stage (with Safety Guidelines)
        activity_stage, activity_cost = self._run_stage(
            PipelineStage.ACTIVITY_GENERATION.value,
            run_id,
            request,
            lambda req, resolved: self._generate_experiments_and_activities(
                req, resolved, grade_slug, subject, notes_stage.output, blueprint
            ),
        )
        stage_runs.append(activity_stage)
        stage_costs.append(activity_cost)

        # 6. Stage 4: Question Generation Stage (Derived Directly from Generated Notes & Experiments)
        question_stage, question_cost = self._run_stage(
            PipelineStage.QUESTION_GENERATION.value,
            run_id,
            request,
            lambda req, resolved: self._generate_derived_questions(
                req,
                resolved,
                grade_slug,
                subject,
                notes_stage.output,
                diagram_stage.output,
                activity_stage.output,
                blueprint,
            ),
        )
        validate_question_batch(question_stage.output.get("questions", []))
        stage_runs.append(question_stage)
        stage_costs.append(question_cost)

        # 7. Stage 5: Reviewer Stage (Strict Safety Hazard Audit & Curriculum Adherence)
        review_stage, review_cost = self._run_stage(
            PipelineStage.REVIEWER_PANEL.value,
            run_id,
            request,
            lambda req, resolved: self._run_reviewer_panel(
                req,
                resolved,
                grade_slug,
                subject,
                notes_stage.output,
                diagram_stage.output,
                activity_stage.output,
                question_stage.output,
                blueprint,
            ),
        )
        stage_runs.append(review_stage)
        stage_costs.append(review_cost)

        # 8. Stage 6: Multi-Agent Approver Stage (Dual-Agent Deliberation before Human Review)
        approver_stage, approver_cost = self._run_stage(
            "approver_panel",
            run_id,
            request,
            lambda req, resolved: self._run_multi_agent_approver(
                req,
                resolved,
                grade_slug,
                subject,
                notes_stage.output,
                activity_stage.output,
                question_stage.output,
                review_stage.output,
            ),
        )
        stage_runs.append(approver_stage)
        stage_costs.append(approver_cost)

        # 9. Quality & Safety Decision
        review_audit = review_stage.output
        approver_audit = approver_stage.output
        has_critical_hazard = review_audit.get("has_hazardous_procedures", False)

        is_approved = (
            not has_critical_hazard
            and review_audit.get("status") == "approved"
            and approver_audit.get("consensus") == "approved_for_human"
        )

        workflow_status = "human_review_queue" if is_approved else "needs_safety_revision"

        # 10. Generate Universal DNA Lineage for All Stages
        curr_dict = request.curriculum.model_dump()
        notes_dna = artifact_dna_service.generate_notes_dna(
            notes_id=f"notes_{run_id}",
            curriculum=curr_dict,
            notes_content=notes_stage.output,
            provenance=notes_stage.provenance.model_dump(),
            parent_substrand_dna_id=parent_substrand_dna_id,
            blueprint_slos=blueprint.get("slos") or [],
        )

        generated_diagrams = diagram_stage.output.get("diagrams") or []
        diagram_dnas = [
            artifact_dna_service.generate_diagram_dna(
                diagram_id=d.get("diagram_id", f"diag_{run_id}_{idx}"),
                curriculum=curr_dict,
                diagram_data=d,
                provenance=diagram_stage.provenance.model_dump(),
                parent_substrand_dna_id=parent_substrand_dna_id,
                concept=d.get("concept", ""),
            )
            for idx, d in enumerate(generated_diagrams)
        ]

        activity_dna = artifact_dna_service.generate_activity_dna(
            activity_id=f"act_{run_id}",
            curriculum=curr_dict,
            activity_data=activity_stage.output,
            provenance=activity_stage.provenance.model_dump(),
            parent_substrand_dna_id=parent_substrand_dna_id,
        )

        question_dnas = []
        for q in question_stage.output.get("questions", []):
            qid = q.get("question_id", f"Q-{grade_slug}-{request.curriculum.slo_id}")
            q_cert = artifact_dna_service.generate_question_dna(
                question_id=qid,
                curriculum=curr_dict,
                question_item=q,
                provenance=question_stage.provenance.model_dump(),
                parent_substrand_dna_id=parent_substrand_dna_id,
            )
            question_dnas.append(q_cert)

            question_dna_service.save_question(
                question_id=qid,
                universal_id=q.get("universal_id", request.curriculum.slo_id),
                curriculum_link=curr_dict,
                pedagogical_dna=q.get("pedagogical_dna", {}),
                content=q.get("content", {}),
                provenance=question_stage.provenance.model_dump(),
                review_audit=review_audit,
                status="approved" if is_approved else "needs_review",
            )

        bundle_id = f"res_{request.request_id[-12:].lower()}"
        bundle_dna = artifact_dna_service.generate_bundle_dna(
            bundle_id=bundle_id,
            curriculum=curr_dict,
            stage_dnas=[notes_dna, *diagram_dnas, activity_dna] + question_dnas,
            provenance={
                "run_id": run_id,
                "stages": len(stage_runs),
                "generated_at": now_iso(),
            },
            parent_substrand_dna_id=parent_substrand_dna_id,
        )

        cost_summary = format_cost_summary(stage_costs)
        total_pipeline_ms = (time.time() - start_time) * 1000

        # 11. Assemble Resource Bundle for Human Approver Page
        bundle = {
            "bundle_id": bundle_id,
            "curriculum": curr_dict,
            "notes": notes_stage.output,
            "diagrams": generated_diagrams,
            "activities": activity_stage.output.get("activities", []),
            "experiments": activity_stage.output.get("experiments", []),
            "safety_guidelines": activity_stage.output.get("safety_guidelines", []),
            "questions": question_stage.output.get("questions", []),
            "review_audit": review_audit,
            "multi_agent_deliberation": approver_audit,
            "status": workflow_status,
            "cost_summary": cost_summary,
            "bundle_dna": {
                "dna_id": bundle_dna.dna_id,
                "status": bundle_dna.status,
                "compliance_scores": bundle_dna.compliance_scores,
                "payload": bundle_dna.dna_payload,
            },
            "stage_dna_ids": {
                "notes_dna_id": notes_dna.dna_id,
                "diagram_dna_ids": [d.dna_id for d in diagram_dnas],
                "activity_dna_id": activity_dna.dna_id,
                "bundle_dna_id": bundle_dna.dna_id,
            },
            "total_latency_ms": round(total_pipeline_ms, 2),
            "updated_at": now_iso(),
        }

        execute(
            """
            INSERT INTO substrand_resources (bundle_id, curriculum, notes, diagrams, activities, questions, review_audit, status, total_tokens, total_cost_usd, updated_at)
            VALUES (
                :bundle_id, CAST(:curriculum AS jsonb), CAST(:notes AS jsonb),
                CAST(:diagrams AS jsonb), CAST(:activities AS jsonb),
                CAST(:questions AS jsonb), CAST(:review_audit AS jsonb),
                :status, :total_tokens, :total_cost_usd, NOW()
            )
            ON CONFLICT (bundle_id) DO UPDATE SET
                curriculum = EXCLUDED.curriculum,
                notes = EXCLUDED.notes,
                diagrams = EXCLUDED.diagrams,
                activities = EXCLUDED.activities,
                questions = EXCLUDED.questions,
                review_audit = EXCLUDED.review_audit,
                status = EXCLUDED.status,
                total_tokens = EXCLUDED.total_tokens,
                total_cost_usd = EXCLUDED.total_cost_usd,
                updated_at = NOW()
            """,
            {
                "bundle_id": bundle_id,
                "curriculum": to_json(curr_dict),
                "notes": to_json(notes_stage.output),
                "diagrams": to_json(generated_diagrams),
                "activities": to_json(activity_stage.output),
                "questions": to_json(question_stage.output.get("questions", [])),
                "review_audit": to_json({"review": review_audit, "deliberation": approver_audit}),
                "status": workflow_status,
                "total_tokens": cost_summary.get("total_tokens", 0),
                "total_cost_usd": cost_summary.get("total_cost_usd", 0.0),
            },
        )

        target_service.record_generation(grade_slug, is_approved=is_approved)

        result = PipelineResult(
            run_id=run_id,
            stage_runs=stage_runs,
            published_bundle=bundle,
            cost_summary=cost_summary,
        )

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

        logger.info(
            "Pipeline run %s completed: %s | %d tokens | $%.4f | %.0fms",
            run_id,
            workflow_status,
            cost_summary.get("total_tokens", 0),
            cost_summary.get("total_cost_usd", 0.0),
            total_pipeline_ms,
        )
        return result

    def _run_stage(
        self, stage: str, run_id: str, request: GenerateRequest, fn
    ) -> tuple[StageRunResult, CostResult]:
        start = time.time()
        resolved = self.router.resolve_for_stage(stage)
        llm_response: LlmResponse = fn(request, resolved)
        latency_ms = (time.time() - start) * 1000
        metrics_service.record_stage_latency(stage, latency_ms)

        cost = calculate_cost(
            model=llm_response.model,
            provider=llm_response.provider,
            usage=llm_response.usage,
        )

        persist_stage_cost(run_id, stage, cost)
        metrics_service.record_stage_cost(
            provider=llm_response.provider,
            tokens=llm_response.usage.total_tokens,
            cost_usd=cost.total_cost_usd,
        )

        provenance = Provenance(
            langfuse_prompt_name=stage,
            langfuse_prompt_version="v2.1",
            langfuse_prompt_label=request.controls.environment,
            prompt_hash_sha256=self.router.prompt_hash(stage, llm_response.content),
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
            prompt_tokens=llm_response.usage.prompt_tokens,
            completion_tokens=llm_response.usage.completion_tokens,
            total_tokens=llm_response.usage.total_tokens,
            cost_usd=cost.total_cost_usd,
            latency_ms=round(latency_ms, 2),
            created_at=now_iso(),
        )
        return StageRunResult(pipeline_stage=stage, output=llm_response.content, provenance=provenance), cost

    def _generate_notes(
        self, request: GenerateRequest, resolved: ResolvedModelConfig, grade_slug: str, subject: str, blueprint: dict
    ) -> LlmResponse:
        context = langfuse_context_service.assemble_agent_context(
            agent_name="note-generator",
            grade_slug=grade_slug,
            subject=subject,
            template_vars={
                "level": request.curriculum.level,
                "strand": request.curriculum.strand,
                "sub_strand": request.curriculum.sub_strand,
                "slo_id": request.curriculum.slo_id,
                "slos": blueprint.get("slos", []),
                "kiqs": blueprint.get("key_inquiry_questions", []),
            },
        )
        return llm_client.generate(resolved, context.messages, temperature=0.2)

    def _generate_diagrams(
        self,
        request: GenerateRequest,
        resolved: ResolvedModelConfig,
        grade_slug: str,
        subject: str,
        notes_output: dict,
        blueprint: dict,
    ) -> LlmResponse:
        """Generate every diagram the blueprint requires, not just the first.

        This previously took ``required_diagrams[0]`` and stored a single-element
        list, so a bundle could never satisfy a coverage requirement of more than
        one visual no matter how often it was re-run.
        """
        required_diagrams = [d for d in (blueprint.get("required_diagrams") or []) if d]
        if not required_diagrams:
            required_diagrams = [f"{request.curriculum.sub_strand} visual model"]

        diagrams: list[dict] = []
        last_response: LlmResponse | None = None
        total_usage_prompt = total_usage_completion = 0

        for index, concept_name in enumerate(required_diagrams, start=1):
            context = langfuse_context_service.assemble_agent_context(
                agent_name="diagram-generator",
                grade_slug=grade_slug,
                subject=subject,
                template_vars={
                    "concept": concept_name,
                    "notes_title": notes_output.get("title", request.curriculum.sub_strand),
                    "diagrams_required": required_diagrams,
                    "diagram_index": index,
                    "diagram_total": len(required_diagrams),
                },
            )

            try:
                llm_resp = llm_client.generate(resolved, context.messages, temperature=0.1)
            except Exception as exc:  # noqa: BLE001
                # One failed visual should not lose the diagrams already produced.
                logger.warning("Diagram %d/%d ('%s') failed: %s", index, len(required_diagrams), concept_name, exc)
                continue

            last_response = llm_resp
            total_usage_prompt += llm_resp.usage.prompt_tokens
            total_usage_completion += llm_resp.usage.completion_tokens

            content = llm_resp.content if isinstance(llm_resp.content, dict) else {}
            accessibility = content.get("accessibility", {}) or {}

            dedup_result = diagram_deduplicator.deduplicate_and_store(
                svg_str=content.get("diagram_svg", ""),
                diagram_title=content.get("diagram_title", concept_name),
                alt_text=accessibility.get("alt_text", ""),
                tactile_description=accessibility.get("tactile_description", ""),
                scene_document=content.get("scene_document") or content.get("scene"),
                metadata={
                    "grade": grade_slug,
                    "subject": subject,
                    "strand": request.curriculum.strand,
                    "sub_strand": request.curriculum.sub_strand,
                    "concept": concept_name,
                },
            )
            metrics_service.record_diagram_dedup(reused=(dedup_result.dedup_status == "reused"))

            diagrams.append({
                "diagram_id": dedup_result.diagram_id,
                "asset_id": dedup_result.diagram_id,
                "diagram_title": dedup_result.diagram_title,
                "title": dedup_result.diagram_title,
                "concept": concept_name,
                "micro_concept": concept_name,
                "diagram_svg": dedup_result.diagram_svg,
                "diagram_hash": dedup_result.diagram_hash,
                "storage_url": dedup_result.storage_url,
                "dedup_status": dedup_result.dedup_status,
                "scene_document": dedup_result.scene_document,
                "accessibility": {
                    "alt_text": dedup_result.alt_text,
                    "tactile_description": dedup_result.tactile_description,
                },
            })

        if last_response is None:
            raise_api_error(
                "DIAGRAM_GENERATION_FAILED",
                f"None of the {len(required_diagrams)} required diagrams could be generated "
                f"for '{request.curriculum.sub_strand}'.",
            )

        last_response.usage.prompt_tokens = total_usage_prompt
        last_response.usage.completion_tokens = total_usage_completion
        last_response.usage.total_tokens = total_usage_prompt + total_usage_completion
        last_response.content = {
            "diagrams": diagrams,
            "diagram_count": len(diagrams),
            "required_count": len(required_diagrams),
            # First diagram promoted for callers that still read a single visual.
            **(diagrams[0] if diagrams else {}),
        }
        return last_response

    def _generate_experiments_and_activities(
        self,
        request: GenerateRequest,
        resolved: ResolvedModelConfig,
        grade_slug: str,
        subject: str,
        notes_output: dict,
        blueprint: dict,
    ) -> LlmResponse:
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
                "target_experiments": blueprint.get("experiments", []),
                "safety_hazard_criteria": (blueprint.get("prompt_context") or {}).get("safety_hazard_criteria", []),
            },
        )
        return llm_client.generate(resolved, context.messages, temperature=0.25)

    def _generate_derived_questions(
        self,
        request: GenerateRequest,
        resolved: ResolvedModelConfig,
        grade_slug: str,
        subject: str,
        notes_output: dict,
        diagrams_output: dict,
        activities_output: dict,
        blueprint: dict,
    ) -> LlmResponse:
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
                "notes_summary": notes_output.get("summary") or notes_output.get("intro", ""),
                "experiments_generated": [e.get("title", "") for e in activities_output.get("experiments", [])],
                "diagram_concept": diagrams_output.get("diagram_title", ""),
                "slos": blueprint.get("slos", []),
            },
        )
        return llm_client.generate(resolved, context.messages, temperature=0.2)

    def _run_reviewer_panel(
        self,
        request: GenerateRequest,
        resolved: ResolvedModelConfig,
        grade_slug: str,
        subject: str,
        notes_output: dict,
        diagrams_output: dict,
        activities_output: dict,
        questions_output: dict,
        blueprint: dict,
    ) -> LlmResponse:
        context = langfuse_context_service.assemble_agent_context(
            agent_name="reviewer-panel",
            grade_slug=grade_slug,
            subject=subject,
            template_vars={
                # The prompt asks for {{ content_to_review }} and was never given
                # it, so the panel judged a title, two counts and a safety list —
                # never the content — and reported a verdict on the package.
                "content_to_review": json.dumps(
                    {
                        "notes": notes_output,
                        "diagrams": diagrams_output,
                        "activities": activities_output,
                        "questions": questions_output,
                    },
                    ensure_ascii=False, default=str,
                )[:60_000],
                # Likewise these two: a reviewer with no register cannot tell a
                # pre-primary defect from a senior-secondary one, and one with no
                # faith scope cannot tell CRE content from IRE content.
                "level_register": register_block(grade_slug),
                # The reviewers and approvers judge notation too: a guide that
                # writes "45 degrees" where its subject writes $45^\\circ$ is
                # wrong in a way only somebody holding the same rule can see.
                "notation": notation.block_for(subject or ""),
                # The reviewers judge against the same domain rules the
                # generator was given, or they are judging against their own
                # recollection of what a map needs.
                "domain_directives": prompt_fragments.compose(
                    subject or "", "notes", grade_slug),
                "faith_scope": faith_prompt_block(subject),
                "notes_title": notes_output.get("title", ""),
                "experiments": activities_output.get("experiments", []),
                "safety_guidelines": activities_output.get("safety_guidelines", []),
                "questions": questions_output.get("questions", []),
                "curriculum_reference": request.curriculum.model_dump(),
                "safety_hazard_criteria": (blueprint.get("prompt_context") or {}).get("safety_hazard_criteria", []),
            },
        )
        return llm_client.generate(resolved, context.messages, temperature=0.1)

    def _run_multi_agent_approver(
        self,
        request: GenerateRequest,
        resolved: ResolvedModelConfig,
        grade_slug: str,
        subject: str,
        notes_output: dict,
        activities_output: dict,
        questions_output: dict,
        reviewer_output: dict,
    ) -> LlmResponse:
        """Executes dual-agent consensus deliberation before human approval, dynamically loading prompt directives from Langfuse."""
        vars_dict = {
            "sub_strand": request.curriculum.sub_strand,
            "subject": subject,
            "grade": grade_slug,
            "level": request.curriculum.level,
            "notes_title": notes_output.get("title", ""),
            "experiments_count": len(activities_output.get("experiments", [])),
            "questions_count": len(questions_output.get("questions", [])),
            "reviewer_status": reviewer_output.get("status", "unknown"),
            "has_hazards": reviewer_output.get("has_hazardous_procedures", False),
            # Both approver prompts ask for these and neither was given them, so
            # the slots rendered empty and the deliberation ran without knowing
            # the learner's age or the learning area's faith.
            "level_register": register_block(grade_slug),
                # The reviewers and approvers judge notation too: a guide that
                # writes "45 degrees" where its subject writes $45^\\circ$ is
                # wrong in a way only somebody holding the same rule can see.
                "notation": notation.block_for(subject or ""),
                # The reviewers judge against the same domain rules the
                # generator was given, or they are judging against their own
                # recollection of what a map needs.
                "domain_directives": prompt_fragments.compose(
                    subject or "", "notes", grade_slug),
            "faith_scope": faith_prompt_block(subject),
        }

        # Dynamically fetch and compile prompts from Langfuse
        prompt1_text, _, _ = langfuse_context_service.compile_prompt("approver-agent1", vars_dict)
        prompt2_text, _, _ = langfuse_context_service.compile_prompt("approver-agent2", vars_dict)

        master_ctx = langfuse_context_service.get_master_context()

        deliberation_messages = [
            {
                "role": "system",
                "content": f"{master_ctx}\n\n## Multi-Agent Approver Directives (from Langfuse)\nAuditor 1 Directive:\n{prompt1_text}\n\nAuditor 2 Directive:\n{prompt2_text}",
            },
            {
                "role": "user",
                "content": (
                    f"Deliberate on the generated educational package for Sub-strand '{request.curriculum.sub_strand}' ({subject}, {grade_slug}).\n"
                    f"Notes Title: {notes_output.get('title')}\n"
                    f"Experiments Count: {len(activities_output.get('experiments', []))}\n"
                    f"Questions Count: {len(questions_output.get('questions', []))}\n"
                    f"Reviewer Quality Status: {reviewer_output.get('status')}\n"
                    f"Hazard Flags: {reviewer_output.get('has_hazardous_procedures', False)}\n\n"
                    "Respond with a JSON object containing:\n"
                    "- 'auditor_1_assessment': text\n"
                    "- 'auditor_2_cross_examination': text\n"
                    "- 'safety_consensus': 'verified_safe' | 'hazard_detected'\n"
                    "- 'consensus': 'approved_for_human' | 'requires_revision'\n"
                    "- 'readiness_score': float (0.0 to 1.0)\n"
                    "- 'summary_for_human_approver': text"
                ),
            },
        ]
        return llm_client.generate(resolved, deliberation_messages, temperature=0.1)


from ..state import runtime_state

provider_router = ProviderRouter(runtime_state)
pipeline_service = PipelineService(provider_router)
pipeline_orchestrator = pipeline_service
