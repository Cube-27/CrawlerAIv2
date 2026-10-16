# Delta: evaluation

## MODIFIED Requirements

### Requirement: Protected CI job and PR evaluation section (INV-19)
`eval-protected.yml` SHALL run on PRs and `main` in the `eval-protected` environment, upload no artifacts and print
only pass/fail: hidden-host scan, hidden replay, the gate against the latest `main` baseline (on `main`, gated before
the run becomes the baseline), the aggregate to the private store and a pass/fail-per-field-type PR comment; the
`backend` job SHALL publish the full dev report. A PR touching extraction code SHALL fill the "Evaluation report"
section. Enforced by: PR template; protected job comment; active. (Previously: hidden-host scan and `no_baseline`
only.) Refs: C10, §16.4, SPEC-03 §4.8–§4.9, D-0234.
#### Scenario: Extraction PR regresses hidden
- **WHEN** a PR drops hidden precision of a required field type by more than 0.5 pt, or adds a wrong-product value
- **THEN** the protected job fails and its comment shows `fail` for that field type, with no numbers
