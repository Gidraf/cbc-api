"""Three-agent quality gate for each production layer.

Split deliberately into two kinds of check:

**Hard invariants** are binary and rule-based — the SVG parses, exactly one
option is correct, part marks sum to the total. These block release outright.

**Measured metrics** come from :mod:`dna_scoring` and are scored on a continuum.

What is gone is the middle category the gate used to be built from: keyword
tripwires standing in for judgement. It searched for the literal strings "gdp"
and "33% direct contribution" to detect a mismatched diagram, and for "bunsen
burner" to detect science content in a literature lesson. Those caught exactly
the incident they were written for and nothing else.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from . import dna_scoring
from .content_type_classifier import ContentTypeProfile
from .grade_order import grade_ordinal

logger = logging.getLogger("cbc-quality-gate")

# A layer must reach this to pass. Metrics that cannot be computed are excluded
# from the mean rather than counted as zero.
PASS_THRESHOLD = 70
REVIEW_THRESHOLD = 55


# ─────────────────────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class ReviewerFeedback:
    aspect: str
    score: float
    status: str  # "pass", "warn", "fail"
    comment: str
    method: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "aspect": self.aspect,
            "score": self.score,
            "status": self.status,
            "comment": self.comment,
            "method": self.method,
        }


@dataclass(slots=True)
class ReviewResult:
    score: int
    status: str
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
            "feedback": [f.to_dict() for f in self.feedback],
            "word_count": self.word_count,
        }


@dataclass(slots=True)
class ApproverResult:
    auditor: str
    verdict: str
    score: int
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
    layer_name: str
    passed: bool
    overall_score: int
    reviewer: ReviewResult
    approver_1: ApproverResult
    approver_2: ApproverResult
    summary_message: str
    blocking_reasons: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer_name": self.layer_name,
            "passed": self.passed,
            "overall_score": self.overall_score,
            "reviewer": self.reviewer.to_dict(),
            "approver_1": self.approver_1.to_dict(),
            "approver_2": self.approver_2.to_dict(),
            "summary_message": self.summary_message,
            "blocking_reasons": self.blocking_reasons,
            "next_actions": self.next_actions,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Hard invariants
# ─────────────────────────────────────────────────────────────────────────────


def _invariants_for_questions(items: list[dict[str, Any]]) -> list[str]:
    """Binary failures that must block release regardless of any score."""
    violations: list[str] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        label = item.get("display_label") or item.get("question_id") or "item"
        q_type = item.get("question_type", "")
        options = item.get("options") or []

        if options:
            correct = [o for o in options if isinstance(o, dict) and o.get("is_correct")]
            if len(correct) != 1:
                violations.append(
                    f"{label}: {len(correct)} options flagged correct; exactly one is required."
                )

        if q_type == "diagram_based" and not item.get("diagram"):
            violations.append(f"{label}: diagram question has no diagram attached and cannot be printed.")

        parts = item.get("structured_parts") or []
        if parts:
            part_total = sum(int(p.get("marks", 0) or 0) for p in parts if isinstance(p, dict))
            declared = int((item.get("pedagogy") or {}).get("max_marks", 0) or item.get("max_marks", 0) or 0)
            if part_total and declared and part_total != declared:
                violations.append(
                    f"{label}: part marks total {part_total} but the item is worth {declared}."
                )

        if not str(item.get("question_text") or "").strip():
            violations.append(f"{label}: no question text.")

    return violations


def _invariants_for_diagram(diagram: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    svg = str(diagram.get("diagram_svg") or diagram.get("svg_markup") or "")
    if "<svg" not in svg.lower():
        violations.append("Diagram contains no SVG markup.")
    if not str((diagram.get("accessibility") or {}).get("alt_text") or "").strip():
        violations.append("Diagram has no alt text, so it is unusable for visually impaired learners.")
    return violations


def _invariants_for_activity(activity: dict[str, Any], content_type: str) -> list[str]:
    violations: list[str] = []
    body_tokens = dna_scoring.tokens(dna_scoring._flatten(activity))
    hazards = body_tokens & dna_scoring._HAZARD_TERMS
    ppe = body_tokens & dna_scoring._PPE_TERMS
    if hazards and not ppe:
        violations.append(
            f"Hazardous materials or procedures are described ({', '.join(sorted(hazards)[:4])}) "
            f"with no safety precautions given."
        )
    return violations


# ─────────────────────────────────────────────────────────────────────────────
# Quality Gate Service
# ─────────────────────────────────────────────────────────────────────────────


class QualityGateService:
    """Orchestrates the three-agent gate for one production layer."""

    def run_layer_gate(
        self,
        layer_name: str,
        content: dict[str, Any] | list[Any],
        blueprint: dict[str, Any],
        content_type_profile: ContentTypeProfile,
        custom_instructions: str = "",
    ) -> LayerQualityGateResult:
        reviewer = self._run_reviewer(layer_name, content, blueprint, content_type_profile)
        approver_1 = self._run_approver_1(layer_name, reviewer, content_type_profile)
        approver_2 = self._run_approver_2(reviewer, approver_1, content_type_profile)

        passed = (
            reviewer.passed
            and approver_1.verdict == "approved"
            and approver_2.verdict == "approved"
        )
        overall = round((reviewer.score + approver_1.score + approver_2.score) / 3)

        next_actions = [
            f"Improve {f.aspect.replace('_', ' ')}: {f.comment}"
            for f in reviewer.feedback
            if f.status in {"fail", "warn"}
        ][:5]

        summary = (
            f"{layer_name.title()} gate {'passed' if passed else 'needs revision'} at {overall}/100. "
            + (
                f"Blocking: {reviewer.risk_flags[0]}"
                if reviewer.risk_flags
                else (
                    f"Weakest measure: {reviewer.feedback[0].aspect.replace('_', ' ')} "
                    f"at {reviewer.feedback[0].score:.2f}."
                    if reviewer.feedback
                    else "All measured criteria met."
                )
            )
        )

        return LayerQualityGateResult(
            layer_name=layer_name,
            passed=passed,
            overall_score=overall,
            reviewer=reviewer,
            approver_1=approver_1,
            approver_2=approver_2,
            summary_message=summary,
            blocking_reasons=reviewer.risk_flags,
            next_actions=next_actions,
        )

    def _run_reviewer(
        self,
        layer_name: str,
        content: dict[str, Any] | list[Any],
        blueprint: dict[str, Any],
        ct: ContentTypeProfile,
    ) -> ReviewResult:
        word_count = len(dna_scoring._flatten(content).split())
        grade_ord = grade_ordinal(blueprint.get("grade") or getattr(ct, "grade", ""))
        risk_flags: list[str] = []
        score_set = dna_scoring.ScoreSet()

        if layer_name == "notes":
            notes = content if isinstance(content, dict) else {}
            score_set = dna_scoring.score_notes(
                notes,
                blueprint.get("slos") or [],
                grade_ord,
                str(blueprint.get("raw_source") or ""),
            )

        elif layer_name == "diagram":
            diagram = content if isinstance(content, dict) else {}
            risk_flags += _invariants_for_diagram(diagram)
            score_set = dna_scoring.score_diagram(diagram, str(blueprint.get("concept") or ""))

        elif layer_name == "activity":
            activity = content if isinstance(content, dict) else {}
            risk_flags += _invariants_for_activity(activity, ct.content_type)
            score_set = dna_scoring.score_activity(activity, ct.content_type)

        elif layer_name == "questions":
            items = content if isinstance(content, list) else (content.get("questions") or [])
            items = [i for i in items if isinstance(i, dict)]
            risk_flags += _invariants_for_questions(items)

            if not items:
                risk_flags.append("No assessment items were produced.")
            else:
                # Score every item, then report the batch by its mean per metric,
                # so one weak item does not hide behind nine strong ones.
                per_item = [
                    dna_scoring.score_question(
                        item,
                        slo_text=str((item.get("curriculum") or {}).get("slo_text") or ""),
                        notes_body=str(blueprint.get("notes_body") or ""),
                        grade_ordinal=(item.get("curriculum") or {}).get("grade_ordinal") or grade_ord,
                    )
                    for item in items
                ]
                metric_names = {name for s in per_item for name in s.scores}
                for name in sorted(metric_names):
                    values = [
                        s.scores[name].value
                        for s in per_item
                        if name in s.scores and s.scores[name].value is not None
                    ]
                    if values:
                        method = next(
                            (s.scores[name].method for s in per_item if name in s.scores), "batch_mean"
                        )
                        score_set.add(name, dna_scoring.Score(
                            round(sum(values) / len(values), 4),
                            method,
                            f"mean across {len(values)} item(s)",
                            len(values),
                        ))
                    else:
                        pending = next(
                            (s.scores[name] for s in per_item if name in s.scores), None
                        )
                        if pending:
                            score_set.add(name, pending)

                # Typology mix, expressed against families rather than a name list.
                # Only meaningful once a batch is big enough to have a mix at all;
                # a single item is not an unbalanced batch, it is one question.
                from ..question_models import family_of

                families = [family_of(i.get("question_type", "")) for i in items]
                selected = families.count("selected_response")
                constructed = families.count("constructed_response")

                if len(items) >= 3:
                    # Target roughly a third selected-response, two thirds constructed.
                    balance = 1.0 - abs((selected / len(items)) - 0.35) / 0.65
                    score_set.add("typology_balance", dna_scoring.Score(
                        round(max(0.0, min(1.0, balance)), 4),
                        "selected_vs_constructed_ratio",
                        f"{selected} selected-response, {constructed} constructed-response",
                        len(items),
                    ))
                else:
                    score_set.add("typology_balance", dna_scoring.Score(
                        None,
                        "pending_batch_too_small",
                        f"{len(items)} item(s); a mix needs at least 3",
                        len(items),
                    ))

        mean = score_set.mean()
        score = round((mean or 0.0) * 100)

        feedback: list[ReviewerFeedback] = []
        for name, sc in score_set.scores.items():
            if sc.value is None:
                feedback.append(ReviewerFeedback(
                    aspect=name,
                    score=0.0,
                    status="pending",
                    comment=f"Not measurable yet — {sc.evidence}.",
                    method=sc.method,
                ))
                continue
            status = "pass" if sc.value >= 0.75 else ("warn" if sc.value >= 0.5 else "fail")
            feedback.append(ReviewerFeedback(
                aspect=name,
                score=sc.value,
                status=status,
                comment=sc.evidence or f"Scored {sc.value:.2f}.",
                method=sc.method,
            ))

        # Weakest first, so the operator reads the thing to fix at the top.
        feedback.sort(key=lambda f: (f.status == "pending", f.score))

        passed = score >= PASS_THRESHOLD and not risk_flags
        status = "approved" if passed else ("needs_revision" if score >= REVIEW_THRESHOLD else "rejected")

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
        reviewer: ReviewResult,
        ct: ContentTypeProfile,
    ) -> ApproverResult:
        """Pedagogical lead: weighs the pedagogy-facing measures."""
        pedagogical_aspects = {
            "slo_congruence", "slo_coverage", "slo_depth", "reading_level_fit",
            "scenario_authenticity", "structural_completeness", "typology_balance",
            "concept_alignment", "procedure_completeness",
            # Depth was in neither approver's set, so a guide too thin to teach
            # from reached "approved, 91/100" from the pedagogical lead on a run
            # where every one of its seven modules failed the floor. Whether a
            # teacher can teach the lesson from what they were handed is the
            # pedagogical question, not a footnote to it.
            "content_depth",
            # And whether what is said TO the child lands at the child's level.
            "learner_language_fit",
        }
        relevant = [f for f in reviewer.feedback if f.aspect in pedagogical_aspects and f.status != "pending"]

        if reviewer.risk_flags:
            return ApproverResult(
                auditor="Auditor 1 (Pedagogical Quality Lead)",
                verdict="needs_revision",
                score=min(reviewer.score, 55),
                safety_verified=False,
                deliberation_notes=(
                    f"Blocked before pedagogical review: {'; '.join(reviewer.risk_flags[:3])}"
                ),
                ready_for_human_review=False,
            )

        if not relevant:
            score = reviewer.score
            notes = f"No pedagogy-specific measures applied to the {layer_name} layer; deferring to the overall score."
        else:
            score = round(sum(f.score for f in relevant) / len(relevant) * 100)
            weakest = min(relevant, key=lambda f: f.score)
            notes = (
                f"Pedagogical measures for {ct.content_type} averaged {score}/100 across "
                f"{len(relevant)} criteria. Weakest: {weakest.aspect.replace('_', ' ')} "
                f"at {weakest.score:.2f} ({weakest.comment})."
            )

        verdict = "approved" if score >= PASS_THRESHOLD else "needs_revision"
        return ApproverResult(
            auditor="Auditor 1 (Pedagogical Quality Lead)",
            verdict=verdict,
            score=score,
            safety_verified=True,
            deliberation_notes=notes,
            ready_for_human_review=verdict == "approved",
        )

    def _run_approver_2(
        self,
        reviewer: ReviewResult,
        approver_1: ApproverResult,
        ct: ContentTypeProfile,
    ) -> ApproverResult:
        """Compliance lead: weighs safety, accessibility and answer integrity."""
        compliance_aspects = {
            "safety_compliance", "sne_accessibility", "answer_key_integrity",
            "rubric_completeness", "source_grounding", "vector_validity",
            "materials_specified", "distractor_diagnostics",
        }
        relevant = [f for f in reviewer.feedback if f.aspect in compliance_aspects and f.status != "pending"]

        if reviewer.risk_flags:
            return ApproverResult(
                auditor="Auditor 2 (Senior Quality & Compliance Lead)",
                verdict="rejected",
                score=min(reviewer.score, 45),
                safety_verified=False,
                deliberation_notes=(
                    f"Hard invariant violated, release blocked: {'; '.join(reviewer.risk_flags[:3])}"
                ),
                ready_for_human_review=False,
            )

        compliance_score = (
            round(sum(f.score for f in relevant) / len(relevant) * 100) if relevant else reviewer.score
        )
        consensus = round((compliance_score + approver_1.score) / 2)

        if consensus >= PASS_THRESHOLD and approver_1.verdict == "approved":
            verdict = "approved"
            notes = (
                f"Consensus {consensus}/100. Safety, accessibility and answer-key integrity "
                f"verified for {ct.content_type} content."
            )
        else:
            verdict = "needs_revision"
            failing = [f.aspect.replace("_", " ") for f in relevant if f.score < 0.75][:3]
            notes = (
                f"Consensus {consensus}/100 is below the {PASS_THRESHOLD} release threshold."
                + (f" Failing compliance measures: {', '.join(failing)}." if failing else "")
            )

        return ApproverResult(
            auditor="Auditor 2 (Senior Quality & Compliance Lead)",
            verdict=verdict,
            score=consensus,
            safety_verified=True,
            deliberation_notes=notes,
            ready_for_human_review=verdict == "approved",
        )


quality_gate_service = QualityGateService()
