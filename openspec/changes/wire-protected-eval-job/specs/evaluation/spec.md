# Delta: evaluation

## MODIFIED Requirements

### Requirement: Protected CI job and PR evaluation section (INV-19)
`.github/workflows/eval-protected.yml` SHALL run on `pull_request` and `push` to `main` in the GitHub environment
`eval-protected` (custodians as required reviewers), with `CRAWLERAI_LOG_REDACT_URLS=true`, uploading no artifacts and
printing only pass/fail lines. It SHALL run the hidden-host scan (file:line only), `crawlerai eval run --split
hidden`, the gate against the latest `main` baseline (on a push to `main`, the gate runs before the run is recorded
as the new baseline, with the unsuppressed report stored as `metrics`), `export-aggregate` to the private store at
`reports/{run_id}.json`, and a PR comment with only the pass/fail per field type and the gate result. Fresh runs are
manual (`workflow_dispatch`). The `backend` job SHALL produce the full dev report (`crawlerai eval run --split dev`)
on every PR. Every PR that touches extraction behaviour (`collect/`, `normalize/`, `resolve/`, `llm/`, `config_ir/`,
`acquire/`) SHALL carry the dev delta report and the hidden pass/fail per field type in its "Evaluation report"
section. Enforced by: PR template; protected job comment; status: both active.
(Previously: the job ran only the hidden-host scan and printed `eval-protected: pass, no_baseline`.)
Refs: C10, §16.4, SPEC-00 §4.6, SPEC-03 §4.8–§4.9, D-0234.

#### Scenario: Extraction PR regresses hidden
- **WHEN** a PR lowers hidden precision of a required field type by more than 0.5 pt, or adds a wrong-product value
- **THEN** the protected job fails and its PR comment shows `fail` for that field type, with no numbers

#### Scenario: A rotation lowers the hidden page count
- **WHEN** a quarterly rotation moves hidden pages into dev
- **THEN** the next gate fails `n_pages_dropped` until a new baseline is recorded
