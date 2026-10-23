"""Behaviour of `tools/no_size_gates.py` (CI job 6, C11), run as CI runs it."""

import subprocess
import sys
from pathlib import Path

import pytest

CHECK = Path(__file__).resolve().parents[1] / "no_size_gates.py"

CLEAN_WORKFLOW = "jobs:\n  backend:\n    steps:\n      - run: uv run pytest\n      - run: uv run ruff check\n"


def make_root(root: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(content, encoding="utf-8")
    return root


def run_check(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(CHECK), "--root", str(root)], capture_output=True, text=True, check=False
    )


def test_checks_without_gates_pass(tmp_path: Path) -> None:
    root = make_root(
        tmp_path,
        {".github/workflows/ci.yml": CLEAN_WORKFLOW, "Makefile": "check:\n\tuv run pytest\n"},
    )

    result = run_check(root)

    assert result.returncode == 0, result.stdout
    assert result.stdout == "no-size-gates: ok, 2 files\n"


@pytest.mark.parametrize(
    ("path", "line"),
    [
        (".github/workflows/ci.yml", "      - run: radon cc --min C src"),
        (".github/workflows/ci.yml", "      - run: test $(cat src/*.py | wc -l) -lt 5000"),
        (".github/workflows/ci.yml", "      - run: pytest --cov --cov-fail-under=90"),
        (".pre-commit-config.yaml", "        args: [--max-lines=400]"),
        ("backend/pyproject.toml", 'select = ["E", "C901"]'),
        ("frontend/eslint.config.js", '  rules: { complexity: ["error", 10] },'),
        ("frontend/vite.config.ts", "  test: { coverage: { thresholds: { lines: 80 } } },"),
        ("frontend/package.json", '    "check": "vp lint -D pedantic",'),
        ("backend/pyproject.toml", "max-complexity-allowed = 20"),
        ("Makefile", "\tcd backend && uv run complexipy --max-complexity-allowed 16"),
        ("Makefile", "\tcd backend && uv run complexipy --ignore-complexity"),
        ("frontend/vite.config.ts", '      "crawlerai/cognitive-complexity": ["error", { max: 25 }],'),
    ],
)
def test_size_complexity_or_coverage_gate_fails_with_path_and_line(tmp_path: Path, path: str, line: str) -> None:
    root = make_root(tmp_path, {path: f"# config\n{line}\n"})

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.startswith(f"{path}:2: ")
    assert result.stdout.count("\n") == 1
