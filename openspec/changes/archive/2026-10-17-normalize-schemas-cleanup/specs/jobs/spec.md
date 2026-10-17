## MODIFIED Requirements

### Requirement: Settings pinned at submit (INV-28)
A job SHALL run with the schema document, per-host config versions, calibration and source precedence pinned at submit;
later changes apply only to later jobs, and a pinned config runs even if suspended. LLM providers, model ids and
limits are the worker process's settings, not pinned: each usage row records the provider and model of its call.
Refs: §17, D-0678, D-0951, D-1377. Enforced by: mid-job calibration and config change test; active.
(Previously: "Not built yet: LLM settings are not pinned, D-0631.")
#### Scenario: Schema edited mid-job
- **WHEN** a schema is edited while a job that uses it runs
- **THEN** remaining tasks use the pinned document and a later job uses the new one
