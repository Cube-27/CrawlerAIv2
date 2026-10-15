---
name: review-pr
description: Review one complete PR (implemented and simplified by its implementor, CI green; the reviewer never runs /simplify) against its spec rows (a PR covers a batch of related rows), the generalization contract and the engineering principles, and return a merge verdict. Use before merging any PR, or when asked to review a branch or PR.
---

# Review a PR

A single reviewer with a verdict, not a panel. You did not write this code: read it adversarially, then judge it
pragmatically. Don't push commits to the branch; the author fixes. Adapted from pstack's `interrogate` (MIT, see
`NOTICE`).

## 0. Only a complete PR, reviewed once

Review when the implementor hands over a finished PR: implemented, and every CI check green on the head
commit, SonarCloud included (`tools/orchestrator/wait_ci.sh <n> <head-sha7>`). If CI is red, don't review: tell the
implementor and stop. Don't run builds or tests yourself; CI did. One single agent does the whole review, once per
PR, whatever its size; don't run `/simplify` (`CLAUDE.md` §3).

## 1. Scope and intent

- `gh pr view <n>` and `gh pr diff <n>`. Find the spec rows the PR claims (a batch), and read those rows, the
  spec's acceptance criteria and invariants, and the ARCHITECTURE sections and decisions that `CLAUDE.md` §1 items
  3-4 name, by section, never in full.
- Write the intent in one paragraph: what the PR must achieve, row by row, and what it must not touch. If the PR
  doesn't match its rows, that is the first finding.

## 2. Check, in this order

1. **Contract (`CLAUDE.md` §2).** Each one is a blocking defect:
   - a hostname, brand or copied page string outside `adapters/`;
   - a phrase or stop-word list;
   - a default that invents a value;
   - a generic DOM selector;
   - a test named after a site;
   - any access to hidden or fresh data;
   - a §22 candidate built;
   - `exec`/`eval` of LLM output;
   - a dependency with a denied license;
   - a customer name or secret in a public file.
2. **Correctness.** Trace real call paths, not hypotheticals. A "what if X is None" finding counts only if a caller
   can actually pass None. Check idempotence for queue tasks, migrations and jobs.
3. **Proof.** Every acceptance criterion of every row maps to a test or command that ran green in CI or in the PR's
   Verification section. Apply the test-behaviour rule: a test that would still pass if the function returned a
   wrong value proves nothing. For extraction changes, the dev delta is present and the hidden gate passed.
4. **Scope and simplicity.** Code outside the batch's rows, speculative options, wrappers with one caller, and
   compatibility shims.
5. **Decisions.** Choices the spec didn't make are listed in the PR's `## Decisions` section. Anything that should
   have been escalated (`CLAUDE.md` §4) is a blocking finding.
6. **SonarCloud and recurring findings.** Read the PR's gate (`tools/orchestrator/wait_ci.sh <n> <head-sha7>`
   prints it). A red gate is an Act-on item. Check the diff against `docs/plans/RECURRING.md` and ENGINEERING's
   "Patterns the analysers flag": a repeat of a listed mistake is an Act-on item.
7. **Frontend PRs.** The PR follows the `docs/DESIGN.md` Patterns, uses no second way to do a listed job, and has
   no styling outside `frontend/src/app/theme.css`. A deviation is an Act-on item.

## 3. Judge

Before sorting, re-check each finding against the code. Drop false positives:
- pre-existing issues, and lines the PR didn't change;
- anything a linter, type checker, test or SonarCloud would catch;
- nits a senior engineer wouldn't raise, and intentional changes that follow from the row.

Act on only what you have verified is real and will be hit in practice.

Sort every finding into one bucket, with a one-line reason each:
- **Act on.** Correctness, security, contract or scope defects. These block the merge. If there are more than 5,
  you aren't filtering hard enough.
- **Consider.** Legitimate, but the cost of fixing now may not be worth it. A follow-up row is fine.
- **Noted.** Valid but not actionable at this stage.
- **Dismissed.** Wrong, a style preference ("I'd have done it differently"), or missing context. Say why. This list
  lets the owner override you.

Filter for "nitpick gravity". If all you have are nits, the code is fine; say so.

## 4. Verdict

Post the review as a PR comment (`gh pr comment <n> --body-file …`), never with `gh pr review`: the implementor and
`watch_agents.sh` read comments only. Start it with a `## Review: #<n> at <sha7>` heading and give the verdict on
its own line as `**Verdict: <verdict>**`: every agent posts as the same GitHub account, so `merge_pr.sh` tells a
review from the implementor's comments by this form. The comment holds the intent, the buckets and one of these
verdicts:
- `MERGE`: no Act-on items and CI is green;
- `MERGE AFTER FIX`: the PR merges once the listed Act-on items are fixed and CI is green again. There is no
  second review, so make each item specific enough that the fix is unambiguous;
- `ESCALATE`: needs the owner (`CLAUDE.md` §4); name the question.

Never approve with an Act-on item open, and never approve on red CI. Link each Act-on item to the code at the head
commit (`https://github.com/<owner>/<repo>/blob/<full-sha>/<path>#L<a>-L<b>`). Send the verdict and the Act-on list
to the implementor with `herdr agent prompt <implementor> "…"`. Then close your own pane:
`herdr pane close "$HERDR_PANE_ID"`. An idle reviewer pane holds about 400 MB, and idle reviewers caused low-memory
reaping. There is no re-review (owner, 2026-10-13).

End the comment with one line naming the category of each Act-on item, for example
`Categories: path-traversal, sonar-gate`. The orchestrator tallies these lines to spot recurring mistakes.
