## ADDED Requirements

### Requirement: Webhook deliveries of a job
`GET /v1/jobs/{id}/webhook-deliveries` SHALL list the job's deliveries newest first by cursor (`status`, `attempts`,
`next_attempt_at` while pending, `last_error`, `response_code`, `event_count`, `created_at`), 404 for an unknown job;
the MCP tool `webhook_deliveries` answers the same page (`services/webhook_deliveries.py`). Refs: D-1511.
#### Scenario: A refused delivery
- **WHEN** a receiver answered a delivery's last attempt with 503
- **THEN** it reads `pending`, `attempts` 1, `last_error` "status 503" and `response_code` 503

## MODIFIED Requirements

### Requirement: MCP tools
The MCP server SHALL use the official `mcp` SDK and expose exactly `scrape`, `map`, `search`, `crawl_start`,
`crawl_status`, `extract`, `extract_status`, `list_schemas`, `create_schema`, `get_site_config`, `export_config`,
`reject_config`, `llms_txt`, `create_schedule`, `list_schedules`, `schedule_jobs`, `pause_schedule`, `resume_schedule`,
`run_schedule`, `delete_schedule` and `webhook_deliveries`, each one service call; long jobs return a `job_id` at once
and status tools page 10 results. No jobs-list or usage tool. (Previously: twenty tools, no `webhook_deliveries`.)
Refs: §13.3, D-0698, D-1391, D-1417, D-1442, D-1511.
#### Scenario: Tool list
- **WHEN** a client lists the tools
- **THEN** it gets exactly the twenty-one tools named above

### Requirement: Scrape browser actions
`POST /v1/scrape` SHALL take an optional `browser_actions` (`records`, a soft row target, default 100; `hint`:
`load_more`, `show_more`, `pagination`, `next` or `scroll`), refused 422 unless `page_kind` is `listing`, and with
`max_age` > 0 or `method_hint` `http`; batch has no such member. The request's `fetch.actions` and `wait_for` run first
on the settled page. With `records` asked, each further kept document state is a capture with its own extraction under
its own URL, stored once the first state's did not fail; the answer lists records once each (a failed further state
makes it `partial`), `capture_id` and formats are the first state's, and `browser_actions` reports the mechanism, stop
reason, actions, pages and items. (Previously: `fetch.actions` or `wait_for` with `browser_actions` was 422.) Refs:
owner #52, D-1218, D-1222, D-1223, D-1513.
#### Scenario: Detail page
- **WHEN** a scrape with `page_kind` `detail` sets `browser_actions`
- **THEN** the answer is a 422 problem naming `browser_actions` and no job is created
#### Scenario: Steps before paging
- **WHEN** a listing scrape sets `browser_actions` and `fetch.actions` with a click on a consent button
- **THEN** the click runs before the paging driver reads the page, and `fetch.attempts` carries its outcome

### Requirement: Schedule endpoints
`/v1/schedules` SHALL create (201), list newest first, read, `PATCH` (name, cadence, or `kind` with `request`, checked
as at creation), delete (204, its jobs kept with `schedule_id` null), pause, resume and run now (202 with `job_id`)
schedules; a request the submission would refuse, a schema prompt, a scrape's browser actions or caller headers or
cookies is a 422, and `GET /v1/jobs?schedule_id=` lists a schedule's jobs; `crawlerai schedules list|pause|resume` does
the same from the command line. (Previously: no refusal of caller headers or cookies.) Refs: §22, D-1411, D-1412,
D-1417, D-1510.
