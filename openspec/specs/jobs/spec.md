# Jobs Specification

## Purpose

Async work and discovery: queue, worker, scheduler, batch scrape, extract, map, crawl, job endpoints and change
detection for re-submitted runs; shared API rules in [rest-api](../rest-api/spec.md). Rationale: ARCHITECTURE §6-§17
([archived](../../changes/archive/2026-10-16-architecture-rev26/ARCHITECTURE.md)); history: SPEC-01, SPEC-10, SPEC-11.

## Requirements

### Requirement: Queue, leases and retries
Job and task kinds, statuses and outcomes SHALL be those in `db/models.py`; task errors are outcomes, and a job ends
`failed` only when every task failed or the budget ran out before any completed. Workers SHALL claim tasks with `FOR
UPDATE SKIP LOCKED` by priority then id under a 10-minute lease; a fetch `error` is retried to 3 attempts with backoff
30 s × 2^(n−1), every other outcome is terminal, and an SSRF or redirect refusal fails the task at once. Politeness is
per site in the worker. Refs: §6, D-0006, D-0632, D-0705, D-0764.

### Requirement: Worker and scheduler roles
`api`, `worker` and `scheduler` SHALL run from one image; the scheduler runs the periodic entries in its table (lease
release, stalled `map`/`extract` jobs failed, webhook delivery, retention, learning) and creates no jobs: recurrence is
the caller re-submitting a request (schedules are §22, not built). Refs: §19, §22, D-0714, D-0837, D-1006.

### Requirement: Settings pinned at submit (INV-28)
A job SHALL run with the schema document, per-host config versions, calibration and source precedence pinned at submit;
later changes apply only to later jobs, and a pinned config runs even if suspended. (Not built yet: LLM settings are not
pinned, D-0631.) Refs: §17, D-0678, D-0951. Enforced by: mid-job calibration and config change test; active.
#### Scenario: Schema edited mid-job
- **WHEN** a schema is edited while a job that uses it runs
- **THEN** remaining tasks use the pinned document and a later job uses the new one

### Requirement: Task failure isolation (INV-31)
One task's failure SHALL never fail another: each task has its own DB session and transaction, and the worker's shared
browser is relaunched at most once per task. Refs: §17, D-0633, D-0715. Enforced by: batch and killed-browser tests; active.
#### Scenario: Killed browser
- **WHEN** the shared browser is killed during one task
- **THEN** only that task fails, the others complete, and the browser was restarted at most once for it

### Requirement: Batch scrape, extract and budgets
`POST /v1/batch/scrape` (1–1000 URLs) and `POST /v1/extract` SHALL answer with a job id and run one task per URL with
role C. Extract globs expand by one map per origin, `limit` ≤ 1000 counts every task, and globs matching nothing are 422.
Extract alone takes `schema.prompt`, drafted from the first three reached URLs while the caller waits (none reached is
422, past 120 s 504). No request kind has a default budget: a job whose request sets no `budget.llm_calls` is bounded
by `project.llm_call_cap`, read when the job checks, null meaning no cap (see [llm](../llm/spec.md)); a crawl takes the
same optional `budget` as a batch. (Previously: a crawl took no `budget` of its own.) Refs: §13.1, D-0628, D-0676,
D-0681, D-0684, D-1044, D-1121, D-1286.

### Requirement: Job endpoints
`GET /v1/jobs` SHALL page all jobs newest first; `/v1/jobs/{id}` returns the summary, `/request` the validated request,
`DELETE` cancels queued tasks (a finished job is 409); `/results` serves records, page outputs, `json_values` and
exports in the pinned schema's columns, values unchanged (INV-27). A `json_values` clean record holds only published
fields, a money value flat as its amount and a `currency` (beside `price`) or `<field>_currency` code, the first key
that names no schema field, else whole (D-1210).
`csv_safe=true` prefixes `'` to cells starting with `=`, `+`, `-`, `@`, tab or CR. Refs: §12.2, §13.1, Appendix A #40,
#51, D-0577, D-0700, D-0745, D-0813, D-0816, D-1210.
#### Scenario: Formula cell
- **WHEN** a value `=1+1` is exported with `csv_safe=true`
- **THEN** the cell reads `'=1+1`

### Requirement: Event stream and webhooks
`/v1/jobs/{id}/events` SHALL stream `job_event` rows as SSE in id order, resuming after `Last-Event-ID`, with a 15 s
heartbeat and an end event last. A job with `webhook_url` gets its summary POSTed when it ends, signed HMAC-SHA256 with
the key's `webhook_secret`, retried 3 times, through the SSRF guard, no redirects; failure never fails the job.
Refs: §17, D-0639, D-0642, D-0644, D-0760.

### Requirement: Crawl canonical form
Task URLs SHALL be keyed by `normalize/url_key.py`: the url type's canonical form with query pairs stably sorted by name;
no parameter is dropped by name (C4) and directory index files are not folded. Refs: §13.2, D-0649, D-0717, D-0992.
#### Scenario: Query order
- **WHEN** `https://example.com/p?b=2&a=1` is canonicalized
- **THEN** the result is `https://example.com/p?a=1&b=2`, unchanged if canonicalized again

### Requirement: Map, scope and sitemaps
`POST /v1/map` SHALL answer synchronously, unpersisted, with in-scope URLs from sitemaps (`crawl/sitemaps.py`) and the
start page's links, `truncated: true` at 60 s. `include`/`exclude` are request globs, exclude winning, and `crawl/`
names no host (INV-03). The scope host is the start page's final host when related by subdomain (RFC 1034), else the
start host. Refs: §13.1, D-0037, D-0038, D-0650, D-0651, D-0991.

### Requirement: Crawl frontier and page-kind rules
The crawl frontier SHALL seed the start URL and sitemap URLs, add in-scope links and pagination candidates, dedupe by
`(job_id, canonical_url)` and cut at `max_depth` and `limit`. The start task stores where its page is (`job.start_location`,
after the site's redirects to a host of the same site), which gives every later task its scope host, and the page the
start URL redirected to is never added as a task. A task takes its first matching page-kind rule; one with no match is
fetched for links only (`links_only`); a matched page missing a required field is `no_match` with no record. No
automatic page-type gate (§22). (Previously: each task read the start task's capture, and the redirect target was
fetched again as a task.) Refs: §13.2, §23, D-0672, D-0674, D-0677, D-1285.
#### Scenario: Unmatched page
- **WHEN** a crawl with a `detail` rule for `https://example.com/p/*` reaches `https://example.com/about`
- **THEN** that task ends `links_only` and has no record
#### Scenario: Redirected start page
- **WHEN** the crawl of `https://example.com/` is redirected to `https://www.example.com/`, which its pages link to
- **THEN** no task is added for `https://www.example.com/`, and `job.start_location` is that URL

### Requirement: Conditional GET and content fingerprint
Only records tasks of `batch_scrape` and `extract` SHALL use `url_state`, and only with a standing record: the HTTP rung
sends stored validators, and a 304 or an equal SimHash fingerprint (`recurring/state.py`, Hamming 0) ends the task
`unchanged`, linking the standing records, with no extraction or LLM call. A detail page's standing record is the newest
of its entity; a listing page's are the latest versions of the entities the task named by `url_state.standing_task_id`
stood for, valid while that task extracted the page the way it would be now. Replay never reads `url_state` (INV-10).
Known limit: SimHash can miss one-word edits (D-0915, needs-owner). (Previously: a listing page had no standing
record, so it was always extracted.) Refs: §14, D-0637, D-0662, D-0663, D-0952, D-1283.
#### Scenario: Unchanged listing
- **WHEN** a listing page whose text is unchanged is scraped again in a records batch
- **THEN** its task ends `unchanged` with no extraction, and the job lists the rows' records the first run stored

### Requirement: Record versions and change feed
A record's fingerprint SHALL hash its published required fields; an equal fingerprint and schema digest stores no row,
otherwise a new `version` is stored with `changed_fields`. `GET /v1/records?changed_since` (RFC 3339 offset required)
returns records committed at or after it, missing none. Refs: §14, D-0666, D-0668, D-0671, D-0872.
#### Scenario: Price change
- **WHEN** a re-run publishes a new price for an entity
- **THEN** version 2 is stored with `changed_fields: ["price"]`; equal values store no new row

### Requirement: Listing diff and gone URLs
Each `completed` records crawl SHALL mark its rule-matched URLs, and for a listing schema its row URLs
(`resolve.records.row_url_fields`), seen in `url_state`; a URL missing from two consecutive runs of the same crawl gets
`gone_at` and a `url_gone` event, cleared when seen again. The listing is on the host the start page is on. A partial
run (limit hit, empty listing, unreached navigation page, sitemap time cap) counts no misses. (Previously: page URLs
only, on the start URL's host.) Refs: §14, D-0689, D-0691, D-0692, D-0693, D-1284.
