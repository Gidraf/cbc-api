"""Every placeholder a prompt uses must be supplied by the route that calls it.

A missing one used to reach the model as the literal text "{{ level_register }}",
so a prompt that told the agent nothing about its audience looked complete in the
console and produced pre-primary content pitched at a secondary student. The
Langfuse text was right; the caller simply never passed the variable.
"""
from __future__ import annotations

import ast
import inspect
import re

import pytest

from app.services.langfuse_seed import SEED_AGENT_PROMPTS

ROUTE_MODULES = ("app.routes.curriculum", "app.routes.questions")

# Supplied by assemble_agent_context itself, not by the caller.
PROVIDED_BY_ASSEMBLER = {"grade", "subject", "subject_context"}


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{\{\s*(\w+)\s*\}\}", text))


def _template_vars_by_agent() -> dict[str, list[set[str]]]:
    """The keys each call site passes, per agent, read from the source."""
    found: dict[str, list[set[str]]] = {}
    for module_name in ROUTE_MODULES:
        module = __import__(module_name, fromlist=["*"])
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "assemble_agent_context"):
                continue

            agent = None
            keys: set[str] | None = None
            for kw in node.keywords:
                if kw.arg == "agent_name" and isinstance(kw.value, ast.Constant):
                    agent = kw.value.value
                elif kw.arg == "template_vars":
                    keys = _dict_keys(kw.value, tree)
            if agent and keys is not None:
                found.setdefault(agent, []).append(keys)
    return found


def _dict_keys(node: ast.AST, tree: ast.AST) -> set[str] | None:
    """The string keys of a dict literal, or of a name bound to one.

    Some call sites build template_vars into a variable first. Reading only
    literals reported those as passing nothing, which is a false alarm that
    would train everyone to ignore this test.
    """
    if isinstance(node, ast.Dict):
        return {
            k.value for k in node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
    if isinstance(node, ast.Name):
        for other in ast.walk(tree):
            if not isinstance(other, ast.Assign):
                continue
            for target in other.targets:
                if isinstance(target, ast.Name) and target.id == node.id:
                    if isinstance(other.value, ast.Dict):
                        return _dict_keys(other.value, tree)
        return None  # cannot resolve; do not claim it is empty
    return None


CALL_SITES = _template_vars_by_agent()


def test_the_route_call_sites_were_actually_found() -> None:
    """If this fails the test below is vacuous and proves nothing."""
    assert CALL_SITES, "no assemble_agent_context call sites parsed"
    assert "strand-generator" in CALL_SITES
    assert "substrand-generator" in CALL_SITES


@pytest.mark.parametrize("agent", sorted(CALL_SITES))
def test_every_placeholder_is_supplied_by_its_caller(agent: str) -> None:
    template = SEED_AGENT_PROMPTS.get(agent)
    if template is None:
        pytest.skip(f"{agent} has no seeded template")

    required = _placeholders(template) - PROVIDED_BY_ASSEMBLER

    for keys in CALL_SITES[agent]:
        missing = required - keys
        assert not missing, (
            f"{agent} uses {sorted(missing)} but the route does not pass "
            f"{'it' if len(missing) == 1 else 'them'}. They would render as literal "
            f"'{{{{ {sorted(missing)[0]} }}}}' text in the prompt."
        )


def test_an_unsupplied_placeholder_is_stripped_not_sent_to_the_model() -> None:
    from app.services.langfuse_context import langfuse_context_service as service

    rendered = service._render_template(
        "AUDIENCE:\n{{ level_register }}\n{{ faith_scope }}\nGrade: {{ grade }}",
        {"grade": "grade-pp1"},
    )

    assert "{{" not in rendered and "}}" not in rendered
    assert "level_register" not in rendered
    assert "grade-pp1" in rendered


def test_the_strand_prompt_now_knows_who_it_is_writing_for() -> None:
    """The bug as observed: strand-generator v60 rendered with three literal
    placeholders under "=== WHO THIS IS FOR ===" ."""
    keys = CALL_SITES["strand-generator"][0]

    assert "level_register" in keys
    assert "faith_scope" in keys
    assert "content_type_directives" in keys
    assert "source_material_text" in keys


def test_a_stored_template_keeps_the_placeholders_it_is_meant_to_keep() -> None:
    """The extractor stores per-sub-strand prompts at ingest time with only the
    curriculum variables bound; notes_content and the rest are filled at
    generation time. Stripping them there destroyed the stored template and
    logged a warning for a case working exactly as intended."""
    from app.services.langfuse_context import langfuse_context_service as service

    template = "Strand: {{ strand }}\nNotes:\n{{ notes_content }}\nWho:\n{{ level_register }}"
    stored = service._render_template(template, {"strand": "Reading"}, partial=True)

    assert "Reading" in stored
    assert "{{ notes_content }}" in stored, "the later-bound placeholder must survive"
    assert "{{ level_register }}" in stored


def test_the_extractor_stores_templates_partially(monkeypatch) -> None:
    """Verifying the flag is actually passed, not merely available."""
    import inspect

    from app.services import curriculum_extractor as extractor

    source = inspect.getsource(extractor.CurriculumExtractorService)
    index = source.index("_get_rendered_langfuse_prompt")
    body = source[index:index + 700]

    assert "partial=True" in body, (
        "the extractor must render stored templates partially, or every stored "
        "prompt loses the placeholders generation depends on"
    )
