"""Repairing an item that failed a check, instead of throwing it away.

The structure gate holds a malformed question before a person can waste
attention on it — a multiple-choice item with two options, a "structured"
question with one part, a calculation carrying four marks and no scheme to
award them against. Holding it is right. Discarding it is not: the item was
generated, paid for, and is usually wrong in exactly one nameable way.

At 500 items a day the difference between repairing and regenerating is the
difference between recovering the work and buying it twice.

The prompt for this has been seeded since the beginning and nothing ever called
it. Its own rules are the reason it is worth calling rather than regenerating:
fix only what the failures name, keep every untouched field byte for byte, and
where a failure cannot be fixed from the design in front of you, say so rather
than inventing a value — "inventing a value to clear a check is worse than the
check failing: it is the same defect, now invisible".
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-content-repair")

AGENT = "content-repair"

# One attempt. A second pass on an item the first could not fix is paying twice
# for the same answer, and the gate will hold it either way.
ATTEMPTS = 1


@dataclass
class Outcome:
    repaired: list[dict[str, Any]] = field(default_factory=list)
    still_broken: list[dict[str, Any]] = field(default_factory=list)
    changes: list[dict[str, Any]] = field(default_factory=list)
    unrepairable: list[dict[str, Any]] = field(default_factory=list)
    attempted: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"attempted": self.attempted, "repaired": len(self.repaired),
                "still_broken": len(self.still_broken),
                "changes": self.changes[:40],
                "unrepairable": self.unrepairable[:20],
                "says": self.summary()}

    def summary(self) -> str:
        if not self.attempted:
            return "Nothing needed repairing."
        if not self.repaired:
            return (f"{self.attempted} item(s) failed the structure gate and "
                    f"none could be repaired from the design in front of them.")
        return (f"{self.repaired and len(self.repaired)} of {self.attempted} "
                f"item(s) that failed the structure gate were repaired and now "
                f"pass it. The rest are held with their reasons.")


def repair_questions(items: list[dict[str, Any]], verdicts: list[dict[str, Any]],
                     *, grade: str, subject: str, design_extract: str = "",
                     resolved: Any = None) -> Outcome:
    """One repair pass over the items the structure gate blocked.

    Re-checked afterwards by the same gate that blocked them: a repair nobody
    verified is a claim, and the whole point of the gate is that claims about
    an item's shape are not taken on trust.
    """
    from . import question_structure
    from .langfuse_context import langfuse_context_service
    from .llm_client import llm_client
    from .level_register import language_block, register_block, teacher_block
    from . import notation as notation_module
    from . import prompt_fragments
    from .faith_scope import prompt_block as faith_block

    outcome = Outcome()
    blocked = {v.get("question_id"): v for v in (verdicts or []) if v.get("blocked")}
    if not blocked or not items:
        return outcome

    if resolved is None:
        from .pipeline import pipeline_orchestrator

        resolved = pipeline_orchestrator.router.resolve_for_stage("question_generation")

    template = langfuse_context_service.get_agent_prompt(AGENT)
    surviving: list[dict[str, Any]] = []

    for item in items:
        verdict = blocked.get(str(item.get("question_id") or ""))
        if not verdict:
            surviving.append(item)
            continue

        outcome.attempted += 1
        failures = [
            f"{f.get('says')} — {f.get('fix')}"
            for f in (verdict.get("findings") or [])
            if f.get("severity") == question_structure.BLOCKS
        ]
        prompt = langfuse_context_service._render_template(template, {
            "grade": grade, "subject": subject,
            "validation_failures": "\n".join(f"  - {f}" for f in failures),
            "content_to_repair": json.dumps(item, ensure_ascii=False, default=str),
            "design_extract": design_extract or "(no design extract available)",
            "level_register": register_block(grade),
            "teacher_band": teacher_block(grade),
            "language_register": language_block(grade),
            "notation": notation_module.for_prompt(subject, grade=grade),
            "domain_directives": prompt_fragments.compose(subject, "questions", grade),
            "faith_scope": faith_block(subject),
        })

        try:
            response = llm_client.generate(
                resolved, [{"role": "user", "content": prompt}], temperature=0.1)
            payload = response.content
            if isinstance(payload, str):
                payload = json.loads(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not repair %s: %s", item.get("question_id"), exc)
            outcome.still_broken.append(item)
            continue

        mended = payload.get("repaired") if isinstance(payload, dict) else None
        if not isinstance(mended, dict):
            outcome.still_broken.append(item)
            continue

        # Re-checked by the gate that blocked it. A repair nobody verified is a
        # claim, and this gate exists because claims are not taken on trust.
        after = question_structure.check(mended)
        outcome.changes.extend(
            c for c in (payload.get("changes") or []) if isinstance(c, dict))
        outcome.unrepairable.extend(
            u for u in (payload.get("unrepairable") or []) if isinstance(u, dict))

        if after.blocked:
            logger.info("Repair of %s did not clear the gate: %s",
                        item.get("question_id"),
                        "; ".join(f.code for f in after.findings))
            outcome.still_broken.append(item)
            continue

        outcome.repaired.append(mended)
        surviving.append(mended)

    outcome.repaired = [m for m in outcome.repaired]
    return outcome
