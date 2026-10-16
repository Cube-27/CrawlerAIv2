# Recurring Crawls Specification

## Purpose

Change detection that makes a repeated run of the same request cheap: conditional GET, a SimHash content fingerprint
that skips extraction on unchanged pages, a record fingerprint that creates record versions with `changed_fields`
(the change feed), and a listing diff that marks URLs gone. A recurring crawl is the caller re-submitting a job; core
stores no schedules. Tables are in [persistence-storage](../persistence-storage/spec.md); job results and events in
[jobs](../jobs/spec.md).
Design rationale: [ARCHITECTURE §14](../../design/recurring-and-storage.md). History:
[SPEC-11](../../changes/archive/2026-10-14-spec-11-recurring-crawls/SPEC-11-recurring-crawls.md) and its
[decisions](../../changes/archive/2026-10-14-spec-11-recurring-crawls/decisions.md).

## Requirements

### Requirement: Recurrence is re-submission
A recurring crawl SHALL be the caller re-submitting the same `crawl`, `extract` or `batch/scrape` request; the system
SHALL NOT store schedules or create jobs on a timer in core. Adaptive scheduling, API delta fetches and schedule
storage are §22 candidates, not built.
Refs: §14, §22, Appendix A #13, SPEC-11 §1, §2.

#### Scenario: Scheduler role
- **WHEN** the scheduler runs
- **THEN** it creates no crawl, extract or batch job

### Requirement: Which tasks keep url_state
Only records tasks of `batch_scrape` and `extract` jobs SHALL send validators and store validators or a content
fingerprint; a task without `records` reads and writes no `url_state`. Crawl tasks fetch whole pages with no
validators (link discovery needs the body), and the synchronous scrape uses no validators. Replay MUST NOT consult
`url_state` (INV-10).
Refs: SPEC-11 §4.2, §5, D-0661, D-0678.

#### Scenario: Markdown batch
- **WHEN** a batch without `records` fetches a page
- **THEN** no `etag`, `last_modified` or fingerprint is stored for it

### Requirement: Standing record
A page SHALL count as `unchanged` (by 304 or fingerprint) only when a standing record exists: the entity's newest
record a task linked at or after `url_state.last_changed_at`, under the job's schema with the current `schema_digest`,
by a task whose extraction had the job's mode and config version. Validators are sent only in that case.
Refs: SPEC-11 §4.2, §4.4, D-0662, D-0870, D-0952.

#### Scenario: Schema edited since
- **WHEN** the schema document was edited after the last run
- **THEN** no record stands, no validators are sent, and the page is extracted

### Requirement: Conditional GET
For a URL with a standing record, the HTTP rung SHALL send `If-None-Match: <etag>` and/or `If-Modified-Since:
<last_modified>` on the first request only (never past a redirect; the browser rung ignores validators). An `ok` 304
SHALL end the task `unchanged` with no capture stored, update `url_state.last_seen_at`, and link the standing record
to the task (`task_record`). Validators are stored only from an `ok`, unredirected HTTP 200, replaced as a pair (NULL
when omitted). A 304 for a URL with no stored record is re-fetched once without validators.
Refs: §14 row 1, SPEC-11 §4.2, §4.6, D-0637, D-0638, D-0762.

#### Scenario: Not modified
- **WHEN** the second run's request gets 304
- **THEN** the task outcome is `unchanged` and no bundle is written

### Requirement: Content fingerprint at Hamming 0
For a page fetched whole, the system SHALL compute SimHash-64 over word 3-gram shingles (fixed 64-bit hash) of the
cleaned visible text, after removing nonce tokens defined structurally as ≥ 16 characters of `[A-Za-z0-9_-]`. Only an
equal fingerprint (Hamming 0, `UNCHANGED_BITS = 0`) with a standing record SHALL mean `unchanged`: extraction is
skipped, the capture is still stored, and the standing record is linked. Otherwise extraction runs and
`content_fingerprint` and `last_changed_at` are updated. A text with no words, or a fingerprint error, counts as
changed. Known limit: SimHash can still miss some one-word edits (D-0915, needs-owner).
Refs: §14 row 2, Appendix A #40, SPEC-11 §4.3, §4.6, D-0663, D-0665, D-0915.

#### Scenario: Nonce only
- **WHEN** the only difference is a 32-character session token
- **THEN** the fingerprint is equal and the page is `unchanged`

#### Scenario: New price
- **WHEN** one visible token changes, such as a price
- **THEN** the fingerprint differs on most texts (90 of 100 fixed test seeds) and extraction runs; on the rest the page is skipped (D-0915)

### Requirement: Unchanged pages skip learning counters
An `unchanged` task SHALL end before extraction, so it joins no drift window and does not count toward
`pages_extracted` (which counts only `extracted` and `partial`), and makes no LLM call.
Refs: §8.3, SPEC-11 §4.3, D-0679.

#### Scenario: Re-run with no changes
- **WHEN** a batch is re-run over unchanged pages
- **THEN** every page is `unchanged`, with zero extractions and zero LLM calls

### Requirement: Record fingerprint
Each stored record SHALL carry `fingerprint` = sha256 of canonical JSON (sorted keys, Decimal as string, lists in
order) of its published required fields and required-group members; a field that did not publish is left out, so it
differs from a published `null`. Records also carry `schema_digest`, the sha256 of the canonical schema document they
were extracted with. The fingerprint functions are pure.
Refs: §6, §14 row 3, SPEC-11 §4.4, D-0668, D-0952.

#### Scenario: Same values
- **WHEN** two extractions publish equal required values
- **THEN** their fingerprints are equal

### Requirement: Record versions and changed_fields
On extraction the system SHALL compare with the entity's latest `record` row of (site, schema, entity_key), highest
`version` then newest id, under a per-(site, schema) advisory lock. Equal fingerprint and digest: no row is inserted,
and the task links the existing record, which now stands for the page. Otherwise a row is inserted with `version =
prev + 1`, `supersedes_record_id = prev.id` and `changed_fields` (every schema field whose canonical JSON differs,
including fields that became published or abstained, in schema order; `[]` for version 1). A field the new extraction
did not publish is not carried over. A change in `field_meta` only stores nothing. Versioning does not write
`url_state`.
Refs: §14 row 3, SPEC-11 §4.4, D-0666, D-0667, D-0669, D-0670, D-0763, D-1007.

#### Scenario: Price change
- **WHEN** a re-run publishes a new price for an entity
- **THEN** version 2 is stored with `changed_fields: ["price"]`

#### Scenario: No change
- **WHEN** a re-run publishes the same values
- **THEN** no new record row exists and the task links version 1

### Requirement: Change feed
`GET /v1/records?site&schema_id&changed_since=<ts>` SHALL return records with `created_at >= changed_since`
(inclusive; an RFC 3339 offset is required, else 422), each with `changed_fields`. `record.created_at` is the commit
time, and the query waits for in-flight record commits, so a poller passing the time it last asked misses no record.
Job results include `changed_fields` on each record; an entity re-extracted unchanged stores no record and is not in
the feed again.
Refs: §14, SPEC-11 §4.4, D-0671, D-0872.

#### Scenario: Missing offset
- **WHEN** `changed_since=2026-10-16T10:00:00` has no offset
- **THEN** the answer is 422 `validation`

### Requirement: Runs and listing of a crawl
A run SHALL be one records crawl that ended `completed` (a cancelled or failed job is not a run). The runs of one
crawl are the records crawls with the same `schema_id`, `url`, `include`, `exclude`, `max_depth`, `limit` and
`page_kind_rules`. A run's listing is the canonical URLs of its tasks that a page-kind rule matched, on the start
URL's host, whether or not their pages were reached.
Refs: §14 row 4, SPEC-11 §4.5, D-0689, D-0690, D-0694.

#### Scenario: Different section
- **WHEN** two crawls of one site differ in `include`
- **THEN** neither counts the other's URLs as missing

### Requirement: Listing diff and gone_at
In the transaction that ends the job, before its end event and after locking the site row, each listing URL SHALL be
upserted into `url_state` with `last_seen_at = now`, `missing_runs = 0`, `gone_at = NULL` and `last_seen_job_id`.
Each of the site's rows with `gone_at IS NULL` last seen by an earlier run of the same crawl gets `missing_runs += 1`;
at 2 it gets `gone_at = now` and a `url_gone` job event. A URL seen again after `gone_at` is cleared. New URLs are
queued by the frontier. A row no listing held (`last_seen_job_id` NULL) is never counted missing.
Refs: §14 row 4, SPEC-11 §4.5, D-0692, D-0693, D-0695.

#### Scenario: Missing twice
- **WHEN** a URL is absent from two consecutive runs' listings
- **THEN** its `gone_at` is set and a `url_gone` event is recorded

#### Scenario: Reappears
- **WHEN** a URL with `gone_at` set is in the next run's listing
- **THEN** `gone_at` is NULL and `missing_runs` is 0

### Requirement: Partial runs count no misses
A run that saw only part of its listing SHALL mark its URLs seen but count no misses: one that reached its `limit`,
one with an empty listing, one where a page no rule matched ended `blocked`, `shell` or `failed`, and one whose
sitemap reading hit its time cap (job event `sitemaps_timed_out {url, seeds}`). A navigation page that ended
`not_found` still counts.
Refs: SPEC-11 §4.5, D-0691, D-0873.

#### Scenario: Blocked category page
- **WHEN** a run's unmatched navigation page ends `blocked`
- **THEN** no URL's `missing_runs` increases in that run
