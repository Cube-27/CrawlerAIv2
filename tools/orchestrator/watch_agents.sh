#!/bin/bash
# One watcher for every herdr agent: exits (printing why) as soon as any named agent is not working
# (SETTLED <name> <status>, including one already idle at start; `unknown` counts as working, since herdr reports
# it briefly for agents mid-turn), disappears (GONE <name>), or free memory
# falls below MIN_FREE_MB (LOWMEM), or a new comment starting READY, BLOCKED or ESCALATE appears on an open PR
# (PRCOMMENT <n>; counted from start). Replaces one `herdr agent wait` per agent.
# IGNORE: comma-separated agent names to skip, e.g. implementors left waiting for `YOUR TURN`.
# Single instance: exits 2 with "ERROR another watcher is running (pid N, windows pid W)" on stderr while a live
# watcher holds the pidfile; a stale pidfile is cleared. Start it only as a tracked background task, never with `&`.
MIN_FREE_MB=${MIN_FREE_MB:-1500}
INTERVAL=${INTERVAL:-30}
IGNORE=${IGNORE:-}

snapshot() {
  # Windows Python prints CRLF; strip \r so statuses compare equal.
  herdr agent list 2>/dev/null | python -c "import json,sys
for a in json.load(sys.stdin)['result']['agents']:
    if a.get('name'): print(a['name'], a['agent_status'])" 2>/dev/null | tr -d '\r' | sort
  return 0
}
free_mb() {
  powershell -NoProfile -c "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null \
    | tr -d '\r'
  return 0
}
pr_signals() {
  # One "<pr> <count>" line per open PR: comments whose body starts with READY, BLOCKED or ESCALATE.
  gh pr list --state open --json number,comments --jq \
    '.[] | "\(.number) \([.comments[] | select(.body | test("^ *(READY|BLOCKED|ESCALATE)"))] | length)"' \
    2>/dev/null | tr -d '\r'
  return "${PIPESTATUS[0]}"
}
ignored() {
  local name=$1
  case ",$IGNORE," in
    *",$name,"*) return 0 ;;
    *) return 1 ;;
  esac
}

# Single instance: a watcher started detached (`&`) can never notify the orchestrator, and a second watcher means
# events go to the wrong one. The pidfile holds "<pid> <windows pid>" and lives in the git common dir, shared by
# every worktree.
lock=$(git rev-parse --git-common-dir)/watch_agents.lock
alive() {
  local pid=$1 winpid=$2 name
  if kill -0 "$pid" 2>/dev/null; then return 0; fi
  # kill -0 sees only this MSYS runtime's processes; ask Windows, and accept only a bash (pids are reused).
  [[ $winpid =~ ^[0-9]+$ ]] || return 1
  name=$(powershell -NoProfile -c "(Get-Process -Id $winpid -ErrorAction SilentlyContinue).ProcessName" \
    2>/dev/null | tr -d '\r')
  [[ $name == bash ]]
  return
}
take_lock() {
  local tmp="$lock.$$" pid winpid rc=1
  read -r winpid < "/proc/$$/winpid" 2>/dev/null
  echo "$$ $winpid" > "$tmp" || return 1
  # ln fails if the pidfile exists, so creating it is atomic and exclusive; one retry after clearing a stale one.
  for _ in 1 2; do
    if ln "$tmp" "$lock" 2>/dev/null; then rc=0; break; fi
    read -r pid winpid < "$lock" 2>/dev/null
    if [[ -n $pid ]] && alive "$pid" "$winpid"; then
      echo "ERROR another watcher is running (pid $pid, windows pid $winpid)" >&2
      rc=2; break
    fi
    rm -f "$lock"
  done
  rm -f "$tmp"
  if (( rc == 1 )); then echo "ERROR could not take $lock" >&2; fi
  return "$rc"
}
release_lock() {
  local pid
  read -r pid _ < "$lock" 2>/dev/null
  if [[ $pid == "$$" ]]; then rm -f "$lock"; fi
  return 0
}

take_lock || exit "$?"
trap release_lock EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

prev=""
until signals=$(pr_signals); do sleep "$INTERVAL"; done   # baseline: comments already there don't count
while true; do
  if now_signals=$(pr_signals); then
    while read -r pr count; do
      [[ -z $pr ]] && continue
      before=$(awk -v n="$pr" '$1==n{print $2}' <<< "$signals")
      if (( count > ${before:-0} )); then echo "PRCOMMENT $pr"; exit 0; fi
    done <<< "$now_signals"
    signals=$now_signals
  fi
  cur=$(snapshot)
  # A failed poll is not every agent gone; keep the last good snapshot.
  if [[ -n $cur ]]; then
    while read -r name _; do
      if [[ -z $name ]] || ignored "$name"; then continue; fi
      if ! awk -v n="$name" '$1==n{f=1} END{exit !f}' <<< "$cur"; then echo "GONE $name"; exit 0; fi
    done <<< "$prev"
    while read -r name status; do
      if [[ -z $name || $status == "working" || $status == "unknown" ]] || ignored "$name"; then continue; fi
      echo "SETTLED $name $status"; exit 0
    done <<< "$cur"
    prev=$cur
  fi
  mem=$(free_mb)
  if [[ $mem =~ ^[0-9]+$ ]] && (( mem < MIN_FREE_MB )); then echo "LOWMEM ${mem}MB"; exit 0; fi
  sleep "$INTERVAL"
done
