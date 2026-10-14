---
name: run-plan
description: Orchestrate implementation from docs/plans/ACTIVE.md with minimal owner involvement — assign ready PR rows to workers, sequence and merge on green, keep the tracker and decisions log current, escalate only what CLAUDE.md requires. Use when asked to run, continue or orchestrate the implementation.
---

# Run the plan

You are the orchestrator. You don't write feature code. You assign rows, sequence merges, merge, and keep `ACTIVE.md` and
`DECISIONS.md` true. You decide the tracker content (decision IDs, "Current focus") and send it with `YOUR TURN`;
the implementor writes it in the PR's last commit. Adapted from pstack's autonomous-run and
orchestrate playbooks (MIT, see `NOTICE`), without its multi-model machinery.

## 0. Frame (once per session)

1. Read `CLAUDE.md`, `docs/ENGINEERING.md`, `docs/plans/ACTIVE.md`, `docs/specs/README.md` (dependencies), and
   the open items in `docs/DECISIONS.md`.
2. Write the exit predicate as something countable. Take it from the owner's request; the default is "every row
   of the current layer (§21 L0…L4) is `done`, CI on `main` is green". Write it under "Current focus" in
   ACTIVE.md.
3. Run session pickup (`/pickup`) if open PRs or `spec-*` branches exist from an earlier session.

## 1. Loop

Repeat until the predicate holds, or nothing is runnable:

`main` requires a PR for every change, and agents never use an admin bypass. So tracker updates travel inside
PRs, and work in flight is read from GitHub, not from ACTIVE.md: open PRs and `spec-*` branches. ACTIVE.md
records only `todo`, `done (#n)`, `blocked (D-NNNN)`, `human` and `deferred`.

1. **Ready set.** A row is ready when it is `todo`, has no open PR or `spec-*` branch, and everything it needs is
   available: the code it touches or builds on is merged, or what it needs from unmerged work is fully specified
   (types, API shapes, table columns). Readiness is per row (owner, 2026-10-13): a row can be ready while its spec's
   other dependencies, or earlier rows of its spec, are not `done`. Rows that are `human` or `blocked` are skipped.
2. **Assign.** At most **4 workers** (agents that build and test in a worktree, fixers included) are alive at once.
   Reviewers don't count, because they use little memory. Every start needs at least 1.5 GB free (owner,
   2026-10-13). `start_agent.sh` refuses past either limit. Name reviewers `reviewer*` and everything else as a
   worker. Within the limit, run ready rows that can proceed
   independently in parallel. Two workers never run rows that edit the same migration. For each assignment:
   - create the worktree off fresh `origin/main` at `<main>/../CrawlerAIv2-worktrees/spec-NN-pr-M`, on branch
     `spec-NN/pr-M-<short-name>`, and start the worker with `tools/orchestrator/start_agent.sh <name> <worktree>
     "<prompt>"` (§1a). Give it: "Run `/implement-pr` for SPEC-NN PR M. An orchestrator assigned you this row.
     Own the PR through `/implement-pr` §6 until it merges."
3. **Review and merge (owner, 2026-10-13).** The implementor owns its PR (`/implement-pr` §6). It starts one
   reviewer in its worktree once the PR is implemented, simplified and green. The review happens once. Its verdict is
   `MERGE` or `MERGE AFTER FIX`. With the second, the implementor fixes the listed items and gets CI green; there is
   no second review. Then it comments `READY <sha7>`. You don't rebase, fix or edit PRs yourself.
   - If CI stays red after 3 honest attempts, escalate.
   - To merge, pick the next `READY` PR and send its implementor `YOUR TURN` with the next free decision IDs and the new "Current focus" text. The
     implementor rebases, adds the tracker commit (row `done (#n)`, `## Decisions` copied to DECISIONS.md, with
     `needs-owner` entries also listed in the index) and comments `READY` again.

     Then merge, close the PR's herdr panes and clean up, gated on the merge, never chained with `;`:
     `if tools/orchestrator/merge_pr.sh <n> <sha7>; then <close panes>; tools/orchestrator/cleanup_worktree.sh
     <worktree> <branch>; fi`. `merge_pr.sh` waits for every check on that commit and merges only if all passed and
     the commit is still the PR's head; never run `gh pr merge` yourself. A failed merge (CI, a transient GitHub
     error) leaves the PR open: retry the merge.
     `cleanup_worktree.sh` refuses (exit 1) unless the branch's PR is merged, or the branch has no PR and is merged
     into origin/main.
   - **Merge strictly one at a time.** Send `YOUR TURN` to one implementor only, after the previous merge. IDs never
     clash, and every merge is tested against the real `main`.
   - `ESCALATE`: follow §2.
4. **CI on main.** Before every merge and after it, check that `main` is green. If `main` turns red, fixing it
   comes before any new assignment. Assign a fix row to one worker, and stop other merges until it is green.
5. **Checkpoint.** Send the new "Current focus" text (next, blocked) with `YOUR TURN`; the implementor writes it in the tracker commit.

## 1a. Processes (never hang the machine)

The owner's concern is the machine, not the agents' count alone. Manage every process you start:
- **One watcher.** Run `tools/orchestrator/watch_agents.sh` in the background. It polls `herdr agent list` and exits
  with `SETTLED <name> <status>` (any named agent not `working`, including one already idle at start), `GONE <name>`,
  `LOWMEM <MB>`, or `PRCOMMENT <n>` (a new comment starting `READY`, `BLOCKED` or `ESCALATE` on an open PR). Handle
  the event, then start it again. Set `IGNORE=<name>,<name>` for agents you are
  deliberately leaving to wait (implementors waiting on CI or for `YOUR TURN`; their PR comment wakes you). Don't run one
  `herdr agent wait` per agent. If the watcher is killed, start it again; a killed watcher means finished agents go
  unnoticed.
  Start it only as a tracked background task (the Bash tool's `run_in_background`), never with `&`: a detached
  watcher can't notify you. It is single-instance and exits 2 while another watcher holds its pidfile
  (`ERROR another watcher is running (pid N, windows pid W)`). On exit 2: if you have a tracked watcher task
  running, keep it and don't start another. Otherwise the holder is a stray: stop it (`kill N`, or
  `taskkill -PID W -F` if `kill` fails), then start the watcher again as a tracked task.
- **Memory admission.** `start_agent.sh` refuses to start an agent below 1.5 GB free. On `LOWMEM`, close idle
  panes, and remove leftover `crawlerai-*` containers, before anything else. Never touch containers or processes of
  other projects.
- **Close what's done.** Close an implementor's and its reviewer's panes once the PR merges (§1.3 cleanup).
  Remove the worktree's containers on merge (`cleanup_worktree.sh`).
- **Start agents only through `start_agent.sh`.** It builds the cwd and checks it. A wrong cwd leaves the agent
  stuck at a trust prompt.

## 2. Escalation (the only times the owner is involved)

Escalate for the `CLAUDE.md` §4 list, or a dead end after 3 attempts:
1. Add a `needs-owner` entry to DECISIONS.md with the question, options, recommendation, and what is blocked.
2. Mark the affected rows `blocked (D-NNNN)`.
   Do steps 1–2 in a small `chore(plan): escalate …` PR from its own worktree, and merge it once CI is green. It
   touches only the two tracker files, so `/review-pr` is not needed.
3. Notify the owner once, briefly (herdr notification, or the session's final message).
4. **Keep going** with other ready rows. Never wait idle on the owner while ready work exists.

The rule from ENGINEERING ("never block on the human") applies to reversible work. These are never done without
the owner:
- changing ARCHITECTURE.md or OPEN_QUESTIONS.md;
- admitting a §22 candidate;
- touching eval access or secrets;
- force-pushing or rewriting `main`, or using an admin bypass of the branch rules;
- deleting data.

## 2a. Self-improvement

Agents should not make the same mistake twice:
- After each review, read its `Categories:` line and the PR's SonarCloud findings. When a category or rule shows up
  a second time, add it to `docs/plans/RECURRING.md`, and in the same change:
  - prefer a **check**: a lint rule, a `tools/` scan or a CI step, so the mistake can't merge again;
  - where no check can catch it, add a **skill rule** to `/implement-pr` or `/review-pr`, and make the rule name the
    finding.
- Your own slips count too. Fix the procedure or a `tools/orchestrator/` script, not just the instance.
- These changes go through a normal PR with a fresh reviewer. Do them as soon as a slot frees up, ahead of new
  rows. They pay back on every later row.

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

- Within the hard limits above, 1 reviewer per PR. No multi-agent panels, no parallel attempts at the same row.
- Workers get one row each. Start a fresh worker per row rather than reusing a long, compacted one.
- Don't re-verify work a merged PR already proved. Trust the CI record (pickup rules).
