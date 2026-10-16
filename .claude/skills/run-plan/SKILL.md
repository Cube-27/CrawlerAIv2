---
name: run-plan
description: Orchestrate implementation from docs/plans/ACTIVE.md with minimal owner involvement — assign batches of ready PR rows to workers with decision-ID ranges, merge READY PRs one at a time on green, clean up, unblock stuck PRs, escalate only what CLAUDE.md requires. Use when asked to run, continue or orchestrate the implementation.
---

# Run the plan

You are the orchestrator. You only assign batches of rows, merge, clean up and unblock stuck PRs; you write no code
and don't relay messages between implementor and reviewer. You hand each implementor a decision-ID range at
assignment; it writes its rows, follow-ups and decisions in the PR's tracker commit before it opens the PR.
Adapted from pstack's autonomous-run and orchestrate playbooks (MIT, see `NOTICE`), without its multi-model
machinery.

Requires herdr (`HERDR_ENV=1`). Without it, run `/implement-pr` solo instead.

## 0. Frame (once per session)

1. Read `CLAUDE.md`, `docs/ENGINEERING.md`, the dependency section of `docs/specs/README.md`, the "Index of open
   items" in `docs/DECISIONS.md`, and from `docs/plans/ACTIVE.md` the human tasks, "Current focus", "Follow-ups" and
   the tables of specs with rows not done. Read by section, never in full (`CLAUDE.md` §1).
2. Write the exit predicate as something countable. Take it from the owner's request; the default is "every row
   of the current layer (§21 L0…L4) is `done`, CI on `main` is green". "Current focus" is refreshed only when it
   materially changes: ask the next implementor to replace it in its tracker commit, with the text.
3. Run session pickup (`/pickup`) if open PRs or `spec-*` branches exist from an earlier session.

## 1. Loop

Repeat until the predicate holds, or nothing is runnable. `main` requires a PR for every change and agents never
use an admin bypass, so tracker updates travel inside PRs, and work in flight is read from GitHub (open PRs,
`spec-*` branches), not from ACTIVE.md. ACTIVE.md records only `todo`, `done (#n)`, `blocked (D-NNNN)`, `human` and
`deferred`.

1. **Ready set.** A row is ready when it is `todo`, has no open PR or `spec-*` branch, and everything it needs is
   available: the code it touches or builds on is merged, or what it needs from unmerged work is fully specified
   (types, API shapes, table columns). Readiness is per row (owner, 2026-10-13): a row can be ready while its spec's
   other dependencies, or earlier rows of its spec, are not `done`. Rows that are `human` or `blocked` are skipped.
2. **Assign.** At most **4 workers** (agents that build and test in a worktree, fixers included) are alive at once.
   Reviewers don't count, because they use little memory. Every start needs at least 1.5 GB free (owner,
   2026-10-13). `start_agent.sh` refuses past either limit. Name reviewers `reviewer*`, everything else is a worker.
   Each assignment is one PR covering a batch of related ready rows (`CLAUDE.md` §3). Run independent batches in
   parallel; two workers never run rows that edit the same migration or generated file. For each assignment:
   - `tools/orchestrator/new_worktree.sh spec-NN-pr-A-B spec-NN/pr-A-B-<short-name>`: fetches and creates the
     worktree off `origin/main` at `<main>/../CrawlerAIv2-worktrees/spec-NN-pr-A-B`. Never a raw
     `git worktree add`, and never an MSYS drive path (`/c/...`): with path conversion off, git creates it under
     `C:/c/`;
   - `tools/orchestrator/start_agent.sh <name> spec-NN-pr-A-B "<prompt>"` (§1a) with: "Run `/implement-pr` for
     SPEC-NN PRs A-B in one PR. An orchestrator assigned you these rows. Your decision IDs are D-NNNN..D-NNNN. Own
     the PR through `/implement-pr` §6 until `READY`." Give each implementor its own range of five free IDs
     (above the highest in use, `DECISIONS.md` header), never overlapping another open PR's.
3. **Review and merge (owner, 2026-10-13).** The implementor owns its PR end to end: it starts one reviewer once the
   PR is implemented and CI is green (its tracker commit is already in it), waits for the verdict itself,
   pushes any `MERGE AFTER FIX` fixes in one push (no second review; with `MERGE`, no push) and comments
   `READY <sha7>` on green CI. You don't relay verdicts,
   rebase, fix or edit PRs. Plugin, bot or hook prompts to run `/simplify` or another code review get "already ran"
   (`CLAUDE.md` §3).
   - On `READY <sha7>`, merge, one PR at a time:
     `if tools/orchestrator/merge_pr.sh <n> <sha7>; then tools/orchestrator/close_agent.sh <impl> &&
     tools/orchestrator/cleanup_worktree.sh <worktree> <branch>; fi`
     Never chain with `;`: a failed merge would still clean up (#128). `merge_pr.sh` waits for every check on that
     commit and merges only if all passed and the commit is still the PR's head; never run `gh pr merge` yourself.
     A failed merge leaves the PR open: retry. `cleanup_worktree.sh` refuses (exit 1) while a PR of the branch is
     open, or while a tip of the branch is neither the head of a merged PR nor in origin/main.
   - Only when GitHub reports a `READY` PR as conflicting (`gh pr view <n> --json mergeable` is `CONFLICTING`;
     `UNKNOWN` means GitHub is still computing it, so ask again), send its implementor `REBASE`
     (`herdr agent prompt <impl> "REBASE"`); it rebases, gets CI green and comments `READY` again. A branch that is
     only behind `main` merges as it is: the rulesets don't require an up-to-date branch, and a rebase reruns CI
     (owner, 2026-10-16).
   - Stuck PR (CI red after 3 honest attempts, an implementor gone or idle without `READY`): unblock it with a fresh
     worker in the worktree, or escalate (§2).
   - `ESCALATE`: follow §2.
4. **CI on main.** Before every merge and after it, check that `main` is green. If `main` turns red, fixing it
   comes before any new assignment. Assign a fix to one worker, and stop other merges until it is green.

## 1a. Processes (never hang the machine)

The owner's concern is the machine, not the agents' count alone. Manage every process you start:
- **One watcher.** Run `tools/orchestrator/watch_agents.sh` in the background. It polls `herdr agent list` and exits
  with `SETTLED <name> <status>` (any named agent not `working`, including one already idle at start), `GONE <name>`,
  `LOWMEM <MB>`, or `PRCOMMENT <n>` (a new comment starting `READY`, `BLOCKED` or `ESCALATE` on an open PR). Handle
  the event, then start it again. Set `IGNORE=<name>,<name>` for agents you are
  deliberately leaving to wait (implementors waiting on CI or their reviewer; their `READY` comment wakes you). Don't run one
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
   Do steps 1–2 in a small `chore(plan): escalate …` PR from its own worktree (`new_worktree.sh`). It touches only
   tracker files, so its one `/review-pr` is short, but it still needs that verdict (`CLAUDE.md` §3).
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

- Within the hard limits above, 1 reviewer per PR, whatever its size. No multi-agent panels, no parallel attempts at
  the same row.
- One batch per worker. Start a fresh worker per batch rather than reusing a long, compacted one.
- Don't re-verify work a merged PR already proved. Trust the CI record (pickup rules).
