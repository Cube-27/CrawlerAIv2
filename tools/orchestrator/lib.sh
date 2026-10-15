#!/bin/bash
# lib.sh — sourced by the orchestrator scripts that place or find a worktree.
# The main checkout is the first entry of `git worktree list`, which git prints in C:/... form; the worktrees sit
# beside it in <main>/../CrawlerAIv2-worktrees, never inside it. Both print "" outside a git repository.

main_checkout() {
  git worktree list --porcelain 2>/dev/null | sed -n '1s/^worktree //p'   # e.g. C:/Projects/CrawlerAIv2
}

# worktrees_root [MAIN] — the directory that holds every worktree of MAIN (default: this repository's main checkout).
worktrees_root() {
  local main=${1:-$(main_checkout)}
  [[ -n $main ]] && echo "$(dirname "$main")/CrawlerAIv2-worktrees"
  return 0
}
