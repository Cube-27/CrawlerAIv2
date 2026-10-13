#!/bin/bash
# start_agent.sh NAME WORKTREE PROMPT [MIN_FREE_MB]
# A worker (any NAME not starting with "reviewer") is refused when MAX_WORKERS (default 4, set by the owner) workers
# are already alive. Reviewers don't count: they run no builds or tests, so their memory use is small.
# Starts a claude herdr agent in <main>/../CrawlerAIv2-worktrees/WORKTREE, checks that the pane's cwd really is
# that worktree (a wrong cwd stops at a trust prompt in the home folder), refuses when free memory is low, then
# sends PROMPT. Prints "<pane> <status>", or "ERROR ..." on stderr and exits 1.
# Build paths here, never inline: in bash double quotes "...\$wt" collapses to a literal "$wt".
set -u
name=$1; wt=$2; prompt=$3; min_free=${4:-1500}
err() { echo "ERROR $*" >&2; exit 1; }
main=$(git worktree list --porcelain | sed -n '1s/^worktree //p')   # e.g. C:/Projects/CrawlerAIv2
root_fwd="$(dirname "$main")/CrawlerAIv2-worktrees"
path=$(cygpath -w "$root_fwd/$wt" 2>/dev/null || echo "$root_fwd/$wt" | tr '/' '\')

free=$(powershell -NoProfile -c "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" | tr -d '\r')
[[ $free =~ ^[0-9]+$ ]] || err "could not read free memory"
(( free >= min_free )) || err "low memory: ${free}MB free < ${min_free}MB"
[[ -d "$root_fwd/$wt" ]] || err "no worktree $root_fwd/$wt"
if [[ $name != reviewer* ]]; then
  workers=$(herdr agent list 2>/dev/null | python -c "import json,sys;print(sum(1 for a in json.load(sys.stdin)['result']['agents'] if a.get('name') and not a['name'].startswith('reviewer')))")
  [[ $workers =~ ^[0-9]+$ ]] || err "could not count live workers"
  (( workers < ${MAX_WORKERS:-4} )) || err "worker limit: $workers alive, max ${MAX_WORKERS:-4}"
fi

pane=$(herdr pane split --current --direction down --cwd "$path" --no-focus 2>/dev/null \
  | python -c "import json,sys;print(json.load(sys.stdin)['result']['pane']['pane_id'])")
[[ -n $pane ]] || err "pane split failed"
close_and_fail() { herdr pane close "$pane" >/dev/null 2>&1; err "$1; closed pane $pane"; }
herdr agent start "$name" --kind claude --pane "$pane" --timeout 60000 >/dev/null 2>&1
cwd=$(herdr agent get "$name" 2>/dev/null | python -c "import json,sys;print(json.load(sys.stdin)['result']['agent'].get('cwd',''))")
[[ $cwd == "$path" ]] || close_and_fail "$name cwd is '$cwd', expected '$path'"
status() {
  herdr agent get "$name" | python -c "import json,sys;print(json.load(sys.stdin)['result']['agent']['agent_status'])"
  return 0
}
# A prompt sent while the agent is still loading can be dropped, so it stays idle: wait up to 15 s for a turn to
# start, resend once, and fail if it still hasn't started.
started() {
  local _
  for _ in $(seq 15); do
    case $(status) in
      working|blocked) return 0 ;;
      *) sleep 1 ;;
    esac
  done
  return 1
}
for attempt in 1 2; do
  herdr agent prompt "$name" "$prompt" >/dev/null 2>&1 || close_and_fail "prompt to $name failed"
  if started; then echo "$pane $(status)"; exit 0; fi
  [[ $attempt == 1 ]] && echo "WARN $name idle after the prompt; resending" >&2
done
close_and_fail "$name never started a turn"
