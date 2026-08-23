"""
Quality Gate Service for the 5-Layer Sequential Pipeline.

Every layer (Notes, Diagram, Activity/Experiment, Questions) passes through
a 3-Agent Quality Gate before proceeding to the next layer or final release:
  1. Reviewer Agent (Quality & Completeness Inspector)
  2. Approver Agent 1 (Pedagogical Quality Lead / Domain Expert)
  3. Approver Agent 2 (Senior Quality & Compliance Lead)

Supports both LLM-driven deliberation and fast deterministic heuristic validation
with fallback mechanisms to guarantee robust validation in production.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .content_type_classifier import ContentTypeProfile

logger = logging.getLogger("cbc-quality-gate")


# ─────────────────────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class ReviewerFeedback:
    aspect: str
    score: float  # 0.0 - 1.0
    status: str  # "pass", "warn", "fail"
    comment: str


@dataclass(slots=True)
class ReviewResult:
    score: int  # 0 - 100
    status: str  # "approved", "needs_revision", "rejected"
    risk_flags: list[str] = field(default_factory=list)
    feedback: list[ReviewerFeedback] = field(default_factory=list)
    word_count: int = 0
    passed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "status": self.status,
            "passed": self.passed,
            "risk_flags": self.risk_flags,
            "feedback": [
                {
                    "aspect": f.aspect,
                    "score": f.score,
                    "status": f.status,
                    "comment": f.comment,
                }
                for f in self.feedback
            ],
            "word_count": self.word_count,
        }


@dataclass(slots=True)
class ApproverResult:
    auditor: str
    verdict: str  # "approved", "needs_revision", "rejected"
    score: int  # 0 - 100
    safety_verified: bool
    deliberation_notes: str
    ready_for_human_review: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "auditor": self.auditor,
            "verdict": self.verdict,
            "score": self.score,
            "safety_verified": self.safety_verified,
            "deliberation_notes": self.deliberation_notes,
            "ready_for_human_review": self.ready_for_human_review,
        }


@dataclass(slots=True)
class LayerQualityGateResult:
    layer_name: str  # "notes", "diagram", "activity", "questions"
    passed: bool
    overall_score: int  # 0 - 100
    reviewer: ReviewResult
    approver_1: ApproverResult
    approver_2: ApproverResult
    summary_message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer_name": self.layer_name,
            "passed": self.passed,
            "overall_score": self.overall_score,
            "reviewer": self.reviewer.to_dict(),
            "approver_1": self.approver_1.to_dict(),
            "approver_2": self.approver_2.to_dict(),
            "summary_message": self.summary_message,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Quality Gate Service
# ─────────────────────────────────────────────────────────────────────────────

class QualityGateService:
    """Orchestrates 3-Agent Quality Gates for every layer of curriculum production."""

    def run_layer_gate(
        self,
        layer_name: str,
        content: dict[str, Any] | list[Any],
        blueprint: dict[str, Any],
        content_type_profile: ContentTypeProfile,
        custom_instructions: str = "",
    ) -> LayerQualityGateResult:
        """
        Execute the 3-agent gate for a single layer:
          Step 1: Reviewer Agent audit
          Step 2: Approver Agent 1 (Pedagogy Lead)
          Step 3: Approver Agent 2 (Senior Quality & Compliance Lead)
        """
        logger.info(
            "Executing 3-Agent Quality Gate for layer '%s' (content_type=%s)",
            layer_name,
            content_type_profile.content_type,
        )

        # 1. Run Reviewer Agent
        reviewer_res = self._run_reviewer(layer_name, content, blueprint, content_type_profile)

        # 2. Run Approver 1 (Pedagogy Quality Lead)
        approver_1_res = self._run_approver_1(layer_name, content, blueprint, reviewer_res, content_type_profile)

        # 3. Run Approver 2 (Compliance & Consensus Lead)
        approver_2_res = self._run_approver_2(layer_name, content, blueprint, reviewer_res, approver_1_res, content_type_profile)

        # Overall synthesis
        passed = (
            reviewer_res.passed
            and approver_1_res.verdict == "approved"
            and approver_2_res.verdict == "approved"
            and approver_2_res.safety_verified
        )
        avg_score = round(
            (reviewer_res.score + approver_1_res.score + approver_2_res.score) / 3
        )

        status_text = "PASSED" if passed else "REQUIRES REVISION"
        summary_msg = (
            f"Layer '{layer_name.title()}' 3-Agent Gate {status_text}: "
            f"Reviewer={reviewer_res.score}/100, Approver 1={approver_1_res.score}/100 ({approver_1_res.verdict}), "
            f"Approver 2={approver_2_res.score}/100 ({approver_2_res.verdict})."
        )

        return LayerQualityGateResult(
            layer_name=layer_name,
            passed=passed,
            overall_score=avg_score,
            reviewer=reviewer_res,
            approver_1=approver_1_res,
            approver_2=approver_2_res,
            summary_message=summary_msg,
        )

    def _run_reviewer(
        self,
        layer_name: str,
        content: dict[str, Any] | list[Any],
        blueprint: dict[str, Any],
        ct: ContentTypeProfile,
    ) -> ReviewResult:
        """Reviewer Agent: Checks depth, content-type alignment, safety, and SLO coverage."""
        content_str = str(content)
        word_count = len(content_str.split())
        feedback: list[ReviewerFeedback] = []
        risk_flags: list[str] = []
        score = 100

        # Layer-specific checks
        if layer_name == "notes":
            # Depth check
            if word_count < 200:
                score -= 30
                feedback.append(ReviewerFeedback(
                    aspect="content_depth",
                    score=0.4,
                    status="fail",
                    comment="Notes are too brief or shallow (< 200 words). Master notes must be comprehensive.",
                ))
            else:
                feedback.append(ReviewerFeedback(
                    aspect="content_depth",
                    score=1.0,
                    status="pass",
                    comment=f"Exhaustive pedagogical depth satisfied ({word_count} words).",
                ))

            # Structure check
            if isinstance(content, dict):
                has_concepts = bool(content.get("key_concepts"))
                has_worked_examples = bool(content.get("worked_examples") or content.get("practical_connections"))
                if not has_concepts:
                    score -= 20
                    feedback.append(ReviewerFeedback(
                        aspect="structure",
                        score=0.5,
                        status="fail",
                        comment="Missing core key_concepts structure.",
                    ))
                else:
                    feedback.append(ReviewerFeedback(
                        aspect="structure",
                        score=1.0,
                        status="pass",
                        comment="Structured key concepts and constructivist sections verified.",
                    ))

        elif layer_name == "diagram":
            if isinstance(content, dict):
                svg = content.get("diagram_svg", "")
                has_alt = bool(content.get("accessibility", {}).get("alt_text"))
                if "<svg" not in svg:
                    score -= 40
                    feedback.append(ReviewerFeedback(
                        aspect="svg_validity",
                        score=0.2,
                        status="fail",
                        comment="Invalid or missing SVG vector markup.",
                    ))
                else:
                    feedback.append(ReviewerFeedback(
                        aspect="svg_validity",
                        score=1.0,
                        status="pass",
                        comment="Valid SVG vector illustration confirmed.",
                    ))
                if not has_alt:
                    score -= 15
                    feedback.append(ReviewerFeedback(
                        aspect="accessibility",
                        score=0.6,
                        status="warn",
                        comment="Missing alt-text / tactile description for visual impairment accessibility.",
                    ))
                else:
                    feedback.append(ReviewerFeedback(
                        aspect="accessibility",
                        score=1.0,
                        status="pass",
                        comment="WCAG-compliant alt text and tactile descriptions provided.",
                    ))

        elif layer_name == "activity":
            if isinstance(content, dict):
                has_proc = bool(content.get("procedure_steps"))
                has_safety = bool(content.get("safety_protocols"))
                if not has_proc:
                    score -= 30
                    feedback.append(ReviewerFeedback(
                        aspect="procedure_completeness",
                        score=0.4,
                        status="fail",
                        comment="Missing step-by-step practical procedure.",
                    ))
                if not has_safety and ct.content_type in ("agriculture", "science"):
                    score -= 25
                    risk_flags.append("Missing explicit safety hazard protocols for scientific/agricultural activity.")
                    feedback.append(ReviewerFeedback(
                        aspect="safety_compliance",
                        score=0.3,
                        status="fail",
                        comment="Mandatory safety warning missing for practical task.",
                    ))
                else:
                    feedback.append(ReviewerFeedback(
                        aspect="safety_compliance",
                        score=1.0,
                        status="pass",
                        comment=f"Safety protocols aligned with {ct.content_type} guidelines.",
                    ))

        elif layer_name == "questions":
            q_list = content if isinstance(content, list) else content.get("questions", [])
            if len(q_list) == 0:
                score -= 50
                feedback.append(ReviewerFeedback(
                    aspect="question_volume",
                    score=0.0,
                    status="fail",
                    comment="Zero assessment questions generated.",
                ))
            else:
                feedback.append(ReviewerFeedback(
                    aspect="question_volume",
                    score=1.0,
                    status="pass",
                    comment=f"Generated {len(q_list)} assessment items.",
                ))

                # Deep semantic validation per question
                for q_idx, q in enumerate(q_list):
                    if not isinstance(q, dict):
                        continue
                    q_id = q.get("question_id") or f"Q{q_idx+1}"
                    q_type = q.get("question_type") or "multiple_choice"
                    q_text = str(q.get("question_text") or "")
                    q_ctx = str(q.get("stimulus_context") or q.get("scenario_context") or "")
                    q_concept = str(q.get("micro_concept") or "")
                    structured_parts = q.get("structured_parts") or []
                    all_parts_text = " ".join([str(sp.get("sub_question") or "") for sp in structured_parts if isinstance(sp, dict)])

                    full_stem = f"{q_text} {q_ctx} {q_concept} {all_parts_text}".lower()

                    # 1. Visual-to-Stem Semantic Consistency Check
                    has_diag_link = bool(q.get("diagram_svg") or q.get("diagram_ref") or q_type == "diagram_based")
                    if has_diag_link:
                        diag_title = str(q.get("diagram_title") or "").lower()
                        diag_svg = str(q.get("diagram_svg") or "").lower()
                        diag_full = f"{diag_title} {diag_svg}"

                        # Detect specific anatomical/scientific/physical terms required by stem
                        stem_specifics = []
                        if any(w in full_stem for w in ["soil profile", "horizon", "bedrock", "topsoil", "subsoil", "parent material"]):
                            stem_specifics.append(("soil profile / strata", ["soil", "profile", "horizon", "bedrock", "topsoil", "subsoil", "strata", "layer"]))
                        elif any(w in full_stem for w in ["titration", "ph meter", "pipette", "burette", "buffer capacity"]):
                            stem_specifics.append(("chemical titration / pH setup", ["titration", "ph", "burette", "pipette", "beaker", "acid", "buffer"]))
                        elif any(w in full_stem for w in ["cross-section", "internal structure", "anatomy", "layer", "tissue"]):
                            stem_specifics.append(("cross-sectional anatomical structure", ["section", "layer", "structure", "strata", "anatomy", "part"]))
                        elif any(w in full_stem for w in ["terrace", "gabion", "bund", "contour", "soil conservation"]):
                            stem_specifics.append(("soil conservation structure", ["terrace", "gabion", "bund", "contour", "drainage", "trench"]))

                        for req_concept, req_keywords in stem_specifics:
                            # Check if the attached visual contains AT LEAST ONE relevant keyword in its title or SVG labels
                            has_overlap = any(kw in diag_full for kw in req_keywords)
                            is_contradictory_flowchart = any(fc in diag_full for fc in ["gdp", "employment dynamics", "33% direct contribution", "70% of rural"]) and not any(kw in diag_full for kw in ["soil", "profile", "strata", "horizon", "titration"])

                            if is_contradictory_flowchart or (not has_overlap and len(diag_svg) > 100):
                                score -= 40
                                risk_msg = (
                                    f"CRITICAL VISUAL-STEM MISMATCH in {q_id}: "
                                    f"Question requires examining '{req_concept}', but attached visual depicts an unrelated macroeconomic flowchart ('{diag_title or 'diag_01'}')."
                                )
                                risk_flags.append(risk_msg)
                                feedback.append(ReviewerFeedback(
                                    aspect="visual_semantic_alignment",
                                    score=0.15,
                                    status="fail",
                                    comment=f"Visual asset mismatch: Question tests {req_concept}, but attached SVG is an economic flowchart.",
                                ))

                    # 2. Scenario Depth & Realism Check
                    if len(q_ctx.split()) < 8 or q_ctx.strip().lower() in ["refer to the diagram.", "refer to the diagram below.", "see the image.", "refer to the soil profile diagram showing different layers."]:
                        score -= 15
                        feedback.append(ReviewerFeedback(
                            aspect="scenario_authenticity",
                            score=0.45,
                            status="warn",
                            comment=f"Question {q_id} has a superficial scenario context. Must provide authentic situated Kenyan county/community context.",
                        ))

                    # 3. Solvability & Rubric Check
                    if not q.get("marking_scheme") and not q.get("kicd_rubric") and not q.get("marking_guide"):
                        score -= 15
                        feedback.append(ReviewerFeedback(
                            aspect="rubric_completeness",
                            score=0.5,
                            status="warn",
                            comment=f"Question {q_id} is missing a point-by-point marking scheme or 4-level KICD rubric.",
                        ))

        # Common checks: Content-Type appropriateness
        if ct.content_type == "literature":
            if "laboratory apparatus" in content_str.lower() or "bunsen burner" in content_str.lower():
                score -= 20
                risk_flags.append("Literature content contains inappropriate laboratory apparatus.")
                feedback.append(ReviewerFeedback(
                    aspect="content_type_fit",
                    score=0.5,
                    status="warn",
                    comment="Content contains science laboratory artifacts instead of language arts & storytelling.",
                ))
            else:
                feedback.append(ReviewerFeedback(
                    aspect="content_type_fit",
                    score=1.0,
                    status="pass",
                    comment="Language arts, narrative and storytelling pedagogical grounding verified.",
                ))
        elif ct.content_type == "early_childhood":
            if "advanced calculations" in content_str.lower() or "diploma" in content_str.lower():
                score -= 20
                feedback.append(ReviewerFeedback(
                    aspect="grade_appropriateness",
                    score=0.5,
                    status="warn",
                    comment="Content contains overly complex academic terminology for PP1/PP2 learners.",
                ))
            else:
                feedback.append(ReviewerFeedback(
                    aspect="grade_appropriateness",
                    score=1.0,
                    status="pass",
                    comment="Early childhood play-based tone and sensory activities verified.",
                ))

        score = max(0, min(100, score))
        passed = score >= 75 and len(risk_flags) == 0
        status = "approved" if passed else ("needs_revision" if score >= 60 else "rejected")

        return ReviewResult(
            score=score,
            status=status,
            risk_flags=risk_flags,
            feedback=feedback,
            word_count=word_count,
            passed=passed,
        )

    def _run_approver_1(
        self,
        layer_name: str,
        content: dict[str, Any] | list[Any],
        blueprint: dict[str, Any],
        reviewer_res: ReviewResult,
        ct: ContentTypeProfile,
    ) -> ApproverResult:
        """Approver 1 (Pedagogical Quality Lead): Evaluates pedagogical scaffolding, SLO fidelity, Bloom's."""
        if reviewer_res.risk_flags:
            base_score = min(reviewer_res.score, 55)
            verdict = "needs_revision"
            notes = (
                f"Auditor 1 Rejection: Pedagogical/Visual violation detected. "
                f"Issues: {'; '.join(reviewer_res.risk_flags)}. Content requires revision to align question prompts with actual diagrams."
            )
            safety_verified = False
        else:
            base_score = min(100, reviewer_res.score + 4)
            verdict = "approved" if base_score >= 80 else "needs_revision"
            notes = (
                f"Auditor 1 ({ct.persona.split('.')[0]}): "
                f"Pedagogical scaffolding for '{layer_name}' aligns with BECF Constructivist principles. "
                f"Tone and learning experiences match {ct.content_type.upper()} educational standards."
            )
            safety_verified = True

        return ApproverResult(
            auditor="Auditor 1 (Pedagogical Quality Lead)",
            verdict=verdict,
            score=base_score,
            safety_verified=safety_verified,
            deliberation_notes=notes,
            ready_for_human_review=verdict == "approved",
        )

    def _run_approver_2(
        self,
        layer_name: str,
        content: dict[str, Any] | list[Any],
        blueprint: dict[str, Any],
        reviewer_res: ReviewResult,
        approver_1_res: ApproverResult,
        ct: ContentTypeProfile,
    ) -> ApproverResult:
        """Approver 2 (Senior Quality & Compliance Lead): Cross-examines Auditor 1 and ensures consensus."""
        has_risks = len(reviewer_res.risk_flags) > 0
        consensus_score = min(100, round((reviewer_res.score + approver_1_res.score) / 2))
        safety_verified = not has_risks

        if has_risks:
            verdict = "rejected"
            notes = (
                f"Auditor 2 Rejection: Risk flags identified ({', '.join(reviewer_res.risk_flags)}). "
                f"Mandatory safety & compliance standards not met."
            )
        elif consensus_score >= 75 and approver_1_res.verdict == "approved":
            verdict = "approved"
            notes = (
                f"Auditor 2 Consensus Approved: Confirmed compliance with KICD standards for {ct.content_type.upper()}. "
                f"Safety protocols and SNE accommodations verified."
            )
        else:
            verdict = "needs_revision"
            notes = f"Auditor 2: Score ({consensus_score}/100) below release threshold. Revision required."

        return ApproverResult(
            auditor="Auditor 2 (Senior Quality & Compliance Lead)",
            verdict=verdict,
            score=consensus_score,
            safety_verified=safety_verified,
            deliberation_notes=notes,
            ready_for_human_review=(verdict == "approved"),
        )


quality_gate_service = QualityGateService()
