#!/bin/bash
# cleanup_worktree.sh WORKTREE BRANCH — after a merge: remove the worktree's throwaway Postgres containers,
# the worktree (retrying while a closing pane still holds it), and the remote and local branch.
# It first checks that the work is merged, and removes nothing unless the branch's PR is MERGED, or the branch has
# no PR and is an ancestor of origin/main. Deleting the remote branch of an open PR makes GitHub close that PR
# (#128: a failed merge chained with `;`). On refusal, or when GitHub can't be read, it exits 1 with an ERROR on
# stderr and keeps the worktree, the branches and the containers.
# Removes only containers named crawlerai-* (with their anonymous volumes): never another project's containers.
# Then removes all Docker build cache and dangling images: the owner keeps no build cache (2026-10-13), and a
# pruned layer is only rebuilt on the next build.
set -u
if [[ $# -ne 2 ]]; then echo "usage: cleanup_worktree.sh WORKTREE BRANCH" >&2; exit 2; fi
wt=$1; branch=$2
main=$(git worktree list --porcelain | sed -n '1s/^worktree //p')
dir="$(dirname "$main")/CrawlerAIv2-worktrees/$wt"
short=${wt//-/}   # spec-03-pr-8 -> spec03pr8

refuse() {
  echo "ERROR $1: kept the worktree $wt, the branch $branch and the containers" >&2
  exit 1
}

require_merged() {
  local states ref
  states=$(gh pr list --head "$branch" --state all --json state --jq '.[].state') \
    || refuse "could not read the PRs of $branch"
  if [[ $states == *MERGED* ]]; then return 0; fi
  if [[ -n $states ]]; then refuse "the PR for $branch is not merged"; fi
  git -C "$main" fetch -q origin || refuse "could not fetch origin"
  ref=$branch
  git -C "$main" rev-parse -q --verify "refs/heads/$branch" >/dev/null || ref="origin/$branch"
  git -C "$main" merge-base --is-ancestor "$ref" origin/main 2>/dev/null \
    || refuse "$branch has no PR and is not merged into origin/main"
  return 0
}

require_merged
for c in $(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -E "^crawlerai-($wt|$short)(-|$)"); do
  docker rm -f -v "$c" >/dev/null && echo "removed container $c and its volumes"
done
for _ in 1 2 3 4 5 6; do git -C "$main" worktree remove --force "$dir" 2>/dev/null && break; sleep 5; done
git -C "$main" push -q origin --delete "$branch" 2>/dev/null
git -C "$main" branch -D "$branch" 2>/dev/null
docker builder prune -af >/dev/null || echo "warning: build cache prune failed" >&2
docker image prune -f >/dev/null || echo "warning: dangling image prune failed" >&2
git -C "$main" pull -q --ff-only && git -C "$main" log --oneline -1
