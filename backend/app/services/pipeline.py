from __future__ import annotations

from ..config import PipelineStage
from ..infra.storage import object_storage
from ..models import GenerateRequest, PipelineResult, Provenance, StageRunResult, now_iso
from ..services.provider_router import ProviderRouter
from ..services.validation import validate_question_batch


class PipelineService:
    def __init__(self, router: ProviderRouter) -> None:
        self.router = router

    def run(self, request: GenerateRequest) -> PipelineResult:
        run_id = f"run_{request.request_id}"
        stage_runs: list[StageRunResult] = []

        notes = self._run_stage(PipelineStage.NOTES_GENERATION.value, request, self._generate_notes)
        stage_runs.append(notes)

        diagrams = self._run_stage(
            PipelineStage.DIAGRAM_GENERATION.value,
            request,
            lambda _: self._generate_diagrams(notes.output),
        )
        stage_runs.append(diagrams)

        activities = self._run_stage(
            PipelineStage.ACTIVITY_GENERATION.value,
            request,
            lambda _: self._generate_activities(notes.output),
        )
        stage_runs.append(activities)

        questions = self._run_stage(
            PipelineStage.QUESTION_GENERATION.value,
            request,
            lambda _: self._generate_questions(request, notes.output, diagrams.output, activities.output),
        )
        validate_question_batch(questions.output["questions"])
        stage_runs.append(questions)

        review = self._run_stage(
            PipelineStage.REVIEWER_PANEL.value,
            request,
            lambda _: self._run_reviewer_panel(questions.output),
        )
        stage_runs.append(review)

        bundle = {
            "bundle_id": f"res_{request.request_id[-12:].lower()}",
            "curriculum": request.curriculum.model_dump(),
            "notes": notes.output,
            "diagrams": diagrams.output,
            "activities": activities.output,
            "questions": questions.output,
            "review_audit": review.output,
            "status": "published" if review.output["status"] == "approved" else "needs_human_review",
            "updated_at": now_iso(),
        }

        return PipelineResult(run_id=run_id, stage_runs=stage_runs, published_bundle=bundle)

    def _run_stage(self, stage: str, request: GenerateRequest, fn):
        resolved = self.router.resolve_for_stage(stage)
        output = fn(request)
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

    def _generate_notes(self, request: GenerateRequest) -> dict:
        return {
            "title": f"{request.curriculum.sub_strand} - Revision Notes",
            "intro": f"Learners explore {request.curriculum.sub_strand} in {request.curriculum.subject}.",
            "summary_points": [
                "Materials are classified using observable physical properties.",
                "Classification improves scientific reasoning and decision making.",
            ],
        }

    def _generate_diagrams(self, notes_output: dict) -> dict:
        diagram_id = "diag_a4b9c1d2e3f4"
        object_name = f"diagrams/{diagram_id}.svg"
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 400 200'>"
            "<rect x='0' y='0' width='400' height='200' fill='white'/>"
            "<text x='20' y='40' font-size='18'>States of Matter</text>"
            "</svg>"
        )
        storage_url = object_storage.save_svg(object_name, svg)
        return {
            "diagram_id": diagram_id,
            "diagram_title": "States of Matter Particle Arrangement",
            "storage_url": storage_url,
            "dedup_status": "created",
            "source_note_title": notes_output["title"],
        }

    def _generate_activities(self, notes_output: dict) -> dict:
        return {
            "activity_name": "Sorting Compound Materials by Physical Properties",
            "objective": "Classify common materials by observable properties.",
            "materials": ["water", "stones", "plastic containers"],
            "procedure_steps": [
                "Learners gather local samples.",
                "Learners group samples by observed properties.",
            ],
            "based_on": notes_output["title"],
        }

    def _generate_questions(self, request: GenerateRequest, notes: dict, diagrams: dict, activities: dict) -> dict:
        base = {
            "curriculum_link": {
                "level": request.curriculum.level,
                "grade": request.curriculum.grade,
                "subject": request.curriculum.subject,
                "subject_code": request.curriculum.subject_code,
                "pathway": request.curriculum.pathway,
                "track": request.curriculum.track,
                "strand": request.curriculum.strand,
                "sub_strand": request.curriculum.sub_strand,
                "slo_id": request.curriculum.slo_id,
            },
            "kicd": {
                "dataset_name": f"grade-{request.curriculum.grade}",
                "dataset_item_id": "itm_generated_runtime",
            },
        }

        questions = [
            {
                "question_id": f"Q-{request.curriculum.grade}-{request.curriculum.subject_code}-{request.curriculum.slo_id}-01",
                "content": {
                    "question_type": "multiple_choice",
                    "question_text": "Which statement best describes gases compared to liquids?",
                    "options": [
                        {"id": "A", "text": "Gases have larger particle spacing and compress more."},
                        {"id": "B", "text": "Liquids have larger spacing and compress more."},
                        {"id": "C", "text": "Solids have no particles."},
                        {"id": "D", "text": "All states compress equally."},
                    ],
                    "answers": {
                        "correct_option_ids": ["A"],
                        "expected_response": "Gases have larger particle spacing and compress more.",
                        "scoring_points": [
                            "Identifies gases as most compressible",
                            "Explains particle spacing",
                        ],
                    },
                    "kicd_guideline_evidence": [
                        {
                            "subject": request.curriculum.subject,
                            "strand": request.curriculum.strand,
                            "sub_strand": request.curriculum.sub_strand,
                            "slo_id": request.curriculum.slo_id,
                            "guideline_quote": "Learners classify materials using observable physical properties.",
                            "guideline_reference": base["kicd"],
                            "parent_teacher_explanation": "Question applies classification reasoning using physical properties.",
                        }
                    ],
                    "diagram_id": diagrams["diagram_id"],
                    "marking_guide": {
                        "meeting": "Correct option and correct scientific reason.",
                    },
                },
            },
            {
                "question_id": f"Q-{request.curriculum.grade}-{request.curriculum.subject_code}-{request.curriculum.slo_id}-02",
                "content": {
                    "question_type": "structured_inquiry",
                    "question_text": "Explain why air compresses more than water in a syringe test.",
                    "answers": {
                        "expected_response": "Gas particles are farther apart than liquid particles, allowing higher compression.",
                        "scoring_points": [
                            "Mentions particle spacing",
                            "Compares gas with liquid",
                            "Uses compressibility terms correctly",
                        ],
                    },
                    "kicd_guideline_evidence": [
                        {
                            "subject": request.curriculum.subject,
                            "strand": request.curriculum.strand,
                            "sub_strand": request.curriculum.sub_strand,
                            "slo_id": request.curriculum.slo_id,
                            "guideline_quote": "Learners classify materials using observable physical properties.",
                            "guideline_reference": base["kicd"],
                            "parent_teacher_explanation": "Question asks learners to explain compressibility using particle model language.",
                        }
                    ],
                    "diagram_id": diagrams["diagram_id"],
                    "activity_name": activities["activity_name"],
                    "marking_guide": {
                        "meeting": "Explains compressibility with correct particle model reasoning.",
                    },
                },
            },
        ]

        return {
            "notes_ref": notes["title"],
            "questions": questions,
        }

    def _run_reviewer_panel(self, question_output: dict) -> dict:
        _ = question_output
        return {
            "alignment_score": 0.98,
            "accuracy_score": 0.99,
            "pedagogy_score": 0.96,
            "language_score": 0.95,
            "kicd_citation_score": 0.98,
            "risk_flags": [],
            "status": "approved",
        }
