## MODIFIED Requirements

### Requirement: Schema, config, record and replay endpoints
`/v1/schemas` SHALL offer create, list, get, replace and retire (presets, retired schemas and taken names are 409) and
`/v1/schemas/draft`; config endpoints expose [learning-configs](../../../../../specs/learning-configs/spec.md), with
`POST /v1/configs/{id}/approve` and `POST /v1/configs/{id}/reject` (each 409 unless the config is the latest version
and `pending_approval`); `GET /v1/records` pages newest first by
keyset cursor (≤ 200) with `changed_since` (see [jobs](../../../../../specs/jobs/spec.md)), and with `job_id` by the job's tasks, newest
task first, a record once; `POST /v1/captures/{id}/replay` runs the current engine cold and persists nothing.
(Previously: no reject endpoint.) Refs: §13.1, §15, D-0396, D-0523, D-0950, D-1280, D-1342, D-1391.

### Requirement: MCP tools
The MCP server SHALL use the official `mcp` SDK and expose exactly `scrape`, `map`, `crawl_start`, `crawl_status`,
`extract`, `extract_status`, `list_schemas`, `create_schema`, `get_site_config`, `export_config`, `reject_config`, each
one service call; long jobs return a `job_id` at once and status tools page 10 results. No jobs-list or usage tool.
(Previously: ten tools, no `reject_config`.) Refs: §13.3, D-0698, D-1391.
#### Scenario: Tool list
- **WHEN** a client lists the tools
- **THEN** it gets exactly the eleven tools named above

## ADDED Requirements

### Requirement: The fetch names its adapter
A scrape answer's `fetch` SHALL carry `adapter`, the name of the platform adapter that read the page's `api` capture
(INV-39), null for any other fetch. Refs: D-1393.
#### Scenario: Adapter capture
- **WHEN** a page is served by a platform adapter's API request
- **THEN** `fetch.method` is `api` and `fetch.adapter` is that adapter's name
