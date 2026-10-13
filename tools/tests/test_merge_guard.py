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
    "gh pr merge",
    "  gh   pr   merge 7",
    "gh.exe pr merge 7 --admin",
    "/usr/bin/gh pr merge 7",
    "gh pr --repo owner/repo merge 7",
    "gh pr -R owner/repo merge 7",
    "gh pr merge 7 --auto --squash",
    "cd backend && gh pr merge 7",
    "tools/orchestrator/wait_ci.sh 7 abc1234; gh pr merge 7",
    "tools/orchestrator/merge_pr.sh 7 abc1234 && gh pr merge 8",
    "echo $(gh pr merge 7)",
    "gh pr view 7 | cat\ngh pr merge 7",
    "GH_TOKEN=x gh pr merge 7",
    "bash -c 'gh pr merge 7'",
    'pwsh -Command "gh pr merge 7"',
    "cat <<EOF\n$(gh pr merge 7)\nEOF",
    "cat <<'EOF'\ntext\nEOF\ngh pr merge 7",
    'Write-Output @"\n$(gh pr merge 7)\n"@',
    'echo "merged: $(gh pr merge 7)"',
    'echo "merged: `gh pr merge 7`"',
    "gh api -X PUT repos/owner/repo/pulls/7/merge",
    "gh api --method PUT /repos/owner/repo/pulls/7/merge -f merge_method=squash",
    "gh api repos/{owner}/{repo}/pulls/7/merge",
    "curl -X PUT https://api.example.com/repos/owner/repo/pulls/7/merge",
    "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"x\"}) { clientMutationId } }'",
    "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {}) { clientMutationId } }'",
]

ALLOWED = [
    "tools/orchestrator/merge_pr.sh 7 abc1234",
    "bash tools/orchestrator/merge_pr.sh 7 abc1234",
    "tools/orchestrator/wait_ci.sh 7 abc1234",
    "gh pr view 7 --json mergeable,mergeStateStatus",
    "gh pr list --state merged",
    "gh pr create --title 'fix(orchestrator): merge guard' --body x",
    "gh pr comment 7 --body 'READY abc1234, orchestrator: run gh pr merge after the tracker commit'",
    "git commit -m 'deny gh pr merge in agents'",
    "git merge origin/main",
    "gh api repos/owner/repo/pulls/7",
    "gh api repos/owner/repo/pulls/7/merges-report",
    "gh run list",
    "cat >> notes.md <<'EOF'\n| self-merge | `gh pr merge` is denied |\nEOF\ngit add notes.md",
    'git commit -F - <<"MSG"\nfix: deny gh pr merge 7\nMSG',
    "git commit -m @'\nfix: deny gh pr merge 7\n'@",
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


def test_powershell_tool_commands_are_checked_too() -> None:
    assert run_guard(hook_input("gh pr merge 7", tool="PowerShell")).returncode == 2


def test_command_with_unbalanced_quotes_falls_back_to_a_text_match() -> None:
    assert run_guard(hook_input("gh pr merge 7 --body 'unterminated")).returncode == 2
    assert run_guard(hook_input("echo 'unterminated")).returncode == 0


def test_input_without_a_command_passes() -> None:
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "x"}})

    assert run_guard(payload).returncode == 0


def test_unreadable_hook_input_is_denied() -> None:
    result = run_guard("not json")

    assert result.returncode == 2
    assert "merge guard" in result.stderr
