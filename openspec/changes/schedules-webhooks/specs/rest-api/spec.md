## MODIFIED Requirements

### Requirement: MCP tools
The MCP server SHALL use the official `mcp` SDK and expose exactly `scrape`, `map`, `crawl_start`, `crawl_status`,
`extract`, `extract_status`, `list_schemas`, `create_schema`, `get_site_config`, `export_config`, `reject_config`,
`create_schedule`, `list_schedules`, `schedule_jobs`, `pause_schedule`, `resume_schedule`, `run_schedule` and
`delete_schedule`, each one service call; long jobs return a `job_id` at once and status tools page 10 results. No
jobs-list or usage tool. (Previously: eleven tools, no schedule tools.) Refs: §13.3, D-0698, D-1391, D-1417.
#### Scenario: Tool list
- **WHEN** a client lists the tools
- **THEN** it gets exactly the eighteen tools named above

## ADDED Requirements

### Requirement: Schedule endpoints
`/v1/schedules` SHALL create (201), list newest first, read, `PATCH` (name, cadence, or `kind` with `request`, checked
as at creation), delete (204, its jobs kept with `schedule_id` null), pause, resume and run now (202 with `job_id`)
schedules; a request the submission would refuse, a schema prompt or a scrape's browser actions is a 422, and
`GET /v1/jobs?schedule_id=` lists a schedule's jobs. Refs: §22, D-1411, D-1412, D-1417.

### Requirement: Webhook payloads
A delivery SHALL POST `{delivery_id, job_id, attempt, events: [{id, type, created_at, data}]}` with
`X-CrawlerAI-Signature: sha256=<HMAC-SHA256 of the body>` and `X-CrawlerAI-Delivery`; `page` data is the task's id,
URL, status, outcome, capture and error, `record` and `record_changed` the stored version (id, entity, version,
`changed_fields`, `complete`, published `data`), `url_gone` the URL, and a job end event the job's summary as `job`
(`api/webhooks.py`). Refs: D-1414, D-1415.
