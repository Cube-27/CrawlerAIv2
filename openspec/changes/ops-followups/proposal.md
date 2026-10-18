## Why
Six follow-ups of merged PRs (#252, #259, #262, #266) leave operators without a way to see why a webhook failed, with
webhook rows that never expire, with caller secrets that stay in an ended job's request, with a schedule that can only
be made from a form, with a playground that hides a listing's `page` member and the reason it had no rows, and with a
listing scrape that refuses the caller's page steps. Owner request 2026-10-17: close the backlog.

## What Changes
- Webhooks: ended `webhook_delivery` rows and their events expire 30 days after creation; `GET
  /v1/jobs/{id}/webhook-deliveries` and the MCP tool `webhook_deliveries` list a job's deliveries (status, attempts, last
  error, the receiver's HTTP status); a collapsed Deliveries panel shows them on a job's page.
- Schedules UI: Edit (name, cadence, request as JSON) on a schedule; "Schedule this run" creates one from a stored run.
- Job secrets: an ended job's request keeps header and cookie names only; a schedule keeps no secret value (a request
  that carries any is refused 422).
- Playground: a scrape's `page` fields (a listing that kept no record) and its `no_rows` reason in words.
- Listing paging: a listing scrape's `browser_actions` runs the caller's `fetch.actions` and `wait_for` first.
- Config approval (#252): reject and approve checked end to end in the UI; nothing to build.

## Impact
`db/{jobs,models}.py`, `core/redaction.py`, `scheduler/{retention,loop}.py`, `api/webhooks.py`,
`api/routers/jobs.py`, `services/{webhook_deliveries,schedules,scrape_paging,fetch_options,jobs}.py`,
`acquire/{browser,browser_tab}.py`, `mcp_server/server.py`, the baseline migration (one column, one index), the
frontend job, schedule and playground screens. API: one endpoint and one MCP tool added; `openapi.json` and the SDKs
regenerated. Specs: jobs, rest-api, acquisition, frontend.
