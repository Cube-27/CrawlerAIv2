---
name: pickup
description: Resume implementation work left by an earlier session or agent, or pause cleanly so another can resume. Use at the start of a session when ACTIVE.md shows rows in-progress or review, when taking over a branch, or when asked to pause or hand off.
---

# Pick up or pause

Adapted from pstack's session-pickup and pause-safely playbooks (MIT, see `NOTICE`).

## Pick up

**The trail is authoritative. Read it; don't redo it.**

1. **Locate the trail.**
   - `docs/plans/ACTIVE.md`: rows `in-progress` or `review`, with their branch names.
   - `git worktree list`, `git log origin/main..<branch>`, `gh pr list --state open`.
   - A resume note at `.worktrees/<name>/RESUME.md`, if the earlier agent paused.
2. **Rebuild the state** for each in-flight row:
   - what is committed on the branch;
   - whether a PR is open and what CI says;
   - what review verdicts exist.
3. **Diff done against pending.** Name the resume point for each row:

   | Situation | Action |
   |---|---|
   | Open PR, CI green, no review | `/review-pr` |
   | Open PR with a `FIX` verdict | A worker addresses the Act-on list |
   | Branch with commits, no PR | A worker continues `/implement-pr` from §3 Verify |
   | Branch with no commits, or abandoned for more than 7 days with no PR | Reset the row to `todo`, remove the worktree, delete the branch |

   Don't re-run checks that already passed in CI on the same head SHA.
4. **Verify inherited claims against the real thing.** Check the PR's CI status on its current head SHA, not a
   self-report in a note.
5. Update ACTIVE.md to match reality. Only the orchestrator does this; working solo, you do it. Then continue with
   `/run-plan` or `/implement-pr`.

**Report:** where the earlier agent stopped, what you inherited, what you reset, and the resume point.

## Pause

Only on an explicit request ("pause", "stop for now", "hand off"). "Keep going" never means pause.

1. Stop at a safe boundary: finish the current atomic step, or back out of it. Start nothing new.
2. Take no irreversible action to pause: no merge, and no new PR.
3. Make the work durable: commit the uncommitted edits as one `wip:` commit on the branch, and push the branch.
   If the tree is broken, say so in one line of the commit body.
4. Write `.worktrees/<name>/RESUME.md`. It is untracked (worktrees are ignored) and contains:
   - intent;
   - what is done and verified;
   - the current state;
   - the next step;
   - key files;
   - gotchas.
5. Leave the row `in-progress` in ACTIVE.md, with "paused, see RESUME.md" in Notes.

**Report:** the commits made, whether the tree is clean, and the first action on resume.
