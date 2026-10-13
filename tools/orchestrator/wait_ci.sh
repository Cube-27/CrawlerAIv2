#!/bin/bash
# wait_ci.sh PR SHA7 — waits until every required check has finished on commit SHA7 of the PR, then prints them
# and the PR's SonarCloud gate. Waiting on the head SHA avoids reading the previous commit's results.
pr=$1; sha=$2
while true; do
  out=$(gh pr view "$pr" --json headRefOid,statusCheckRollup --jq '.headRefOid[:7] as $h | .statusCheckRollup[]
    | select(.__typename=="CheckRun") | select(.name|test("SonarCloud|CodeRabbit")|not)
    | "\($h) \(.name) \(.status) \(.conclusion)"' 2>/dev/null)
  if [ "$(gh pr view "$pr" --json headRefOid --jq '.headRefOid[:7]')" != "$sha" ]; then echo "ERROR head is no longer $sha"; exit 1; fi
  if echo "$out" | grep -q "^$sha .*backend" && ! echo "$out" | grep -qv "COMPLETED"; then echo "$out"; break; fi
  sleep 15
done
repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner | tr '/' '_')
echo "sonar $(curl -s "https://sonarcloud.io/api/qualitygates/project_status?projectKey=$repo&pullRequest=$pr" \
  | python -c "import json,sys;print(json.load(sys.stdin)['projectStatus']['status'])" 2>/dev/null)"
