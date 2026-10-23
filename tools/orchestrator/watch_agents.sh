#!/bin/bash
# watch_agents.sh NAME... — the orchestrator's one watcher for its builders; run it in the background and re-arm it
# after each event. Every WATCH_POLL_S seconds (default 60) it checks each named herdr agent and exits 0 with one line:
# - `NAME: READY TO MERGE #n sha` or `NAME: BLOCKED #n: reason`: a report line newer than the one on screen at start;
# - `BLOCKED-DIALOG NAME`: the agent waits at a permission or question dialog;
# - `GONE NAME`: the agent exited.
# A working agent is skipped, so a turn's own READY line is read only once the turn has ended. Exits 2 on no names.
set -u
(( $# > 0 )) || { echo "usage: watch_agents.sh NAME..." >&2; exit 2; }
report='^\s*(READY TO MERGE|BLOCKED) #'
declare -A seen

status() {
  herdr agent get "$1" 2>/dev/null | grep -o '"agent_status":"[a-z]*"' | head -1 | cut -d'"' -f4
  return 0
}

last_report() {
  herdr agent read "$1" --source recent-unwrapped --lines 200 2>/dev/null | grep -E "$report" | tail -1 | sed 's/^\s*//'
  return 0
}

for name in "$@"; do seen[$name]=$(last_report "$name"); done
while true; do
  sleep "${WATCH_POLL_S:-60}"
  for name in "$@"; do
    case $(status "$name") in
      "") echo "GONE $name"; exit 0 ;;
      blocked) echo "BLOCKED-DIALOG $name"; exit 0 ;;
      working) continue ;;
    esac
    line=$(last_report "$name")
    if [[ -n $line && $line != "${seen[$name]}" ]]; then echo "$name: $line"; exit 0; fi
  done
done
