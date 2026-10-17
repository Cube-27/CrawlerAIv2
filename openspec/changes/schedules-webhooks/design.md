# Design: schedules and webhook events

## Data shape

- `schedule`: `kind` (`batch_scrape`, `crawl`, `extract`: what the queue runs), `request` (as a run submits it, a
  `records` schema by id), `cron` xor `interval_s` (≥ 60), `timezone` (IANA), `next_run_at`, `paused`,
  `last_run_at`, `last_error`, `api_key_id`. The last job is the newest `job` with its `schedule_id`.
- `webhook_event` (the outbox): `job_id`, `event`, `payload`, `created_at`, `delivery_id` (NULL while waiting).
- `webhook_delivery`: one POST of a group of events: `status`, `attempts`, `next_attempt_at`, `last_error`.
- `job.webhook_events`, `job.webhook_batch`: the request's webhook options, read where events are written.

## Exactly once

A run's job is inserted in the transaction that holds the schedule's row (`FOR UPDATE SKIP LOCKED`) and moves its
`next_run_at`: the services take a `Placement` naming that open transaction. Both commit, or neither does.
