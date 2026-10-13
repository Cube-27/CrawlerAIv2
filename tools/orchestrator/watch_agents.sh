#!/bin/bash
# One watcher for every herdr agent: exits (printing why) as soon as any named agent stops working,
# disappears, or free memory falls below MIN_FREE_MB. Replaces one `herdr agent wait` per agent.
MIN_FREE_MB=${MIN_FREE_MB:-1500}
INTERVAL=${INTERVAL:-30}

snapshot() {
  herdr agent list 2>/dev/null | python -c "import json,sys
for a in json.load(sys.stdin)['result']['agents']:
    if a.get('name'): print(a['name'], a['agent_status'])" 2>/dev/null | sort
}
free_mb() { powershell -NoProfile -c "[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)" 2>/dev/null | tr -d '\r'; }

prev=$(snapshot)
while true; do
  sleep "$INTERVAL"
  cur=$(snapshot)
  # An agent that was working and now isn't, or that vanished.
  while read -r name status; do
    [ -z "$name" ] && continue
    [ "$status" != "working" ] && continue
    now=$(echo "$cur" | awk -v n="$name" '$1==n{print $2}')
    if [ -z "$now" ]; then echo "GONE $name"; exit 0; fi
    if [ "$now" != "working" ]; then echo "SETTLED $name $now"; exit 0; fi
  done <<< "$prev"
  mem=$(free_mb)
  if [ -n "$mem" ] && [ "$mem" -lt "$MIN_FREE_MB" ]; then echo "LOWMEM ${mem}MB"; exit 0; fi
  prev=$cur
done
