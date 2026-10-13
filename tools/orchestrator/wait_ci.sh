#!/bin/bash
# wait_ci.sh PR SHA7 [TIMEOUT_MIN] — waits until every check run on commit SHA7 of the PR has finished, then prints
# them. The "SonarCloud Code Analysis" check's conclusion is the PR's quality gate. Waiting on the head SHA avoids
# reading the previous commit's results. Exits 1 if the head moves or TIMEOUT_MIN (default 45) passes.
pr=$1; sha=$2; deadline=$(( $(date +%s) + ${3:-45} * 60 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  out=$(gh pr view "$pr" --json headRefOid,statusCheckRollup --jq '.headRefOid[:7] as $h
    | "head \($h)", (.statusCheckRollup[] | select(.__typename=="CheckRun") | select(.name|test("CodeRabbit")|not)
    | "\(.name) \(.status) \(.conclusion)")' 2>/dev/null)
  head=$(echo "$out" | sed -n 's/^head //p')
  if [ -n "$head" ] && [ "$head" != "$sha" ]; then echo "ERROR head is no longer $sha (now $head)"; exit 1; fi
  checks=$(echo "$out" | grep -v '^head ')
  if echo "$checks" | grep -q '^backend ' && echo "$checks" | grep -q '^SonarCloud' \
      && ! echo "$checks" | grep -qv ' COMPLETED '; then echo "$checks"; exit 0; fi
  sleep 15
done
echo "ERROR timed out waiting for CI on $sha"; exit 1
