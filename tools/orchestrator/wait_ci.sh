#!/bin/bash
# wait_ci.sh PR SHA7 [TIMEOUT_MIN] — waits until every check run on commit SHA7 of the PR has finished, then prints
# them. The "SonarCloud Code Analysis" check's conclusion is the PR's quality gate. Waiting on the head SHA avoids
# reading the previous commit's results. Exits 0 only when every check passed (SUCCESS, NEUTRAL or SKIPPED); 1 on a
# failed check, a moved head or TIMEOUT_MIN (default 45). Right after a push GitHub may still report the old head,
# so a different head is an error once it is neither SHA7 nor the head seen first, or after 3 minutes.
pr=$1; sha=$2; deadline=$(( $(date +%s) + ${3:-45} * 60 )); lag_end=$(( $(date +%s) + 180 )); first=""
while [ "$(date +%s)" -lt "$deadline" ]; do
  out=$(gh pr view "$pr" --json headRefOid,statusCheckRollup --jq '.headRefOid[:7] as $h
    | "head \($h)", (.statusCheckRollup[] | select(.__typename=="CheckRun") | select(.name|test("CodeRabbit")|not)
    | "\(.name) \(.status) \(.conclusion)")' 2>/dev/null)
  head=$(echo "$out" | sed -n 's/^head //p')
  [ -z "$first" ] && first=$head
  if [ -n "$head" ] && [ "$head" != "$sha" ]; then
    if [ "$head" != "$first" ] || [ "$(date +%s)" -ge "$lag_end" ]; then echo "ERROR head is no longer $sha (now $head)"; exit 1; fi
    sleep 15; continue   # GitHub has not caught up with the push yet
  fi
  checks=$(echo "$out" | grep -v '^head ')
  if [ "$head" = "$sha" ] && echo "$checks" | grep -q '^backend ' && echo "$checks" | grep -q '^SonarCloud' \
      && ! echo "$checks" | grep -qv ' COMPLETED '; then
    echo "$checks"
    if echo "$checks" | grep -qvE ' (SUCCESS|NEUTRAL|SKIPPED)$'; then echo "ERROR a check did not pass"; exit 1; fi
    exit 0
  fi
  sleep 15
done
echo "ERROR timed out waiting for CI on $sha"; exit 1
