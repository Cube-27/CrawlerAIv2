## MODIFIED Requirements

### Requirement: Schema, config, record and replay endpoints
`/v1/schemas` SHALL offer create, list, get, replace and retire (presets, retired schemas and taken names are 409) and
`/v1/schemas/draft`; config endpoints expose [learning-configs](../learning-configs/spec.md), with
`POST /v1/configs/{id}/approve` (409 unless the config is `pending_approval`); `GET /v1/records` pages newest first by
keyset cursor (≤ 200) with `changed_since` (see [jobs](../jobs/spec.md)), and with `job_id` by the job's tasks, newest
task first, a record once; `POST /v1/captures/{id}/replay` runs the current engine cold and persists nothing.
(Previously: no approve endpoint.) Refs: §13.1, §15, D-0396, D-0523, D-0950, D-1280, D-1342.

### Requirement: Project settings
`GET/PATCH /v1/project/settings` SHALL read and set `llm_call_cap`, the LLM calls a job may make when its request sets
no `budget.llm_calls`, `draft_call_cap`, the uncharged role S calls one API key may make (null: no cap), and
`require_config_approval`, whether a learned config waits for approval (off until set). (Previously: the two caps
only.) Refs: §13.1, Appendix A #47, D-1121, D-1282, D-1342, D-1346.
