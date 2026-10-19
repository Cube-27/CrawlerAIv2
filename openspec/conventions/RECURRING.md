# Recurring findings

Mistakes that agents made more than once, and what now prevents each one. A finding that recurs gets a **check**
where one can catch it (lint rule, `tools/` scan, CI step). Read this list before opening a PR.

| Finding | Seen in | Prevented by |
|---|---|---|
| A CLI path argument is read without a base-directory check (SonarCloud `pythonsecurity:S8707`, path traversal). | #21, #22, #30 | Rule: resolve the path and refuse it outside the working directory or repo root, with a test, as `fetch --out` does (D-0146). |
| A `pytest.raises` block holds more than one statement or call (SonarCloud `python:S5778`). | #20, #23, #30, #33 | Check: ruff `PT012` (one statement). For nested calls, which `PT012` doesn't see: `ENGINEERING.md` "Patterns the analysers flag" (S5778). |
| A worker reports DONE while the PR's SonarCloud gate is red. | #28, #30 | Rule: `READY` requires the PR's gate `OK`. `tools/orchestrator/wait_ci.sh` prints the gate. |
| Duplicated lines on new code push the SonarCloud gate over 3%. | #28 | Watch. Skill rule if it recurs. |
| Repeated SonarCloud rules on new code (`python:S9073`, `S6353`, `S1192`, `S7503`; `typescript:S6759`, `S6479`, `S3358`; and the others that fired more than once). | Sonar history, #177 | `ENGINEERING.md` "Patterns the analysers flag": one line per rule with the right pattern; workers read it before the PR. |
| Throwaway test Postgres containers, their anonymous volumes and Docker build cache outlive their worktree (21.8 GB of cache and 2 leaked volumes by 2026-10-13). | #28, #30, owner | `tools/orchestrator/cleanup_worktree.sh` on merge removes `crawlerai-*` containers with `-v`, removes all build cache (owner: no cache needed) and drops dangling images; DB tests use one shared container (`tools/orchestrator/test_db.sh`, a database pair per worktree, dropped by `cleanup_worktree.sh`) instead of one per worktree; skill rule (`/implement-pr` §1): remove images you build. |
| A wait loop reads the previous commit's CI results. | orchestrator | `tools/orchestrator/wait_ci.sh` waits on the head SHA. |
| A merge ran after a failed CI wait (`wait_ci.sh ... ; gh pr merge`), so #38's last commit merged before its CI ran. Main stayed green. | orchestrator (#38) | The orchestrator merges with `gh pr merge --match-head-commit <sha>` only after every check on that head is green; `wait_ci.sh` tolerates the old head right after a push and exits 1 on a failed check. |
| Sonar shell rules on orchestrator scripts (`shelldre`: `[[`, errors to stderr, `case` default, explicit `return`). | #40, Sonar history | `ENGINEERING.md` "Patterns the analysers flag" (S7688, S7677, S7679, S7682). |
| `wait_ci.sh` waited about 30 minutes for checks on a PR that conflicted with main: GitHub starts no `pull_request` workflow on a conflicting PR, so only CodeRabbit and SonarCloud reported. | #109 | Check: `tools/orchestrator/wait_ci.sh` exits 1 at once when the PR is `CONFLICTING`/`DIRTY` (`rebase onto origin/main`), and when no workflow run exists for the head after 5 minutes. |
| A frontend screen test times out under load: it renders the whole app through the router and types the API key key by key, and one file lacked the per-file 20 s budget (`SitesScreen.test.tsx`, then `SettingsScreen.test.tsx`). | UAT F25 (#152), F35 (#160) | Check: one `test.testTimeout` in `frontend/vite.config.ts` for every file; `src/test/connect.ts` pasted the key until SPEC-14 PR 1 removed the key prompt. Skill rule if it recurs: paste instead of typing long text, and open a screen by its address. |
