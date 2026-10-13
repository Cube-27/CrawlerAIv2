"""Behaviour of `tools/file_length.py` (C11, INV-18): a warning per long source file, never a failure."""

import os
import subprocess
import sys
from pathlib import Path

from scan_repo import make_repo

CHECK = Path(__file__).resolve().parents[1] / "file_length.py"


def lines(count: int) -> str:
    return "x = 1\n" * count


def run_check(root: Path, *, github: bool = False) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "GITHUB_ACTIONS"}
    if github:
        env["GITHUB_ACTIONS"] = "true"
    return subprocess.run(  # noqa: S603
        [sys.executable, str(CHECK), "--root", str(root)], capture_output=True, text=True, check=False, env=env
    )


def test_a_source_file_over_800_lines_warns_and_passes(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {"backend/src/long.py": lines(801), "frontend/src/Short.tsx": lines(800)})

    result = run_check(root)

    assert result.returncode == 0
    assert result.stdout == (
        "warning: backend/src/long.py has 801 lines, over the soft limit of 800. "
        "Split it along logical boundaries, not to meet the number.\n"
        "file-length: 1 of 2 source files over 800 lines (a warning, not a failure)\n"
    )


def test_in_github_actions_a_warning_is_an_annotation_on_the_file(tmp_path: Path) -> None:
    root = make_repo(tmp_path, {"tools/long.sh": lines(900)})

    result = run_check(root, github=True)

    assert result.returncode == 0
    assert result.stdout.splitlines()[0] == (
        "::warning file=tools/long.sh::tools/long.sh has 900 lines, over the soft limit of 800. "
        "Split it along logical boundaries, not to meet the number."
    )


def test_documents_generated_files_and_untracked_files_are_not_counted(tmp_path: Path) -> None:
    root = make_repo(
        tmp_path,
        {
            "docs/LONG.md": lines(2000),
            "frontend/src/api/schema.d.ts": lines(2000),
            "frontend/src/ok.ts": lines(10),
        },
    )
    (root / "untracked.py").write_text(lines(2000), encoding="utf-8")

    result = run_check(root)

    assert result.returncode == 0
    assert result.stdout == "file-length: ok, 1 source files within 800 lines\n"
