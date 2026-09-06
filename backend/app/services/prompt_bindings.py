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

# Keys that appear in the same function but are not template variables: the
# shape of a chat message, and the shape of a model call. Crediting a whole
# function catches the bindings a closure hides, and picks these up with them.
_NOT_TEMPLATE_VARS = frozenset({
    "role", "content", "type", "text", "name", "model", "provider",
    "temperature", "max_tokens", "messages", "stream", "id", "index",
    "status", "error", "prompt", "response",
})


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
    constants = _string_constants(tree)

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

    # A function that fetches a prompt and renders it somewhere else in its own
    # body binds nothing as far as the walk above is concerned. Two real shapes
    # do this and both were reported as binding NOTHING:
    #
    #   - `_scope_chunk_reader` fetches the template, then renders it inside a
    #     nested `for_chunk` closure;
    #   - the content-type classifier builds its variables as a list of
    #     `("name", value)` tuples rather than a dict.
    #
    # Both were false positives, and a check that cries wolf is a check that
    # gets turned off. So a function naming exactly one agent is credited with
    # every variable bound anywhere inside it, closures included.
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        named = {a for a in _agents_named_in(function, constants) if a}
        if len(named) != 1:
            continue          # ambiguous: crediting either one would be a guess
        agent = named.pop()
        found.setdefault(agent, set()).update(_names_bound_in(function))

    return found


def _string_constants(tree: ast.AST) -> dict[str, str]:
    """Module-level `AGENT = "material-generator"` names.

    Several services name their agent once at the top and pass the constant.
    Reading only literals reported those as never called — including the
    material generator, which runs on every sub-strand.
    """
    out: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value.value
    return out


def _agents_named_in(function: ast.AST, constants: dict[str, str] | None = None) -> set[str]:
    """Agent names this function fetches a prompt for."""
    fetchers = ("_get_rendered_langfuse_prompt", "get_prompt", "get_agent_prompt",
                "fetch_prompt", "compile_prompt")
    out: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        name = getattr(node.func, "attr", getattr(node.func, "id", ""))
        first = node.args[0]
        if name in fetchers:
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                out.add(first.value)
            elif isinstance(first, ast.Name) and (constants or {}).get(first.id):
                out.add(constants[first.id])
        for keyword in node.keywords:
            if keyword.arg == "agent_name" and isinstance(keyword.value, ast.Constant):
                out.add(str(keyword.value.value))
    return out


def _names_bound_in(function: ast.AST) -> set[str]:
    """Every variable name bound in this function, in either shape.

    A dict key `"level_register":` and a tuple `("level_register", value)` are
    the same binding written two ways, and only one of them was being read.
    """
    import re as _re

    out: set[str] = set()
    for node in ast.walk(function):
        # A third shape: `template.replace("{{ raw_text }}", text)`. The design
        # agent binds every one of its variables this way, and reading only
        # dicts and tuples reported it as supplying nothing.
        if (isinstance(node, ast.Call)
                and getattr(node.func, "attr", "") == "replace"
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            out |= set(_re.findall(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}",
                                   node.args[0].value))
        if isinstance(node, ast.Dict):
            out |= _keys_of(node)
        elif isinstance(node, ast.Tuple) and node.elts:
            first = node.elts[0]
            if (len(node.elts) == 2 and isinstance(first, ast.Constant)
                    and isinstance(first.value, str)):
                out.add(first.value)
    return out


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


# ── the other direction ─────────────────────────────────────────────────────


def unused_bindings() -> dict[str, list[str]]:
    """Variables the code hands an agent that its prompt never asks for.

    The existing check runs one way: a prompt naming a variable nothing binds
    renders as an empty string. The reverse is just as silent and was live for
    months — thirteen call sites computed `language_block(grade)`, the block
    that says how the words must SOUND for an age, bound it as
    `language_register`, and no prompt referenced that name. The instruction
    that stops a Grade 9 guide reading like a nursery rhyme never once reached
    a model.

    A control that appears to work and does nothing is worse than no control:
    `min_visuals` was a field on the visuals request, settable from the
    console, that reached no prompt for its entire life.
    """
    import re

    from .langfuse_seed import SEED_AGENT_PROMPTS

    placeholder = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")
    out: dict[str, list[str]] = {}
    for agent, bound in all_bindings().items():
        prompt = SEED_AGENT_PROMPTS.get(agent)
        if prompt is None:
            continue
        text = prompt if isinstance(prompt, str) else str(prompt)
        asked = set(placeholder.findall(text))
        dead = sorted(bound - asked - _AUTO_INJECTED - _NOT_TEMPLATE_VARS)
        if dead:
            out[agent] = dead
    return out


def alignment_report() -> dict[str, Any]:
    """Both directions at once, for a test and for the console.

    Run whenever a prompt or a call site changes: whichever half was not
    updated is named, rather than discovered later in the content.
    """
    import re

    from .langfuse_seed import SEED_AGENT_PROMPTS

    placeholder = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")
    bindings = all_bindings()
    unsupplied: dict[str, list[str]] = {}
    for agent, prompt in SEED_AGENT_PROMPTS.items():
        if agent not in bindings:
            continue  # never called; a different problem, reported below
        text = prompt if isinstance(prompt, str) else str(prompt)
        missing = sorted(set(placeholder.findall(text))
                         - set(bindings[agent]) - _AUTO_INJECTED)
        if missing:
            unsupplied[agent] = missing

    never_called = sorted(set(SEED_AGENT_PROMPTS) - set(bindings))
    unused = unused_bindings()
    return {
        "agents": len(SEED_AGENT_PROMPTS),
        "aligned": not (unsupplied or unused),
        "unsupplied": unsupplied,
        "unused": unused,
        "never_called": never_called,
        "says": _summarise(unsupplied, unused, never_called),
    }


def _summarise(unsupplied: dict[str, list[str]], unused: dict[str, list[str]],
               never_called: list[str]) -> str:
    parts: list[str] = []
    if unsupplied:
        parts.append(
            f"{len(unsupplied)} prompt(s) name a variable nothing binds, so it "
            f"renders empty: " + ", ".join(sorted(unsupplied)) + ".")
    if unused:
        parts.append(
            f"{len(unused)} agent(s) are handed a variable their prompt never "
            f"asks for, so setting it does nothing: "
            + ", ".join(f"{a} ({', '.join(v)})" for a, v in sorted(unused.items()))
            + ".")
    if never_called:
        parts.append(
            f"{len(never_called)} prompt(s) are seeded and called by nothing: "
            + ", ".join(never_called) + ".")
    return " ".join(parts) or "Every prompt and every call site agree."
