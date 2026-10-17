## Why

A caller who wants a page, a batch, a crawl or an extract re-run every hour has to re-submit it from a cron job of its
own, and a webhook says only that a job ended. The owner asked for recurring runs and for webhook events beyond the
job's end (owner delegation 2026-10-17), which admits §22 "Recurring schedule storage".

## What Changes

- A `schedule` table and `/v1/schedules` (create, list, read, update, delete, pause, resume, run now): the request of
  a scrape (run as the batch of its URL), batch scrape, crawl or extract, run on a 5-field cron expression in an IANA
  time zone or every `interval_s` seconds. A scheduler entry submits each due run through the jobs services in the
  transaction that moves the schedule on, so a run is submitted exactly once; a schedule that missed runs runs once.
  Jobs carry `schedule_id`; `GET /v1/jobs?schedule_id=` is a schedule's history. Scheduled runs are re-runs of one
  request, so record versions, `changed_fields` and `url_gone` follow them.
- Webhook events: a queued request's `webhook_events` (`page`, `record`, `record_changed`, `url_gone`,
  `job_completed`, `job_failed`, `job_cancelled`; the job's end by default) and `webhook_batch` (`max_events`,
  `max_seconds`). Events go to a durable outbox (`webhook_event`) in the transaction that causes them; the scheduler
  groups them into deliveries, POSTed signed (HMAC-SHA256), with 5 attempts and backoff, through the SSRF guard.
- MCP: seven schedule tools. UI: a Schedules screen, "Schedule this" in the playground, webhook settings in Options.

## Impact

- Capabilities: jobs, rest-api, frontend. Design: §22 "Recurring schedule storage" admitted (owner-decisions row).
- Code: `db/models.py` and the baseline migration (`schedule`, `webhook_event`, reshaped `webhook_delivery`, job
  columns), `db/webhook_outbox.py`, `api/webhooks.py`, `core/cadence.py`, `services/schedules.py`,
  `services/webhook_options.py`, `api/routers/schedules.py`, `mcp_server/server.py`, `scheduler/loop.py`, frontend.
- Dependencies: `cronsim` (BSD-3-Clause), `tzdata` (Apache-2.0).
