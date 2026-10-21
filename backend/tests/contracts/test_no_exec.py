"""INV-17: LLM output is never executed. ruff's S102 and S307 catch `exec` and `eval`
calls; this scan also catches `compile` and imports of `subprocess`, which ruff's S rules only flag at the call."""

import ast
from pathlib import Path
from typing import TypeGuard

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"

# Builtins that turn a string into running code.
CODE_BUILTINS = frozenset({"exec", "eval", "compile"})


def violations(path: Path, tree: ast.AST) -> list[str]:
    relative = path.relative_to(SRC).as_posix()
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in CODE_BUILTINS:
            found.append(f"{relative}:{node.lineno} calls {node.func.id}")
        if _imports_subprocess(node):
            found.append(f"{relative}:{node.lineno} imports subprocess")
    return found


def _imports_subprocess(node: ast.AST) -> TypeGuard[ast.Import | ast.ImportFrom]:
    if isinstance(node, ast.Import):
        return any(alias.name.split(".")[0] == "subprocess" for alias in node.names)
    return isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "subprocess"


def scan(root: Path) -> list[str]:
    return [found for path in sorted(root.rglob("*.py")) for found in violations(path, ast.parse(path.read_bytes()))]


def test_no_module_executes_code_or_starts_a_process() -> None:
    assert scan(SRC) == []


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("exec(reply)\n", "crawlerai/planted.py:1 calls exec"),
        ("import subprocess\n", "crawlerai/planted.py:1 imports subprocess"),
    ],
)
def test_the_scan_finds_each_kind(code: str, expected: str) -> None:
    path = SRC / "crawlerai" / "planted.py"
    assert violations(path, ast.parse(code)) == [expected]
