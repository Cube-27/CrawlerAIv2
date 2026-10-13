---
name: implement-pr
description: Implement exactly one row of a spec's PR plan (docs/plans/ACTIVE.md) end to end — branch, tests first, code, verification, PR, tracker update. Use when assigned "SPEC-NN PR M" or asked to implement the next PR.
---

# Implement one PR

You own one row of `docs/plans/ACTIVE.md`, from `todo` to an open, verified PR. Rules: `CLAUDE.md` (binding) and
`docs/ENGINEERING.md`. Adapted from pstack (MIT, see `NOTICE`).

## 0. Claim

1. Read `CLAUDE.md`, then `docs/plans/ACTIVE.md`. Pick the assigned row, or the first `todo` row whose spec
   dependencies (`docs/specs/README.md`) and earlier rows in the same spec are `done`.
2. If an orchestrator assigned you the row, your cwd is already the row's worktree: use it. Otherwise, create a
   worktree off fresh `origin/main` at `<main>/../CrawlerAIv2-worktrees/spec-NN-pr-M`, on branch
   `spec-NN/pr-M-<short-name>`. `<main>` is the main checkout (the first entry of `git worktree list`), so the
   worktree sits beside the repo, never inside it. Never work in the main checkout. In Git Bash, give git
   Windows-style paths (`C:/Projects/...`); `/c/...` is mangled to `C:/c/...`.
3. **Shared files have one writer.** If an orchestrator assigned you the row, don't edit `ACTIVE.md` or
   `DECISIONS.md`. Your decisions go in the PR body, and the orchestrator records them. Working solo, you update
   both files yourself in your PR.
4. Read the spec: the design sections your row touches, its invariants, its testing strategy, its acceptance
   criteria, and your row of the PR plan. Read the ARCHITECTURE sections it cites, and the `DECISIONS.md` entries
   for that spec.

## 1. Frame

Write the exit predicate as a checklist in the PR draft (a local file is fine until the PR opens):
- the acceptance criteria this row must meet, quoted from the spec;
- `make check` green (once SPEC-00 PR 9 exists; before then, the checks that exist);
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
   `feat(normalize): decline ambiguous dollar symbols`.

Stop and re-read `CLAUDE.md` §2 if you are about to:
- write a hostname or brand name outside `adapters/`;
- add a list of phrases;
- add a default value;
- add a DOM selector to generic code;
- build something from ARCHITECTURE §22.

Stay in scope. Work outside the row becomes a note in ACTIVE.md, not code.

## 3. Verify

- Run the full local checks. Read the output; don't infer it.
- Go through each acceptance criterion and point to the test or command that proves it.
- If extraction behaviour changed, run the dev eval and capture the delta per field type.
- If a check fails twice for the same reason, apply "attack the premise" (ENGINEERING). After three honest
  attempts, escalate (`CLAUDE.md` §5).
- Database tests: point `CRAWLERAI_TEST_DATABASE_URL` (and `CRAWLERAI_TEST_PRIVATE_DATABASE_URL`) at a throwaway
  Postgres on `127.0.0.1` and a free port (`localhost` hangs asyncpg on Windows; 5432 may be taken). Name its
  container `crawlerai-<worktree>-pg`, and remove it before you hand back.

## 4. Self-review before the PR

Review your own diff as a hostile reviewer, then fix what you find:
- **Contract:** C1–C13, line by line, against the diff.
- **Tests:** would each test still pass if the function returned a wrong value? If so, rewrite it.
- **Scope:** anything not in the row's scope gets removed.
- **Simplicity:** wrappers with one caller, unused options, speculative guards. Remove them.
- **Comments:** remove comments that restate the code. Keep the ones that state a *why* or a standard (C2
  justifications).
- **Recurring findings:** go through `docs/plans/RECURRING.md`. These mistakes reached review more than once; don't
  repeat them. In particular:
  - a path taken from a CLI argument is resolved and refused outside its base directory, with a test (S8707);
  - a `pytest.raises` block contains exactly one call: build its arguments before the `with` (S5778).

## 5. Open the PR

- Rebase onto `origin/main` into small, ordered commits, with failing tests before fixes where it tells the
  story.
- Title: `type(scope): subject` (Conventional Commits).
- Body: use the repo PR template. Keep it a one-minute briefing:
  - `## Why`: 1–3 sentences; link the spec row.
  - `## What changed`: 1–3 bullets.
  - `## Scope`: what it covers and what it deliberately leaves out.
  - `## Verification`: real commands and their outcomes; acceptance criteria → proof; the dev eval delta when
    relevant.
  - `## Decisions`: each decision in the DECISIONS.md template's fields (no ID), marked `decided` or
    `needs-owner`; or "none".
- Open it ready, not as a draft, with `gh pr create`. Working solo, also set the row to `done (#n)` and add your
  decisions to DECISIONS.md in a last commit on this PR, before it merges.

## 6. Hand back

Before reporting, the PR must be rebased on current `origin/main`, every CI job green on its head commit, and the
PR's SonarCloud gate `OK`: `tools/orchestrator/wait_ci.sh <n> <head-sha7>` waits for the checks on that commit and
prints the gate.
A red gate is fixed in code, never with `NOSONAR`, exclusions or a weaker threshold.

Report:
- the PR URL;
- the exit predicate and its state;
- decisions logged;
- anything left for a follow-up row.

Don't merge your own PR. The orchestrator (`/run-plan`) or a reviewer merges it after review and green CI. If you
were asked to merge, use `/review-pr` first.
