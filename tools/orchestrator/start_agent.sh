#!/bin/bash
# start_agent.sh NAME WORKTREE PROMPT [MIN_FREE_MB]
# Starts a claude herdr agent in <main>/../CrawlerAIv2-worktrees/WORKTREE, checks that the pane's cwd really is
# that worktree (a wrong cwd stops at a trust prompt in the home folder), refuses when free memory is low, then
# sends PROMPT. Prints "<pane> <status>", or "ERROR ..." and exits 1.
# Build paths here, never inline: in bash double quotes "...\$wt" collapses to a literal "$wt".
set -u
name=$1; wt=$2; prompt=$3; min_free=${4:-1500}
main=$(git worktree list --porcelain | sed -n '1s/^worktree //p')   # e.g. C:/Projects/CrawlerAIv2
root_fwd="$(dirname "$main")/CrawlerAIv2-worktrees"
path=$(cygpath -w "$root_fwd/$wt" 2>/dev/null || echo "$root_fwd/$wt" | tr '/' '\')

free=$(powershell -NoProfile -c "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" | tr -d '\r')
case $free in ""|*[!0-9]*) echo "ERROR could not read free memory"; exit 1;; esac
if [ "$free" -lt "$min_free" ]; then echo "ERROR low memory: ${free}MB free < ${min_free}MB"; exit 1; fi
[ -d "$root_fwd/$wt" ] || { echo "ERROR no worktree $root_fwd/$wt"; exit 1; }

pane=$(herdr pane split --current --direction down --cwd "$path" --no-focus 2>/dev/null \
  | python -c "import json,sys;print(json.load(sys.stdin)['result']['pane']['pane_id'])")
[ -n "$pane" ] || { echo "ERROR pane split failed"; exit 1; }
herdr agent start "$name" --kind claude --pane "$pane" --timeout 60000 >/dev/null 2>&1
cwd=$(herdr agent get "$name" 2>/dev/null | python -c "import json,sys;print(json.load(sys.stdin)['result']['agent'].get('cwd',''))")
if [ "$cwd" != "$path" ]; then
  echo "ERROR $name cwd is '$cwd', expected '$path'; closing pane $pane"
  herdr pane close "$pane" >/dev/null 2>&1; exit 1
fi
herdr agent prompt "$name" "$prompt" --wait --timeout 15000 >/dev/null 2>&1
echo "$pane $(herdr agent get "$name" | python -c "import json,sys;print(json.load(sys.stdin)['result']['agent']['agent_status'])")"
