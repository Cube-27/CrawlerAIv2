---
name: run-plan
description: Orchestrate implementation from docs/plans/ACTIVE.md with minimal owner involvement — assign ready PR rows to workers, review, merge on green, keep the tracker and decisions log current, escalate only what CLAUDE.md requires. Use when asked to run, continue or orchestrate the implementation.
---

# Run the plan

You are the orchestrator. You don't write feature code. You assign rows, review, merge, and keep `ACTIVE.md` and
`DECISIONS.md` true. **You are the only writer of those two files.** Adapted from pstack's autonomous-run and
orchestrate playbooks (MIT, see `NOTICE`), without its multi-model machinery.

## 0. Frame (once per session)

1. Read `CLAUDE.md`, `docs/ENGINEERING.md`, `docs/plans/ACTIVE.md`, `docs/specs/README.md` (dependencies), and
   the open items in `docs/DECISIONS.md`.
2. Write the exit predicate as something countable. Take it from the owner's request; the default is "every row
   of the current layer (§21 L0…L4) is `done`, CI on `main` is green". Write it under "Current focus" in
   ACTIVE.md.
3. Run session pickup (`/pickup`) if ACTIVE.md shows rows `in-progress` or `review` from an earlier session.

## 1. Loop

Repeat until the predicate holds, or nothing is runnable:

1. **Ready set.** A row is ready when it is `todo`, its spec's dependencies are `done`, and the earlier rows in its
   spec are `done` (unless the spec says the rows are independent). Rows that are `human` or `blocked` are skipped.
2. **Assign.** Keep at most **2 workers in flight** (cost cap; the owner may raise it). Two workers never run rows
   of the same spec, or rows that touch the same files or migrations. For each assignment:
   - mark the row `in-progress` with the branch name, then commit and push that change to `main`
     (`chore(plan): start SPEC-NN PR M`);
   - start the worker (a herdr pane or a subagent) with: "Run `/implement-pr` for SPEC-NN PR M. An orchestrator
     assigned you this row. Report the PR URL when done."
3. **On a worker report.** Run `/review-pr <n>` in a fresh reviewer agent, never the worker itself.
   - `FIX`: send the Act-on list back to the same worker. After 3 FIX rounds on one PR, escalate.
   - `MERGE`: wait for green CI, then `gh pr merge <n> --squash --delete-branch`. Remove the worktree. Set the row
     to `done (#n)`. Copy the PR's `## Decisions` into DECISIONS.md with the next IDs (`decided` →
     `decided`; `needs-owner` → the index). Commit both files to `main`: `chore(plan): done SPEC-NN PR M`.
   - `ESCALATE`: follow §2.
4. **CI on main.** Before every merge and after it, check that `main` is green. If `main` turns red, fixing it
   comes before any new assignment. Assign a fix row to one worker, and stop other merges until it is green.
5. **Checkpoint.** After each merge, update "Current focus" in ACTIVE.md: next, in progress, blocked.

## 2. Escalation (the only times the owner is involved)

Escalate for the `CLAUDE.md` §4 list, or a dead end after 3 attempts:
1. Add a `needs-owner` entry to DECISIONS.md with the question, options, recommendation, and what is blocked.
2. Mark the affected rows `blocked (D-NNNN)`.
3. Notify the owner once, briefly (herdr notification, or the session's final message).
4. **Keep going** with other ready rows. Never wait idle on the owner while ready work exists.

The rule from ENGINEERING ("never block on the human") applies to reversible work. These are never done without
the owner:
- changing ARCHITECTURE.md or OPEN_QUESTIONS.md;
- admitting a §22 candidate;
- touching eval access or secrets;
- force-pushing or rewriting `main`;
- deleting data.

## 3. Stop

Stop when:
- the predicate holds;
- or every remaining row is `human` or `blocked`, which you report as such.

A plateau is not a stop; a red `main` is not a stop. Never weaken a check, skip a hook, or mark a row `done` without
a merged PR to reach the predicate.

**Final report** (short):
- the predicate and its state;
- rows merged this session, with PR numbers;
- rows blocked and why (D-IDs);
- human tasks now due (H-numbers in ACTIVE.md);
- the next ready rows.

## Cost discipline

- Default 2 workers and 1 reviewer per PR. No multi-agent panels, no parallel attempts at the same row.
- Workers get one row each. Start a fresh worker per row rather than reusing a long, compacted one.
- Don't re-verify work a merged PR already proved. Trust the CI record (pickup rules).
