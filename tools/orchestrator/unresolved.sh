#!/bin/bash
# unresolved.sh PR — prints the number of unresolved review threads on PR (any author). Merge needs 0.
set -u
[[ $# -eq 1 ]] || { echo "usage: unresolved.sh PR" >&2; exit 2; }
repo=$(gh repo view --json owner,name -q '.owner.login + " " + .name') || exit 1
read -r owner name <<< "$repo"
gh api graphql --paginate -F owner="$owner" -F name="$name" -F pr="$1" -f query='query($owner: String!, $name: String!, $pr: Int!, $endCursor: String) { repository(owner: $owner, name: $name) { pullRequest(number: $pr) { reviewThreads(first: 100, after: $endCursor) { nodes { isResolved } pageInfo { hasNextPage endCursor } } } } }' \
  --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved | not) | "x"' | wc -l
