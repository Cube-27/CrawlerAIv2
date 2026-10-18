"""Behaviour of `tools/orchestrator/merge_pr.sh`, run under bash with a fake `gh` on PATH. The fake answers each
`gh pr view` and `gh api --jq` as the real `gh` prints it for the script's jq programs (comment first lines, changed
files, Claude's summary comment and inline comment ids, checks, head) and logs a merge instead of making one."""

import shutil
import subprocess
from pathlib import Path

import pytest
from fake_bin import fake_bin

MERGE_PR = Path(__file__).resolve().parents[1] / "orchestrator" / "merge_pr.sh"
BASH = shutil.which("bash")
SHA = "abc1234"
FULL_SHA = SHA + "0" * 33
FAKE_GH = f"""#!/bin/bash
case "$*" in
  *changedFiles*) echo "$FAKE_FILES" ;;
  *nameWithOwner*) echo "owner/repo" ;;
  *graphql*) echo "${{FAKE_UNRESOLVED:-0}}" ;;
  *"Code review"*) printf '%s' "$FAKE_SUMMARY" ;;
  *"pulls/7/comments"*) printf '%s' "$FAKE_INLINE" ;;
  *"--json comments"*) cat "$FAKE_COMMENTS" ;;
  *statusCheckRollup*) printf '%s\\n' "{SHA} MERGEABLE CLEAN" "backend COMPLETED SUCCESS" \\
                         "SonarCloud Code Analysis COMPLETED SUCCESS" ;;
  *"--json headRefOid"*) echo {FULL_SHA} ;;
  *) echo "gh $*" >> "$FAKE_LOG" ;;
esac
"""
READY = f"READY {SHA}"
MERGED = f"gh pr merge 7 --squash --match-head-commit {FULL_SHA}\n"

pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def run_merge_pr(
    tmp_path: Path, comments: list[str], files: int = 3, summary: str = "", inline: str = "", unresolved: int = 0
) -> tuple[subprocess.CompletedProcess[str], str]:
    listed = tmp_path / "comments.txt"
    listed.write_text("".join(f"{line}\n" for line in comments), newline="\n")
    log = tmp_path / "gh.log"
    log.touch()
    env = fake_bin(
        tmp_path,
        {"gh": FAKE_GH},
        FAKE_COMMENTS=listed.as_posix(),
        FAKE_FILES=str(files),
        FAKE_SUMMARY=summary,
        FAKE_INLINE=inline,
        FAKE_UNRESOLVED=str(unresolved),
        FAKE_LOG=log.as_posix(),
        WAIT_CI_POLL_S="1",
    )
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
def test_a_ready_head_is_merged_at_that_head(tmp_path: Path, ready: str) -> None:
    result, calls = run_merge_pr(tmp_path, ["## CodeAnt Nitpicks", ready])

    assert (result.returncode, result.stderr) == (0, "")
    assert calls == MERGED


@pytest.mark.parametrize(
    "ready",
    [
        pytest.param([], id="no-ready"),
        pytest.param(["READY def5678"], id="ready-for-another-commit"),
        pytest.param([f"READY {SHA}9"], id="ready-for-a-longer-sha"),
        pytest.param([f"Fixed in {SHA}. READY {SHA}"], id="ready-not-first"),
    ],
)
def test_without_a_ready_comment_for_the_head_nothing_is_merged(tmp_path: Path, ready: list[str]) -> None:
    result, calls = run_merge_pr(tmp_path, ready)

    assert result.returncode == 1
    assert result.stderr == (
        f"ERROR PR #7 has no READY {SHA} comment: the implementor comments READY <sha7> on green CI\n"
    )
    assert calls == ""


@pytest.mark.parametrize(
    ("files", "summary", "inline"),
    [
        pytest.param(10, "", "", id="ten-files-unreviewed"),
        pytest.param(11, "4001\n", "", id="no-issues-comment"),
        pytest.param(54, "", "5001\n5002\n", id="inline-comments"),
    ],
)
def test_a_small_or_claude_reviewed_pr_is_merged(tmp_path: Path, files: int, summary: str, inline: str) -> None:
    result, calls = run_merge_pr(tmp_path, [READY], files, summary, inline)

    assert (result.returncode, result.stderr) == (0, "")
    assert calls == MERGED


def test_a_pr_over_ten_files_without_claude_review_is_not_merged(tmp_path: Path) -> None:
    result, calls = run_merge_pr(tmp_path, [READY], files=11)

    assert result.returncode == 1
    assert result.stderr == (
        "ERROR PR #7 changes 11 files (over 10) and has no Claude review:"
        " comment /claude-review and act on its findings first\n"
    )
    assert calls == ""


def test_a_pr_with_an_unresolved_review_thread_is_not_merged(tmp_path: Path) -> None:
    result, calls = run_merge_pr(tmp_path, [READY], unresolved=2)

    assert result.returncode == 1
    assert result.stderr == (
        "ERROR PR #7 has 2 unresolved review thread(s): fix or answer each finding and resolve it\n"
    )
    assert calls == ""
