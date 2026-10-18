"""Claude Code PreToolUse hook: deny a Bash or PowerShell command that merges a pull request directly.

`tools/orchestrator/merge_pr.sh` is the only sanctioned merge path: it merges on a passing CI wait, pinned to the
head commit, on the implementor's `READY`. Agents merged their own PRs anyway (#71, #100), so this hook
denies `gh pr merge` (including `--auto`), REST calls to the merge endpoint (`pulls/<n>/merge`, any client) and the
GraphQL merge mutations. The command string is all the hook sees, so `merge_pr.sh`'s own `gh` call is not a tool
call and passes. This guards against mistakes, not against an agent set on evading it (aliases, scripts written to
disk, a quoted here-document piped to a shell).

Reads the hook JSON on stdin. Exits 2 with the reason on stderr to deny, 0 to allow. Input it can't read is denied.
"""

import json
import re
import shlex
import sys
from collections.abc import Iterator
from itertools import pairwise

REASON = (
    "merge guard: agents don't merge PRs directly. Comment READY <sha7> on the PR and stop; the orchestrator merges"
    " with tools/orchestrator/merge_pr.sh on READY (CLAUDE.md)."
)

# GitHub REST "Merge a pull request": PUT /repos/{owner}/{repo}/pulls/{pull_number}/merge.
PULLS_MERGE = re.compile(r"(?:^|/)pulls/[^/\s]+/merge/?(?:\?\S*)?$")
# GitHub GraphQL mutations that merge a pull request or schedule its merge.
MERGE_MUTATIONS = re.compile(r"\b(?:mergePullRequest|enablePullRequestAutoMerge|enqueuePullRequest)\b")
# Fallback for text shlex can't split (unbalanced quotes).
GH_PR_MERGE_TEXT = re.compile(r"\bgh(?:\.exe)?\s+pr\s+merge\b")

# Bash and PowerShell control operators and grouping; each starts a new command.
SEPARATORS = ";&|()<>\n`"
SEPARATOR_CHARS = frozenset(SEPARATORS)
# gh flags placed between `pr` and `merge` that take a value.
GH_VALUE_FLAGS = frozenset({"-R", "--repo"})
# Flags and commands whose next argument is itself a command string: `bash -c`, `pwsh -Command`, `cmd /c`, `iex`.
NESTED_COMMAND_MARKERS = frozenset({"-c", "-command", "/c", "iex", "invoke-expression"})
MAX_NESTING = 3
# Bodies that the shell passes on as literal text, never runs: a bash here-document with a quoted delimiter
# (`<<'EOF'`, Bash manual "Here Documents": no expansion in the body) and a PowerShell single-quoted here-string
# (`@'...'@`, about_Quoting_Rules). Unquoted ones expand `$(...)`, so they stay in.
QUOTED_HEREDOC = re.compile(r"(<<-?[ \t]*(['\"])(\w+)\2[^\n]*)\n.*?^[ \t]*\3[ \t]*$", re.MULTILINE | re.DOTALL)
LITERAL_HERE_STRING = re.compile(r"@'\r?\n.*?\r?\n'@", re.DOTALL)


def without_literal_bodies(command: str) -> str:
    return LITERAL_HERE_STRING.sub("''", QUOTED_HEREDOC.sub(r"\1", command))


def tokenize(command: str) -> list[str]:
    lexer = shlex.shlex(without_literal_bodies(command), posix=True, punctuation_chars=SEPARATORS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def segments(tokens: list[str]) -> Iterator[list[str]]:
    current: list[str] = []
    for token in tokens:
        if token and set(token) <= SEPARATOR_CHARS:
            yield current
            current = []
        else:
            current.append(token)
    yield current


def is_gh(token: str) -> bool:
    return re.split(r"[\\/]", token)[-1].lower() in {"gh", "gh.exe"}


def gh_positionals(args: list[str]) -> list[str]:
    positionals: list[str] = []
    skip_value = False
    for arg in args:
        if skip_value:
            skip_value = False
        elif arg in GH_VALUE_FLAGS:
            skip_value = True
        elif not arg.startswith("-"):
            positionals.append(arg)
    return positionals


def runs_gh_pr_merge(segment: list[str]) -> bool:
    return any(
        is_gh(token) and gh_positionals(segment[index + 1 :])[:2] == ["pr", "merge"]
        for index, token in enumerate(segment)
    )


def calls_merge_api(segment: list[str]) -> bool:
    return any(PULLS_MERGE.search(token) or MERGE_MUTATIONS.search(token) for token in segment)


def nested_commands(segment: list[str]) -> Iterator[str]:
    for marker, argument in pairwise(segment):
        if marker.lower() in NESTED_COMMAND_MARKERS:
            yield argument
    # Command substitution inside a double-quoted string (`"$(...)"`, `` "`...`" ``) still runs.
    yield from (token for token in segment if "$(" in token or "`" in token)


def merges_directly(command: str, depth: int = 0) -> bool:
    try:
        tokens = tokenize(command)
    except ValueError:
        return bool(GH_PR_MERGE_TEXT.search(command)) or calls_merge_api(command.split())
    for segment in segments(tokens):
        if runs_gh_pr_merge(segment) or calls_merge_api(segment):
            return True
        if depth < MAX_NESTING and any(merges_directly(inner, depth + 1) for inner in nested_commands(segment)):
            return True
    return False


def command_of(payload: str) -> str:
    """The hook input's command, or "" for a tool without one. Raises ValueError on input that isn't hook JSON."""
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("hook input is not a JSON object")
    tool_input = data.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    return command if isinstance(command, str) else ""


def main() -> int:
    try:
        command = command_of(sys.stdin.read())
    except ValueError as error:
        print(f"merge guard: unreadable hook input ({error}); denying.", file=sys.stderr)
        return 2
    if merges_directly(command):
        print(REASON, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
