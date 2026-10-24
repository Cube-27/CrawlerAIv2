#!/bin/bash
# new_worktree.sh NAME BRANCH — fetch origin, then create the worktree <main>/../CrawlerAIv2-worktrees/NAME on a new
# BRANCH off origin/main, give it the main checkout's untracked inputs (`.env`, the data files the backend fetches)
# and a synced backend environment, and print its path. <main> is the main checkout (the first entry of `git worktree list`,
# which git prints in C:/... form), so the worktree sits beside the repo, never inside it.
# Exits 2 on bad arguments. Exits 1 with an ERROR on stderr, creating nothing, when NAME's path already exists, BRANCH
# already exists locally or on origin, or git fails. The local checks run before any network call.
set -u
usage() { echo "$1" >&2; exit 2; }
err() { echo "ERROR $*" >&2; exit 1; }
[[ $# -eq 2 ]] || usage "usage: new_worktree.sh NAME BRANCH"
name=$1; branch=$2
if [[ -z $name || $name == */* || $name == *\\* || $name == . || $name == .. ]]; then
  usage "ERROR NAME must be a directory name, not a path: '$name'"
fi
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
main=$(main_checkout)
[[ -n $main ]] || err "not inside a git repository"
dir="$(worktrees_root "$main")/$name"
[[ -e $dir ]] && err "$dir already exists"
git -C "$main" rev-parse -q --verify "refs/heads/$branch" >/dev/null && err "branch $branch already exists"
[[ -n $(git -C "$main" ls-remote --heads origin "$branch") ]] && err "branch $branch already exists on origin"
git -C "$main" fetch -q origin main || err "git fetch origin main failed"
git -C "$main" worktree add -q -b "$branch" "$dir" origin/main || err "git worktree add $dir failed"
# Gitignored inputs a worker would otherwise copy by hand; .env is a symlink so the secret has one copy.
[[ -f $main/.env ]] && ln -s "$main/.env" "$dir/.env"
for data in schemaorg publicsuffix; do
  [[ -d $main/backend/data/$data ]] && cp -r "$main/backend/data/$data" "$dir/backend/data/$data"
done
# Dependencies from the lockfile's wheels only, as CI installs them; the project itself is built (editable).
if [[ -f $dir/backend/pyproject.toml ]] && ! (cd "$dir/backend" && uv sync -q --no-build --no-binary-package crawlerai) >&2; then
  # Leave nothing behind, so a retry with the same NAME and BRANCH can succeed.
  git -C "$main" worktree remove --force "$dir" && git -C "$main" branch -q -D "$branch"
  err "uv sync failed in $dir/backend"
fi
echo "$dir"
