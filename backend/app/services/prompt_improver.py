"""Turning a reviewer's complaint about the OUTPUT into a change to the PROMPT.

A reviewer reads a Grade 9 guide and writes "this explains which key on the
calculator is the minus sign". That is a defect in the prompt, not in the
guide: every future guide will do it again. Until now the only route from that
sentence to the prompt ran through a person who knew which of twenty-two
prompts to open and what to change in it.

What this does NOT do is apply the change. A prompt is the behaviour of every
generator downstream of it, and a model rewriting one on the strength of a
single complaint is how a system loses a rule nobody remembers adding. So it
proposes, validates, shows the difference, and stops.

Two models rather than one, where both are configured. They disagree usefully:
asked to fix the same complaint, one adds a rule and the other rewrites a
section, and seeing both is what tells a reviewer whether the complaint was
about a missing instruction or a badly worded one.
"""
from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("cbc-prompt-improver")

# What a proposal is asked to respect. These are not style notes: each one is a
# way an "improved" prompt has broken a pipeline.
AGENT = "prompt-improver"


def _rules() -> str:
    """The improver's own instructions, loaded like every other prompt.

    They were a Python constant, which a test caught: "a prompt written in
    Python cannot be read or improved without a deploy". That is the exact
    principle this whole feature exists to serve, and the tool for it had its
    own prompt hardcoded.
    """
    from .langfuse_context import langfuse_context_service

    return langfuse_context_service.get_agent_prompt(AGENT)



@dataclass
class Proposal:
    model: str = ""
    revised: str = ""
    changes: list[dict[str, Any]] = field(default_factory=list)
    already_covered: list[str] = field(default_factory=list)
    declined: list[dict[str, Any]] = field(default_factory=list)
    # What validation says about the revision, BEFORE anybody can save it.
    valid: bool = False
    problems: list[str] = field(default_factory=list)
    diff: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"model": self.model, "revised": self.revised,
                "changes": self.changes, "already_covered": self.already_covered,
                "declined": self.declined, "valid": self.valid,
                "problems": self.problems, "diff": self.diff,
                "error": self.error}


def _diff(before: str, after: str) -> str:
    return "\n".join(difflib.unified_diff(
        before.splitlines(), after.splitlines(),
        fromfile="serving", tofile="proposed", lineterm="", n=2))[:20_000]


def _placeholders(text: str) -> set[str]:
    import re

    return set(re.findall(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}", text or ""))


def validate(name: str, before: str, after: str) -> tuple[bool, list[str]]:
    """Whether a revision is safe to serve.

    The slot check runs here rather than only in `prompt_validators` because
    the failure it catches — a renamed placeholder — is invisible in the
    output: the prompt still looks complete and the instruction is simply gone.
    """
    problems: list[str] = []
    if not after.strip():
        return False, ["The revision is empty."]

    lost = sorted(_placeholders(before) - _placeholders(after))
    if lost:
        problems.append(
            f"It drops {', '.join(lost)}. Code binds {'those' if len(lost) > 1 else 'that'}, "
            f"so the instruction depending on it would vanish with no error.")
    added = sorted(_placeholders(after) - _placeholders(before))
    if added:
        problems.append(
            f"It adds {', '.join(added)}, which nothing supplies — "
            f"{'they' if len(added) > 1 else 'it'} would reach the model as "
            f"literal text.")

    try:
        from . import prompt_validators

        report = prompt_validators.validate(name, after)
        # Errors only. A warning is a note about a prompt that will still work,
        # and refusing a revision over one would stop every improvement that
        # made a prompt longer.
        problems.extend(f.message for f in report.errors)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Validator unavailable for %s: %s", name, exc)

    return not problems, problems


def propose(name: str, notes: list[str], *, models: list[Any] | None = None,
            current: str = "") -> list[Proposal]:
    """One proposal per model. Never applied, only offered."""
    from .langfuse_context import langfuse_context_service
    from .llm_client import llm_client
    from .pipeline import pipeline_orchestrator

    import json

    before = current or langfuse_context_service.get_agent_prompt(name)
    if not before:
        return [Proposal(error=f"No prompt is serving as '{name}'.")]
    if not notes:
        return [Proposal(error="No reviewer notes to act on.")]

    if not models:
        models = [pipeline_orchestrator.router.resolve_for_stage("question_generation")]

    asked = (
        f"{_rules()}\n\n=== THE PROMPT, AS IT IS SERVING ===\n{before}\n\n"
        f"=== WHAT REVIEWERS SAID ABOUT ITS OUTPUT ===\n"
        + "\n".join(f"  {i}. {n}" for i, n in enumerate(notes, start=1))
    )

    out: list[Proposal] = []
    for resolved in models:
        model_name = str(getattr(resolved, "model", "") or "model")
        proposal = Proposal(model=model_name)
        try:
            response = llm_client.generate(
                resolved, [{"role": "user", "content": asked}], temperature=0.1)
            payload = response.content
            if isinstance(payload, str):
                payload = json.loads(payload)
            proposal.revised = str((payload or {}).get("revised") or "")
            proposal.changes = [c for c in ((payload or {}).get("changes") or [])
                                if isinstance(c, dict)]
            proposal.already_covered = [str(a) for a in
                                        ((payload or {}).get("already_covered") or [])]
            proposal.declined = [d for d in ((payload or {}).get("declined") or [])
                                 if isinstance(d, dict)]
        except Exception as exc:  # noqa: BLE001
            logger.warning("No proposal from %s for %s: %s", model_name, name, exc)
            proposal.error = str(exc)[:300]
            out.append(proposal)
            continue

        if proposal.revised:
            proposal.valid, proposal.problems = validate(name, before, proposal.revised)
            proposal.diff = _diff(before, proposal.revised)
        else:
            proposal.error = "The model returned no revised text."
        out.append(proposal)
    return out
