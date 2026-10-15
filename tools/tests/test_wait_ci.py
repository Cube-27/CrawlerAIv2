"""Behaviour of `tools/orchestrator/wait_ci.sh`, run under bash with a fake `gh` on PATH that prints a fixed
`gh pr view --jq` result, as the real `gh` prints it for the script's jq program."""

import shutil
import subprocess
from pathlib import Path

import pytest
from fake_bin import fake_bin

WAIT_CI = Path(__file__).resolve().parents[1] / "orchestrator" / "wait_ci.sh"
BASH = shutil.which("bash")
FAKE_GH = '#!/bin/bash\ncat "$FAKE_GH_OUT"\n'
GREEN_CHECKS = [
    "backend COMPLETED SUCCESS",
    "frontend COMPLETED SUCCESS",
    "SonarCloud Code Analysis COMPLETED SUCCESS",
]

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def run_wait_ci(tmp_path: Path, lines: list[str], no_run_s: int = 300) -> subprocess.CompletedProcess[str]:
    response = tmp_path / "gh_out.txt"
    response.write_text("\n".join(lines) + "\n", newline="\n")
    env = fake_bin(
        tmp_path,
        {"gh": FAKE_GH},
        FAKE_GH_OUT=response.as_posix(),
        WAIT_CI_POLL_S="1",
        WAIT_CI_NO_RUN_S=str(no_run_s),
    )
    return subprocess.run(  # noqa: S603
        [str(BASH), WAIT_CI.as_posix(), "7", "abc1234", "1"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def pr_view(merge: str, checks: list[str]) -> list[str]:
    return [f"abc1234 {merge}", *checks]


@pytest.mark.parametrize("merge", ["CONFLICTING DIRTY", "CONFLICTING UNKNOWN", "UNKNOWN DIRTY"])
def test_conflicting_pr_fails_at_once(tmp_path: Path, merge: str) -> None:
    result = run_wait_ci(tmp_path, pr_view(merge, ["SonarCloud Code Analysis COMPLETED SUCCESS"]))
    assert result.returncode == 1
    assert result.stderr.strip() == "ERROR PR #7 conflicts with main: rebase onto origin/main"
    assert result.stdout == ""


def test_no_workflow_run_fails_after_grace(tmp_path: Path) -> None:
    checks = ["SonarCloud Code Analysis COMPLETED SUCCESS"]
    result = run_wait_ci(tmp_path, pr_view("MERGEABLE CLEAN", checks), no_run_s=0)
    assert result.returncode == 1
    assert result.stderr.strip() == (
        "ERROR no workflow run for abc1234 after 0s and the PR does not conflict: "
        "check the workflow triggers or re-push"
    )


@pytest.mark.parametrize("merge", ["MERGEABLE CLEAN", "UNKNOWN UNKNOWN"])
def test_green_checks_pass_and_print(tmp_path: Path, merge: str) -> None:
    result = run_wait_ci(tmp_path, pr_view(merge, GREEN_CHECKS), no_run_s=0)
    assert result.returncode == 0
    assert result.stdout.splitlines() == GREEN_CHECKS
    assert result.stderr == ""


def test_failed_check_fails(tmp_path: Path) -> None:
    checks = ["backend COMPLETED FAILURE", "SonarCloud Code Analysis COMPLETED SUCCESS"]
    result = run_wait_ci(tmp_path, pr_view("MERGEABLE CLEAN", checks))
    assert result.returncode == 1
    assert result.stdout.splitlines() == checks
    assert result.stderr.strip() == "ERROR a check did not pass"
