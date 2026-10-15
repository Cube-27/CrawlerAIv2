# SPEC-11 decisions

Decisions for [SPEC-11 — Recurring crawls: conditional GET, fingerprints, record versions, listing diff](../specs/SPEC-11-recurring-crawls.md).
Template, statuses and rules: [DECISIONS.md](../DECISIONS.md).

### D-0637 — Validators reach the HTTP rung through `Rungs.conditional`
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 1 (#131) · Status: decided
- Decision: `acquire(..., validators=)` calls `Rungs.conditional` (a `ConditionalRung` that `fetch_http` satisfies) instead of `Rungs.http`. Every other rung keeps `(url, policy)`. Validators go on the first request only, never past a redirect.
- Alternatives: `Rungs.http` taking validators, which changes about 10 test stubs; validators on `FetchPolicy`, which is per-request policy recorded in every manifest.
- Why: SPEC-11 §4.2 sends validators on the HTTP rung only, and the binding follows the `recipe` pattern. Every `Rungs` that needs conditional GET must set `conditional`; the worker's `Rungs` in `cli.py` is wired in SPEC-11 PR 2.
- Reversible: yes

### D-0638 — Validators are stored from `ok`, unredirected HTTP 200 responses only, and replaced as a pair
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 1 (#131) · Status: decided
- Decision: `record_fetch` writes `etag` and `last_modified` only from an HTTP 200 that is `ok` and has `final_url == url`. Each is replaced by the value received, or NULL when the response omits it. A 304 is `unchanged` only when the fetch is `ok`.
- Alternatives: Also store them from browser navigations; keep an old validator when a new 200 omits it.
- Why: Only the HTTP rung sends validators. API and redirected responses describe another resource. A page not fetched whole must not later be `unchanged` (RFC 9110 §8.8).
- Reversible: yes

### D-0661 — Only records tasks read or write `url_state`
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 2 (#135) · Status: decided
- Decision: A `batch_scrape` task without `records` sends no validators and stores no validators or fingerprint.
- Alternatives: every task maintains `url_state`.
- Why: If validators or a fingerprint are stored for content no record was made from, a later records task would take a 304 or a near-equal fingerprint as `unchanged` and let a stale record stand. A job without records has no record to skip extraction for.
- Reversible: yes.

### D-0662 — A record stands for an unchanged page only if it is of the same schema version and config, and is not older than the last change
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 2 (#135) · Status: decided
- Decision: A page is `unchanged` (by 304 or by fingerprint) only when `standing_record` finds a record that meets all of these:
  - it belongs to the page's entity (D-0488) under the job's schema version;
  - it was extracted in the same mode with the same config version;
  - its `created_at` is no earlier than `url_state.last_changed_at`.
  Validators are sent only in that case. They are stored only together with a stored record, or when the task ends `unchanged`.
- Alternatives: `url_state` alone decides. Then a new schema version, a new config, or a change first seen by another schema's task would be skipped against a record that does not describe the page.
- Why: `url_state` is keyed per URL (ARCHITECTURE §6), but records are per schema version and config. §4.6 says to fetch again when no record stands. INV-28 says a job extracts with what it pinned.
- Reversible: yes.

### D-0663 — `simhash64` declines a text without words
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 2 (#135) · Status: decided
- Decision: `simhash64` returns `None` when no words remain after nonce stripping. The page then counts as changed and is extracted. If computing the fingerprint raises, the error is logged and the page is extracted (§4.6).
- Alternatives: hash to 0, which would make every wordless page `unchanged` against every other wordless page.
- Why: A page with no visible words gives the fingerprint nothing to compare, and its structured data can still change. This declines rather than guesses (C7).
- Reversible: yes.

### D-0664 — `url_task.record_id` is deferred to PR 3
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 2 (#135) · Status: decided
- Decision: An `unchanged` task does not yet point at its standing record. A job's records results list only the records that job made. The `url_task.record_id` plumbing (§4.2) comes with the records service in PR 3, where an equal record fingerprint also needs a task to reference an existing record.
- Alternatives: add the column (migration 0015) here, with no reader until PR 3.
- Why: Its only reader is the records results, which PR 3 changes. A column with no reader is speculative.
- Reversible: yes.

### D-0666 — Record versions compare with the entity's latest `record` row
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 3 (#136) · Status: decided
- Decision: A new record is compared with the latest `record` row of (site, schema_id, entity_key): the highest `version`, then the newest id. It is compared with that row's stored `record.fingerprint`, not with `url_state.record_fingerprint`. Records stored before PR 3 have no fingerprint, so the next extraction of each supersedes it.
- Alternatives: Compare with `url_state.record_fingerprint`.
- Why: `url_state` is keyed (site, URL), has no schema, and holds one fingerprint per URL, while a listing has one entity per row. §4.4 compares per (site, entity, schema), and that key already has an index.
- Reversible: yes

### D-0667 — Record versions do not write `url_state`
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 3 (#136) · Status: decided
- Decision: `store_records` writes neither `url_state.record_fingerprint` nor `last_changed_at`. The column `record_fingerprint` stays unused; versions compare with `record.fingerprint` (D-0666).
- Alternatives: UPDATE both on a detail page that adds a version (as first built in #136).
- Why: `url_state` is per URL, and `last_changed_at` is when the page's content last changed (#135, D-0662). When a new schema version stored its first record, that write made the original schema's record stop standing, and `test_recurring_scrape` caught it after the rebase onto #135. §4.4's "`url_state.record_fingerprint` ... updated" needs a clarifying spec edit.
- Reversible: yes

### D-0668 — What the record fingerprint and `changed_fields` cover
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 3 (#136) · Status: decided
- Decision: The fingerprint is sha256 over canonical JSON of the required fields and required-group members that published. A field that did not publish is left out, so it differs from a published `null`. `changed_fields` covers every schema field, in schema order, and compares canonical JSON, so `true` ≠ `1`. A first version has `[]`.
- Alternatives: Include unpublished fields as `null`; limit `changed_fields` to the fingerprinted fields.
- Why: §4.4 counts "fields that became published or abstained" as changed.
- Reversible: yes

### D-0669 — Concurrent record writers take an advisory lock per (site, schema)
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 3 (#136) · Status: decided
- Decision: `store_records` takes `pg_advisory_xact_lock` on (site, schema) before it reads the latest versions.
- Alternatives: UNIQUE (site_id, schema_id, entity_key, version). That needs a migration, and existing databases already hold duplicate version-1 rows from repeated scrapes.
- Why: No migration is needed. A task's transaction already serializes on the same site and schema at its progressive-state row.
- Reversible: yes

### D-0670 — The record writer is a required argument of `resolve.task`
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 3 (#136) · Status: decided
- Decision: `store_extraction` and `extract_task` take `write_records: RecordWriter`, which is `store_records` from `recurring.versions`.
- Alternatives: Move `resolve.task` above `recurring`; version records after resolve has stored them.
- Why: The import layers put resolve below recurring, and a required argument means no caller can store unversioned records.
- Reversible: yes

### D-0671 — `changed_since` is inclusive and needs an offset; unchanged entities are not in a job's results
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 3 (#136) · Status: decided
- Decision: `GET /v1/records?changed_since` filters `record.created_at >= changed_since` and requires an RFC 3339 offset (422 otherwise). An entity re-extracted unchanged stores no record, so it is not in that job's results. Its scrape answers with the stored record's id.
- Alternatives: `>`; a job–record link table so that job results list unchanged entities too.
- Why: `>=` can only repeat a record, which its id deduplicates, while `>` could lose one. §6 has no link table.
- Reversible: yes

### D-0679 — Unchanged pages are kept out of drift windows and `pages_extracted` by control flow
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 5 (#139) · Status: decided
- Decision: An `unchanged` task, by 304 or by content fingerprint, ends before extraction. It has no `ExtractionResult` to record, so it never reaches `store_page_record`, the only caller of the drift window (`record_page`) and the progressive count (`_count_page`). No outcome check is added to those hooks. A test pins this on both unchanged paths.
- Alternatives: An explicit `unchanged` guard in the drift and count hooks.
- Why: `ExtractionResult.outcome` cannot be `unchanged` (`resolve.types.Outcome`), so such a guard could never fire; it would be a speculative check.
- Reversible: yes

### D-0689 — A run's listing is the URLs its frontier gave a page kind, on the start host
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 4 (#142) · Status: decided
- Decision: The listing of a records crawl is the canonical URLs of its tasks that matched a page-kind rule, on the start URL's host. A URL counts whether or not its page was reached.
- Alternatives: The row URLs of listing records, as SPEC-11 §4.5 first worded it.
- Why: No job stores listing records (`check_records`, D-0674). The rule-matched URLs are the catalog the crawl found, through listing pages or sitemaps. Subdomain URLs are left out, as pinned configs leave them out (D-0678).
- Reversible: yes

### D-0690 — The runs of a crawl are the records crawls with the same scope
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 4 (#142) · Status: decided
- Decision: Only URLs last held by an earlier job of kind `crawl` are counted missing. That job must have the same `schema_id` and the same request `url`, `include`, `exclude`, `max_depth`, `limit` and `page_kind_rules`.
- Alternatives: Every `url_state` row of the site.
- Why: §14: a recurring crawl is the caller re-submitting the job. Site-wide, two crawls of different sections of a site would each mark the other's URLs gone after two runs.
- Reversible: yes

### D-0691 — A run that saw part of its listing only marks nothing missing
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 4 (#142) · Status: decided
- Decision: Three kinds of run count no misses: one that reached its `limit`; one that listed nothing; and one with a page no rule matched that ended `blocked`, `shell` or `failed`. Its URLs are still marked seen. A navigation page that ended `not_found` still counts.
- Alternatives: Count every run.
- Why: Each of those runs may have missed URLs that are still listed. The frontier stops at `limit`, and the crawl handler reads no links from an unreached page, so a blocked category page would otherwise mark its products gone after two runs (review of #142). A `not_found` page is itself a change in the listing. All of these decline rather than guess (C7).
- Reversible: yes

### D-0692 — The diff runs in the transaction that ends the job, before its end event
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 4 (#142) · Status: decided
- Decision: `settle_job` takes an optional `JobEnding` hook. `complete_task`, `fail_task` and `release_expired_leases` pass it through, and the worker and the scheduler pass `close_run`. A cancelled or failed job is not a run.
- Alternatives: A scheduler sweep over completed jobs, after the end; diffing in the worker after the task commits.
- Why: `db` sits below `recurring` in the import layers, so the hook is injected. Events recorded after the end event can fall outside the batch in which the SSE stream reads the end event and closes.
- Reversible: yes

### D-0693 — `url_state.last_seen_job_id` (migration 0015)
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 4 (#142) · Status: decided
- Decision: Nullable, FK `job`, `ON DELETE SET NULL`. A row that no listing held (one written by a scrape's conditional GET) stays NULL and is never counted missing.
- Alternatives: A separate "seen in a listing" flag.
- Why: §4.5 names this plumbing column. It also gives the job to compare scopes with.
- Reversible: yes

### D-0694 — SPEC-11 §4.5 clarifying edit
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 4 (#142) · Status: decided
- Decision: §4.5 now states D-0689–D-0692. The listing is the rule-matched URLs on the start host, and the runs are records crawls with the same scope. Partial runs count no misses, the diff runs before the end event, and the frontier queues new URLs.
- Alternatives: Leave §4.5 on listing records and the whole site.
- Why: No job produces listing records, and a site-wide diff marks URLs from other crawls gone. ARCHITECTURE §14 row 4 is unchanged, so this is a clarifying edit (CLAUDE.md §6).
- Reversible: yes

### D-0695 — The listing diff takes the site's row lock first
- Date: 2026-10-14 · Spec/PR: SPEC-11 PR 4 (#142) · Status: decided
- Decision: `close_run` reads the site with `SELECT … FOR UPDATE` before it touches `url_state`.
- Alternatives: Let Postgres abort one of two deadlocked runs and let the task retry.
- Why: `_seen` locks rows in sorted order, but the `_missed` UPDATE locks them in scan order, so two runs of a site ending together could deadlock.
- Reversible: yes

### D-0870 — A record found unchanged after a content change stands for the page
- Date: 2026-10-16 · Spec/PR: SPEC-11 follow-ups (#199) · Status: decided
- Decision: `standing_record` takes the entity's newest record a task linked (`task_record.created_at`, migration 0018; existing links backfilled from their record) at or after `url_state.last_changed_at`, by a task whose extraction has the job's mode and config version.
- Alternatives: Write `last_changed_at` back on an equal record fingerprint (moves it for every schema version, D-0667).
- Why: §4.4: an equal fingerprint references the latest record, which then describes the current content; otherwise every run re-extracts the page.
- Reversible: yes

### D-0871 — `task_abstained` reads the records the task stands for
- Date: 2026-10-16 · Spec/PR: SPEC-11 follow-ups (#199) · Status: decided
- Decision: The event reads `field_meta` of the task's `task_record` records, when the task has an extraction.
- Alternatives: The extraction's own records only, which leaves out an unchanged re-extraction.
- Why: The task resolved those abstentions again; an `unchanged` task has no extraction and records no extraction events.
- Reversible: yes

### D-0872 — `record.created_at` is the commit time; `changed_since` waits for in-flight commits
- Date: 2026-10-16 · Spec/PR: SPEC-11 follow-ups (#199) · Status: decided
- Decision: A deferred constraint trigger (migration 0018) restamps a transaction's records with `clock_timestamp()` once at commit, holding `pg_advisory_xact_lock_shared(RECORD_FEED_LOCK)`; `list_records` with `changed_since` takes that lock exclusively and releases it before it queries. Indexed on `record (created_at)`.
- Alternatives: A sleep or overlap window; an xid watermark (needs a response cursor, a public API change); `track_commit_timestamp` (a server setting).
- Why: A record that commits after a poll began is visible with a later time, so the next poll from then lists it. Cost: one UPDATE per committing transaction; polls briefly wait on commits in progress.
- Reversible: yes

### D-0873 — A timed-out sitemap reading makes a run partial (`sitemaps_timed_out`)
- Date: 2026-10-16 · Spec/PR: SPEC-11 follow-ups (#199) · Status: decided
- Decision: The crawl handler records the job event `sitemaps_timed_out` `{url, seeds}` when its sitemap reading hits `SITEMAP_TIMEOUT_S`; `close_run` then counts no misses. A new event kind, as `url_gone` is.
- Alternatives: A `url_task` or `job` column (a schema change); every run whose start page read sitemaps is partial.
- Why: The sitemaps' tail was not read, so URLs only it lists may still be listed (D-0691's reasoning, review of #142).
- Reversible: yes

### D-0874 — Clarifying spec edits: SPEC-11 §4.2/§4.4/§4.5/§5, SPEC-05 §4.3, SPEC-08 §4.11
- Date: 2026-10-16 · Spec/PR: SPEC-11 follow-ups (#199) · Status: decided
- Decision: The specs now say what the code does: `task_record` (D-0762); compare with `record.fingerprint`, `url_state` not written (D-0666, D-0667); commit time (D-0872); timed-out sitemaps (D-0873); §5 no longer cites INV-10/INV-11 for properties they do not state; JSON-LD locators address the block as written (#78); `platform_draft` is `{steps, manual}` with no per-field `params` (D-0606).
- Alternatives: None: the text was wrong.
- Why: CLAUDE.md §6 clarifying edits; no architecture change.
- Reversible: yes
