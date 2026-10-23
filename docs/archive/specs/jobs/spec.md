# Jobs Specification

## Purpose

Async work and discovery: queue, worker, scheduler, batch scrape, extract, map, crawl, job endpoints and change
detection for re-submitted runs; shared API rules in [rest-api](../rest-api/spec.md).

## Requirements

### Requirement: Queue, leases and retries
Job and task kinds, statuses and outcomes SHALL be those in `db/models.py`; task errors are outcomes, and a job ends
`failed` only when every task failed or the budget ran out before any completed. Workers SHALL claim tasks with `FOR
UPDATE SKIP LOCKED` by priority, then fairness between jobs, then id ("Crawl strategy and best-first scoring") under a 10-minute lease; a fetch `error` is retried to 3 attempts with backoff
30 s × 2^(n−1) (`core/retry.backoff_delay`, the rule the polite fetch also pauses a host by), a page `blocked` by a
vendor's challenge once (not when the browser rung met that challenge itself) and a fetch a 429 kept out once (never after the fetch tried it in the browser, acquisition spec), every other outcome is terminal, and an SSRF or redirect refusal fails the task at once.
Politeness is per site, shared by every worker. A worker SHALL run up to `TASK_SLOTS` (4: twice its browser's
`BROWSER_CONTEXTS`) tasks at once, claiming only for a free slot, and SHALL end a task still running at `TASK_DEADLINE` (3 min, inside the lease): cancelled, recorded `failed`
with outcome `timeout` (a `timeout` error), not retried, so its job moves on; work that outlives its cancellation has its database session
ended, and the failure is recorded before the lease expires, so the task is never claimed again beside it; a database error while recording it leaves the task to its lease's expiry, which treats it like any lost lease, requeued after backoff or failed on its last attempt (the old claim's writes then fail its lease fence). Refs: §6,
D-0006, D-0632, D-0705, D-0764, owner plan 2026-10-19
(crawl speed).
#### Scenario: A page that never finishes
- **WHEN** a task's work is still running at its deadline
- **THEN** it is recorded `failed` with outcome `timeout` and the job's other tasks complete

### Requirement: Crawl location pinned per job
A job SHALL fetch every page from one location: the request's `fetch.proxy_pool`, else none (direct). It is stored in
the job's request, which its workers read, and the job's egress country and basis (`job.egress_country`,
`egress_basis`, [acquisition](../acquisition/spec.md)) are pinned with it at submit and copied to each record the job
stores; a site that prices by the visitor's country (a `/en-in/` path) is then read from one place throughout. A scrape
pins the same way for its one URL. Refs: owner plan 2026-10-19 P8.
#### Scenario: Batch over two sites
- **WHEN** a batch names proxy pool `a` and its URLs are on two sites
- **THEN** every page of the job is fetched through `a`

### Requirement: Worker and scheduler roles
`api`, `worker` and `scheduler` SHALL run from one image; the scheduler runs the periodic entries in its table (lease
release, stalled `map`/`extract` jobs failed, due schedules run, webhook deliveries formed and sent, retention,
learning) and creates jobs only for due schedules. Refs: §19,
§22, D-0714, D-0837, D-1006, D-1410.

### Requirement: Settings pinned at submit (INV-28)
A job SHALL run with the schema document, per-host config versions, calibration and source precedence pinned at submit;
later changes apply only to later jobs, and a pinned config runs even if suspended. LLM providers, model ids and
limits are the worker process's settings, not pinned: each usage row records the provider and model of its call.
Refs: §17, D-0678, D-0951, D-1377. Enforced by: mid-job calibration and config change test; active.
#### Scenario: Schema edited mid-job
- **WHEN** a schema is edited while a job that uses it runs
- **THEN** remaining tasks use the pinned document and a later job uses the new one

### Requirement: Task failure isolation (INV-31)
One task's failure SHALL never fail another: each task has its own DB session and transaction, and the worker's shared
browser is relaunched at most once per task. The task's fetch runs before its transaction opens; the site's row, its
robots.txt snapshot, its adapter declines and its domain memory are read and written there, and the memory learned from
the extraction beside the transaction, each in a short transaction of its own, so no task holds a site's rows while it
fetches or extracts and the tasks of one site run side by side. Everything else the task writes, its capture, records
and usage included, commits with its result in its transaction. Refs: §17, D-0633,
D-0715, D-1786. Enforced by: batch, killed-browser and same-site tests; active.
#### Scenario: Killed browser
- **WHEN** the shared browser is killed during one task
- **THEN** only that task fails, the others complete, and the browser was restarted at most once for it

### Requirement: Batch scrape, extract and budgets
`POST /v1/batch/scrape` (1–1000 URLs) and `POST /v1/extract` SHALL answer with a job id and run one task per URL with
role C. Extract globs expand by one map per origin, `limit` ≤ 1000 counts every task, and globs matching nothing are 422.
Extract alone takes `schema.prompt`, drafted from the first three reached URLs while the caller waits (none reached is
422, past 120 s 504). No request kind has a default budget: a job whose request sets no `budget.llm_calls` is bounded
by `project.llm_call_cap`, read when the job checks, null meaning no cap (see [llm](../llm/spec.md)); a crawl takes the
same optional `budget` as a batch. Refs: §13.1, D-0628, D-0676,
D-0681, D-0684, D-1044, D-1121, D-1286.

### Requirement: Page outcomes
A task SHALL end with one outcome, from evidence the fetch and the resolution already hold (no per-site rule): the data
outcomes `extracted`, `partial`, `no_match` and `links_only`; the outcomes of a page not served, which are
the capture's block class (`blocked`, with reason `challenge: <vendor>` when a vendor's challenge says so; `shell`;
`not_found`; `auth_wall`; `soft_404` and `geo_redirect`, from the final URL against the one asked
([acquisition](../acquisition/spec.md)); `redirected_to_listing`; `unsupported_media`, a 2xx answer that is no HTML
document), and `geo_blocked`, a `blocked` page whose kept attempt is a 451 (challenge label `legal`, RFC 7725), which
is not retried as a vendor's block; and, for a `failed` task, `timeout` when the fetch's
kept attempt got no answer in time or the task ran past `TASK_DEADLINE`, else `failed`. A served page that states its
item is not for sale and gives no price is `partial` with `price` `missing`, reason `out_of_stock`
([resolution](../resolution/spec.md)). `no_match` is a page that states no entity of the schema (no needed field has a
candidate from the page) or, crawl-discovered, an incomplete one; an extraction miss on a caller-supplied page (a
rejected candidate, an unreadable-content signal) is `partial` (resolution, "Incomplete pages"). Refs: owner plan
2026-10-19 P9.
#### Scenario: Fetch that timed out
- **WHEN** a fetch's kept attempt is an `error` with reason `timeout`
- **THEN** the task ends `failed` with outcome `timeout`, not `failed`
#### Scenario: Page withheld for legal reasons
- **WHEN** a page's fetch is refused with a 451
- **THEN** the task ends `done` with outcome `geo_blocked` and no records

### Requirement: Job outcome summary
`GET /v1/jobs/{id}/outcomes` and `crawlerai jobs summary <id>` SHALL answer, for one job, its pages counted per outcome
and the fields of the records its tasks stand for counted per status (`published`, `missing`, `conflict`, `abstained`,
`interaction_required`) with the reasons of the unpublished ones, and per field the records of pages fetched over HTTP
with no browser attempt that left it `missing` with reason `no_candidates` (`missing_unrendered`), with the hint
`render.mode: locate` when there are any, or a listing page fetched over HTTP with no browser attempt listed nothing
(`partial` with no record), and the job's `render.mode` is `off` (never an XHR, selector or blob name), and
per detect-and-report signal (`signals`: `websocket`, `eventsource`, `wasm`, `grpc_web`, `flutter`, `blazor_wasm`,
`live_view`, `obfuscated_text`, `closed_shadow_root`, `turbo_stream`, `gatsby_page_data`, `amp_alternate`) the pages an
extraction raised it on (its `signal:<name>` diagnostic; a browser capture records its resources counted by type, never
a URL), names and counts only, a signal no page raised left out; a signal changes no fetch and no extraction. All are
from stored results (`url_task.outcome`, `record.field_meta`, `capture`, `extraction.diagnostics`), with no table of
its own. `crawlerai jobs reextract <id>` SHALL extract the job's stored captures again with the current engine and each site's active config,
reading only the object store and the database (no network, no LLM, nothing stored; `services.captures.replay`, whose
`extract_page` the worker and the evaluation harness run), and print those field counts beside the stored ones.
Refs: owner plan 2026-10-19 P9; architecture v3 a.5, (b)
"report" rows, PR 8.
#### Scenario: Summary of a job
- **WHEN** a job's pages ended `extracted`, `soft_404` and `timeout`, and its records hold fields in three statuses
- **THEN** the answer counts one page of each outcome and every field under its status, with the reasons of the unpublished
#### Scenario: Fields HTTP pages did not carry
- **WHEN** a job with `render.mode` `off` stores two records of HTTP pages and one of a rendered page, each leaving
  `colour` `missing/no_candidates`
- **THEN** `missing_unrendered` is `{"colour": 2}` and the hint is `render.mode: locate`
#### Scenario: A listing that listed nothing over HTTP
- **WHEN** a job with `render.mode` `off` holds one listing page fetched over HTTP that listed nothing
- **THEN** `missing_unrendered` is `{}` and the hint is `render.mode: locate`
#### Scenario: Signal counts
- **WHEN** two of a job's pages opened a WebSocket and one of them also links an AMP alternate
- **THEN** `signals` is `{"websocket": 2, "amp_alternate": 1}`, with no URL, and both pages were fetched and extracted as
  any other

### Requirement: Job endpoints
`GET /v1/jobs` SHALL page all jobs newest first; `/v1/jobs/{id}` returns the summary, `/outcomes` the job's outcomes, `/request` the validated request,
`DELETE` cancels queued tasks (a finished job is 409); `/results` serves records, page outputs, `json_values` and
exports in the pinned schema's columns, values unchanged in their served form (normalization spec; INV-27). A `json_values` clean record holds only published
fields, a money value flat as its amount and a `currency` (beside `price`) or `<field>_currency` code, the first key
that names no schema field, else whole (D-1210). A page output carries `fetch` (the scrape answer's summary, every
attempt with its challenge label, from the capture), and a `json_values` item carries it when `include=fetch` is
given; `include` repeats (`metadata`, `fetch`), and a capture without attempts has none (D-1392).
`csv_safe=true` prefixes `'` to cells starting with `=`, `+`, `-`, `@`, tab or CR. Refs: §12.2, §13.1, Appendix A #40,
#51, D-0577, D-0700, D-0745, D-0813, D-0816, D-1210, D-1392.
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
events 30 days after creation, never a pending one (`scheduler/retention.py`). Refs: §17, D-0639, D-0642, D-0644,
D-0760, D-1414,
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
`include` when given.
Refs: §13.2, §23, D-0672, D-0674, D-0677, D-1285, D-1382, D-1441.
#### Scenario: Unmatched page
- **WHEN** a crawl with a `detail` rule for `https://example.com/p/*` reaches `https://example.com/about`
- **THEN** that task ends `links_only` and has no record
#### Scenario: Redirected page
- **WHEN** a crawl's task for `https://example.com/p/old` is redirected to `https://example.com/p/new`, which a page
  found later links to
- **THEN** no task is added for `https://example.com/p/new`

### Requirement: Fresh extraction
Every records task SHALL fetch its page whole and extract it, a recurring run's too: no conditional request is sent and
no record stored by an earlier task stands for the page (owner 2026-10-21: learning keeps selectors, recipes and
cookies, never values). What changed is told per record ("Record versions and change feed", "Page delta"). Replay
never reads `url_state` (INV-10). Refs: §14, D-0637, D-0662, D-0663, D-0952, D-1340.
#### Scenario: Re-run of an unchanged page
- **WHEN** a page whose text is unchanged is scraped again in a records batch
- **THEN** it is fetched whole and extracted, and its record holds what this extraction published

### Requirement: Record versions and change feed
A record's fingerprint SHALL hash its published values; a record equal to its entity's latest version in fingerprint,
field metadata, completeness and schema digest stores no row and the task links that version, otherwise a new `version`
is stored with `changed_fields`. `GET /v1/records?changed_since` (RFC 3339 offset required)
returns records committed at or after it, missing none. Refs: §14, D-0666, D-0668, D-0671, D-0872.
#### Scenario: Price change
- **WHEN** a re-run publishes a new price for an entity
- **THEN** version 2 is stored with `changed_fields: ["price"]`; equal values store no new row

### Requirement: Page delta
Each record a records task stands for SHALL carry its delta against the previous record of the same entity under the
same schema on the site (`task_record.delta`, set as the task stores it): `new` when the entity had none, `changed` when
a field of the schema published another value, with each changed field's previous and new value as published, else `same`.
A job's records answer it as `delta` (`kind`, `changes` of `field`, `previous`, `value`; null when not listed by job),
the job's outcomes count it (`records`: `new`, `changed`, `same`, each record once, at the first task that stood for
it), and its exports add `_delta` and `_previous` (the changed fields' previous values by name) after the status
columns. Refs: owner 2026-10-21 (page delta after fresh extraction).
#### Scenario: Re-run with a new price
- **WHEN** an entity was stored at price 10 and a later job extracts it at 12, its other values equal
- **THEN** that job's record has delta `changed` with `{"field": "price", "previous": 10, "value": 12}`, and a third
  run that still reads 12 answers `same`

### Requirement: Listing diff and gone URLs
Each `completed` records crawl SHALL mark its rule-matched URLs, and for a listing schema its row URLs
(`collect.schema_org_map.item_url_fields`), seen in `url_state`; a URL missing from two consecutive runs of the same crawl gets
`gone_at` and a `url_gone` event, cleared when seen again. The listing is on the host the start page is on. A partial
run (limit hit, empty listing, unreached navigation page, sitemap time cap) counts no misses. Refs: §14, D-0689, D-0691,
D-0692, D-0693, D-1284.

### Requirement: Request context and actions per page
Batch, crawl and extract jobs SHALL fetch every page with the request's `fetch` context, `wait_for` and `actions`
(D-1439); the job keeps the secret values in `job.request` for its workers while it runs, and when it ends its header
and cookie values are replaced by `**********`, names kept (D-1510); `GET /v1/jobs/{id}/request` answers them as
`**********`. A task's `fetch.cache` means what a scrape's does ([rest-api](../rest-api/spec.md), `POST /v1/scrape`)
with `max_age` 0, since a job has no `max_age`: one page run serves both (`services/page_run.py`). `default` and
`bypass` fetch; `only` serves each task from the latest `ok` capture of its URL made with the same actions and context,
names and value digest ([acquisition](../acquisition/spec.md), "Caller request context"), or fails the task
`not_cached`. Refs: owner delegation 2026-10-17, D-1432, D-1435, D-1439,
D-1510.
#### Scenario: Stored request
- **WHEN** a batch is submitted with cookie `sid` and its request is read back
- **THEN** the answer's `fetch.cookies.sid` is `**********`
#### Scenario: Ended job
- **WHEN** a job submitted with header `X-Token: abc` ends
- **THEN** `job.request` holds `**********` for `X-Token`, and a running job still holds `abc`

### Requirement: Crawl strategy and best-first scoring
A crawl SHALL take `strategy` `bfs` (default), `dfs` or `best_first`; `query` and `keywords` are accepted only with
`best_first`. A scored crawl stores each task's score (`url_task.score`, 0 to 1) and `claim_tasks` SHALL lease by
`priority`, then round robin between jobs (each job's best task first, jobs with fewer leased tasks first), then id; score (descending, none last) orders only
within a job, so a scored crawl does not lease ahead of other jobs' tasks. Best first scores a link by BM25 of its
anchor text and URL path
against the query, the holding page's relevance, the sitemap `priority` and depth (`crawl/scoring.py`), with no
vocabulary list. A scored crawl SHALL fetch at most `limit` pages: it queues up to five times as many candidates,
keeps the best when full, skips a leased task once the finished and higher-ranked leased pages reach `limit`, and
cancels the queued rest when the last page is spent. `max_pages` is an alias of `limit`. Refs: D-1440, D-1446, D-1593.
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
schedule keeps no secret value: a request with `fetch.headers` or `fetch.cookies` is refused.
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
