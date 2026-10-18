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
        ("backend/src/crawlerai/cli.py\n", "backend=true\nfrontend=true\nlicenses=false\n"),
        ("backend/uv.lock\n", "backend=true\nfrontend=true\nlicenses=true\n"),
        ("", "backend=false\nfrontend=false\nlicenses=false\n"),
    ],
)
def test_each_job_runs_only_when_a_changed_path_is_one_of_its_inputs(changed: str, expected: str) -> None:
    assert run(stdin=changed) == expected


def test_a_path_that_only_shares_a_name_prefix_with_a_directory_is_not_its_input() -> None:
    assert run(stdin="frontend-notes.md\nbackend_old/readme.md\n") == "backend=false\nfrontend=false\nlicenses=false\n"


def test_all_runs_every_job_without_reading_input() -> None:
    assert run("--all") == "backend=true\nfrontend=true\nlicenses=true\n"
