#!/bin/bash
# One watcher for every herdr agent: exits (printing why) as soon as any named agent is not working
# (SETTLED <name> <status>, including one already idle at start), disappears (GONE <name>), or free memory
# falls below MIN_FREE_MB (LOWMEM). Replaces one `herdr agent wait` per agent.
# IGNORE: comma-separated agent names to skip, e.g. implementors left waiting for `YOUR TURN`.
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
ignored() {
  case ",$IGNORE," in
    *",$1,"*) return 0 ;;
    *) return 1 ;;
  esac
}

prev=""
while true; do
  cur=$(snapshot)
  # A failed poll is not every agent gone; keep the last good snapshot.
  if [[ -n $cur ]]; then
    while read -r name _; do
      if [[ -z $name ]] || ignored "$name"; then continue; fi
      if ! awk -v n="$name" '$1==n{f=1} END{exit !f}' <<< "$cur"; then echo "GONE $name"; exit 0; fi
    done <<< "$prev"
    while read -r name status; do
      if [[ -z $name || $status == "working" ]] || ignored "$name"; then continue; fi
      echo "SETTLED $name $status"; exit 0
    done <<< "$cur"
    prev=$cur
  fi
  mem=$(free_mb)
  if [[ $mem =~ ^[0-9]+$ ]] && (( mem < MIN_FREE_MB )); then echo "LOWMEM ${mem}MB"; exit 0; fi
  sleep "$INTERVAL"
done
