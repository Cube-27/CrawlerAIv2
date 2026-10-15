#!/bin/bash
# wait_ci.sh PR SHA7 [TIMEOUT_MIN] — waits until every check run on commit SHA7 of the PR has finished, then prints
# them. The "SonarCloud Code Analysis" check's conclusion is the PR's quality gate. Waiting on the head SHA avoids
# reading the previous commit's results. Exits 0 only when every check passed (SUCCESS, NEUTRAL or SKIPPED); 1 on a
# failed check, a moved head or TIMEOUT_MIN (default 45). Right after a push GitHub may still report the old head,
# so a different head is an error once it is neither SHA7 nor the head seen first, or after 3 minutes.
# GitHub starts no pull_request workflow on a PR that conflicts with its base (#109 waited 30 minutes for checks that
# never came), so a conflicting PR is an error at once, and so is a head whose `backend` check (reported even when
# the `changes` job skips it) has not appeared after WAIT_CI_NO_RUN_S seconds (default 300). WAIT_CI_POLL_S (default
# 15) is the poll interval.
pr=$1; sha=$2; deadline=$(( $(date +%s) + ${3:-45} * 60 )); lag_end=$(( $(date +%s) + 180 )); first=""
poll=${WAIT_CI_POLL_S:-15}; no_run_s=${WAIT_CI_NO_RUN_S:-300}; no_run_end=$(( $(date +%s) + no_run_s ))
err() { echo "ERROR $*" >&2; exit 1; }

# Fails when the PR conflicts with its base; mergeable is UNKNOWN while GitHub is still computing it.
check_conflict() {
  local state=$1
  case "$state" in
    *CONFLICTING*|*DIRTY*) err "PR #$pr conflicts with main: rebase onto origin/main" ;;
    *) return 0 ;;
  esac
}

# Fails when the ci workflow has not started on the head by the grace deadline.
check_ci_started() {
  local checks=$1
  if ! grep -q '^backend ' <<< "$checks" && (( $(date +%s) >= no_run_end )); then
    err "no workflow run for $sha after ${no_run_s}s and the PR does not conflict: check the workflow triggers or re-push"
  fi
  return 0
}

while (( $(date +%s) < deadline )); do
  out=$(gh pr view "$pr" --json headRefOid,mergeable,mergeStateStatus,statusCheckRollup --jq '
    "\(.headRefOid[:7]) \(.mergeable) \(.mergeStateStatus)",
    (.statusCheckRollup[] | select(.__typename=="CheckRun") | select(.name|test("CodeRabbit")|not)
    | "\(.name) \(.status) \(.conclusion)")' 2>/dev/null)
  read -r head merge <<< "${out%%$'\n'*}"
  [[ -z $first ]] && first=$head
  if [[ -n $head && $head != "$sha" ]]; then
    if [[ $head != "$first" ]] || (( $(date +%s) >= lag_end )); then err "head is no longer $sha (now $head)"; fi
    sleep "$poll"; continue   # GitHub has not caught up with the push yet
  fi
  [[ $head == "$sha" ]] || { sleep "$poll"; continue; }   # gh failed; retry
  checks=$(tail -n +2 <<< "$out")
  check_conflict "$merge"
  check_ci_started "$checks"
  if grep -q '^SonarCloud' <<< "$checks" && grep -q '^backend ' <<< "$checks" && ! grep -qv ' COMPLETED ' <<< "$checks"; then
    echo "$checks"
    if grep -qvE ' (SUCCESS|NEUTRAL|SKIPPED)$' <<< "$checks"; then err "a check did not pass"; fi
    exit 0
  fi
  sleep "$poll"
done
err "timed out waiting for CI on $sha"
