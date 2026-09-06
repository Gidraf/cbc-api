"""Does this content serve the outcomes, and is it pitched at the right person?

Two prompts had been seeded since the beginning and nothing ever called them.
Both answer a question the mechanical gates cannot:

  `slo-aligner`    Artifact counts say how much was produced; only outcome
                   coverage says whether the curriculum was actually taught.
                   Ten questions all testing one outcome look identical to ten
                   questions covering the sub-strand until someone checks.
  `layer-reviewer` Whether the content is pitched for the learner it names —
                   and, now, for the TEACHER who has to read it. A Grade 9
                   guide that explains which key on a calculator is the minus
                   sign is correct for its learner and wrong for its reader.

Neither replaces the mechanical gates. Those decide whether an item has the
right shape; these two decide whether it is the right content, which is not a
question that can be answered by counting.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-content-fit")

ALIGNER = "slo-aligner"
REVIEWER = "layer-reviewer"


@dataclass
class Fit:
    coverage_percentage: int = 0
    covered: list[dict[str, Any]] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)
    unattached: list[str] = field(default_factory=list)
    level_score: int = 0
    level_status: str = ""
    level_feedback: list[dict[str, Any]] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    teacher_band: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def ran(self) -> bool:
        return bool(self.covered or self.uncovered or self.level_status)

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage_percentage": self.coverage_percentage,
            "covered": self.covered, "uncovered": self.uncovered,
            "unattached": self.unattached,
            "level_score": self.level_score, "level_status": self.level_status,
            "level_feedback": self.level_feedback,
            "risk_flags": self.risk_flags,
            "teacher_band": self.teacher_band,
            "errors": self.errors,
            "says": self.summary(),
        }

    def summary(self) -> str:
        if not self.ran:
            return "Neither check could be run." + (
                " " + "; ".join(self.errors) if self.errors else "")
        parts = []
        if self.uncovered:
            parts.append(
                f"{len(self.uncovered)} outcome(s) have nothing serving them: "
                + "; ".join(self.uncovered[:3]) + ".")
        elif self.covered:
            parts.append(f"Every outcome is served ({self.coverage_percentage}%).")
        if self.level_status:
            parts.append(f"Pitch: {self.level_status} at {self.level_score}/100.")
        if self.unattached:
            parts.append(f"{len(self.unattached)} piece(s) serve no outcome.")
        return " ".join(parts)


def _ask(agent: str, variables: dict[str, Any], resolved: Any) -> dict[str, Any]:
    from .langfuse_context import langfuse_context_service
    from .llm_client import llm_client

    template = langfuse_context_service.get_agent_prompt(agent)
    prompt = langfuse_context_service._render_template(template, variables)
    response = llm_client.generate(
        resolved, [{"role": "user", "content": prompt}], temperature=0.1)
    payload = response.content
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload if isinstance(payload, dict) else {}


def check(content: Any, *, grade: str, subject: str, strand: str,
          sub_strand: str, slos: list[Any], layer_name: str = "content",
          resolved: Any = None) -> Fit:
    """Run both, and report what each found.

    They are run independently and one failing does not lose the other: a
    coverage report with no pitch review is still worth reading, and the
    reverse is true too.
    """
    from . import notation as notation_module
    from . import prompt_fragments
    from .faith_scope import prompt_block as faith_block
    from .level_register import language_block, register_block, teacher_block

    fit = Fit(teacher_band=teacher_block(grade))
    if resolved is None:
        from .pipeline import pipeline_orchestrator

        resolved = pipeline_orchestrator.router.resolve_for_stage("question_generation")

    body = json.dumps(content, ensure_ascii=False, default=str)[:40_000]
    outcomes = json.dumps(slos or [], ensure_ascii=False, default=str)
    shared = {
        "grade": grade, "subject": subject, "strand": strand,
        "sub_strand": sub_strand, "slos": outcomes,
        "level_register": register_block(grade),
        "teacher_band": fit.teacher_band,
        "language_register": language_block(grade),
        "notation": notation_module.for_prompt(subject, grade=grade),
        "domain_directives": prompt_fragments.compose(subject, "notes", grade),
        "faith_scope": faith_block(subject),
    }

    # 1. Which outcomes the content actually serves.
    if slos:
        try:
            found = _ask(ALIGNER, {**shared, "content_to_align": body}, resolved)
            fit.covered = [c for c in (found.get("coverage") or []) if isinstance(c, dict)]
            fit.uncovered = [str(u) for u in (found.get("uncovered") or [])]
            fit.unattached = [str(u) for u in (found.get("unattached") or [])]
            fit.coverage_percentage = int(found.get("coverage_percentage") or 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Outcome alignment failed for %s: %s", sub_strand, exc)
            fit.errors.append(f"Outcome coverage could not be measured: {exc}"[:200])
    else:
        fit.errors.append(
            "This sub-strand's design carries no learning outcomes, so there is "
            "nothing to measure coverage against. Ingest a fuller design.")

    # 2. Whether it is pitched for the learner AND for the teacher reading it.
    try:
        from .content_type_classifier import classify_content_type

        profile = classify_content_type(subject, grade, sub_strand)
        verdict = _ask(REVIEWER, {
            **shared,
            "layer_name": layer_name,
            "content_to_review": body,
            "content_type_directives": profile.format_for_prompt(),
        }, resolved)
        fit.level_score = int(verdict.get("score") or 0)
        fit.level_status = str(verdict.get("status") or "")
        fit.level_feedback = [f for f in (verdict.get("feedback") or [])
                              if isinstance(f, dict)]
        fit.risk_flags = [str(r) for r in (verdict.get("risk_flags") or [])]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Level review failed for %s: %s", sub_strand, exc)
        fit.errors.append(f"Pitch could not be reviewed: {exc}"[:200])

    return fit
