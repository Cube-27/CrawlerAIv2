# Learning and Configs delta

## MODIFIED Requirements

### Requirement: Drift suspension
Config-mode pages SHALL feed a per-field 50-page window; from 3 pages, a field whose yield or validity falls below its
baseline minus the margins in `backend/data/drift_margins.json` (fitted on the golden set only,
[evaluation](../evaluation/spec.md)) is `suspended`, falls back to cold extraction and triggers re-learning.
(Previously: cited the retired INV-02.) Refs: §8.3, D-0032, D-0571.
#### Scenario: Layout change
- **WHEN** a field matches on 1 of the last 10 pages after validating at yield 1.0
- **THEN** it is suspended, role C may fill it, and a learn job runs
