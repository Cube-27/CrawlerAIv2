#!/bin/bash
# new_worktree.sh NAME BRANCH — fetch origin, then create the worktree <main>/../CrawlerAIv2-worktrees/NAME on a new
# BRANCH off origin/main, and print its path. <main> is the main checkout (the first entry of `git worktree list`), so
# the worktree sits beside the repo, never inside it.
# Exits 2 on bad arguments. Exits 1 with an ERROR on stderr, creating nothing, when NAME's path already exists, BRANCH
# already exists locally or on origin, the path is an MSYS drive path (/c/...: with MSYS path conversion off, git
# reads it as C:/c/...), or git fails.
set -u
if [[ $# -ne 2 ]]; then echo "usage: new_worktree.sh NAME BRANCH" >&2; exit 2; fi
name=$1; branch=$2
err() { echo "ERROR $*" >&2; exit 1; }
if [[ -z $name || $name == */* || $name == *\\* || $name == . || $name == .. ]]; then
  echo "ERROR NAME must be a directory name, not a path: '$name'" >&2
  exit 2
fi
main=$(git worktree list --porcelain | sed -n '1s/^worktree //p')   # e.g. C:/Projects/CrawlerAIv2
[[ -n $main ]] || err "not inside a git repository"
dir="$(dirname "$main")/CrawlerAIv2-worktrees/$name"
[[ $dir =~ ^/[a-zA-Z]/ ]] && err "$dir is an MSYS drive path; give git a C:/... path"
[[ -e $dir ]] && err "$dir already exists"
git -C "$main" fetch -q origin main || err "git fetch origin main failed"
git -C "$main" rev-parse -q --verify "refs/heads/$branch" >/dev/null && err "branch $branch already exists"
[[ -n $(git -C "$main" ls-remote --heads origin "$branch") ]] && err "branch $branch already exists on origin"
git -C "$main" worktree add -q -b "$branch" "$dir" origin/main || err "git worktree add $dir failed"
echo "$dir"
