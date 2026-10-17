## MODIFIED Requirements

### Requirement: Data screens
Jobs (`/jobs`, run history, filters in the URL), Records (one schema, at most six field columns, drawer inspector with Replay), Schemas (one form for create, adopt and edit; edit only on active non-preset), Sites and configs (host lookup, learn with `force`, correction via `PUT /v1/configs/{id}` with changed fields only, Approve on a `pending_approval` config, absent fields named) and Settings (the project's "LLM call limit per run" and "Approve learned configs" via `/v1/project/settings`; LLM usage tables from `GET /v1/usage/llm`, unknown cost never guessed) SHALL live under `frontend/src/screens/`. (Previously: no approval.) Refs: D-0433, D-0656, D-0700, D-0978, D-0983, D-1342.
#### Scenario: Correction round-trip
- **WHEN** an operator edits a field's steps and submits
- **THEN** `PUT /v1/configs/{id}` carries only changed and confirmed fields and the validation report shows inline
