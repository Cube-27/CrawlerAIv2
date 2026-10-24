#!/bin/bash
# pr_ready.sh PR — the one definition of "ready to merge". The builder runs it before it reports, the orchestrator
# before it merges; both report its last line as printed. It waits, so CI or a bot still running is never a reason
# to stop. In order:
# 1. CI on the PR's head passes (`wait_ci.sh`; it also fails a PR that conflicts with main).
# 2. CodeAnt's review has finished. CodeAnt reviews a PR's first commit only and skips PRs over 100 files, so a later
#    push never waits for it. CODEANT_WAIT_S (default 900) bounds the wait; past it the PR is ready without the review,
#    with a warning.
# 3. No unresolved review thread (`unresolved.sh`): every bot point is fixed or answered, then resolved.
# 4. SonarCloud found no new bug or vulnerability and no security hotspot to review on the PR. Code smells don't block:
#    they wait for the batched Sonar cleanup (`docs/agents/orchestrator.md`, Sonar), so a builder never spends a push
#    and a CI round on one.
# Prints `READY TO MERGE #PR SHA7` and exits 0, or `NOT READY #PR: reason` and exits 1; exits 2 on bad arguments.
# Above that line it prints the PR's open code smells and, when 20 or more PRs merged since the last Sonar cleanup
# (a commit with scope `sonar`), that one is due.
set -u
[[ $# -eq 1 && $1 =~ ^[0-9]+$ ]] || { echo "usage: pr_ready.sh PR" >&2; exit 2; }
pr=$1
here=$(dirname "${BASH_SOURCE[0]}")
sonar="https://sonarcloud.io/api"
project="Cube-27_CrawlerAIv2"
no() { echo "NOT READY #$pr: $*"; exit 1; }

# The first "total" of a SonarCloud search answer: the issue count, or the hotspot count under "paging".
sonar_total() {
  local path=$1
  curl -fsS "$sonar/$path" | grep -o '"total":[0-9]*' | head -1 | cut -d: -f2
  return 0
}

read -r sha files <<< "$(gh pr view "$pr" --json headRefOid,changedFiles --jq '"\(.headRefOid[:7]) \(.changedFiles)"')"
[[ -n ${sha:-} ]] || no "cannot read the PR"

bash "$here/wait_ci.sh" "$pr" "$sha" >/dev/null || no "CI did not pass on $sha (the error is above)"

if (( files <= 100 )); then
  end=$(( $(date +%s) + ${CODEANT_WAIT_S:-900} ))
  until gh api "repos/{owner}/{repo}/issues/$pr/comments" --paginate \
      --jq '.[] | select(.user.login | startswith("codeant")) | .body' 2>/dev/null \
      | grep -q 'codeant-review-status:.*"done":true'; do
    if (( $(date +%s) >= end )); then
      echo "warning: CodeAnt's review has not finished; ready without it" >&2
      break
    fi
    sleep 20
  done
fi

threads=$(bash "$here/unresolved.sh" "$pr") || no "cannot read the review threads"
(( threads == 0 )) || no "$threads unresolved review thread(s): fix or answer each, then resolve it"

issues="issues/search?componentKeys=$project&pullRequest=$pr&resolved=false&ps=1"
bugs=$(sonar_total "$issues&types=BUG,VULNERABILITY")
hotspots=$(sonar_total "hotspots/search?projectKey=$project&pullRequest=$pr&status=TO_REVIEW&ps=1")
smells=$(sonar_total "$issues&types=CODE_SMELL")
[[ -n $bugs && -n $hotspots ]] || no "cannot read SonarCloud's result for the PR"
(( bugs == 0 )) || no "SonarCloud found $bugs new bug(s) or vulnerability(ies): fix them"
(( hotspots == 0 )) || no "SonarCloud has $hotspots security hotspot(s) to review: fix them or say why in the PR"
(( ${smells:-0} == 0 )) || echo "info: $smells Sonar code smell(s) left for the batched cleanup"

since=$(git log origin/main --format=%s 2>/dev/null | awk '/^[a-z]+\(sonar\)/ { exit } { n++ } END { print n + 0 }')
(( since < 20 )) || echo "info: $since PRs merged since the last Sonar cleanup; one is due (orchestrator.md, Sonar)"

echo "READY TO MERGE #$pr $sha"
