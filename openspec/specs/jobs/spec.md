# Jobs Specification

## Purpose

Asynchronous work: job kinds, the task queue with leases and retries, the worker and scheduler roles, settings pinned
at submit, task failure isolation, `batch/scrape` and `extract`, and the job endpoints (list, status, request,
cancel, results, SSE events, webhooks, budgets). Discovery for `map` and `crawl` is in
[crawl-map](../crawl-map/spec.md); change detection in [recurring](../recurring/spec.md); the sync scrape and shared
API rules in [rest-api](../rest-api/spec.md).
Design rationale: [ARCHITECTURE §13](../../design/api.md), [§17](../../design/operations.md). History:
[SPEC-10](../../changes/archive/2026-10-14-spec-10-jobs-crawl-extract-mcp/SPEC-10-jobs-crawl-extract-mcp.md) and its
[decisions](../../changes/archive/2026-10-14-spec-10-jobs-crawl-extract-mcp/decisions.md); queue from
[SPEC-01](../../changes/archive/2026-10-13-spec-01-persistence-queue-storage/SPEC-01-persistence-queue-storage.md).

## Requirements

### Requirement: Job kinds, statuses and task outcomes
A job SHALL have `kind` ∈ {`scrape`, `batch_scrape`, `map`, `crawl`, `extract`, `learn`} and `status` ∈ {`queued`,
`running`, `completed`, `failed`, `cancelled`}; a `url_task` has `status` ∈ {`queued`, `claimed`, `done`, `failed`,
`cancelled`} and `outcome` ∈ {`extracted`, `partial`, `unchanged`, `links_only`, `blocked`, `shell`, `not_found`,
`no_match`, `failed`}. Task-level errors are outcomes, not job failures: a job SHALL end `failed` only when every task
failed or the budget ran out before any task completed, and `completed` otherwise once no task is queued or claimed.
Job end times and event times use `clock_timestamp()`. `learn` jobs belong to
[learning-configs](../learning-configs/spec.md).
Refs: §6, SPEC-01 §4.3, SPEC-10 §4.8, D-0764.

#### Scenario: One task fails
- **WHEN** a batch of three URLs ends with one task `failed` and two `extracted`
- **THEN** the job is `completed` and `outcomes` counts one `failed`

### Requirement: Queue, leases and retries
Workers SHALL claim tasks with one `FOR UPDATE SKIP LOCKED` statement ordered by priority then id, setting a 10-minute
lease. A transient failure (a worker fetch ending in `error`) SHALL be retried until 3 attempts with backoff 30 s ×
2^(attempts−1), then the task is `failed`; every other outcome is terminal. A refused redirect or an SSRF refusal of
the task URL, checked before the fetch, fails the task at once with no capture or usage. Politeness is per site in
the worker, not in the claim.
Refs: SPEC-01 §4.3, D-0006, D-0632, D-0705.

#### Scenario: Transient fetch error
- **WHEN** a batch task's fetch ends in `error` on its first attempt
- **THEN** it is queued again with `next_attempt_at` 30 s later

### Requirement: Worker and scheduler roles
The `api`, `worker` and `scheduler` roles SHALL run from one image. The worker registers a handler per job kind with
tasks (`batch_scrape` and `extract` share the scrape handler; `crawl` has its own) and binds role C, charged to the
task's job. The scheduler runs a table of periodic entries: `release_expired_leases` (1 min), `fail_stalled_jobs`
(1 min: `map` and `extract` jobs still `running` with no task one lease after they started end `failed`, 100 per
turn), `deliver_webhooks` (5 s), and the retention and learning entries of other capabilities. The scheduler creates
no jobs in core.
Refs: §19, SPEC-01 §4.3, D-0714, D-0837, D-1006.

#### Scenario: Lost in-process job
- **WHEN** a `map` job stays `running` with no task for longer than the lease
- **THEN** the scheduler ends it `failed`

### Requirement: Settings pinned at submit (INV-28)
A job SHALL run with the schema document (`job.pinned.schema`), site config versions, calibration, source precedence
and LLM settings pinned when it was submitted; later changes apply only to jobs submitted after them. Configs are
pinned per host, for the start URL's host only on a crawl; a host without an active config stays cold (`adhoc`) for
the whole job, and a pinned config runs even after it is suspended or replaced. (Not built yet: LLM settings are not
in `job.pinned`, D-0631.)
Refs: §17, Appendix A #32, SPEC-10 §4.2, D-0631, D-0678, D-0951.
Enforced by: test that changes calibration and a config mid-job, and the job's remaining tasks still use the pinned
versions; status: SPEC-10 (test: SPEC-10 PR 2).

#### Scenario: Schema edited mid-job
- **WHEN** a schema is edited while a job that uses it runs
- **THEN** the job's remaining tasks extract with the pinned document and a job submitted after the edit uses the new one

### Requirement: Task failure isolation (INV-31)
One task's failure SHALL never fail another: each task runs in its own DB session and transaction, and a crashed
shared browser is restarted at most once per task. A worker holds one browser; a fetch that leaves it disconnected
relaunches it and fetches again, and if that dies too the result stands and the next task launches a new one. A
task's fetch usage is counted after its extraction, inside the task's transaction.
Refs: §17, Appendix A #32, SPEC-10 §4.2, D-0633, D-0715.
Enforced by: tests that a batch with one failing task completes the others, and a killed browser fails only its
task; status: SPEC-10 (test: SPEC-10 PR 2).

#### Scenario: Killed browser
- **WHEN** the shared browser is killed during one task
- **THEN** only that task fails and the browser was restarted at most once for it

### Requirement: Batch scrape
`POST /v1/batch/scrape {urls (1–1000), formats, schema?, page_kind?, fetch?, locale?, budget?, webhook_url?}` SHALL
answer `{job_id}` and create one `url_task` per URL, each run by the scrape steps with role C. `schema` is `{id}`,
`{inline}` or `{fields}`; a `schema.prompt` is 422. `records` is asked alone. URLs are caller-supplied: an incomplete
page returns its record with `complete=false`, outcome `partial`.
Refs: §13.1, SPEC-10 §4.3, D-0628, D-0629, D-1006.

#### Scenario: Prompt on a batch
- **WHEN** a batch body has `schema.prompt`
- **THEN** the answer is 422 `validation` and no job is stored

### Requirement: Extract
`POST /v1/extract {urls, schema, page_kind, limit, fetch?, locale?, budget?, webhook_url?}` SHALL answer `{job_id,
schema}` with the schema the job pinned, extracting every task with `page_kind` in the site's progressive mode. An
entry containing `*` is a glob whose scheme and authority are literal (`?` and `[` alone leave a URL); globs are
expanded by a map of their canonical origin (`https://host/`, one map per origin, at most 20 globs per host). `limit`
(≤ 1000, default 1000) counts every task, given URLs first; globs that match nothing with no other URL are a 422 and
store no job. All extract URLs, glob-expanded ones included, are caller-supplied (`partial` records).
Refs: §10, §13.1, SPEC-10 §4.6, D-0681, D-0682, D-0683, D-0686, D-0835.

#### Scenario: Glob matches nothing
- **WHEN** the only entry is a glob that the map matches to no URL
- **THEN** the answer is 422 and no extract job exists

### Requirement: Extract prompt draft
With `schema.prompt`, the job SHALL be stored and set `running` first, then the first three task URLs fetched
politely while the caller waits; the reached pages are role S's samples and no other URL is tried. Once drafted, the
schema, pins and tasks are written in one transaction. No reached sample is a 422, a draft past 120 s a 504, and any
draft failure moves the job to `failed` with no tasks. Sample fetches are not stored.
Refs: SPEC-10 §4.6, D-0684, D-0685.

#### Scenario: No sample reached
- **WHEN** none of the first three URLs is reached
- **THEN** the answer is 422 and the job is `failed`

### Requirement: Budgets and the LLM call limit
A job's `budget.llm_calls` SHALL bound every LLM call charged to it (role S drafts and role C). It defaults to 10 on
`scrape` and `extract`; a batch without `budget` is unbounded; `crawl` and `map` take no `budget` member. Field-name
drafts run before the job and count against no budget. Budget mechanics are in [llm](../llm/spec.md).
Refs: §17, Appendix A #9, D-0676, D-1006, D-1044, D-0926.

#### Scenario: Batch without a budget
- **WHEN** a batch is submitted with no `budget`
- **THEN** its role C calls are not limited

### Requirement: Job summary
`GET /v1/jobs/{id}` SHALL return `{id, kind, status, created_at, started_at, finished_at, counts: {queued, claimed,
done, failed, cancelled}, outcomes: {extracted, partial, unchanged, links_only, blocked, shell, not_found, no_match,
failed}, usage, webhook_url, engine_version, cancel_requested, llm_cost_usd, start_url, url_count}`. `GET
/v1/jobs/{id}/request` returns the stored request as validated, defaults filled in.
Refs: §13.1, SPEC-10 §4.2, D-0745, D-0855.

#### Scenario: Batch summary
- **WHEN** a batch of 5 URLs is read
- **THEN** `url_count` is 5 and `start_url` is null

### Requirement: Jobs list
`GET /v1/jobs?kind&status&cursor&limit` SHALL return `{items, next_cursor}`: every job (learn jobs included, not
scoped to the key) newest first by UUIDv7 id, optionally filtered by `kind` and `status`; `limit` 1–200, default 50;
`next_cursor` is null on the last page. No MCP tool lists jobs.
Refs: §13.1, SPEC-10 §4.2, D-0700, D-0707, D-0708.

#### Scenario: Last page
- **WHEN** the page holds the oldest job
- **THEN** `next_cursor` is null

### Requirement: Cancel
`DELETE /v1/jobs/{id}` SHALL cancel the job's queued tasks at once, set `cancel_requested`, end a queued job
`cancelled` and settle a running one, which stays `running` until its claimed tasks end. A repeat cancel answers 200
unchanged; a `completed` or `failed` job answers 409.
Refs: SPEC-10 §4.2, D-0579, D-0745.

#### Scenario: Cancel a finished job
- **WHEN** `DELETE` targets a `completed` job
- **THEN** the answer is 409 `conflict`

### Requirement: Job results
`GET /v1/jobs/{id}/results?format&cursor&limit` SHALL answer: `json` for a schema job, a `RecordPage` newest first by
record id (the records its tasks stand for through `task_record`, each with `changed_fields`); `json` for a job
without a schema, every task oldest first by task id, with the requested formats built from its capture on read,
only for `extracted` tasks, and `last_error` (why it failed, or `robots` for a robots-blocked task); `json_records`,
`csv_records`, `markdown` as `{format, content, next_cursor}` in the pinned schema's columns (409 without a schema).
Values are serialized unchanged (INV-27).
Refs: §12.2, §13.1, SPEC-10 §4.2, D-0577, D-0578, D-0630, D-0677, D-0745, D-0762.

#### Scenario: Export without a schema
- **WHEN** `format=csv_records` is asked of a markdown-only batch
- **THEN** the answer is 409

### Requirement: Clean JSON values and safe CSV
`format=json_values` SHALL work for every job: one item per task, oldest first, task-id cursor, `{format:
"json_values", items}` with each item `{url, outcome, records, metadata?}`; a clean record is the schema's fields in
name order, each its published value or null, and `records` is always an array (empty for failed, blocked,
`links_only` or schemaless tasks). `include=metadata` is accepted only with `json_values` (else 422) and adds
`metadata` for an `extracted` or `partial` task while its capture is kept. `csv_safe=true` is accepted only with
`csv_records` (else 422) and prefixes `'` to every cell starting with `=`, `+`, `-`, `@`, tab or CR; without it the
export is unchanged.
Refs: §12.2, Appendix A #40, D-0813, D-0814, D-0815, D-0816, D-0879, D-0912.

#### Scenario: Formula cell
- **WHEN** a value `=1+1` is exported with `csv_safe=true`
- **THEN** the cell reads `'=1+1`

### Requirement: Event stream
`GET /v1/jobs/{id}/events` SHALL stream server-sent events from `job_event` in id order, resume after
`Last-Event-ID`, and send a heartbeat when idle 15 s. Kinds: `task_fetched` (method, block_class), `task_extracted`
(outcome, mode, llm_calls), `task_abstained` (fields), `task_failed` `{task_id, url, attempts, last_error}` (only when
a task ends `failed`), `drift_suspended`, `learning_started`, `learning_finished`, `url_gone`, `sitemaps_timed_out`,
`progress` (counts and outcomes, computed by the stream, no id), and the end events `completed`, `failed`,
`cancelled`, last. An event committed late by another process with a smaller id can be skipped by a live client.
Refs: §17, SPEC-10 §4.2, D-0644, D-0645, D-0646, D-0760, D-0873.

#### Scenario: Resume
- **WHEN** a client reconnects with `Last-Event-ID`
- **THEN** it receives only events with a larger id

### Requirement: Completion webhooks
When a job with `webhook_url` ends `completed`, `failed` or `cancelled`, a `webhook_delivery` row SHALL commit with the
job's end; the scheduler POSTs the job summary with `X-CrawlerAI-Signature: sha256=<lowercase hex HMAC-SHA256 of the
exact body>`, keyed with the UTF-8 bytes of the submitting key's hex `webhook_secret`. A 2xx is `delivered`; otherwise
it retries after 30 s × 4^(n−1), `failed` after 3 attempts. Every attempt passes the SSRF guard, redirects are not
followed, `last_error` never holds the URL, a job with no key is never sent unsigned, and delivery failure never
fails the job.
Refs: SPEC-10 §4.2, §4.8, D-0639, D-0640, D-0642, D-0643.

#### Scenario: Redirecting receiver
- **WHEN** the webhook target answers 302
- **THEN** the attempt counts as failed and the redirect is not followed
