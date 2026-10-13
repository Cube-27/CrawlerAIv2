"""Behaviour of `tools/no_size_gates.py` (SPEC-00 §4.6 job 6, INV-18, C11), run as CI runs it."""

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
        (".github/workflows/ci.yml", "      - run: xenon --max-absolute B src"),
        (".github/workflows/ci.yml", "      - run: cloc src"),
        (".github/workflows/ci.yml", "      - run: test $(cat src/*.py | wc -l) -lt 5000"),
        (".github/workflows/lint.yaml", "      - run: flake8 --max-complexity 10"),
        (".github/workflows/ci.yml", "      - run: pytest --cov --cov-fail-under=90"),
        (".pre-commit-config.yaml", "        args: [--max-lines=400]"),
        ("Makefile", "\tnpx c8 --check-coverage --lines 80 vitest run"),
        ("backend/pyproject.toml", "[tool.ruff.lint.mccabe]"),
        ("backend/pyproject.toml", 'select = ["E", "C901"]'),
        ("backend/pyproject.toml", 'extend-select = ["PLR0915"]'),
        ("backend/pyproject.toml", "fail_under = 90"),
        ("tools/ruff.toml", 'select = ["C90"]'),
        ("frontend/eslint.config.js", '  rules: { "max-lines-per-function": ["error", 50] },'),
        ("frontend/eslint.config.js", '  rules: { complexity: ["error", 10] },'),
        ("frontend/eslint.config.js", '  rules: { "max-statements": ["error", 20] },'),
        ("frontend/vite.config.ts", "  test: { coverage: { thresholds: { lines: 80 } } },"),
        ("frontend/vite.config.ts", '  lint: { rules: { "eslint/max-lines": ["error", 300] } },'),
        ("frontend/vite.config.ts", '    categories: { pedantic: "error" },'),
        ("frontend/vite.config.ts", '      style: "warn",'),
        ("frontend/.oxlintrc.json", '  "categories": { "restriction": "error" },'),
        ("frontend/oxlint.config.ts", '  rules: { "eslint/complexity": ["error", 10] },'),
        ("frontend/package.json", '    "check": "vp lint -D pedantic",'),
        ("frontend/package.json", '    "check": "vp lint --deny=style",'),
        ("frontend/package.json", '  "jest": { "coverageThreshold": { "global": { "lines": 80 } } }'),
        # The complexity check with any threshold but 15, or with complexipy's ratchet or report-only modes.
        ("backend/pyproject.toml", "max-complexity-allowed = 20"),
        ("Makefile", "\tcd backend && uv run complexipy --max-complexity-allowed 16"),
        # The limit is set only in config: a flag would be a second place to change it.
        (".pre-commit-config.yaml", "        entry: uv run complexipy --max-complexity-allowed 15"),
        ("Makefile", "\tcd backend && uv run complexipy --max-complexity-allowed=150"),
        ("backend/pyproject.toml", "snapshot-create = true"),
        (".github/workflows/ci.yml", "      - run: uv run complexipy --snapshot-ignore"),
        ("Makefile", "\tcd backend && uv run complexipy --ignore-complexity"),
        ("backend/pyproject.toml", "ignore-complexity = true"),
        ("frontend/vite.config.ts", '      "crawlerai/cognitive-complexity": ["error", { max: 25 }],'),
        ("frontend/vite.config.ts", '      "crawlerai/cognitive-complexity": ["warn", { max: 15 }],'),
        ("frontend/vite.config.ts", '      "complexity/complexity": ["error", { cognitive: 15 }],'),
    ],
)
def test_size_complexity_or_coverage_gate_fails_with_path_and_line(tmp_path: Path, path: str, line: str) -> None:
    root = make_root(tmp_path, {path: f"# config\n{line}\n"})

    result = run_check(root)

    assert result.returncode == 1
    assert result.stdout.startswith(f"{path}:2: ")
    assert result.stdout.count("\n") == 1


def test_a_style_key_that_is_not_an_oxlint_category_severity_passes(tmp_path: Path) -> None:
    root = make_root(tmp_path, {"frontend/vite.config.ts": '  css: { modules: { style: "camelCase" } },\n'})

    result = run_check(root)

    assert result.returncode == 0, result.stdout
    assert result.stdout == "no-size-gates: ok, 1 files\n"


def test_files_outside_workflows_hooks_and_tool_configs_are_not_scanned(tmp_path: Path) -> None:
    root = make_root(
        tmp_path,
        {
            ".github/workflows/ci.yml": CLEAN_WORKFLOW,
            "docs/ENGINEERING.md": "Do not add radon, xenon or --cov-fail-under (C11).\n",
            "backend/src/crawlerai/core/notes.py": "# max-lines is not a gate here\n",
        },
    )

    result = run_check(root)

    assert result.returncode == 0, result.stdout
    assert result.stdout == "no-size-gates: ok, 1 files\n"


def test_every_finding_is_reported(tmp_path: Path) -> None:
    root = make_root(
        tmp_path,
        {
            ".github/workflows/ci.yml": "      - run: radon cc src\n      - run: pytest --cov-fail-under=80\n",
            "Makefile": "check:\n\txenon src\n",
        },
    )

    result = run_check(root)

    assert result.returncode == 1
    assert [line.split(": ")[0] for line in result.stdout.splitlines()] == [
        ".github/workflows/ci.yml:1",
        ".github/workflows/ci.yml:2",
        "Makefile:2",
    ]


def test_the_complexity_limit_of_15_and_the_file_length_warning_pass(tmp_path: Path) -> None:
    root = make_root(
        tmp_path,
        {
            "backend/pyproject.toml": "[tool.complexipy]\nmax-complexity-allowed=15\nfailed = true\n",
            "Makefile": "check-complexity:\n\tcd backend && uv run complexipy --no-ignore\n",
            "frontend/vite.config.ts": (
                '    jsPlugins: [{ name: "crawlerai", specifier: "./lint/cognitive-complexity.js" }],\n'
                '      "crawlerai/cognitive-complexity": ["error", { max: 15 }],\n'
                '      "crawlerai/cognitive-complexity": [ "error", {max:15} ],\n'
            ),
            ".github/workflows/ci.yml": "      - run: python3 tools/file_length.py\n",
        },
    )

    result = run_check(root)

    assert result.returncode == 0, result.stdout
    assert result.stdout == "no-size-gates: ok, 4 files\n"
