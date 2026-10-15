"""Behaviour of `tools/orchestrator/merge_pr.sh`, run under bash with a fake `gh` on PATH. The fake answers each
`gh pr view --jq` as the real `gh` prints it for the script's jq programs (comments, checks, head) and logs a merge
instead of making one."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

MERGE_PR = Path(__file__).resolve().parents[1] / "orchestrator" / "merge_pr.sh"
BASH = shutil.which("bash")
SHA = "abc1234"
FULL_SHA = SHA + "0" * 33
FAKE_GH = f"""#!/bin/bash
case "$*" in
  *"--json comments"*) cat "$FAKE_COMMENTS" ;;
  *statusCheckRollup*) printf '%s\\n' "{SHA} MERGEABLE CLEAN" "backend COMPLETED SUCCESS" \\
                         "SonarCloud Code Analysis COMPLETED SUCCESS" ;;
  *"--json headRefOid"*) echo {FULL_SHA} ;;
  *) echo "gh $*" >> "$FAKE_LOG" ;;
esac
"""
READY = f"- READY {SHA}"
REVIEW = "review ## Review: #7 at abc1234"

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def run_merge_pr(tmp_path: Path, comments: list[str]) -> tuple[subprocess.CompletedProcess[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH, newline="\n")
    gh.chmod(0o755)
    listed = tmp_path / "comments.txt"
    listed.write_text("".join(f"{line}\n" for line in comments), newline="\n")
    log = tmp_path / "gh.log"
    log.touch()
    env = {
        **os.environ,
        "PATH": f"{bin_dir.as_posix()}{os.pathsep}{os.environ['PATH']}",
        "FAKE_COMMENTS": listed.as_posix(),
        "FAKE_LOG": log.as_posix(),
        "WAIT_CI_POLL_S": "1",
    }
    result = subprocess.run(  # noqa: S603
        [str(BASH), MERGE_PR.as_posix(), "7", SHA],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result, log.read_text()


@pytest.mark.parametrize("ready", [READY, f"{READY}, after the review fixes"])
def test_a_ready_head_with_a_merge_verdict_is_merged_at_that_head(tmp_path: Path, ready: str) -> None:
    result, calls = run_merge_pr(tmp_path, ["- ## CodeAnt Nitpicks", REVIEW, ready])

    assert (result.returncode, result.stderr) == (0, "")
    assert calls == f"gh pr merge 7 --squash --match-head-commit {FULL_SHA}\n"


@pytest.mark.parametrize(
    "ready",
    [
        pytest.param([], id="no-ready"),
        pytest.param(["- READY def5678"], id="ready-for-another-commit"),
        pytest.param([f"- READY {SHA}9"], id="ready-for-a-longer-sha"),
        pytest.param([f"- Fixed in {SHA}. READY {SHA}"], id="ready-not-first"),
    ],
)
def test_without_a_ready_comment_for_the_head_nothing_is_merged(tmp_path: Path, ready: list[str]) -> None:
    result, calls = run_merge_pr(tmp_path, [REVIEW, *ready])

    assert result.returncode == 1
    assert result.stderr == (
        f"ERROR PR #7 has no READY {SHA} comment: the implementor comments READY <sha7> on green CI\n"
    )
    assert calls == ""


@pytest.mark.parametrize(
    "comments",
    [
        pytest.param([READY], id="no-review"),
        pytest.param([READY, "- ## Review: #7 at abc1234"], id="review-without-a-merge-verdict"),
        pytest.param([READY, "- Verdict MERGE (no Act-on items)"], id="verdict-outside-a-review"),
    ],
)
def test_without_a_merge_verdict_nothing_is_merged(tmp_path: Path, comments: list[str]) -> None:
    result, calls = run_merge_pr(tmp_path, comments)

    assert result.returncode == 1
    assert result.stderr == "ERROR PR #7 has no reviewer verdict MERGE or MERGE AFTER FIX: run /review-pr first\n"
    assert calls == ""
