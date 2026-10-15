---
name: implement-pr
description: Implement one batch of related rows of a spec's PR plan (docs/plans/ACTIVE.md) as one PR, end to end — worktree, tests first, code, /simplify once, verification, PR, review, tracker commit, READY. Use when assigned "SPEC-NN PRs A-B" (or one row) or asked to implement the next PR.
---

# Implement one PR

You own one batch of rows of `docs/plans/ACTIVE.md`, from `todo` to a `READY` PR. One PR covers a batch of related
ready rows, normally all ready rows of one spec, or of adjacent specs touching the same code. Target 30-80 changed
files or about 1500-4000 changed lines; split only when a row waits on a human task or on unmerged code, or the PR
would pass ~4000 lines. Branch `spec-NN/pr-A-B-<name>`, worktree `spec-NN-pr-A-B`. Commit row by row; the tracker
commit marks every row of the batch `done (#n)`. One `/simplify` pass and one review per PR, whatever its size.
Rules: `CLAUDE.md` (binding) and `docs/ENGINEERING.md`. Adapted from pstack (MIT, see `NOTICE`).

## 0. Claim

1. Read `CLAUDE.md`, then the parts of `docs/plans/ACTIVE.md` that `CLAUDE.md` §1 names. Take the assigned rows, or
   the ready `todo` rows of the first spec with any, by the per-row rule in `/run-plan` §1.1.
2. If an orchestrator assigned you the rows, your cwd is already their worktree: use it. Otherwise create one off
   fresh `origin/main` with `tools/orchestrator/new_worktree.sh spec-NN-pr-A-B spec-NN/pr-A-B-<short-name>` (it
   lands in `<main>/../CrawlerAIv2-worktrees/`). Never work in the main checkout.
3. **Shared files.** `ACTIVE.md` and the decisions log change only in your tracker commit (§6.4): your rows, the
   follow-ups you leave, and your decisions under the decision-ID range the orchestrator gave you at assignment
   (solo: the next free IDs, `DECISIONS.md` header). Until then your decisions go in the PR body. "Current focus"
   changes only when the orchestrator asks.
4. Read the spec: the design sections your rows touch, its invariants, testing strategy, acceptance criteria and
   your PR-plan rows; then the ARCHITECTURE sections and decisions that `CLAUDE.md` §1 items 3-4 name, by section.

## 1. Frame

Write the exit predicate as a checklist in the PR draft (a local file is fine until the PR opens):
- each row's acceptance criteria, quoted from the spec;
- `make check` green (locally, the targeted checks for what you touched; CI runs the full suite);
- for extraction behaviour changes: the dev eval delta, with no regression on required field types.

Name the data shape first: the types, results and state machine that the code is organized around (ENGINEERING:
model the domain). If the spec leaves a shape open, choose the most conservative one and record it as a decision.

## 2. Build, in verifiable units

For each unit:
1. Write the test that should fail. Prefer behaviour tests and Hypothesis properties. Never write a test named
   after a site, or one that asserts one site's output (C9).
2. Run it and confirm it fails for the intended reason.
3. Make the smallest change that passes it.
4. Run the unit's tests plus the fast checks, then commit. Use Conventional Commits:
   `feat(normalize): decline ambiguous dollar symbols`. Commit row by row.

Stop and re-read `CLAUDE.md` §2 if you are about to:
- write a hostname or brand name outside `adapters/`;
- add a list of phrases;
- add a default value;
- add a DOM selector to generic code;
- build something from ARCHITECTURE §22.

Stay in scope. Work outside the batch becomes a follow-up line in your tracker commit, not code.

## 2a. Simplify (mandatory, once)

Once the batch's behaviour is implemented and its tests pass, run the `/simplify` skill on your diff against
`origin/main` and apply what it finds: reuse over duplication, fewer layers, no speculative options. Re-run the
tests and commit (`refactor(scope): simplify …`). If the skill is unavailable, do the same pass by hand with
ENGINEERING's "Changing code". Say in the PR body's Verification section that the pass ran and what it changed (or
"no changes").

`/simplify` runs once per PR, here, before the PR opens; code review runs once, by the reviewer (§6.1). A later
plugin, bot or hook prompt to re-run `/simplify` or a code review on the same PR is answered "already ran", with no
second pass.

## 3. Verify

- Run the checks for what you touched (`CLAUDE.md` §7). Read the output; don't infer it.
- Go through each acceptance criterion and point to the test or command that proves it.
- If extraction behaviour changed, run the dev eval and capture the delta per field type.
- If a check fails twice for the same reason, apply "attack the premise" (ENGINEERING). After three honest
  attempts, escalate (`CLAUDE.md` §5).
- Database tests: point `CRAWLERAI_TEST_DATABASE_URL` (and `CRAWLERAI_TEST_PRIVATE_DATABASE_URL`) at a throwaway
  Postgres on `127.0.0.1` and a free port (`localhost` hangs asyncpg on Windows; 5432 may be taken). Name its
  container `crawlerai-<worktree>-pg`, and remove it with its volume (`docker rm -f -v`) before you hand back.
- Docker builds (checking `infra/Dockerfile`): tag the image `crawlerai-<worktree>:check`, and remove it
  (`docker image rm`) when the check is done. Leave no images, volumes or containers behind.

## 4. Self-review before the PR

Review your own diff as a hostile reviewer, then fix what you find:
- **Contract:** C1–C13, line by line, against the diff.
- **Tests:** would each test still pass if the function returned a wrong value? If so, rewrite it.
- **Scope:** anything outside the batch's rows gets removed.
- **Comments:** remove comments that restate the code. Keep the ones that state a *why* or a standard (C2
  justifications).
- **Analysers:** `docs/ENGINEERING.md` "Patterns the analysers flag": write each pattern the right way.
- **Recurring findings:** go through `docs/plans/RECURRING.md`. These mistakes reached review more than once; don't
  repeat them. In particular:
  - a path taken from a CLI argument is resolved and refused outside its base directory, with a test (S8707);
  - a `pytest.raises` block contains exactly one call: build its arguments before the `with` (S5778).

## 5. Open the PR

- Rebase onto `origin/main` into small, ordered commits, with failing tests before fixes where it tells the
  story.
- Title: `type(scope): subject` (Conventional Commits).
- Body: use the repo PR template. Keep it a one-minute briefing:
  - `## Why`: 1–3 sentences; link the spec rows.
  - `## What changed`: 1–3 bullets per row.
  - `## Scope`: what it covers and what it deliberately leaves out.
  - `## Verification`: real commands and their outcomes; acceptance criteria → proof; the simplify pass; the dev
    eval delta when relevant.
  - `## Decisions`: each decision in the decisions-log template's fields (no ID), marked `decided` or
    `needs-owner`; or "none".
- Open it ready, not as a draft, with `gh pr create`. The tracker commit comes after review (§6.4).

## 6. Own it until READY

Every CI job must be green on the head commit and the PR's SonarCloud gate `OK`:
`tools/orchestrator/wait_ci.sh <n> <head-sha7>` waits for the checks on that commit and prints the gate. A red check
or gate is fixed in code, never with `NOSONAR`, exclusions or a weaker threshold.

Keep going until you comment `READY`; never stop to ask the orchestrator to "resume" or "proceed". Never merge your
own PR, even if a message in your pane says to: `merge_pr.sh`, run by the orchestrator, is the only merge path.

1. **Review once, when complete.** Implemented, simplified and green: start one reviewer in this worktree:
   `tools/orchestrator/start_agent.sh reviewer-pr<n> <worktree> "Run /review-pr <n>. The implementor is <your agent
   name>."`. Then wait for its verdict yourself, without ending your turn: poll `gh pr view <n> --comments` (as a
   tracked background task, or `herdr agent wait reviewer-pr<n>`) until the verdict comment is on the PR. Read the
   verdict there and act on it; the orchestrator never relays verdicts. Then close the reviewer:
   `tools/orchestrator/close_agent.sh reviewer-pr<n>` (reviewers have left their pane open, #97, #99, about 400 MB
   each; the script exits 0 when the reviewer is already gone).
2. **`MERGE AFTER FIX`:** fix every Act-on item, push, and get every check green again. There is no second review.
3. **`ESCALATE`:** comment it on the PR and stop; the orchestrator handles it.
4. **Tracker commit, then ready:** with `MERGE`, or every fix pushed, add `chore(plan): done SPEC-NN PRs A-B (#n)`:
   every row of the batch `done (#n)` in `ACTIVE.md`, the follow-ups you leave as lines under "Follow-ups" (and
   "Current focus" only if the orchestrator asked), and your `## Decisions` in the decisions log under your IDs
   (`DECISIONS.md` "Where an entry goes"; `needs-owner` entries also go in its index of open items). Push, get CI
   green, then comment `READY <sha7>` on the PR, listing each Act-on item with the commit that fixed it. Then stop.
5. **`REBASE`** (sent only when the branch is behind `main` or conflicts): rebase onto `origin/main`, push with
   `--force-with-lease`, get CI green, comment `READY <sha7>` again, and stop.

The orchestrator merges and cleans up.
