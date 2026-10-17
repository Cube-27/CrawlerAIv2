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

## Decisions

All decided under the owner delegation of 2026-10-17, which asked for recurring runs and webhook events beyond the
job's end; owner-decisions #64 admits §22 "Recurring schedule storage".

### D-1410 — §22 "Recurring schedule storage" admitted; a run is submitted exactly once
- Date: 2026-10-17 · Change/PR: schedules-webhooks (#259) · Status: decided (owner-delegated 2026-10-17)
- Decision: §22 "Recurring schedule storage" admitted: a `schedule` table and a scheduler entry that submits due runs
  through the jobs services. A run's job is inserted in the transaction that holds the schedule's row (`FOR UPDATE
  SKIP LOCKED`) and moves its `next_run_at` (`Placement`), so it is submitted exactly once (INV-46); the scheduler
  now creates jobs, for due schedules only.
- Reversible: yes

### D-1411 — What a schedule holds
- Date: 2026-10-17 · Change/PR: schedules-webhooks (#259) · Status: decided (owner-delegated 2026-10-17)
- Decision: What a schedule holds: a batch scrape, crawl or extract request, checked as its submission is when it is
  created or its request changes. A scrape is stored as the batch of its one URL (its queued form); browser actions
  belong to a scrape answered while the caller waits and are refused, as is a `schema.prompt` (its draft needs
  fetched pages). A `records` schema is resolved once and stored by id, so field names are drafted once and a schema
  edit applies to later runs (INV-28 still pins per job).
- Reversible: yes

### D-1412 — Cadence: cron in an IANA zone, or an interval
- Date: 2026-10-17 · Change/PR: schedules-webhooks (#259) · Status: decided (owner-delegated 2026-10-17)
- Decision: Cadence: a 5-field POSIX crontab expression read by `cronsim` (BSD-3-Clause) as wall-clock times in an
  IANA zone (`tzdata`, Apache-2.0, so the zone database ships with the image), or `interval_s` ≥ 60 anchored on its
  first due time. Missed runs: one run, then the first due time after now, on the interval's phase; resuming a paused
  schedule makes up no runs.
- Reversible: yes

### D-1413 — Refused runs, run now and delete
- Date: 2026-10-17 · Change/PR: schedules-webhooks (#259) · Status: decided (owner-delegated 2026-10-17)
- Decision: A due run the services refuse (a target refused by then, globs that match nothing) stores no job, sets
  `last_error`, and the schedule moves on. Run now submits at once, paused or not, and leaves `next_run_at`. Deleting
  a schedule keeps its jobs (`job.schedule_id` set null); the last job is the newest job with its id, not a stored
  column.
- Reversible: yes

### D-1414 — Webhook events and the outbox
- Date: 2026-10-17 · Change/PR: schedules-webhooks (#259) · Status: decided (owner-delegated 2026-10-17)
- Decision: Webhook events: `page`, `record`, `record_changed`, `url_gone`, `job_completed`, `job_failed`,
  `job_cancelled`; a request naming none gets the job's end (as before). Each event is written to the `webhook_event`
  outbox in the transaction that causes it, and only for a job that asked for it.
- Reversible: yes

### D-1415 — Delivery body and headers
- Date: 2026-10-17 · Change/PR: schedules-webhooks (#259) · Status: decided (owner-delegated 2026-10-17)
- Decision: Delivery body `{delivery_id, job_id, attempt, events: [{id, type, created_at, data}]}`; a job end event
  carries the job's summary at delivery as `data.job`. `X-CrawlerAI-Delivery` repeats the delivery id on every
  attempt so a receiver can drop duplicates; the signature header is unchanged.
- Reversible: yes

### D-1416 — Batching and retries
- Date: 2026-10-17 · Change/PR: schedules-webhooks (#259) · Status: decided (owner-delegated 2026-10-17)
- Decision: `webhook_batch` `{max_events, max_seconds}`: a delivery is formed once `max_events` wait or the oldest
  waited `max_seconds`; without it, one event a delivery; once the job has ended, what waits is sent at once. 5
  attempts, 30 s × 4ⁿ backoff; deliveries are independent, so a receiver orders events by id (UUIDv7).
- Reversible: yes

### D-1417 — API, MCP and CLI surfaces
- Date: 2026-10-17 · Change/PR: schedules-webhooks (#259) · Status: decided (owner-delegated 2026-10-17)
- Decision: Surfaces: `/v1/schedules` CRUD with pause, resume and run (202 with `job_id`), `GET
  /v1/jobs?schedule_id=`, seven MCP tools (`create_schedule`, `list_schedules`, `schedule_jobs`, `pause_schedule`,
  `resume_schedule`, `run_schedule`, `delete_schedule`), and `crawlerai schedules list|pause|resume` for operators.
- Reversible: yes

### D-1418 — Schedules screen and Schedule this
- Date: 2026-10-17 · Change/PR: schedules-webhooks (#259) · Status: decided (owner-delegated 2026-10-17)
- Decision: UI: a Schedules entry under Data, a list (cadence, state, next and last run, Pause/Resume, Run now,
  Delete) and a schedule page (facts, request, its runs); "Schedule this" beside Get code in Scrape, Batch, Crawl and
  Extract stores the body the primary action would send (interval in minutes or cron, the viewer's zone by default).
  The dialog has no form of its own: it sits inside the playground's form in React's tree, where its submit would
  start the run.
- Reversible: yes

### D-1419 — Webhook options in the UI
- Date: 2026-10-17 · Change/PR: schedules-webhooks (#259) · Status: decided (owner-delegated 2026-10-17)
- Decision: UI webhook options: URL, Events (checkboxes, the job's end checked by default and then not sent), Batch
  events and Batch seconds (both or neither); without a URL the others are disabled and nothing is sent.
- Reversible: yes
