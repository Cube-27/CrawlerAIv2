#!/bin/bash
# run_queue.sh QUEUE [--escalate AGENT] — runs a plan's merge queue with herdr and no model: starts builders, watches
# them, checks and merges their PRs, cleans up, and starts the next. Run it in its own herdr pane from the main
# checkout; it costs no tokens while it runs. A model is needed only for judgement, so the runner wakes one only then:
# on a builder's BLOCKED report, a permission dialog, a builder gone, a PR flagged for the owner, a builder that did
# not reach an accepted READY after two asks, and when the queue ends or can't move. Each of those shows a herdr
# notification and, with --escalate, is sent once to that agent (the orchestrator) as a prompt.
#
# QUEUE is a file outside the repo, one line per PR: `id  deps  brief  [owner]`, whitespace-separated. `id` is the
# builder's name, worktree and branch (`change/<id>`; herdr names: [a-z][a-z0-9_-]*), `deps` the ids that must merge
# first (comma-separated, `-` for none), `brief` the brief file, and `owner` holds the merge for the owner (a public API
# or contract change not yet approved). Lines starting with `#` are comments. State is kept in QUEUE.state (`id state
# [pr]`: queued, running, merged, held), so a restarted runner continues where it stopped. Delete an id's lines there to
# start it afresh (no worktree or branch of that id may exist then), or append `id running` to resume watching a
# builder you unblocked; after merging a held PR yourself, append `id merged PR`. At most QUEUE_BUILDERS (default 2)
# builders run at once; QUEUE_POLL_S (default 60) is the poll interval.
set -u
usage() { echo "usage: run_queue.sh QUEUE [--escalate AGENT]" >&2; exit 2; }
[[ $# -eq 1 || ($# -eq 3 && $2 == --escalate) ]] || usage
queue=$1; escalate=${3:-}; state=$queue.state
[[ -f $queue ]] || usage
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$here/lib.sh"
report='^\s*(READY TO MERGE|BLOCKED) #'
standing="builder-protocol.md HARD RULES apply; end with READY TO MERGE #<n> <sha7> or BLOCKED #<n>: <reason>."
touch "$state"
declare -A done_seq

log() { echo "$(date +%H:%M:%S) $*"; return 0; }

# get ID: the id's state line from QUEUE.state ("" when queued). `asked` lines only count the asks of an id, so a
# restart keeps the count.
get() { local id=$1; awk -v id="$id" '$1 == id && $2 != "asked" { line = $0 } END { print line }' "$state"; return 0; }
asks() { local id=$1; awk -v id="$id" '$1 == id && $2 == "asked" { n++ } END { print n + 0 }' "$state"; return 0; }
put() { echo "$*" >> "$state"; return 0; }   # the last line of an id wins

# tell MESSAGE: a herdr notification, and the escalation agent's prompt when one is named. One per event.
tell() {
  log "ESCALATE $*"
  herdr notification show "merge queue" --body "$*" --sound request >/dev/null 2>&1
  [[ -n $escalate ]] && herdr agent prompt "$escalate" "Merge queue ($queue): $*" >/dev/null 2>&1
  return 0
}

hold() { local id=$1 held=${2:-} reason=$3; put "$id held $held"; tell "$id: $reason"; return 0; }

status() {
  local id=$1
  herdr agent get "$id" 2>/dev/null | grep -o '"agent_status":"[a-z]*"' | head -1 | cut -d'"' -f4
  return 0
}

# The agent's completion_seq: it grows each time the agent ends a turn (herdr reports it once a turn has ended).
turn_of() {
  local id=$1
  herdr agent get "$id" 2>/dev/null | grep -o '"completion_seq":[0-9]*' | head -1 | cut -d: -f2
  return 0
}

# The report line that ended the agent's last turn, if it ended with one.
report_of() {
  local id=$1
  herdr agent read "$id" --source recent-unwrapped --lines 40 2>/dev/null | grep -E "$report" | tail -1 | sed 's/^\s*//'
  return 0
}

# ask ID MESSAGE: send the builder MESSAGE with the standing line; a third ask for one id holds it instead.
ask() {
  local id=$1 message=$2
  if (( $(asks "$id") >= 2 )); then hold "$id" "" "asked twice without a READY that pr_ready.sh accepts; last: $message"; return 0; fi
  put "$id asked"
  done_seq[$id]=$(turn_of "$id")
  herdr agent prompt "$id" "$message $standing" >/dev/null || hold "$id" "" "could not prompt the builder"
  log "$id: asked: $message"
  return 0
}

merged() { local id=$1; [[ $(get "$id") == "$id merged"* ]]; return $?; }

# checking ID: true while a pr_ready.sh started in the id's worktree still runs. A builder ends its turn while that
# check runs in the background and is woken when it exits, so such a turn end needs no ask.
checking() {
  local id=$1 wt pid
  wt=$(worktrees_root)/$id
  for pid in $(ps -eo pid=,args= | awk '/pr_ready\.sh/ && !/awk/ { print $1 }'); do
    [[ $(readlink "/proc/$pid/cwd" 2>/dev/null) == "$wt"* ]] && return 0
  done
  return 1
}

deps_merged() {
  local deps=$1 dep
  [[ $deps == - ]] && return 0
  for dep in ${deps//,/ }; do merged "$dep" || return 1; done
  return 0
}

start() {   # ID BRIEF
  local id=$1 brief=$2 wt pane
  wt=$(bash "$here/new_worktree.sh" "$id" "change/$id") || { hold "$id" "" "new_worktree.sh failed"; return 0; }
  rm -f "$wt/.env"
  pane=$(herdr tab create --cwd "$wt" --label "$id" --no-focus | grep -o '"pane_id":"[^"]*"' | head -1 | cut -d'"' -f4)
  herdr agent start "$id" --kind claude --pane "$pane" -- --permission-mode auto >/dev/null \
    || { hold "$id" "" "herdr agent start failed (folder-trust prompt? see its tab)"; return 0; }
  done_seq[$id]=$(turn_of "$id")
  herdr agent prompt "$id" "$(cat "$brief")" >/dev/null || { hold "$id" "" "could not send the brief"; return 0; }
  put "$id running"
  log "started $id in $wt"
}

merge() {   # ID PR SHA7 OWNER
  local id=$1 pr=$2 sha=$3 owner=$4 out full branch pane
  # The PR must be this builder's and its head the commit it reported; that head is the one checked and merged
  # (--match-head-commit), so a push after the check is never merged unchecked.
  read -r branch full <<< "$(gh pr view "$pr" --json headRefName,headRefOid --jq '"\(.headRefName) \(.headRefOid)"')"
  if [[ $branch != "change/$id" ]]; then hold "$id" "$pr" "reported PR #$pr is on ${branch:-?}, not change/$id"; return 0; fi
  if [[ $full != "$sha"* ]]; then
    ask "$id" "PR #$pr's head is ${full:0:7}, not the $sha you reported. Run pr_ready.sh on the head."
    return 0
  fi
  out=$(bash "$here/pr_ready.sh" "$pr" 2>&1 | tail -1)
  if [[ $out != "READY TO MERGE #$pr $sha"* ]]; then
    ask "$id" "pr_ready.sh says: $out. Fix it, push, and run pr_ready.sh again."
    return 0
  fi
  if [[ -n $owner ]]; then hold "$id" "$pr" "PR #$pr is ready and flagged for the owner's approval"; return 0; fi
  if ! out=$(gh pr merge "$pr" --squash --match-head-commit "$full" 2>&1 >/dev/null); then
    hold "$id" "$pr" "gh pr merge failed: $(echo "$out" | tail -1)"; return 0
  fi
  pane=$(herdr agent get "$id" 2>/dev/null | grep -o '"pane_id":"[^"]*"' | head -1 | cut -d'"' -f4)
  [[ -n $pane ]] && herdr pane close "$pane" >/dev/null 2>&1
  bash "$here/cleanup_worktree.sh" "$id" "change/$id" >/dev/null 2>&1 || log "$id: cleanup_worktree.sh failed; clean up by hand"
  git pull -q --ff-only || log "git pull failed"
  put "$id merged $pr"
  log "merged #$pr ($id)"
}

watch() {   # ID OWNER
  local id=$1 owner=$2 turn line now
  now=$(status "$id")
  [[ -z $now ]] && { sleep 5; now=$(status "$id"); }   # one failed herdr call is not a gone builder
  case $now in
    "") hold "$id" "" "builder gone before reporting"; return 0 ;;
    blocked) hold "$id" "" "builder waits at a permission or question dialog"; return 0 ;;
    idle|done) ;;
    *) return 0 ;;   # working, or not yet classified
  esac
  turn=$(turn_of "$id")
  [[ -n $turn && $turn == "${done_seq[$id]:-}" ]] && return 0   # this turn's end was handled already
  checking "$id" && return 0   # its readiness check still runs; the turn is handled once that check wakes it
  done_seq[$id]=$turn
  line=$(report_of "$id")
  if [[ $line =~ ^READY\ TO\ MERGE\ \#([0-9]+)\ ([0-9a-f]{7}) ]]; then
    merge "$id" "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" "$owner"
  elif [[ $line == BLOCKED* ]]; then
    hold "$id" "" "$line"
  else
    ask "$id" "Your turn ended without a report line. Continue your PR to pr_ready.sh's READY TO MERGE."
  fi
}

log "queue $queue, state $state${escalate:+, escalating to $escalate}"
# After a restart done_seq is empty, so each running builder's last ended turn is handled once more: a READY is
# re-checked by pr_ready.sh, which is safe to repeat.
while true; do
  running=0; busy=0; open=0
  # The queue is read on fd 3: herdr, gh and the scripts read stdin and would swallow its lines.
  while read -r id deps brief owner <&3; do
    case $(get "$id") in
      "$id running"*) watch "$id" "$owner" ;;
      *) ;;
    esac
  done 3< <(awk '!/^#/ && NF' "$queue")
  while read -r id deps brief owner <&3; do
    case $(get "$id") in
      "$id running"*) running=$((running + 1)); open=$((open + 1)) ;;
      # A held builder that is still alive keeps its slot, so holding one never starts a third.
      "$id held"*) open=$((open + 1)); [[ -n $(status "$id") ]] && busy=$((busy + 1)) ;;
      "$id merged"*) ;;
      *) open=$((open + 1))
         if deps_merged "$deps" && (( running + busy < ${QUEUE_BUILDERS:-2} )); then
           start "$id" "$brief"; running=$((running + 1))
         fi ;;
    esac
  done 3< <(awk '!/^#/ && NF' "$queue")
  if (( open == 0 )); then tell "every PR in the queue merged"; exit 0; fi
  if (( running == 0 )); then tell "the queue can't move: every open PR is held or waits on a held one"; exit 1; fi
  sleep "${QUEUE_POLL_S:-60}"
done
