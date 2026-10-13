#!/bin/bash
# merge_pr.sh PR SHA7 — squash-merges PR only if wait_ci.sh reports every check passed on commit SHA7, and only if
# SHA7 is still the PR's head when the merge runs (--match-head-commit). Never chain `gh pr merge` after a wait with
# `;`: a failed wait must stop the merge.
set -eu
pr=$1; sha=$2
bash "$(dirname "$0")/wait_ci.sh" "$pr" "$sha"
full=$(gh pr view "$pr" --json headRefOid --jq .headRefOid)
if [[ $full != "$sha"* ]]; then echo "ERROR head is $full, not $sha" >&2; exit 1; fi
gh pr merge "$pr" --squash --match-head-commit "$full"
