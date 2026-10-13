---
name: review-pr
description: Review one PR against its spec row, the generalization contract and the engineering principles, and return a merge verdict. Use before merging any PR, or when asked to review a branch or PR.
---

# Review a PR

A single reviewer with a verdict, not a panel. You did not write this code: read it adversarially, then judge it
pragmatically. Don't push commits to the branch; the author fixes. Adapted from pstack's `interrogate` (MIT, see
`NOTICE`).

## 1. Scope and intent

- `gh pr view <n>` and `gh pr diff <n>`. Find the spec row the PR claims, and read that row, the spec's acceptance
  criteria and invariants, and the ARCHITECTURE sections it cites.
- Write the intent in one paragraph: what the PR must achieve and what it must not touch. If the PR doesn't match
  its row, that is the first finding.

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
3. **Proof.** Every acceptance criterion maps to a test or command that ran green in CI or in the PR's
   Verification section. Apply the test-behaviour rule: a test that would still pass if the function returned a
   wrong value proves nothing. For extraction changes, the dev delta is present and the hidden gate passed.
4. **Scope and simplicity.** Code outside the row's scope, speculative options, wrappers with one caller, and
   compatibility shims.
5. **Decisions.** Choices the spec didn't make are listed in the PR's `## Decisions` section. Anything that should
   have been escalated (`CLAUDE.md` §4) is a blocking finding.
6. **SonarCloud and recurring findings.** Read the PR's gate (`tools/orchestrator/wait_ci.sh <n> <head-sha7>`
   prints it). A red gate is an Act-on item. Check the diff against `docs/plans/RECURRING.md`: a repeat of a listed mistake is an Act-on item.

## 3. Judge

Sort every finding into one bucket, with a one-line reason each:
- **Act on.** Correctness, security, contract or scope defects. These block the merge. If there are more than 5,
  you aren't filtering hard enough.
- **Consider.** Legitimate, but the cost of fixing now may not be worth it. A follow-up row is fine.
- **Noted.** Valid but not actionable at this stage.
- **Dismissed.** Wrong, a style preference ("I'd have done it differently"), or missing context. Say why. This list
  lets the owner override you.

Filter for "nitpick gravity". If all you have are nits, the code is fine; say so.

## 4. Verdict

Post the review as a PR comment (`gh pr review <n> --comment --body-file …`) with the intent, the buckets and one of
these verdicts:
- `MERGE`: no Act-on items and CI is green;
- `FIX`: Act-on items listed, to go back to the author;
- `ESCALATE`: needs the owner (`CLAUDE.md` §4); name the question.

Never approve with an Act-on item open, and never approve on red CI.

End the comment with one line naming the category of each Act-on item, for example
`Categories: path-traversal, sonar-gate`. The orchestrator tallies these lines to spot recurring mistakes.
