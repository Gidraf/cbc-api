"""Names a route uses must exist before the request arrives.

Two 500s shipped from the same class of mistake within one session: a mirroring
block inserted above the line that assigns the variable it reads, and an import
edit that silently did not apply. Both crashed only when the endpoint ran, after
the model had been called and the tokens spent.

The interpreter cannot catch either at import time — a function body is not
executed until it is called — so these check them statically instead.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SOURCES = sorted(
    list((_ROOT / "app" / "routes").glob("*.py"))
    + list((_ROOT / "app" / "services").glob("*.py"))
)


def _builtins() -> set[str]:
    import builtins

    return set(dir(builtins))


@pytest.mark.parametrize("path", _SOURCES, ids=lambda p: p.name)
def test_no_module_uses_a_name_it_never_imports(path) -> None:
    """`citation_check` and `notes_coverage` were used in a route and imported
    nowhere: pyflakes saw it, nothing else did, and it was a 500 in production."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pyflakes", str(path)],
        capture_output=True, text=True, check=False,
    )
    undefined = [
        line for line in result.stdout.splitlines()
        if "undefined name" in line.lower()
    ]
    assert not undefined, "\n".join(undefined)


_FUNCTION = (ast.FunctionDef, ast.AsyncFunctionDef)


def _function_bodies(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, _FUNCTION):
            yield node


def _own_nodes(function: ast.AST):
    """Everything in this function EXCEPT the bodies of functions inside it.

    A nested closure has its own scope: its parameters are not reads of the
    outer function's locals, and treating them as such reported `message` — the
    parameter of a nested `fail()` — as used before a later local of the same
    name was assigned.
    """
    for statement in function.body:
        # A nested def is a statement of this function, so skipping only its
        # CHILDREN still walked its whole body — which is how the parameter of
        # a nested fail(check, message) was read as an outer local.
        if isinstance(statement, (*_FUNCTION, ast.Lambda)):
            continue
        stack = [statement]
        while stack:
            node = stack.pop()
            yield node
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (*_FUNCTION, ast.Lambda)):
                    continue
                stack.append(child)


@pytest.mark.parametrize("path", _SOURCES, ids=lambda p: p.name)
def test_no_function_reads_a_local_before_it_is_assigned(path) -> None:
    """A block moved above the line that assigns what it reads raises
    UnboundLocalError — only when the endpoint runs, after the tokens are spent.

    Deliberately conservative: only a plain top-level assignment counts, and a
    name touched inside a loop or a comprehension is skipped, because those
    legitimately read before the textually-first assignment.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    failures: list[str] = []

    for function in _function_bodies(tree):
        # A name declared global or nonlocal is not a local at all, and its
        # binding lives outside this function entirely.
        elsewhere: set[str] = set()
        for node in ast.walk(function):
            if isinstance(node, (ast.Global, ast.Nonlocal)):
                elsewhere.update(node.names)

        looped: set[str] = set()
        for node in ast.walk(function):
            if isinstance(node, (ast.For, ast.AsyncFor, ast.While, ast.comprehension,
                                 ast.ListComp, ast.DictComp, ast.SetComp,
                                 ast.GeneratorExp, ast.Lambda)):
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Name):
                        looped.add(inner.id)

        bound: dict[str, int] = {a.arg: function.lineno for a in function.args.args}
        # The EARLIEST binding, not the first one visited: the walk is not in
        # source order, so `row = ...` reassigned later was recorded as the
        # first binding and every earlier read looked premature.
        def bind(name: str, line: int) -> None:
            bound[name] = min(bound.get(name, line), line)

        for node in _own_nodes(function):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                bind(node.id, node.lineno)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bind((alias.asname or alias.name).split(".")[0], node.lineno)

        for node in _own_nodes(function):
            if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
                continue
            first = bound.get(node.id)
            if first and node.lineno < first and node.id not in looped | elsewhere:
                failures.append(
                    f"{path.name}:{node.lineno} reads '{node.id}', "
                    f"first assigned at line {first} in {function.name}()"
                )

    assert not failures, "\n".join(sorted(set(failures)))


def test_the_checker_catches_the_bug_it_was_written_for(tmp_path) -> None:
    """A block moved above the line that assigns what it reads. This shipped
    twice in one session and crashed only when the endpoint ran."""
    bad = tmp_path / "bad.py"
    bad.write_text(
        "def handler():\n"
        "    if isinstance(notes_content, dict):\n"
        "        pass\n"
        "    notes_content = fetch()\n"
        "    return notes_content\n"
    )

    with pytest.raises(AssertionError, match="notes_content"):
        test_no_function_reads_a_local_before_it_is_assigned(bad)


def test_the_checker_does_not_flag_a_reassignment(tmp_path) -> None:
    """`row = ...` twice is normal; the walk is not in source order, and taking
    the first binding visited reported every earlier read as premature."""
    ok = tmp_path / "ok.py"
    ok.write_text(
        "def handler():\n"
        "    row = first()\n"
        "    if row:\n"
        "        return row\n"
        "    row = second()\n"
        "    return row\n"
    )

    test_no_function_reads_a_local_before_it_is_assigned(ok)


def test_the_checker_does_not_flag_a_nested_closures_parameter(tmp_path) -> None:
    """A nested def has its own scope: its parameters are not outer locals."""
    ok = tmp_path / "closure.py"
    ok.write_text(
        "def handler():\n"
        "    def fail(message):\n"
        "        record(message)\n"
        "    message = build()\n"
        "    return message\n"
    )

    test_no_function_reads_a_local_before_it_is_assigned(ok)


def test_the_checker_respects_a_global_declaration(tmp_path) -> None:
    ok = tmp_path / "glob.py"
    ok.write_text(
        "_SEEDED = False\n"
        "def seed():\n"
        "    global _SEEDED\n"
        "    if _SEEDED:\n"
        "        return\n"
        "    _SEEDED = True\n"
    )

    test_no_function_reads_a_local_before_it_is_assigned(ok)
