from __future__ import annotations

import logging
import re
from typing import Any

from ..llm_client import llm_client
from ..pipeline import pipeline_orchestrator

logger = logging.getLogger("cbc-narration-agent")


def _prompt(agent: str, *, grade: str, subject: str = "Mathematics", **slots: str) -> str:
    """One prompt, from Langfuse, with its slots filled.

    The words used to be built here in Python, which made them the only prompts
    in the system an operator could not read or change without a deploy.
    """
    from ..langfuse_context import langfuse_context_service
    from ..level_register import register_block
    from ..faith_scope import prompt_block as faith_block
    from ..notation import block_for as notation_block

    template = langfuse_context_service.get_agent_prompt(agent)
    filled = {
        "grade": grade,
        "subject": subject,
        # The same two blocks every other generator gets, so a walkthrough for
        # Grade 3 is not narrated in the register of a Grade 9 lesson.
        "level_register": register_block(grade),
        "notation": notation_block(subject, grade=grade),
        "faith_scope": faith_block(subject),
        **slots,
    }
    for slot, value in filled.items():
        template = template.replace("{{ " + slot + " }}", str(value or ""))
    return template


class NarrationAgent:
    """LLM Agent responsible for converting notes to equations, and equations to spoken words."""

    def extract_equations_from_notes(self, notes_text: str, grade: str = "grade-7",
                                     subject: str = "Mathematics") -> list[dict[str, Any]]:
        """Extract explicit and implicit mathematical equations/formulas from notes text."""
        equations: list[dict[str, Any]] = []

        # 1. Regex pass for explicit LaTeX ($...$, $$...$$) and inline math
        latex_matches = re.findall(r"\$\$?(.*?)\$\$?", notes_text)
        for m in latex_matches:
            cleaned = m.strip()
            if "=" in cleaned or any(op in cleaned for op in ("+", "-", r"\times", r"\div", r"\frac")):
                equations.append({
                    "latex": cleaned,
                    "concept": "Extracted formula",
                    "source_text": f"${cleaned}$",
                })

        # 2. Text heuristics for fractions & formulas
        heuristic_matches = [
            (r"\barea\s*=\s*(?:half\s*)?base\s*(?:\*|x|times)\s*height\b", r"A = \frac{1}{2} b h", "Area of triangle"),
            (r"\blcm\s*of\s*(\d+)\s*and\s*(\d+)\s*(?:is|=)\s*(\d+)\b", r"\text{LCM}(\1, \2) = \3", "LCM computation"),
            (r"(\d+)/(\d+)\s*\+\s*(\d+)/(\d+)", r"\frac{\1}{\2} + \frac{\3}{\4}", "Fraction addition"),
            (r"(\d+)\s*x\s*([-+])\s*(\d+)\s*=\s*(\d+)", r"\1x \2 \3 = \4", "Linear equation"),
        ]
        for pattern, latex_tmpl, name in heuristic_matches:
            for match in re.finditer(pattern, notes_text, re.IGNORECASE):
                try:
                    eq_latex = match.expand(latex_tmpl)
                except Exception:
                    eq_latex = latex_tmpl
                equations.append({
                    "latex": eq_latex,
                    "concept": name,
                    "source_text": match.group(0),
                })

        # 3. LLM extraction if we have LLM available and text is rich
        try:
            config = pipeline_orchestrator.router.resolve_for_stage("notes_generation")
            if config and len(notes_text.strip()) > 80:
                prompt = _prompt(
                    "math-equation-extractor",
                    grade=grade,
                    subject=subject,
                    notes_text=notes_text[:2000],
                )
                res = llm_client.generate(
                    config,
                    [{"role": "user", "content": prompt}],
                    temperature=0.1,
                )
                llm_eqs = res.content.get("equations") or []
                for le in llm_eqs:
                    if isinstance(le, dict) and le.get("latex"):
                        equations.append(le)
        except Exception as exc:
            logger.debug("LLM equation extraction skipped: %s", exc)

        # Deduplicate
        seen: set[str] = set()
        unique_eqs: list[dict[str, Any]] = []
        for eq in equations:
            lat = eq.get("latex", "").strip()
            if lat and lat not in seen:
                seen.add(lat)
                unique_eqs.append(eq)

        return unique_eqs

    def narrate_solution_step(
        self,
        operation: str,
        latex: str,
        expression_before: str = "",
        expression_after: str = "",
        grade: str = "grade-7",
    ) -> str:
        """Convert a mathematical step into clear, grade-appropriate spoken English."""
        clean_op = operation.strip()
        clean_latex = latex.strip()

        # Deterministic spoken representations for common operations
        if "LCM" in clean_op or "lcm" in clean_op.lower():
            return f"Step: {clean_op}. We find the common denominator so we can combine the terms: {clean_latex}."
        if "Expand" in clean_op or "expand" in clean_op.lower():
            return f"Step: {clean_op}. Multiplying out the brackets gives {clean_latex}."
        if "Subtract" in clean_op or "subtract" in clean_op.lower():
            return f"Step: {clean_op}. We balance the equation by subtracting, arriving at {clean_latex}."
        if "Add" in clean_op or "add" in clean_op.lower():
            return f"Step: {clean_op}. We add terms to both sides, which simplifies to {clean_latex}."
        if "Divide" in clean_op or "divide" in clean_op.lower():
            return f"Step: {clean_op}. Dividing both sides isolates the variable, giving {clean_latex}."
        if "Substitute" in clean_op or "substitute" in clean_op.lower():
            return f"Step: {clean_op}. Inserting the known values into the formula gives {clean_latex}."

        # Template fallback
        return f"{clean_op}. This gives {clean_latex}."

    def narrate_concept(self, concept_title: str, concept_text: str, grade: str = "grade-7",
                        subject: str = "Mathematics") -> str:
        """Generate a spoken lesson narration for audio playback in notes/examples."""
        try:
            config = pipeline_orchestrator.router.resolve_for_stage("notes_generation")
            if config and len(concept_text.strip()) > 30:
                prompt = _prompt(
                    "math-narrator",
                    grade=grade,
                    subject=subject,
                    operation=concept_title,
                    expression_before="",
                    expression_after="",
                    latex=concept_text[:500],
                )
                res = llm_client.generate(
                    config,
                    [{"role": "user", "content": prompt}],
                    temperature=0.2,
                )
                narration = res.content.get("narration")
                if narration and isinstance(narration, str):
                    return narration.strip()
        except Exception:
            pass

        return f"In this section on {concept_title}, let us examine the main concept. {concept_text[:200].strip()}."


narration_agent = NarrationAgent()
