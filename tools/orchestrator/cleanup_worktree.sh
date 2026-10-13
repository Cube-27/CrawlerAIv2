#!/bin/bash
# cleanup_worktree.sh WORKTREE BRANCH — after a merge: remove the worktree's throwaway Postgres containers,
# the worktree (retrying while a closing pane still holds it), and the remote and local branch.
# Removes only containers named crawlerai-*: never another project's containers.
set -u
wt=$1; branch=$2
main=$(git worktree list --porcelain | sed -n '1s/^worktree //p')
dir="$(dirname "$main")/CrawlerAIv2-worktrees/$wt"
short=${wt//-/}   # spec-03-pr-8 -> spec03pr8
for c in $(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -E "^crawlerai-($wt|$short)(-|$)"); do
  docker rm -f "$c" >/dev/null && echo "removed container $c"
done
for _ in 1 2 3 4 5 6; do git -C "$main" worktree remove --force "$dir" 2>/dev/null && break; sleep 5; done
git -C "$main" push -q origin --delete "$branch" 2>/dev/null
git -C "$main" branch -D "$branch" 2>/dev/null
git -C "$main" pull -q --ff-only && git -C "$main" log --oneline -1
