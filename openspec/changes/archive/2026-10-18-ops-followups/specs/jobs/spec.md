## MODIFIED Requirements

### Requirement: Event stream and webhooks
`/v1/jobs/{id}/events` SHALL stream `job_event` rows as SSE in id order, resuming after `Last-Event-ID`, with a 15 s
heartbeat and an end event last. A queued request's `webhook_url` is owed the `webhook_events` it names (the job's end
when none), each written to `webhook_event` in the transaction that causes it (`db/webhook_outbox.py`), grouped into
deliveries by `webhook_batch`, and POSTed signed HMAC-SHA256 with the key's `webhook_secret`, in at most 5 attempts
with backoff, through the SSRF guard, no redirects; failure never fails the job. A delivery keeps its attempts, its last
error and the receiver's last HTTP status; the scheduler deletes ended deliveries (`delivered`, `failed`) and their
events 30 days after creation, never a pending one (`scheduler/retention.py`). (Previously: only the job's summary,
when it ended, in 3 attempts; ended rows were never deleted.) Refs: §17, D-0639, D-0642, D-0644, D-0760, D-1414,
D-1415, D-1416, D-1511.
#### Scenario: Batched page events
- **WHEN** a job whose webhook asks for `page` with `webhook_batch` `{max_events: 2, max_seconds: 3600}` finishes two
  tasks and ends
- **THEN** one delivery carries both `page` events, and the job's end event follows in a delivery of its own
#### Scenario: Expired deliveries
- **WHEN** a `delivered`, a `failed` and a `pending` delivery are each 31 days old
- **THEN** retention deletes the first two with their events and keeps the pending one

### Requirement: Request context and actions per page
Batch, crawl and extract jobs SHALL fetch every page with the request's `fetch` context, `wait_for` and `actions`
(D-1439); the job keeps the secret values in `job.request` for its workers while it runs, and when it ends its header
and cookie values are replaced by `**********`, names kept (D-1510); `GET /v1/jobs/{id}/request` answers them as
`**********`. `fetch.cache` `only` serves each task from the latest `ok` capture of its URL made with the same actions
and context names, or fails the task `not_cached`; `bypass` sends no validators. (Previously: the values stayed in
`job.request` after the job ended.) Refs: owner delegation 2026-10-17, D-1432, D-1435, D-1439, D-1510.
#### Scenario: Stored request
- **WHEN** a batch is submitted with cookie `sid` and its request is read back
- **THEN** the answer's `fetch.cookies.sid` is `**********`
#### Scenario: Ended job
- **WHEN** a job submitted with header `X-Token: abc` ends
- **THEN** `job.request` holds `**********` for `X-Token`, and a running job still holds `abc`

### Requirement: Recurring schedules (INV-46)
A schedule SHALL hold the request of a batch scrape, crawl or extract (a scrape stored as the batch of its URL, a
`records` schema by id), checked as its submission is when created, and run at each time of a 5-field cron expression
in an IANA zone or every `interval_s` ≥ 60 s (`core/cadence.py`, `services/schedules.py`). A due run's job is stored in
the transaction that holds its row (`FOR UPDATE SKIP LOCKED`) and moves it on, so it is submitted exactly once; a
schedule that missed runs runs once; a refused run stores no job and sets `last_error`; resuming makes up no runs. A
schedule keeps no secret value: a request with `fetch.headers` or `fetch.cookies` is refused. (Previously: such a
request was stored with its values as `**********`, which a run then sent.)
Enforced by: concurrent scheduler test; active. Refs: §22, D-1410, D-1411, D-1412, D-1413, D-1510.
#### Scenario: Two schedulers
- **WHEN** two scheduler runs read one due schedule at once
- **THEN** one job is submitted, and the schedule's next run is its next due time
#### Scenario: Missed runs
- **WHEN** an interval schedule is read 50 minutes after its due time, every 5 minutes
- **THEN** one job is submitted and the next run is its first due time after now, on its phase
#### Scenario: Secret values
- **WHEN** a schedule is created with a request whose `fetch.cookies` names `sid`
- **THEN** the answer is a 422 problem and no schedule is stored
