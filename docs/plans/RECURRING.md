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
| Throwaway test Postgres containers, their anonymous volumes and Docker build cache outlive their worktree (21.8 GB of cache and 2 leaked volumes by 2026-10-13). | #28, #30, owner | `tools/orchestrator/cleanup_worktree.sh` on merge removes `crawlerai-*` containers with `-v`, removes all build cache (owner: no cache needed) and drops dangling images; skill rule (`/implement-pr` §3): remove containers with `-v` and images you build. |
| A herdr pane starts in the home folder because the cwd string was built inline (`"...\$wt"` drops the variable). | orchestrator, twice | `tools/orchestrator/start_agent.sh` builds the path and checks the agent's cwd. |
| An orchestrator tracker commit written early conflicts with a PR that merged first. | #26 | Skill rule (`/run-plan` §1): write a tracker commit early only for the PR that merges next. |
| A wait loop reads the previous commit's CI results. | orchestrator | `tools/orchestrator/wait_ci.sh` waits on the head SHA. |
| A merge ran after a failed CI wait (`wait_ci.sh ... ; gh pr merge`), so #38's last commit merged before its CI ran. Main stayed green. | orchestrator (#38) | `tools/orchestrator/merge_pr.sh`: merges only on a passing wait, pinned to the head commit; `wait_ci.sh` tolerates the old head right after a push and exits 1 on a failed check. |
| Sonar shell rules on orchestrator scripts (`shelldre`: `[[`, errors to stderr, `case` default, explicit `return`). | #40 | Watch. Skill rule if it recurs. |
| A prompt sent while the agent was still loading was dropped, and `start_agent.sh` reported the agent idle. | orchestrator (SPEC-02 PR 6 worker) | `start_agent.sh` waits 15 s for a turn, resends once, then fails and closes the pane. |
| Agent panes split the orchestrator's pane downward, stacking into rows one or two lines high that the owner can't read. | orchestrator (owner) | `start_agent.sh` opens each agent in its own tab labelled with its name. |
