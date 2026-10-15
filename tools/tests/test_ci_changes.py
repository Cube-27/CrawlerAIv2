"""Behaviour of `tools/ci_changes.py`, run as CI runs it: changed paths on stdin, job flags on stdout."""

import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "ci_changes.py"


def run(*args: str, stdin: str = "") -> str:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(TOOL), *args], input=stdin, capture_output=True, text=True, check=True
    )
    return result.stdout


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        ("docs/specs/SPEC-99.md\nREADME.md\n", "backend=false\nfrontend=false\nlicenses=false\n"),
        ("frontend/src/app/theme.css\n", "backend=false\nfrontend=true\nlicenses=false\n"),
        ("backend/src/crawlerai/cli.py\n", "backend=true\nfrontend=true\nlicenses=false\n"),
        ("backend/uv.lock\n", "backend=true\nfrontend=true\nlicenses=true\n"),
        ("frontend/pnpm-lock.yaml\n", "backend=false\nfrontend=true\nlicenses=true\n"),
        ("tools/theme_only_check.py\n", "backend=true\nfrontend=true\nlicenses=false\n"),
        ("tools/license_policy.py\n", "backend=true\nfrontend=false\nlicenses=true\n"),
        ("infra/postgres/init.sql\n", "backend=true\nfrontend=false\nlicenses=false\n"),
        (".github/workflows/ci.yml\n", "backend=true\nfrontend=true\nlicenses=true\n"),
        ("", "backend=false\nfrontend=false\nlicenses=false\n"),
    ],
)
def test_each_job_runs_only_when_a_changed_path_is_one_of_its_inputs(changed: str, expected: str) -> None:
    assert run(stdin=changed) == expected


def test_a_path_that_only_shares_a_name_prefix_with_a_directory_is_not_its_input() -> None:
    assert run(stdin="frontend-notes.md\nbackend_old/readme.md\n") == "backend=false\nfrontend=false\nlicenses=false\n"


def test_a_file_moved_out_of_backend_still_runs_backend() -> None:
    # `git diff --no-renames` lists a move as the old path deleted and the new one added.
    assert run(stdin="backend/notes.txt\ndocs/notes.txt\n") == "backend=true\nfrontend=true\nlicenses=false\n"


def test_all_runs_every_job_without_reading_input() -> None:
    assert run("--all") == "backend=true\nfrontend=true\nlicenses=true\n"
