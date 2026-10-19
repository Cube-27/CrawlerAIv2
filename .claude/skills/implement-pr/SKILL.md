---
name: implement-pr
description: Implement a task or backlog item as one PR, end to end: worktree, runtime verification, verify-* checks, PR, one bot-fix round, green CI. Use when asked to implement a change or open a PR.
---

# Implement one PR

Rules: `CLAUDE.md` and `openspec/conventions/ENGINEERING.md`.

1. **Worktree.** `tools/orchestrator/new_worktree.sh <change-id> change/<change-id>` (off fresh `origin/main`, with
   `.env`, the data files and a synced `backend/` environment). DB work: `eval "$(tools/orchestrator/test_db.sh up)"`,
   and `tools/orchestrator/test_db.sh drop` before you finish; remove any image you build.
2. **Build.** The smallest change that fixes the class of pages (C8). A behaviour change edits the capability spec it
   touches (`openspec/specs/`).
3. **Verify, in this order.**
   - Runtime grounding: run the real path (`crawlerai` CLI or the worker) on public pages that show the behaviour, and
     read the output. This is the main evidence.
   - Every `.claude/skills/verify-*` skill whose paths your diff touches: run its one command.
   - A test only for a behaviour that neither of those covers: one behaviour-level or property test, none per case.
     Delete tests your change makes redundant.
   - `uv run mypy src tests migrations` in `backend/`, plus the test files you touched, one at a time (never the full
     suite or `pytest -n`; CI runs everything).
   - Extraction changes (C10): ONE regression run on the final code, on a copy of the eval DB, reported per field type.
4. **Open the PR** with `gh pr create` from the repo template (title `type(scope): subject`). Decisions within the
   change's scope go in the PR body only.
5. **One review round.** Wait for the first CI run (`tools/orchestrator/wait_ci.sh <n> <head-sha7>`) and CodeAnt's
   first review, which arrive together. Triage every thread from any bot: fix it or reply why it is not a defect.
   Push ALL fixes in ONE commit, then wait for green once more and resolve the threads (`gh api graphql`
   `resolveReviewThread`). Don't wait for a re-review, and don't push piecemeal. Fix red checks in code, never with
   exclusions or weaker thresholds.
6. Never merge your own PR. Comment `READY <sha7>` on the green head. Report back tersely: PR and head sha, what
   changed, the evidence, and anything that needs the owner (an invariant, a product decision, or labels). Don't
   write escalations into the repo.
