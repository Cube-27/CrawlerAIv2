#!/bin/bash
# merge_pr.sh PR SHA7 — squash-merges PR only if wait_ci.sh reports every check passed on commit SHA7, and only if
# SHA7 is still the PR's head when the merge runs (--match-head-commit). Never chain `gh pr merge` after a wait with
# `;`: a failed wait must stop the merge. A PR that conflicts with main, or whose head has no workflow run, fails the
# wait at once or after its grace period (see wait_ci.sh) instead of timing out.
# Before the wait it refuses (exit 1, ERROR on stderr) a PR without the implementor's `READY <SHA7>` (a comment whose
# first line starts with it), and a PR that changes more than REVIEW_MIN_FILES files without Claude's review: what
# the `claude-review` workflow's code-review plugin posts when the implementor comments `/claude-review` (CLAUDE.md
# §3; owner, 2026-10-17), either its `## Code review` comment (no issues) or its inline comments. Anthropic's managed
# Code Review posts its notices as the same app, as review bodies, so any comment by the app is not enough.
# It also refuses a PR with an unresolved review thread (owner, 2026-10-18): every bot or human finding (Claude,
# CodeRabbit, CodeAnt, SonarCloud) is fixed or answered, and its thread resolved, before the merge.
set -eu
pr=$1; sha=$2
REVIEW_MIN_FILES=10
first_lines=$(gh pr view "$pr" --json comments --jq '.comments[] | .body | split("\n")[0]')
if ! grep -qE "^READY $sha([^0-9a-fA-F]|$)" <<< "$first_lines"; then
  echo "ERROR PR #$pr has no READY $sha comment: the implementor comments READY <sha7> on green CI" >&2; exit 1
fi
files=$(gh pr view "$pr" --json changedFiles --jq .changedFiles)
if (( files > REVIEW_MIN_FILES )); then
  summary=$(gh pr view "$pr" --json comments \
    --jq '.comments[] | select(.author.login == "claude" and (.body | startswith("## Code review"))) | .id')
  inline=$(gh api "repos/{owner}/{repo}/pulls/$pr/comments" --paginate \
    --jq '.[] | select(.user.login == "claude[bot]") | .id')
  if [[ -z $summary$inline ]]; then
    echo "ERROR PR #$pr changes $files files (over $REVIEW_MIN_FILES) and has no Claude review:" \
      "comment /claude-review and act on its findings first" >&2
    exit 1
  fi
fi
repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
# Paginated (--paginate follows pageInfo.endCursor), so a PR with more than 100 threads is counted in full.
unresolved=$(gh api graphql --paginate -F owner="${repo%%/*}" -F name="${repo##*/}" -F pr="$pr" -f query='
  query($owner: String!, $name: String!, $pr: Int!, $endCursor: String) { repository(owner: $owner, name: $name) {
    pullRequest(number: $pr) { reviewThreads(first: 100, after: $endCursor) {
      nodes { isResolved } pageInfo { hasNextPage endCursor } } } } }' \
  --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved | not) | "x"' | wc -l)
if (( unresolved > 0 )); then
  echo "ERROR PR #$pr has $unresolved unresolved review thread(s): fix or answer each finding and resolve it" >&2
  exit 1
fi
bash "$(dirname "$0")/wait_ci.sh" "$pr" "$sha"
full=$(gh pr view "$pr" --json headRefOid --jq .headRefOid)
if [[ $full != "$sha"* ]]; then echo "ERROR head is $full, not $sha" >&2; exit 1; fi
gh pr merge "$pr" --squash --match-head-commit "$full"
