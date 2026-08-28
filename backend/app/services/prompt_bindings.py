"""Which template variables the code actually supplies to each agent.

Read from the call sites rather than kept by hand: a hand-kept list is exactly
the thing that goes stale, and the defect it exists to catch — a prompt naming
a variable nothing binds, which renders as an empty string and silently drops
whatever instruction depended on it — is invisible either way until content
comes back wrong.

This was found the hard way. The note generator gained {{ design_extract }} and
{{ time_allocation }} and ran with both slots stripped; an AST sweep then found
eight more sites dropping slo_id, level, concept, diagram_info and notes_title.
"""
from __future__ import annotations

import ast
import functools
import logging
import pathlib
from typing import Any

logger = logging.getLogger("cbc-prompt-bindings")

# Where the calls live. Narrow on purpose: a wider sweep picks up test doubles
# and reports bindings that no running code supplies.
_SOURCES = ("routes", "services")

# assemble_agent_context injects these from its own arguments, before it merges
# whatever the call site passed. Missing them made every authoring prompt look
# as though it asked for a grade nobody supplied.
_AUTO_INJECTED = frozenset({"grade", "subject", "subject_context"})


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent.parent


def _keys_of(node: ast.AST) -> set[str]:
    """The literal keys of a dict expression, ignoring anything computed."""
    if not isinstance(node, ast.Dict):
        return set()
    return {
        k.value for k in node.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }


def _dict_assignments(tree: ast.AST) -> dict[str, set[str]]:
    """Locals assigned a dict literal, so `template_vars = {...}` is seen.

    Most call sites build the variables into a local first. Reading only inline
    dicts reported the note generator as binding six variables when it binds
    eighteen — and the missing twelve would have been flagged as unbound.
    """
    assigned: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.setdefault(target.id, set()).update(_keys_of(node.value))
    return assigned


def _resolve(node: ast.AST, assigned: dict[str, set[str]]) -> set[str]:
    """The keys of a dict expression, or of the local a Name points at."""
    if isinstance(node, ast.Name):
        return set(assigned.get(node.id, set()))
    if isinstance(node, ast.Dict):
        keys = _keys_of(node)
        # {**base, "extra": ...} — follow the spread too.
        for key, value in zip(node.keys, node.values):
            if key is None:
                keys |= _resolve(value, assigned)
        return keys
    return set()


def _scan(tree: ast.AST) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    assigned = _dict_assignments(tree)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        agent = ""
        variables: set[str] = set()
        for keyword in node.keywords:
            if keyword.arg == "agent_name" and isinstance(keyword.value, ast.Constant):
                agent = str(keyword.value.value)
            elif keyword.arg in ("template_vars", "variables"):
                variables |= _resolve(keyword.value, assigned)
        # compile_prompt("name", vars_dict) — positional, and the dict is a
        # variable, so the keys are not statically knowable. Recorded as seen
        # with no bindings rather than as an agent that binds nothing.
        if not agent and node.args and isinstance(node.args[0], ast.Constant):
            callee = node.func
            name = getattr(callee, "attr", getattr(callee, "id", ""))
            if name == "compile_prompt" and isinstance(node.args[0].value, str):
                agent = str(node.args[0].value)
                if len(node.args) > 1:
                    variables |= _resolve(node.args[1], assigned)

        # `_get_rendered_langfuse_prompt("curriculum-extractor", …)` and
        # `get_prompt("…")` are calls too. Missing them reported live prompts as
        # unused, which is the opposite of the signal this is for.
        if not agent and node.args and isinstance(node.args[0], ast.Constant):
            callee = node.func
            name = getattr(callee, "attr", getattr(callee, "id", ""))
            if name in ("_get_rendered_langfuse_prompt", "get_prompt",
                        "get_agent_prompt", "fetch_prompt"):
                value = node.args[0].value
                if isinstance(value, str):
                    agent = value

        if agent:
            found.setdefault(agent, set()).update(variables)
            if any(k.arg == "agent_name" for k in node.keywords):
                found[agent].update(_AUTO_INJECTED)

    return found


@functools.lru_cache(maxsize=1)
def all_bindings() -> dict[str, frozenset[str]]:
    """Every agent the code calls, and the variables it hands each one."""
    root = _repo_root()
    merged: dict[str, set[str]] = {}

    for folder in _SOURCES:
        for path in (root / folder).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, OSError) as exc:  # noqa: PERF203
                logger.debug("Skipped %s: %s", path, exc)
                continue
            for agent, variables in _scan(tree).items():
                merged.setdefault(agent, set()).update(variables)

    return {agent: frozenset(v) for agent, v in merged.items()}


@functools.lru_cache(maxsize=1)
def raw_fetched() -> frozenset[str]:
    """Agents whose prompt is fetched as text and framed by hand-built messages.

    Their source document arrives as an appended message rather than through a
    template slot, so a missing {{ source_material_text }} is not the defect it
    would be in a prompt that is rendered whole.
    """
    root = _repo_root()
    found: set[str] = set()
    for folder in _SOURCES:
        for path in (root / folder).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, OSError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                if not isinstance(node.args[0], ast.Constant):
                    continue
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                if name in ("get_agent_prompt", "_get_rendered_langfuse_prompt"):
                    value = node.args[0].value
                    if isinstance(value, str):
                        found.add(value)
    return frozenset(found)


def bindings_for(agent: str) -> set[str]:
    """What this agent is given. Empty when the agent is never called in code,
    which is itself worth knowing — an unused prompt cannot be validated against
    bindings that do not exist."""
    return set(all_bindings().get(agent, frozenset()))


# Fetched by a dedicated reader rather than by name at a call site.
_READ_ELSEWHERE = frozenset({"BECF", "cbc-master-context"})


def unused_agents(seeded: list[str]) -> list[str]:
    """Prompts that are seeded and never read. `layer-reviewer` was one: pushed
    to Langfuse on every deploy, edited by nobody, read by nothing."""
    called = set(all_bindings()) | _READ_ELSEWHERE
    return sorted(name for name in seeded if name not in called)
