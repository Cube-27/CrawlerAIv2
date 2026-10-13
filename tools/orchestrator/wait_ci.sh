#!/bin/bash
# wait_ci.sh PR SHA7 [TIMEOUT_MIN] — waits until every check run on commit SHA7 of the PR has finished, then prints
# them. The "SonarCloud Code Analysis" check's conclusion is the PR's quality gate. Waiting on the head SHA avoids
# reading the previous commit's results. Exits 0 only when every check passed (SUCCESS, NEUTRAL or SKIPPED); 1 on a
# failed check, a moved head or TIMEOUT_MIN (default 45). Right after a push GitHub may still report the old head,
# so a different head is an error once it is neither SHA7 nor the head seen first, or after 3 minutes.
# GitHub starts no pull_request workflow on a PR that conflicts with its base (#109 waited 30 minutes for checks that
# never came), so a conflicting PR is an error at once, and so is a head with no workflow run after
# WAIT_CI_NO_RUN_S seconds (default 300). WAIT_CI_POLL_S (default 15) is the poll interval.
pr=$1; sha=$2; deadline=$(( $(date +%s) + ${3:-45} * 60 )); lag_end=$(( $(date +%s) + 180 )); first=""
poll=${WAIT_CI_POLL_S:-15}; no_run_end=$(( $(date +%s) + ${WAIT_CI_NO_RUN_S:-300} ))
err() { echo "ERROR $*" >&2; exit 1; }

# Fails when the PR conflicts with its base; mergeable is UNKNOWN while GitHub is still computing it.
check_conflict() {
  case "$1" in
    *CONFLICTING*|*DIRTY*) err "PR #$pr conflicts with main: rebase onto origin/main" ;;
    *) return 0 ;;
  esac
}

# Fails when no workflow run (a check run with a workflow name) has appeared for the head by the grace deadline.
check_runs_started() {
  if [[ $1 == 0 ]] && (( $(date +%s) >= no_run_end )); then
    err "no workflow run for $sha after ${WAIT_CI_NO_RUN_S:-300}s and the PR does not conflict: check the workflow triggers or re-push"
  fi
  return 0
}

while (( $(date +%s) < deadline )); do
  out=$(gh pr view "$pr" --json headRefOid,mergeable,mergeStateStatus,statusCheckRollup --jq '.headRefOid[:7] as $h
    | "head \($h)", "merge \(.mergeable) \(.mergeStateStatus)",
      "runs \([.statusCheckRollup[] | select(.__typename=="CheckRun") | select((.workflowName // "") != "")] | length)",
      (.statusCheckRollup[] | select(.__typename=="CheckRun") | select(.name|test("CodeRabbit")|not)
    | "\(.name) \(.status) \(.conclusion)")' 2>/dev/null)
  head=$(sed -n 's/^head //p' <<< "$out")
  [[ -z $first ]] && first=$head
  if [[ -n $head && $head != "$sha" ]]; then
    if [[ $head != "$first" ]] || (( $(date +%s) >= lag_end )); then err "head is no longer $sha (now $head)"; fi
    sleep "$poll"; continue   # GitHub has not caught up with the push yet
  fi
  if [[ $head == "$sha" ]]; then
    check_conflict "$(sed -n 's/^merge //p' <<< "$out")"
    check_runs_started "$(sed -n 's/^runs //p' <<< "$out")"
  fi
  checks=$(grep -vE '^(head|merge|runs) ' <<< "$out")
  if [[ $head == "$sha" ]] && grep -q '^backend ' <<< "$checks" && grep -q '^SonarCloud' <<< "$checks" \
      && ! grep -qv ' COMPLETED ' <<< "$checks"; then
    echo "$checks"
    if grep -qvE ' (SUCCESS|NEUTRAL|SKIPPED)$' <<< "$checks"; then err "a check did not pass"; fi
    exit 0
  fi
  sleep "$poll"
done
err "timed out waiting for CI on $sha"
