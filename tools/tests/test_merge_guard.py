"""Behaviour of `tools/orchestrator/merge_guard.py`, the PreToolUse hook that keeps agents from merging PRs directly,
run as Claude Code runs it: hook JSON on stdin, exit 2 and a reason on stderr to deny."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parents[1] / "orchestrator" / "merge_guard.py"


def run_guard(payload: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(GUARD)], input=payload, capture_output=True, text=True, check=False
    )


def hook_input(command: str, tool: str = "Bash") -> str:
    return json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"command": command}})


DENIED = [
    "gh pr merge 100 --squash",
    "  gh   pr   merge 7",
    "/usr/bin/gh pr merge 7",
    "gh pr -R owner/repo merge 7",
    "cd backend && gh pr merge 7",
    "echo $(gh pr merge 7)",
    "GH_TOKEN=x gh pr merge 7",
    "bash -c 'gh pr merge 7'",
    "cat <<'EOF'\ntext\nEOF\ngh pr merge 7",
    'echo "merged: `gh pr merge 7`"',
    "gh api -X PUT repos/owner/repo/pulls/7/merge",
    "curl -X PUT https://api.example.com/repos/owner/repo/pulls/7/merge",
    "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"x\"}) { clientMutationId } }'",
    "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {}) { clientMutationId } }'",
]

ALLOWED = [
    "tools/orchestrator/merge_pr.sh 7 abc1234",
    "gh pr view 7 --json mergeable,mergeStateStatus",
    "gh pr comment 7 --body 'READY abc1234, orchestrator: run gh pr merge after the tracker commit'",
    "git commit -m 'deny gh pr merge in agents'",
    "gh api repos/owner/repo/pulls/7/merges-report",
    "cat >> notes.md <<'EOF'\n| self-merge | `gh pr merge` is denied |\nEOF\ngit add notes.md",
    "",
]


@pytest.mark.parametrize("command", DENIED)
def test_direct_merge_commands_are_denied_with_a_reason(command: str) -> None:
    result = run_guard(hook_input(command))

    assert result.returncode == 2
    assert "tools/orchestrator/merge_pr.sh" in result.stderr


@pytest.mark.parametrize("command", ALLOWED)
def test_other_commands_pass(command: str) -> None:
    result = run_guard(hook_input(command))

    assert (result.returncode, result.stderr) == (0, "")


def test_input_without_a_command_passes_and_unreadable_input_is_denied() -> None:
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "x"}})
    unreadable = run_guard("not json")

    assert run_guard(payload).returncode == 0
    assert unreadable.returncode == 2
    assert "merge guard" in unreadable.stderr
