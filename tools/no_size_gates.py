"""Fail when a workflow, hook or tool config adds a size, complexity or coverage gate (SPEC-00 §4.6, INV-18, C11).

Scans the CI workflows, the local hooks and `make check`, and the configs of the tools they run, for the flags,
rules and tools that turn line counts, complexity or a coverage percentage into a failing check. Prints
`path:line: line` per match and exits 1, or prints one summary line and exits 0.
"""

import argparse
import re
import sys
from pathlib import Path

# Where a gate could be switched on: CI, the hooks, `make check`, and the configs of the linters and test runners
# those call.
SCANNED = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    ".pre-commit-config.yaml",
    "Makefile",
    "backend/pyproject.toml",
    "tools/ruff.toml",
    "frontend/package.json",
    "frontend/eslint.config.*",
    "frontend/vite.config.*",
    "frontend/oxlint.config.*",
    "frontend/.oxlintrc.json",
    "frontend/vitest.config.*",
)

GATES = re.compile(
    "|".join(
        (
            # Complexity and line-count tools.
            r"\b(?:radon|xenon|cloc|tokei)\b",
            r"\bwc\s+-l\b",
            # Size and complexity limits: flake8/ruff mccabe, pylint and ESLint/Oxlint rules.
            r"max[-_](?:lines|module-lines|complexity|statements|branches|args|params|returns|depth|nested)",
            r"\bmccabe\b",
            r"\bC90\d?\b",
            r"\bPLR09\d*\b",
            r"\btoo-many-",
            r"(?<![\w-])[\"']?complexity[\"']?\s*:",
            # Oxlint categories that switch on max-* and complexity as a group: pedantic (max-depth, max-lines,
            # max-lines-per-function), style (max-params, max-statements), restriction (complexity).
            r"(?<![\w-])[\"']?(?:pedantic|style|restriction)[\"']?\s*:\s*[\"']?(?:warn|error|deny)\b",
            r"(?:-[WD]|--warn|--deny)[\s=]+(?:pedantic|style|restriction)\b",
            # Coverage thresholds: pytest-cov and coverage.py, c8 and nyc, Vitest, Jest.
            r"fail[-_]under",
            r"check-coverage",
            r"\bthresholds\b",
            r"coverageThreshold",
        )
    )
)


def scanned_files(root: Path) -> list[Path]:
    return sorted({path for pattern in SCANNED for path in root.glob(pattern) if path.is_file()})


def check(root: Path) -> tuple[list[str], int]:
    """Return one `path:line: line` per gate found, and the number of files scanned."""
    files = scanned_files(root)
    findings: list[str] = []
    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        relative = path.relative_to(root).as_posix()
        findings.extend(
            f"{relative}:{number}: {line.strip()}" for number, line in enumerate(lines, 1) if GATES.search(line)
        )
    return findings, len(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="repository root")
    args = parser.parse_args(argv)

    findings, scanned = check(args.root)
    for finding in findings:
        print(finding)
    if findings:
        return 1
    print(f"no-size-gates: ok, {scanned} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
