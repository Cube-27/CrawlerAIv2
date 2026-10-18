#!/bin/bash
# lib.sh — sourced by the orchestrator scripts that place or find a worktree.
# The main checkout is the first entry of `git worktree list`, which git prints in C:/... form; the worktrees sit
# beside it in <main>/../CrawlerAIv2-worktrees, never inside it. Both print "" outside a git repository.

main_checkout() {
  git worktree list --porcelain 2>/dev/null | sed -n '1s/^worktree //p'   # e.g. C:/Projects/CrawlerAIv2
  return $?
}

# worktrees_root [MAIN] — the directory that holds every worktree of MAIN (default: this repository's main checkout).
worktrees_root() {
  local main=${1:-$(main_checkout)}
  [[ -n $main ]] && echo "$(dirname "$main")/CrawlerAIv2-worktrees"
  return 0
}

# project_agents [MAIN] — reads `herdr agent list` JSON on stdin and prints "<name> <status>" for each named agent of
# this project: its cwd is MAIN, under MAIN, or under worktrees_root MAIN. herdr lists every project's agents, and
# another project's workers must not wake the watcher or count toward MAX_WORKERS. Paths compare with separators
# unified and case folded: herdr prints C:\... while git prints C:/..., and Windows paths are case-insensitive.
# Exits non-zero on input that is not an agent list.
project_agents() {
  local main=${1:-$(main_checkout)}
  python -c 'import json, sys
def norm(path):
    return path.replace("\\", "/").rstrip("/").casefold()
roots = [norm(root) for root in sys.argv[1:] if root]
for agent in json.load(sys.stdin)["result"]["agents"]:
    cwd = norm(agent.get("cwd") or "")
    if agent.get("name") and any(cwd == root or cwd.startswith(root + "/") for root in roots):
        print(agent["name"], agent["agent_status"])' "$main" "$(worktrees_root "$main")" | tr -d '\r'
  return "${PIPESTATUS[0]}"
}
