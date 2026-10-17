## MODIFIED Requirements

### Requirement: Worker and scheduler roles
`api`, `worker` and `scheduler` SHALL run from one image; the scheduler runs the periodic entries in its table (lease
release, stalled `map`/`extract` jobs failed, due schedules run, webhook deliveries formed and sent, retention,
learning) and creates jobs only for due schedules. (Previously: it created no jobs; schedules were §22.) Refs: §19,
§22, D-0714, D-0837, D-1006, D-1410.

### Requirement: Event stream and webhooks
`/v1/jobs/{id}/events` SHALL stream `job_event` rows as SSE in id order, resuming after `Last-Event-ID`, with a 15 s
heartbeat and an end event last. A queued request's `webhook_url` is owed the `webhook_events` it names (the job's end
when none), each written to `webhook_event` in the transaction that causes it (`db/webhook_outbox.py`), grouped into
deliveries by `webhook_batch`, and POSTed signed HMAC-SHA256 with the key's `webhook_secret`, in at most 5 attempts
with backoff, through the SSRF guard, no redirects; failure never fails the job. (Previously: only the job's summary,
when it ended, in 3 attempts.) Refs: §17, D-0639, D-0642, D-0644, D-0760, D-1414, D-1415, D-1416.
#### Scenario: Batched page events
- **WHEN** a job whose webhook asks for `page` with `webhook_batch` `{max_events: 2, max_seconds: 3600}` finishes two
  tasks and ends
- **THEN** one delivery carries both `page` events, and the job's end event follows in a delivery of its own

## ADDED Requirements

### Requirement: Recurring schedules (INV-46)
A schedule SHALL hold the request of a batch scrape, crawl or extract (a scrape stored as the batch of its URL, a
`records` schema by id), checked as its submission is when created, and run at each time of a 5-field cron expression
in an IANA zone or every `interval_s` ≥ 60 s (`core/cadence.py`, `services/schedules.py`). A due run's job is stored in
the transaction that holds its row (`FOR UPDATE SKIP LOCKED`) and moves it on, so it is submitted exactly once; a
schedule that missed runs runs once; a refused run stores no job and sets `last_error`; resuming makes up no runs.
Enforced by: concurrent scheduler test; active. Refs: §22, D-1410, D-1411, D-1412, D-1413.
#### Scenario: Two schedulers
- **WHEN** two scheduler runs read one due schedule at once
- **THEN** one job is submitted, and the schedule's next run is its next due time
#### Scenario: Missed runs
- **WHEN** an interval schedule is read 50 minutes after its due time, every 5 minutes
- **THEN** one job is submitted and the next run is its first due time after now, on its phase
