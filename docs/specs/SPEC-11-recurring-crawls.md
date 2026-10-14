# SPEC-11 — Recurring crawls: conditional GET, fingerprints, record versions, listing diff

Layer: L4. Architecture refs: §14 (all), §6 (`url_state`, `record`), G6, Appendix A #13, §21 L4.

## 1. Summary

Change detection from day one (Appendix A #13) so repeat crawls of the same sites are cheap (G6): conditional
GET, a content fingerprint that skips extraction on unchanged pages, a record fingerprint that creates versions
with `changed_fields`, and a listing diff that queues new URLs and sets `gone_at` on disappeared ones. A
recurring crawl is the caller re-submitting the same `crawl`/`extract` request (§14); the mechanisms make the
repeat cheap. No schedule storage exists in core (§22 candidate).

## 2. Scope

Core:
- `url_state` maintenance; `If-None-Match`/`If-Modified-Since`; `unchanged` outcome.
- SimHash-64 content fingerprint over visible text; Hamming ≤ 3 → `unchanged`, extraction skipped.
- Record fingerprint over normalized required fields; versioned records with `changed_fields`.
- Listing diff: new URLs queued; missing for 2 runs → `gone_at` set.
- Change feed through `/v1/records?changed_since` and job results carrying `changed_fields`.

Out of scope (§22):
- Adaptive recrawl scheduling; API delta fetches; any cron/schedule table (the scheduler role does not create
  jobs in core).
- Change detection beyond the four mechanisms in §14.

## 3. Dependencies

- SPEC-01 (`url_state`, record version columns), SPEC-02 (fetch), SPEC-05 (records, visible text), SPEC-10
  (crawl jobs, results), SPEC-08 (drift windows must ignore unchanged pages).

## 4. Design

### 4.1 Modules

- `crawlerai.recurring.conditional` — build/consume validators.
- `crawlerai.recurring.simhash` — `simhash64(text) -> int`, `hamming(a, b) -> int` (own implementation, ~40 lines;
  no dependency of unknown license).
- `crawlerai.recurring.record_fp` — `record_fingerprint(record_data, schema) -> str`.
- `crawlerai.recurring.listing_diff` — per-run diff against `url_state`.
- `crawlerai.recurring.state` — `url_state` upsert helpers.
- Worker handler changes in `crawlerai.worker.handlers.crawl` and `scrape`.

### 4.2 Conditional GET (§14 row 1)

- Before fetching a URL with an existing `url_state` row, send `If-None-Match: <etag>` and/or
  `If-Modified-Since: <last_modified>` (HTTP rung only; the browser rung ignores validators).
- 304 → task outcome `unchanged`; no capture is stored; `url_state.last_seen_at` updated; the previous record
  is referenced by the task (`url_task.capture_id` stays null; results for the task point at the latest record
  version — plumbing: `url_task.record_id`).
- 200 → store the new `etag`/`last_modified`.

### 4.3 Content fingerprint (§14 row 2)

- Input: the cleaned visible text (SPEC-05 4.4) with scripts/styles already removed; additionally strip tokens
  that look like nonces — defined structurally as tokens of ≥ 16 characters consisting only of `[A-Za-z0-9_-]`
  (no vocabulary; structural).
- SimHash-64 over word 3-gram shingles hashed with a fixed 64-bit hash (e.g. `blake2b(digest_size=8)`).
- If `hamming(new, url_state.content_fingerprint) <= 3` → outcome `unchanged`, extraction skipped, the capture
  is still stored (replayability; it expires normally). The threshold 3 is a starting point to confirm on dev
  (preamble).
- Otherwise extraction runs; `content_fingerprint` and `last_changed_at` are updated.
- Unchanged pages do not count toward drift windows (SPEC-08 4.9) or `pages_extracted` (§8.3 counts only
  `extracted` and `partial`).

### 4.4 Record fingerprint and versions (§14 row 3)

- `record_fingerprint = sha256(canonical_json({field: normalized value for required fields and groups}))`
  (sorted keys, Decimal as string, lists in order).
- On extraction, compare with `url_state.record_fingerprint` for the same (site, entity_key, schema):
  - equal → the new record row is not inserted; the task references the existing latest record (`version`
    unchanged);
  - different → insert with `version = prev.version + 1`, `supersedes_record_id = prev.id`, `changed_fields =
    [fields whose normalized values differ, including fields that became published or abstained]`;
    `url_state.record_fingerprint` and `last_changed_at` updated.
- `GET /v1/records?site&schema_id&changed_since=<ts>` returns records with `version > 1` or new entities since
  the timestamp, each with `changed_fields`; job results include `changed_fields` on each record.

### 4.5 Listing diff (§14 row 4)

- A "run" = one records crawl that completed. The runs of one crawl are the records crawls with the same scope
  (start URL, `include`, `exclude`, `max_depth`, `limit`, `page_kind_rules`) and schema: a recurring crawl is the
  caller re-submitting the request (§14).
- A run's listing is the URLs of its tasks that a page-kind rule matched, on the start URL's host, whether or not
  their pages were reached. (No job stores listing records, so their row URLs cannot be the listing.)
- At job completion, in the transaction that ends the job and before its end event, each URL of the listing is
  upserted into `url_state` with `last_seen_at = now`, `missing_runs = 0`, `gone_at = NULL` and `last_seen_job_id`
  = the job (plumbing). For the site's rows with `gone_at IS NULL` last seen by an earlier run of the same crawl:
  `missing_runs += 1`; `missing_runs >= 2` → `gone_at = now` and a `job_event(kind='url_gone', url)`.
- A run that saw part of its listing only counts no misses: one that reached its `limit`, one with an empty
  listing, and one with a page no rule matched that ended `blocked`, `shell` or `failed` (its links were not read).
  A navigation page that is `not_found` still counts.
- New URLs are queued as tasks by the SPEC-10 frontier, which takes every URL a run finds in scope.
- A URL seen again after `gone_at` was set gets `gone_at = NULL` and `missing_runs = 0`.

### 4.6 Error handling

A 304 for a URL with no stored record (state drift) is treated as a 200 by re-fetching without validators once.
Fingerprint computation errors fall through to normal extraction (never skip on error).

## 5. Invariants

INV-10 (fingerprint functions are pure; property-tested), INV-22, INV-11 (unchanged pages carry no new
records). No new C-rule exposure; `recurring/` contains no site literals (INV-03).

## 6. Testing strategy

- SimHash: property tests — identical text → identical hash; a single-word change in a 500-word text → Hamming
  ≤ 3; a different text → Hamming > 3 with high probability (fixed seeds); nonce stripping by the structural
  rule.
- Conditional GET: local server with ETag support; second fetch yields `unchanged` and no bundle.
- Record versions: synthetic extractions with a changed price → version 2 with `changed_fields=["price"]`;
  unchanged → no new row.
- Listing diff: three simulated runs; a URL missing twice gets `gone_at`; reappearance clears it.
- Dev replay: unaffected (replay does not consult `url_state`).

## 7. Acceptance criteria (§21 L4 done-when)

- Re-running a crawl over the local replay server with unchanged pages produces `unchanged` outcomes for every
  page, zero extractions, zero LLM calls.
- A changed price yields a new record version carrying `changed_fields: ["price"]`.
- A URL absent from two consecutive listing runs has `gone_at` set.

## 8. PR plan

| # | Title | Scope | Checks | Done when |
|---|---|---|---|---|
| 1 | `url_state` helpers + conditional GET | `recurring/state,conditional`, http rung | unit (local server) | 304 → unchanged. |
| 2 | SimHash + content fingerprint skip | `recurring/simhash`, handler wiring | property | Unchanged skip. |
| 3 | Record fingerprint + versions + `changed_since` | `recurring/record_fp`, records service | unit | Versions + feed. |
| 4 | Listing diff + `gone_at` | `recurring/listing_diff`, job completion hook | unit | Two-run rule. |
| 5 | Drift/`pages_extracted` exclusions for unchanged pages | SPEC-08 hooks | unit | Windows unaffected. |

## 9. Open issues

- **Review finding (how a crawl recurs).** Resolved in ARCHITECTURE rev 5 §14: a recurring crawl is the caller
  re-submitting a job; a scheduler is not core. Schedule storage is the §22 candidate "Recurring schedule
  storage".
- **Review finding (`gone` and record versions lack columns in §6).** Resolved in ARCHITECTURE rev 5 §6
  (`url_state.missing_runs`, `gone_at`; `record.version`, `changed_fields`). `supersedes_record_id`,
  `url_task.record_id` and `url_state.last_seen_job_id` remain plumbing.
- **Nonce stripping rule** (≥ 16-char opaque tokens) is structural but unmeasured; confirm on dev that
  boilerplate-only changes are skipped.
