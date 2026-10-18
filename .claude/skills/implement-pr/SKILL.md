---
name: implement-pr
description: Implement a task or backlog item as one PR, end to end: worktree, test DB, touched tests, mypy, PR, green CI, resolved bot threads. Use when asked to implement a change or open a PR.
---

# Implement one PR

Rules: `CLAUDE.md` and `openspec/conventions/ENGINEERING.md`.

1. **Worktree.** `tools/orchestrator/new_worktree.sh <change-id> change/<change-id>` (off fresh `origin/main`, lands in
   `<main>/../CrawlerAIv2-worktrees/`). Never work in the main checkout.
2. **Build.** Tests first, smallest change that passes them, commit per task (Conventional Commits). A behaviour
   change edits the capability spec it touches (`openspec/specs/`); no site-named tests (C9).
3. **Test DB** (DB tests only): `eval "$(tools/orchestrator/test_db.sh up)"`; `tools/orchestrator/test_db.sh drop`
   before you finish.
4. **Verify locally, small.** Run only the test files you touched or whose imports you changed, one file at a time
   (`uv run pytest tests/unit/test_x.py`, `pnpm test --maxWorkers=1 <file>`); never `pytest -n`, never the full
   suite. Then `uv run mypy src tests migrations` in `backend/`. CI runs everything.
5. **Open the PR** with `gh pr create` from the repo template (title `type(scope): subject`). For extraction
   changes the evaluation section carries the golden-set delta per field type (C10).
6. **CI.** `tools/orchestrator/wait_ci.sh <n> <head-sha7>` until every check is green; fix red checks in code, never
   with exclusions or weaker thresholds.
7. **Bot threads.** Triage every review thread (CodeRabbit, CodeAnt, Sonar): fix it or reply why it is not a defect,
   then resolve it (`gh api graphql` `resolveReviewThread`). Push all fixes together, then wait for green again.
8. Never merge your own PR. Comment `READY <sha7>` on the green head and stop.
