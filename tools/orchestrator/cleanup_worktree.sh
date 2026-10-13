#!/bin/bash
# cleanup_worktree.sh WORKTREE BRANCH — after a merge: remove the worktree's throwaway Postgres containers,
# the worktree (retrying while a closing pane still holds it), and the remote and local branch.
# Removes only containers named crawlerai-* (with their anonymous volumes): never another project's containers.
# Then caps Docker's build cache at 5 GB and drops dangling images. The cache is shared with other projects, but it
# is only a speed-up: a pruned layer is rebuilt on the next build.
set -u
wt=$1; branch=$2
main=$(git worktree list --porcelain | sed -n '1s/^worktree //p')
dir="$(dirname "$main")/CrawlerAIv2-worktrees/$wt"
short=${wt//-/}   # spec-03-pr-8 -> spec03pr8
for c in $(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -E "^crawlerai-($wt|$short)(-|$)"); do
  docker rm -f -v "$c" >/dev/null && echo "removed container $c and its volumes"
done
for _ in 1 2 3 4 5 6; do git -C "$main" worktree remove --force "$dir" 2>/dev/null && break; sleep 5; done
git -C "$main" push -q origin --delete "$branch" 2>/dev/null
git -C "$main" branch -D "$branch" 2>/dev/null
docker builder prune -f --max-used-space 5gb >/dev/null || echo "warning: build cache prune failed" >&2
docker image prune -f >/dev/null || echo "warning: dangling image prune failed" >&2
git -C "$main" pull -q --ff-only && git -C "$main" log --oneline -1
