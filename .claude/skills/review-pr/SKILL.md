---
name: review-pr
description: Review one complete PR (implemented by its implementor, CI green) as one single agent that also does the simplification review against its change's tasks and spec deltas (a PR covers a batch of tasks of one OpenSpec change), the generalization contract and the engineering principles, and return a merge verdict. Use before merging any PR, or when asked to review a branch or PR.
---

# Review a PR

A single reviewer with a verdict, not a panel. You did not write this code: read it adversarially, then judge it
pragmatically. Don't push commits to the branch; the author fixes. Adapted from pstack's `interrogate` (MIT, see
`NOTICE`).

## 0. Only a complete PR, reviewed once

Review when the implementor hands over a finished PR: implemented, and every CI check green on the head
commit, SonarCloud included (`tools/orchestrator/wait_ci.sh <n> <head-sha7>`). If CI is red, don't review: tell the
implementor and stop. Don't run builds or tests yourself; CI did. One single agent does the whole review, once per
PR, whatever its size: no sub-agents, no `/simplify`, no `/code-review` (`CLAUDE.md` §3).

## 1. Scope and intent

- `gh pr view <n>` and `gh pr diff <n>`. Find the change (`openspec/changes/<change-id>/`) and tasks, or the backlog
  item, the PR claims. Read `openspec/project.md`, the change folder (proposal, tasks, deltas, `design.md` if any),
  the capability specs it touches, and the design sections and decisions they link, by section. Don't read archived
  specs unless the diff changes the design of their code.
- Write the intent in one paragraph: what the PR must achieve, task by task, and what it must not touch. If the PR
  doesn't match its tasks, that is the first finding.

## 2. Check, in this order

1. **Contract (C1–C13 in `openspec/project.md`, and `CLAUDE.md` §2).** Each one is a blocking defect:
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
3. **Proof.** Every task and every scenario of the change's deltas maps to a test or command that ran green in CI or in the PR's
   Verification section. Apply the test-behaviour rule: a test that would still pass if the function returned a
   wrong value proves nothing. For extraction changes, the dev delta is present and the hidden gate passed.
4. **Scope.** Code outside the batch's tasks, speculative options, and compatibility shims.
   **Spec deltas:** each delta requirement is 1–3 lines of SHALL (a scenario only where a test or invariant enforces
   it, `CLAUDE.md` §6), matches what the code does,
   and does not contradict `openspec/design/` or the contract (that would need the owner, `CLAUDE.md` §4). A PR that
   changes behaviour a requirement states, without a delta, is an Act-on item.
5. **Simplification** (this replaces `/simplify`). Read the diff once more for these; each is an Act-on item when it
   is clear and cheap to fix, else Consider:
   - **Reuse:** new code that duplicates an existing helper, normalizer or module (`grep` for it), or the same logic
     written twice in the diff (C8);
   - **Simpler:** wrappers or classes with one caller, needless indirection or configuration, unreachable branches,
     code that the standard library or an existing call already does;
   - **Efficiency:** repeated work in a loop (re-parsing, re-querying, re-compiling), N+1 queries, quadratic scans
     over inputs that can be large;
   - **Altitude:** logic in the wrong layer or module for its field type or stage (ENGINEERING structure rules).
6. **Decisions and tracker lines.** Choices the change didn't make are logged in the PR's tracker commit (entries
   under the implementor's ID range, in the change's `design.md` or `openspec/decisions/log.md`, listed in
   `## Decisions`). Anything that should have been escalated (`CLAUDE.md` §4) is a blocking finding. The tracker
   commit is part of the PR (`/implement-pr` §5): check that every task of the batch, and only those, is checked with
   this PR's number in `tasks.md`; that each follow-up is one factual line in `openspec/backlog.md` for work the PR
   really leaves; that each decision entry matches the code and uses an ID in the range; and, when the PR completes
   the change, that the deltas are applied to `openspec/specs/` exactly and the folder moved to
   `openspec/changes/archive/<date>-<change-id>/`. A wrong or missing tracker line is an Act-on item.
7. **SonarCloud and recurring findings.** Read the PR's gate (`tools/orchestrator/wait_ci.sh <n> <head-sha7>`
   prints it). A red gate is an Act-on item. Check the diff against `openspec/conventions/RECURRING.md` and ENGINEERING's
   "Patterns the analysers flag": a repeat of a listed mistake is an Act-on item.
8. **Frontend PRs.** The PR follows the `openspec/conventions/DESIGN.md` Patterns, uses no second way to do a listed job, and has
   no styling outside `frontend/src/app/theme.css`. A deviation is an Act-on item.

## 3. Judge

Before sorting, re-check each finding against the code. Drop false positives:
- pre-existing issues, and lines the PR didn't change;
- anything a linter, type checker, test or SonarCloud would catch;
- nits a senior engineer wouldn't raise, and intentional changes that follow from the task.

Act on only what you have verified is real and will be hit in practice.

Sort every finding into one bucket, with a one-line reason each:
- **Act on.** Correctness, security, contract or scope defects. These block the merge. If there are more than 5,
  you aren't filtering hard enough.
- **Consider.** Legitimate, but the cost of fixing now may not be worth it. A follow-up line in `openspec/backlog.md` is fine.
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
commit (`https://github.com/<owner>/<repo>/blob/<full-sha>/<path>#L<a>-L<b>`). The comment's first line is the `## Review` heading,
with nothing before it. In a herdr pane, send the verdict and the Act-on list to the implementor with
`herdr agent prompt <implementor> "…"`, then close your pane: `herdr pane close "$HERDR_PANE_ID"` (an idle reviewer
pane holds about 400 MB). As a subagent, return the verdict and the Act-on list as your result. There is no re-review (owner, 2026-10-13).

End the comment with one line naming the category of each Act-on item, for example
`Categories: path-traversal, sonar-gate`. The orchestrator tallies these lines to spot recurring mistakes.
