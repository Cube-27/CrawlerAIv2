# Recurring findings

Mistakes that agents made more than once, and what now prevents each one. The orchestrator keeps this file
current (`/run-plan` §2a). A finding that recurs gets a **check** where one can catch it (lint rule, `tools/` scan, CI
step); a **skill rule** only where no check can. Workers read this list before opening a PR (`/implement-pr` §4).

| Finding | Seen in | Prevented by |
|---|---|---|
| A CLI path argument is read without a base-directory check (SonarCloud `pythonsecurity:S8707`, path traversal). | #21, #22, #30 | Skill rule (`/implement-pr` §4): resolve the path and refuse it outside the working directory or repo root, with a test, as `fetch --out` does (D-0146). |
| A `pytest.raises` block holds more than one statement or call (SonarCloud `python:S5778`). | #20, #23, #30, #33 | Check: ruff `PT012` (one statement). Skill rule for nested calls, which `PT012` doesn't see: build arguments before the `with`. |
| A worker reports DONE while the PR's SonarCloud gate is red. | #28, #30 | Skill rule (`/implement-pr` §6): DONE requires the PR's gate `OK`. `tools/orchestrator/wait_ci.sh` prints the gate. |
| Duplicated lines on new code push the SonarCloud gate over 3%. | #28 | Watch. Skill rule if it recurs. |
| Throwaway test Postgres containers outlive their worktree. | #28, #30 | `tools/orchestrator/cleanup_worktree.sh` on merge; skill rule (`/implement-pr` §3): remove containers you start. |
| A herdr pane starts in the home folder because the cwd string was built inline (`"...\$wt"` drops the variable). | orchestrator, twice | `tools/orchestrator/start_agent.sh` builds the path and checks the agent's cwd. |
| An orchestrator tracker commit written early conflicts with a PR that merged first. | #26 | Skill rule (`/run-plan` §1): write a tracker commit early only for the PR that merges next. |
| A wait loop reads the previous commit's CI results. | orchestrator | `tools/orchestrator/wait_ci.sh` waits on the head SHA. |
