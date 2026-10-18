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
30 s × 2^(n−1) (`core/retry.backoff_delay`, the rule the polite fetch also pauses a host by), a page `blocked` by a
vendor's challenge once, every other outcome is terminal, and an SSRF or redirect refusal fails the task at once.
Politeness is per site in the worker. (Previously: a vendor block was terminal.) Refs: §6, D-0006, D-0632, D-0705,
D-0764.

### Requirement: Worker and scheduler roles
`api`, `worker` and `scheduler` SHALL run from one image; the scheduler runs the periodic entries in its table (lease
release, stalled `map`/`extract` jobs failed, due schedules run, webhook deliveries formed and sent, retention,
learning) and creates jobs only for due schedules. (Previously: it created no jobs; schedules were §22.) Refs: §19,
§22, D-0714, D-0837, D-1006, D-1410.

### Requirement: Settings pinned at submit (INV-28)
A job SHALL run with the schema document, per-host config versions, calibration and source precedence pinned at submit;
later changes apply only to later jobs, and a pinned config runs even if suspended. LLM providers, model ids and
limits are the worker process's settings, not pinned: each usage row records the provider and model of its call.
Refs: §17, D-0678, D-0951, D-1377. Enforced by: mid-job calibration and config change test; active.
(Previously: "Not built yet: LLM settings are not pinned, D-0631.")
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
that names no schema field, else whole (D-1210). A page output carries `fetch` (the scrape answer's summary, every
attempt with its challenge label, from the capture), and a `json_values` item carries it when `include=fetch` is
given; `include` repeats (`metadata`, `fetch`), and a capture without attempts has none (D-1392).
`csv_safe=true` prefixes `'` to cells starting with `=`, `+`, `-`, `@`, tab or CR. Refs: §12.2, §13.1, Appendix A #40,
#51, D-0577, D-0700, D-0745, D-0813, D-0816, D-1210, D-1392.
(Previously: `include` took only `metadata`; no `fetch` member.)
#### Scenario: Formula cell
- **WHEN** a value `=1+1` is exported with `csv_safe=true`
- **THEN** the cell reads `'=1+1`

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
`(job_id, canonical_url)` and by the canonical final URL each fetched task stores (`url_task.final_url`), and cut at
`max_depth` and `limit`. The start task stores where its page is (`job.start_location`, after the site's redirects to a
host of the same site), which gives every later task its scope host; once a task's final URL is stored, a URL it was
redirected to is not added as a task (one queued before then stays a task). A task takes its first matching page-kind rule; one with no match is fetched for links only (`links_only`); a
matched page missing a required field is `no_match` with no record. No automatic page-type gate (§22). The scope is the
start host, plus its subdomains with `allow_subdomains` and any host with `allow_external`, less `exclude` and within
`include` when given. (Previously: only the start page's redirect target was kept out; subdomains needed an `include`.)
Refs: §13.2, §23, D-0672, D-0674, D-0677, D-1285, D-1382, D-1441.
#### Scenario: Unmatched page
- **WHEN** a crawl with a `detail` rule for `https://example.com/p/*` reaches `https://example.com/about`
- **THEN** that task ends `links_only` and has no record
#### Scenario: Redirected page
- **WHEN** a crawl's task for `https://example.com/p/old` is redirected to `https://example.com/p/new`, which a page
  found later links to
- **THEN** no task is added for `https://example.com/p/new`

### Requirement: Conditional GET and content fingerprint
Only records tasks of `batch_scrape` and `extract` SHALL use `url_state`, and only with a standing record: the HTTP rung
sends stored validators, and a 304 or an equal content digest (BLAKE2b of the visible words, nonce-like tokens left out,
`recurring/simhash.py`; for a listing without words, of the URLs it links to, in order; the SimHash stored beside it
only reports how far a change moved) ends the task `unchanged`, linking the standing records, with no extraction or LLM
call; a listing its recipe served in further pages is extracted again, since only its first page is fingerprinted. A detail page's standing record is the newest of its entity; a listing page's are the latest versions of the
entities the task named by `url_state.standing_task_id` stood for, valid while that task extracted the page the way it
would be now. Replay never reads `url_state` (INV-10). (Previously: a listing without words was always extracted.)
Refs: §14, D-0637, D-0662, D-0663, D-0952, D-1283, D-1340, D-1383.
#### Scenario: Unchanged listing
- **WHEN** a listing page whose text is unchanged is scraped again in a records batch
- **THEN** its task ends `unchanged` with no extraction, and the job lists the rows' records the first run stored
#### Scenario: One-word edit
- **WHEN** a page's visible text changes by one word and its SimHash stays equal
- **THEN** its content digest differs and the page is extracted again
#### Scenario: Listing without words
- **WHEN** a listing of image links with no visible words is scraped again with the same links, then with one more
- **THEN** the second run is `unchanged` and the third is extracted

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

### Requirement: Crawl strategy and best-first scoring
A crawl SHALL take `strategy` `bfs` (default), `dfs` or `best_first`; `query` and `keywords` are accepted only with
`best_first`. A scored crawl stores each task's score (`url_task.score`, 0 to 1) and `claim_tasks` SHALL lease by
`priority`, then score descending (none last), then id. Best first scores a link by BM25 of its anchor text and URL path
against the query, the holding page's relevance, the sitemap `priority` and depth (`crawl/scoring.py`), with no
vocabulary list. A scored crawl SHALL fetch at most `limit` pages: it queues up to five times as many candidates,
keeps the best when full, skips a leased task once the finished and higher-ranked leased pages reach `limit`, and
cancels the queued rest when the last page is spent. `max_pages` is an alias of `limit`. Refs: D-1440, D-1446.
#### Scenario: Best first spends the limit on matches
- **WHEN** a `best_first` crawl with `query` "rate limits" and `limit` 3 starts on a page linking `/guides/rate-limits`,
  `/blog/news` and `/about`, and the guide links `/guides/rate-limits/retry`
- **THEN** the pages fetched are the start page, the guide and its retry page, and the other tasks end `cancelled`

### Requirement: Exports and llms.txt of a job
A job's records SHALL export as `jsonl`, `xlsx` and `parquet` from the columns of `csv_records`, with `csv_safe`
applying to every spreadsheet cell; `llms.txt` of a crawl, batch or map job SHALL be an H1 title, a blockquote summary
and sections of links with descriptions, and `llms-full.txt` the pages' markdown under the same opening. `map` takes
`llms_txt` to answer the file of the URLs it found. Refs: D-1426, D-1427.
#### Scenario: Job without records
- **WHEN** a job without a schema is exported as `xlsx`
- **THEN** it is refused with 409

### Requirement: Recurring schedules (INV-46)
A schedule SHALL hold the request of a batch scrape, crawl or extract (a scrape stored as the batch of its URL, a
`records` schema by id), checked as its submission is when created, and run at each time of a 5-field cron expression
in an IANA zone or every `interval_s` of 60 s to 2³¹−1 s (`core/cadence.py`, `services/schedules.py`). A due run's job is stored in
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
