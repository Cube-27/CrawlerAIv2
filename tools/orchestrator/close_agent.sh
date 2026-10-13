#!/bin/bash
# close_agent.sh NAME — closes the herdr pane of agent NAME, so an idle agent stops holding memory (an idle reviewer
# pane holds about 400 MB). An agent that is already gone is not an error: prints "gone NAME" and exits 0.
# Prints "closed NAME PANE", or "ERROR ..." on stderr and exits 1.
set -u
name=${1:-}
err() {
  echo "ERROR $*" >&2
  exit 1
}
[[ -n $name ]] || err "usage: close_agent.sh NAME"
if ! info=$(herdr agent get "$name" 2>/dev/null); then
  echo "gone $name"
  exit 0
fi
pane=$(python -c 'import json,sys;print(json.load(sys.stdin)["result"]["agent"]["pane_id"])' <<< "$info")
[[ -n $pane ]] || err "no pane for agent $name"
herdr pane close "$pane" >/dev/null 2>&1 || err "could not close pane $pane of $name"
echo "closed $name $pane"
exit 0
