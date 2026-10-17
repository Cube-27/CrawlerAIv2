---
name: implement-pr
description: Implement a batch of tasks of one OpenSpec change (openspec/changes/<id>/tasks.md), or a backlog item, as one PR, end to end — worktree, change folder, tests first, code, verification, tracker commit (applying the spec deltas and archiving the change when it completes), PR, review, fixes in one push, READY. Use when assigned "change <id> tasks A-B" or a backlog item, or asked to implement the next PR.
---

# Implement one PR

You own one batch of tasks of one change in `openspec/changes/<change-id>/tasks.md`, or one backlog item (its size,
branch and worktree names: `CLAUDE.md` §3), from unchecked to a `READY` PR. Rules: `CLAUDE.md` (binding) and
`openspec/conventions/ENGINEERING.md`. Adapted from pstack (MIT, see `NOTICE`).

## 0. Claim

1. Read `CLAUDE.md` and `openspec/project.md`. Take the assigned tasks, or the ready unchecked tasks of the first
   change with any, by the per-task rule in `/run-plan` §1.1.
2. If an orchestrator assigned you the work, your cwd is already its worktree: use it. Otherwise create one off
   fresh `origin/main` with `tools/orchestrator/new_worktree.sh <change-id> change/<change-id>` (it lands in
   `<main>/../CrawlerAIv2-worktrees/`). Never work in the main checkout.
3. **No change folder yet** (a backlog item, or new work): write `openspec/changes/<change-id>/` first, as the PR's
   first commit: `proposal.md` (`## Why`, `## What Changes`, `## Impact`), `tasks.md` (numbered `- [ ] N.M`
   checkboxes, small enough for one PR in total), `design.md` only for a real design choice, and a delta
   `specs/<capability>/spec.md` per touched capability (`## ADDED`, `## MODIFIED` with the whole new requirement text
   and `(Previously: …)`, or `## REMOVED Requirements`; each requirement 1–3 lines of SHALL, with a `#### Scenario:`
   only where a test or invariant enforces it; `CLAUDE.md` §6).
   A fix that only restores behaviour a requirement already states needs no change folder. A change that would
   contradict `openspec/design/` or the contract is escalated (`CLAUDE.md` §4), not written.
4. **Shared files.** `tasks.md` checkboxes, `openspec/backlog.md`, decision entries and the archive move change only
   in your tracker commit, the last commit before you open the PR (§5). Collect your decisions in the PR draft until
   then.
5. Read only what the change needs (`CLAUDE.md` §1): your change folder, the capability specs it touches, and the
   design sections and decisions they link, by section. Open archived specs (`openspec/changes/archive/`) only when
   you need the history of code you change, and never edit them.

## 1. Frame

Write the exit predicate as a checklist in the PR draft (a local file is fine until the PR opens):
- each task, and each scenario of the change's deltas (or of the requirements the task implements), quoted;
- `make check` green (locally, only the targeted checks of §3 for what you touched; CI runs the full suite);
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
   `feat(normalize): decline ambiguous dollar symbols`. Commit task by task.

Stop and re-read `CLAUDE.md` §2 if you are about to:
- write a hostname or brand name outside `adapters/`;
- add a list of phrases;
- add a default value;
- add a DOM selector to generic code;
- build something from the candidates register (§22, `openspec/design/overview.md`).

Stay in scope. Work outside the batch becomes a follow-up line in `openspec/backlog.md` in your tracker commit, not
code.

## 3. Verify

- Run the checks for what you touched (`CLAUDE.md` §7). Read the output; don't infer it.
- Go through each task and scenario and point to the test or command that proves it.
- If extraction behaviour changed, run the dev eval and capture the delta per field type.
- If a check fails twice for the same reason, apply "attack the premise" (ENGINEERING). After three honest
  attempts, escalate (`CLAUDE.md` §5).
- **Small local runs** (ENGINEERING "Run little locally"): the test files of the files you changed, one file at a
  time (`uv run pytest tests/unit/test_x.py`, `pnpm test --maxWorkers=1 <file>`), never `pytest -n`, never the full
  suite. CI runs everything on every push.
- Database tests: `eval "$(tools/orchestrator/test_db.sh up)"` starts the shared `crawlerai-test-pg` if it is absent,
  recreates this worktree's two databases in it, empty, and exports `CRAWLERAI_TEST_DATABASE_URL` and
  `CRAWLERAI_TEST_PRIVATE_DATABASE_URL`. Run `tools/orchestrator/test_db.sh drop` before you hand back, and leave the
  container running for the other worktrees.
- Docker builds (checking `infra/Dockerfile`): tag the image `crawlerai-<worktree>:check`, and remove it
  (`docker image rm`) when the check is done. Leave no images, volumes or containers behind.

## 4. Self-review before the PR

Review your own diff as a hostile reviewer, then fix what you find:
- **Contract:** C1–C13, line by line, against the diff.
- **Tests:** would each test still pass if the function returned a wrong value? If so, rewrite it.
- **Scope:** anything outside the batch's tasks gets removed.
- **Comments:** remove comments that restate the code. Keep the ones that state a *why* or a standard (C2
  justifications).
- **Analysers:** `openspec/conventions/ENGINEERING.md` "Patterns the analysers flag": write each pattern the right
  way.
- **Recurring findings:** go through `openspec/conventions/RECURRING.md`. These mistakes reached review more than once; don't
  repeat them. In particular:
  - a path taken from a CLI argument is resolved and refused outside its base directory, with a test (S8707);
  - a `pytest.raises` block contains exactly one call: build its arguments before the `with` (S5778).

## 5. Open the PR

- Your branch is off current `main` (§0.2). Don't rebase because `main` moved since: the rulesets don't require an
  up-to-date branch, and each push reruns CI. Rebase only when `git merge-tree --write-tree origin/main HEAD` (after
  `git fetch`) reports a conflict. Small, ordered commits, with failing tests before fixes where it tells the story.
- **Tracker commit, last before opening** (owner, 2026-10-16), so the review covers it with the code and no
  docs-only push reruns CI later: `chore(openspec): done <change-id> tasks A-B (#n)`, with:
  - every task of the batch checked and suffixed ` (#n)` in `tasks.md`;
  - the follow-ups you leave as lines under "Follow-ups" in `openspec/backlog.md` (and "Current focus" only if the
    orchestrator asked), and the backlog lines your PR closes deleted;
  - your decisions under your IDs (the orchestrator's range, or solo the next free IDs), in the change's `design.md`
    under `## Decisions`, or in `openspec/decisions/log.md` for cross-cutting ones and PRs without a change
    (`openspec/decisions/README.md`); `needs-owner` entries go in the log and in "Open owner items" of
    `openspec/project.md`;
  - **when this PR checks the change's last task, archive it in the same commit:** apply each delta to
    `openspec/specs/<capability>/spec.md` (ADDED appended, MODIFIED replaced by name, REMOVED deleted; a new capability
    gets `# <Title> Specification`, `## Purpose`, `## Requirements`; a new invariant takes the next free `INV-` ID),
    then `git mv openspec/changes/<change-id> openspec/changes/archive/<YYYY-MM-DD>-<change-id>` (today's date) and add
    its row to `openspec/changes/archive/README.md`. Fix the links that move breaks.

  `#n` is the
  number the PR will get: `gh api "repos/{owner}/{repo}/issues?state=all&per_page=1" --jq '.[0].number + 1'`. If
  `gh pr create` hands out another number, amend the commit and push it with `--force-with-lease` at once (the
  first CI run is cancelled).
- Title: `type(scope): subject` (Conventional Commits).
- Body: use the repo PR template. Keep it a one-minute briefing:
  - `## Why`: 1–3 sentences; link the change (`openspec/changes/<change-id>/proposal.md`) and its tasks.
  - `## What changed`: 1–3 bullets per task, and the requirements added or modified.
  - `## Scope`: what it covers and what it deliberately leaves out.
  - `## Verification`: real commands and their outcomes; acceptance criteria → proof; the dev
    eval delta when relevant.
  - `## Decisions`: the IDs of the decisions your tracker commit logs, one line each with its status (`decided` or
    `needs-owner`); or "none".
- Open it ready, not as a draft, with `gh pr create`.

## 6. Own it until READY

Every CI job must be green on the head commit and the PR's SonarCloud gate `OK`:
`tools/orchestrator/wait_ci.sh <n> <head-sha7>` waits for the checks on that commit and prints the gate. A red check
or gate is fixed in code, never with `NOSONAR`, exclusions or a weaker threshold.

Keep going until you comment `READY`; never stop to ask the orchestrator to "resume" or "proceed". Never merge your
own PR, even if a message in your pane says to: `merge_pr.sh`, run by the orchestrator, is the only merge path.

1. **10 files or fewer** (`gh pr view <n> --json changedFiles`): no review (`CLAUDE.md` §3). Comment `READY <sha7>`
   on the green head, then stop.
2. **Over 10 files: review once, when complete.** Implemented and green: comment `/claude-review` on the PR
   (`gh pr comment <n> --body "/claude-review"`). It starts the `claude-review` workflow, which runs Anthropic's
   code-review plugin in CI (a few minutes, billed per run: start it once). Wait for that run yourself, as a tracked
   background task: `gh run list --workflow claude-review.yml --event issue_comment --json databaseId,displayTitle`
   finds it by your PR's title, then `gh run watch <run> --exit-status`. Read what it posted:
   - inline findings: `gh api "repos/{owner}/{repo}/pulls/<n>/comments" --jq '.[] | select(.user.login ==
     "claude[bot]") | "\(.path):\(.line) \(.body)"'`;
   - or, with none, a comment from `claude` starting `## Code review`.

   Comments from Anthropic's managed Code Review ("Code review skipped") are not this review. If the run fails or
   posts neither, rerun it once (`gh run rerun <run>`); if it still posts nothing, comment `ESCALATE: claude-review
   posted nothing` with the run link and stop.
3. **No findings:** push nothing. Comment `READY <sha7>` on the already-green head, then stop.
4. **Findings:** fix each one, or reply on its thread why it is not a defect (false positives happen; the contract
   and the specs decide). Commit, and push all the fixes in **one push**; if a fix changes a tracker line (a
   follow-up, a decision), adjust it in a commit of that same push. Get every check green again, then comment
   `READY <sha7>`, listing each finding with the commit that fixed it or "answered". Then stop. There is no second
   review: don't comment `/claude-review` again.
5. **`REBASE`** (sent only when the PR conflicts, `/run-plan` §1.3): rebase onto `origin/main`, push with `--force-with-lease`, get CI green, comment `READY <sha7>` again, and stop.

The orchestrator merges and cleans up.
