#!/bin/bash
# merge_pr.sh PR SHA7 — squash-merges PR only if wait_ci.sh reports every check passed on commit SHA7, and only if
# SHA7 is still the PR's head when the merge runs (--match-head-commit). Never chain `gh pr merge` after a wait with
# `;`: a failed wait must stop the merge. A PR that conflicts with main, or whose head has no workflow run, fails the
# wait at once or after its grace period (see wait_ci.sh) instead of timing out.
# Before the wait it refuses (exit 1, ERROR on stderr) a PR without the two comments CLAUDE.md §3 requires: the
# implementor's `READY <SHA7>` (a comment whose first line starts with it) and a reviewer's verdict `MERGE` or
# `MERGE AFTER FIX`. Every agent posts as the same GitHub account, so the verdict is told from the implementor's
# comments by its form (/review-pr §4): a comment that starts with a `## Review` heading and has a line
# `**Verdict: MERGE**` or `**Verdict: MERGE AFTER FIX**`.
set -eu
pr=$1; sha=$2
# One line per comment: "review" for a verdict that allows the merge, else "-"; then the comment's first line.
comments=$(gh pr view "$pr" --json comments --jq '.comments[]
  | "\(if (.body | startswith("## Review")) and (.body | test("(?m)^[*][*]Verdict: MERGE[* .]")) then "review" else "-" end) \(.body | split("\n")[0])"')
if ! grep -qE "^- READY $sha([^0-9a-fA-F]|$)" <<< "$comments"; then
  echo "ERROR PR #$pr has no READY $sha comment: the implementor comments READY <sha7> on green CI" >&2; exit 1
fi
if ! grep -q '^review ' <<< "$comments"; then
  echo "ERROR PR #$pr has no reviewer verdict MERGE or MERGE AFTER FIX: run /review-pr first" >&2; exit 1
fi
bash "$(dirname "$0")/wait_ci.sh" "$pr" "$sha"
full=$(gh pr view "$pr" --json headRefOid --jq .headRefOid)
if [[ $full != "$sha"* ]]; then echo "ERROR head is $full, not $sha" >&2; exit 1; fi
gh pr merge "$pr" --squash --match-head-commit "$full"
