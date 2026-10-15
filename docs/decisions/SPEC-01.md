# SPEC-01 decisions

Decisions for [SPEC-01 — Persistence, job queue and capture storage](../specs/SPEC-01-persistence-queue-storage.md).
Template, statuses and rules: [DECISIONS.md](../DECISIONS.md).

### D-0088 — UUIDv7 generated in-repo
- Date: 2026-10-12 · Spec/PR: SPEC-01 PR 1 (#11) · Status: decided
- Decision: `crawlerai.core.ids.uuid7()` implements RFC 9562 §5.7, because Python 3.12 has no `uuid.uuid7`.
- Alternatives: a third-party UUIDv7 package.
- Why: About ten tested lines and no dependency. Switch to the stdlib on Python 3.14.
- Reversible: yes

### D-0089 — `project.name` is UNIQUE
- Date: 2026-10-12 · Spec/PR: SPEC-01 PR 1 (#11) · Status: decided
- Decision: The `default` project is found by name; its ID is a v7 generated in the migration.
- Alternatives: a fixed well-known UUID.
- Why: Keeps SPEC-01 §4.2's v7 IDs.
- Reversible: yes

### D-0090 — `site.fetch_method` defaults to `http`
- Date: 2026-10-12 · Spec/PR: SPEC-01 PR 1 (#11) · Status: decided
- Decision: A new site starts at the `http` rung (server default).
- Alternatives: no default.
- Why: ARCHITECTURE §7.1: HTTP is the default rung, and `fetch_method` is then recorded from evidence.
- Reversible: yes

### D-0091 — Column shapes left open by ARCHITECTURE §6
- Date: 2026-10-12 · Spec/PR: SPEC-01 PR 1 (#11) · Status: decided
- Decision: `site.robots_snapshot` is nullable text; `site.crawl_delay_ms` is a nullable int ≥ 0; `api_key.hashed_key` is unique text; `api_key.webhook_secret` is NOT NULL; `schema_def` has UNIQUE (`name`, `version`), `version >= 1`, and `required_groups` defaults to `[]`.
- Alternatives: a jsonb robots snapshot; a nullable webhook secret.
- Why: The most conservative reading. SPEC-02 can add parsed robots columns.
- Reversible: yes

### D-0092 — DB tests skip without a database URL; CI always runs them
- Date: 2026-10-12 · Spec/PR: SPEC-01 PR 1 (#11) · Status: decided
- Decision: `tests/db` skips when `CRAWLERAI_DATABASE_URL` is unset. CI sets it and runs pytest after the migration round trip, using the `anyio` plugin.
- Alternatives: pytest-asyncio; fail without a DB.
- Why: No new dependency, and the tests always run in CI.
- Reversible: yes

### D-0093 — Foreign keys reference columns, not `"table.column"` strings
- Date: 2026-10-12 · Spec/PR: SPEC-01 PR 1 (#11) · Status: decided
- Decision: `ForeignKey(Project.id)` and `project.c.id`.
- Alternatives: allowlist `project.id` in the C3 scanner.
- Why: The scan reads `"project.id"` as a host (`.id` is a TLD). See the follow-up in ACTIVE.md.
- Reversible: yes

### D-0094 — `ObjectStore` methods are synchronous
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 5 (#13) · Status: decided
- Decision: `ObjectStore` methods are plain sync calls; async callers run them in a thread (`asyncio.to_thread`).
- Alternatives: An async protocol over aioboto3/aiofiles.
- Why: boto3 is sync; an async S3 client adds a dependency for 10k pages/day (§19 sizing).
- Reversible: yes, before SPEC-02 PR 3 has callers

### D-0095 — S3 endpoint and credentials come from boto3's standard configuration
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 5 (#13) · Status: decided
- Decision: No `CRAWLERAI_*` S3 settings; `AWS_ENDPOINT_URL`, credentials and region come from the AWS environment/config chain, which covers S3-compatible stores (§15).
- Alternatives: `CRAWLERAI_S3_ENDPOINT` and similar settings.
- Why: boto3 already reads them.
- Reversible: yes

### D-0096 — Object key rules
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 5 (#13) · Status: decided
- Decision: Keys are relative `/`-separated paths with non-empty segments that don't start with `.` and contain no `\` or NUL; otherwise `ValueError`. `list(prefix)` is a string-prefix match returning sorted keys; deleting a missing key is a no-op.
- Alternatives: Backend-specific rules; raising on a missing delete.
- Why: One key means one object on both backends (no `..` escape from an `fs` root; dot-files reserved for in-progress `fs` writes); retention stays idempotent.
- Reversible: yes

### D-0097 — Bundle manifest shapes the spec leaves open
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 5 (#13) · Status: decided
- Decision: Headers are ordered `[name, value]` lists (RFC 9110 §5.3 allows repeats); `timings_ms` is `dict[str, int]`; `fetch_policy` is a JSON object; `content_type` may be null; models forbid extra keys. `CaptureBundle.network` is a tuple of bytes aligned by index with `manifest.network_bodies`. The bundle validates `html_sha256`, per-body `sha256`, `network/NNNN.json` naming, and that only browser captures carry network bodies; `decode` turns any mismatch into `CorruptBundle`.
- Alternatives: Header dicts (lose repeats); `NetworkBody` carrying its bytes.
- Why: Most conservative reading of §4.5 "as received" and "round-trip exactly"; inconsistent bundles can't be represented.
- Reversible: before captures exist; after, needs `bundle_version: 2`

### D-0098 — `zstandard` for zstd
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 5 (#13) · Status: decided
- Decision: `zstandard` (BSD-3). Python 3.12 has no stdlib zstd.
- Alternatives: `pyzstd` (BSD-3).
- Why: Widely used, licence-clean, typed.
- Reversible: yes; the format is standard zstd

### D-0099 — Job and task transition tables
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 2 (#14) · Status: decided
- Decision: Job: `queued→{running, cancelled}`, `running→{completed, failed, cancelled}`. Task: `queued→{claimed, cancelled}`, `claimed→{queued, done, failed, cancelled}`. Terminal states have no exits. `claimed→queued` covers retry and expired lease (§4.3); a requeue clears `claimed_by` and `lease_until`, a terminal transition keeps `claimed_by`.
- Alternatives: `queued→completed` for empty jobs; `queued→failed`.
- Why: The smallest graph that covers §4.3 and SPEC-10 §4.2.
- Reversible: yes

### D-0100 — `settled_status` rules
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 2 (#14) · Status: decided
- Decision: A job does not settle while any task is `claimed`. With `cancel_requested` it ends `cancelled` and its queued tasks are not run (SPEC-10 §4.2). Otherwise it ends once nothing is queued: `failed` only if every task failed (D-0006), else `completed`. A job with no tasks completes.
- Alternatives: An empty job fails.
- Why: Nothing failed in an empty job.
- Reversible: yes

### D-0101 — Ending a job records its event in the same transaction
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 2 (#14) · Status: decided
- Decision: `transition_job` to a terminal status inserts `job_event(kind=<status>, payload={})`.
- Alternatives: Callers emit the event themselves.
- Why: One writer; the status and the event cannot diverge (§4.3).
- Reversible: yes

### D-0102 — `job_event.kind` is free text
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 2 (#14) · Status: decided
- Decision: No CHECK constraint.
- Alternatives: A CHECK on SPEC-10 §4.2's kinds.
- Why: SPEC-01 §4.2 doesn't list it among the enumerations, and later specs add kinds.
- Reversible: yes

### D-0103 — Monotonic `uuid7()`
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 2 (#14) · Status: decided
- Decision: Within one process, `rand_a` is a 12-bit counter starting at a random value in its lower half; on overflow or clock regression the timestamp advances (RFC 9562 §6.2). Ordering across processes is not guaranteed.
- Alternatives: `job_event.id` as a bigint identity (deviates from §4.2 "ids are uuid"); order by `ts`.
- Why: SPEC-10 orders `job_event` by id for SSE resume.
- Reversible: yes

### D-0104 — Self-referencing FK spelled via `__tablename__`
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 2 (#14) · Status: decided
- Decision: `ForeignKey(f"{__tablename__}.id")` for `url_task.parent_task_id`, and `op.create_foreign_key(..., ["id"])` in the migration.
- Alternatives: Fix the C3 scanner in this row.
- Why: The scan reads `"url_task.id"` as a host: the D-0093 class recurring. The scanner fix is a follow-up in ACTIVE.md.
- Reversible: yes

### D-0105 — Hypothesis as a dev dependency
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 2 (#14) · Status: decided
- Decision: `hypothesis` (MPL-2.0, not on the deny-list) for property tests.
- Alternatives: Hand-written generators.
- Why: ENGINEERING and SPEC-01 §6 prescribe property tests.
- Reversible: yes

### D-0119 — Handlers take a `ClaimedTask` snapshot and an `AsyncConnection`
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 3 (#17) · Status: decided
- Decision: `TaskHandler = Callable[[ClaimedTask, AsyncConnection], Awaitable[TaskResult]]`; `ClaimedTask` is a frozen dataclass of the claimed row.
- Alternatives: The ORM `UrlTask` and an `AsyncSession`, as §4.3 sketches.
- Why: `db.jobs` works on `AsyncConnection`; an ORM instance expires on rollback, exactly when the worker needs it to record the failure.
- Reversible: yes, until handlers exist

### D-0120 — Task status follows outcome
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 3 (#17) · Status: decided
- Decision: `Finished(outcome)` with any outcome but `failed` ends the task `done`; `Failed` ends it `failed` or requeues it. `TaskOutcome = Literal[FinishedOutcome, "failed"]`.
- Alternatives: `blocked`/`not_found` as status `failed`.
- Why: D-0006 counts tasks that errored, not pages that were blocked or missing (§4.3).
- Reversible: yes

### D-0121 — Handler exceptions are transient
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 3 (#17) · Status: decided
- Decision: An uncaught exception requeues the task with backoff (at most 3 attempts); a missing handler for a job kind fails the task at once.
- Alternatives: Treat exceptions as permanent.
- Why: DB blips and network errors surface as exceptions; retrying a bug costs at most two attempts.
- Reversible: yes

### D-0122 — Claims are fenced by (`claimed_by`, `attempts`); one transaction per task
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 3 (#17) · Status: decided
- Decision: Finishing updates require the claim's worker and attempt count; a mismatch raises `LeaseLost` and the handler's writes roll back. A release gives back the attempt, so the fence holds only while released snapshots are discarded (follow-up in ACTIVE.md).
- Alternatives: Fence on `claimed_by` only; commit handler writes separately.
- Why: A lost lease must not let two runs both record a result (§4.3).
- Reversible: yes

### D-0123 — The claim starts the job; settling locks the job row
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 3 (#17) · Status: decided
- Decision: `claim_tasks` moves claimed tasks' `queued` jobs to `running`. Finishing a task locks its job row (`FOR UPDATE`), skips settling while an open task remains, then applies `settled_status`; a job no longer `running` is left alone.
- Alternatives: Settle without a lock.
- Why: Exactly one worker ends each job (§4.3).
- Reversible: yes

### D-0124 — Worker constants
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 3 (#17) · Status: decided
- Decision: Claim batch 10; idle poll 1 s; `last_error` cut to 2048 UTF-8 bytes on a character boundary; URLs (RFC 3986 scheme + `://`) become `<url>` when `log_redact_urls` is set. On stop, unstarted claimed tasks are requeued with their attempt given back.
- Alternatives: Batch 1; leave unstarted tasks to lease expiry.
- Why: §19 sizing makes batch size uncritical; a clean stop shouldn't strand tasks.
- Reversible: yes

### D-0125 — `url_task` UNIQUE (`job_id`, `canonical_url`) and a partial index on open tasks
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 3 (#17) · Status: decided
- Decision: Migration 0004 adds both; no separate `job_id` index, since the UNIQUE's index leads with it.
- Alternatives: Leave the UNIQUE to SPEC-10.
- Why: SPEC-10 §4 needs the UNIQUE; the partial index keeps settling O(log n) per task (10k test: 268 s → ~80 s).
- Reversible: yes

### D-0131 — An expired lease is a transient failure of its attempt
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 4 (#19) · Status: decided
- Decision: `release_expired_leases` runs `fail_task(..., "lease expired", transient=True)` on each expired claim: requeued with backoff while `attempts < MAX_ATTEMPTS`, else failed and the job settled.
- Alternatives: Requeue unconditionally and immediately (the spec's literal "requeues").
- Why: A task that kills or hangs its worker every time would otherwise be requeued forever; §4.3 caps transient retries at 3.
- Reversible: yes

### D-0132 — Claims are fenced by (`claimed_by`, `lease_until`), with `lease_until` from `clock_timestamp()`
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 4 (#19) · Status: decided
- Decision: `ClaimedTask` carries `lease_until`; finishing requires both to match. The claim sets `lease_until = clock_timestamp() + LEASE`, so two claims of a task never share it. Supersedes the fence in D-0122. SPEC-01 §4.3's claim SQL is updated to match (clarifying edit).
- Alternatives: A claim-token column (needs a migration); stop `release_task` giving the attempt back (changes D-0124).
- Why: (`claimed_by`, `attempts`) was not unique once `release_task` decrements `attempts`. A future lease heartbeat must update the holder's `ClaimedTask` too.
- Reversible: yes

### D-0133 — DB tests use a dedicated `CRAWLERAI_TEST_DATABASE_URL`
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 4 (#19) · Status: decided
- Decision: `tests/db` reads only `CRAWLERAI_TEST_DATABASE_URL` (skipped when unset) and migrates it; CI sets it to its service DB, `make check` to `crawlerai_check`. Updates D-0092.
- Alternatives: Scope the cleanup to the test's own jobs.
- Why: `claim_tasks` and the worker loop take every due task in the database, so tests against a dev DB would run its tasks. Test-only, not a `Settings` field.
- Reversible: yes

### D-0134 — The scheduler logs and survives a failing entry
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 4 (#19) · Status: decided
- Decision: Each entry runs in its own transaction; an exception rolls back, is logged with its traceback, and the entry runs again at its next interval. Next run = end of previous run + interval.
- Alternatives: Let the error end the process (§4.8), relying on a restart policy.
- Why: One entry's failure shouldn't stop the others; a fresh pooled connection per run recovers from a dropped connection.
- Reversible: yes

### D-0135 — A DB error while recording a task failure ends the worker
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 4 (#19) · Status: decided
- Decision: Documented in `worker/loop.py`: `run_worker` raises and the process exits; its claimed tasks return through `release_expired_leases`.
- Alternatives: Catch and continue (the connection is usually gone).
- Why: §4.8; the scheduler recovers the tasks.
- Reversible: yes

### D-0136 — (`schema_id`, `schema_version`) is a composite FK to `schema_def (id, version)`
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 6 (#20) · Status: decided
- Decision: `record`, `extraction_config` and `progressive_state` reference `schema_def (id, version)`, which gets `UNIQUE (id, version)`; no separate FK on `schema_id` alone.
- Alternatives: An FK on `schema_id` alone, with `schema_version` unchecked.
- Why: A `schema_def` row is one version, so the pair could otherwise disagree (§5.2).
- Reversible: yes

### D-0137 — Expiring a capture keeps its task and extraction
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 6 (#20) · Status: decided
- Decision: `url_task.capture_id` and `extraction.capture_id` are nullable, `ON DELETE SET NULL`, and indexed.
- Alternatives: NOT NULL with `ON DELETE CASCADE` (deletes extractions that records cite); a plain FK (blocks `expire_captures`).
- Why: Production captures expire after 30 days (§15); extractions and records are kept.
- Reversible: yes

### D-0138 — Column shapes left open by §6
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 6 (#20) · Status: decided
- Decision: Most conservative reading: `capture.status_code`, `final_url`, `html_sha256` NOT NULL as in the bundle manifest; `expires_at` nullable; `object_key` UNIQUE; `candidate.raw_value` jsonb NOT NULL, `normalized_value` nullable; `record.version` ≥ 1 default 1, `changed_fields` jsonb `[]`, `fingerprint` nullable until SPEC-11; `url_state` PK (`site_id`, `canonical_url`), `last_modified` text as received (RFC 9110 §13.1.3); `progressive_state` PK (`site_id`, `schema_id`, `schema_version`, `page_kind`) starting `cold`; `extraction_config` UNIQUE (`site_id`, `schema_id`, `page_kind`, `version`), status default `draft`. Full list in #20.
- Alternatives: A bigint SimHash `content_fingerprint`; a timestamptz `last_modified`.
- Why: SPEC-11 can tighten the fingerprint type when it computes one.
- Reversible: yes, before data exists

### D-0139 — Extra indexes beyond §4.2
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 6 (#20) · Status: decided
- Decision: `ix_capture_expires_at` (partial) and `ix_candidate_created_at` for retention; `ix_url_task_capture_id` and `ix_extraction_capture_id` for `SET NULL` on capture delete; `ix_candidate_extraction_id` for reading an extraction's candidates.
- Alternatives: Add them with the retention PR (8).
- Why: Each serves a query this spec defines (§4.3 scheduler entries, §6 retention).
- Reversible: yes

### D-0140 — `CaptureMethod`/`BlockClass` live in `crawlerai.core.capture`
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 6 (#20) · Status: decided
- Decision: Moved from `storage.capture_bundle`; `storage`, `acquire` and `db` import them from `core`.
- Alternatives: Duplicate the Literals in `db.models`.
- Why: The layering contract keeps `db` and `storage` independent; one definition keeps the CHECK and the bundle in sync.
- Reversible: yes

### D-0148 — `usage_event` column shapes
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 7 (#23) · Status: decided
- Decision: `quantity` bigint ≥ 0 in whole units; `resource` CHECK on the six §4.6 resources; `provider`, `model_or_pool` nullable; `metadata` jsonb NOT NULL default `{}`; FK to `job` without cascade; no timestamp column (the UUIDv7 id carries the time); no `job_id` index until a query reads by job.
- Alternatives: Numeric quantity; free-text resource; a `ts` column.
- Why: All §4.6 budgets are ints; §4.6 lists resources as a closed set, unlike `job_event.kind` (D-0102).
- Reversible: yes

### D-0149 — The `pages` budget counts the job's tasks that ended
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 7 (#23) · Status: decided
- Decision: `budget_remaining(job, "pages")` = budget − tasks in `done` or `failed`; other budgets read `job.usage[resource]`; never below 0; `None` means no budget.
- Alternatives: Count claimed tasks too; record `pages` as a usage resource.
- Why: `pages` is a budget key (§4.6) but not a usage resource; a page is spent once its task ends.
- Reversible: yes

### D-0150 — Budgets are advisory across workers
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 7 (#23) · Status: decided
- Decision: No reservation; concurrent checks may both proceed, so a job can overshoot by the work in flight.
- Alternatives: Lock the job row when checking.
- Why: §4.6: "checked by the caller before expensive work"; a lock would serialize a job's workers.
- Reversible: yes

### D-0151 — Budget exhaustion is a handler result, not an exception
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 7 (#23) · Status: decided
- Decision: Handlers return `Failed(BUDGET_EXHAUSTED, transient=False)`; the worker doesn't change.
- Alternatives: A `BudgetExhausted` exception mapped to a permanent failure.
- Why: An exception rolls back the task's transaction, including usage already recorded, so budgets would undercount.
- Reversible: yes

### D-0152 — `ENGINE_VERSION` details
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 7 (#23) · Status: decided
- Decision: Calibration hash = first 12 hex digits of SHA-256 over the file bytes; missing `VERSION` → `unknown`, missing calibration → `none`; a malformed `VERSION` raises at import. Files are read only from a source tree; an installed wheel reports `unknown+cal.none` (open item in ACTIVE.md).
- Alternatives: The full hash; `git rev-parse` at import.
- Why: An honest marker for unbuilt trees, with no subprocess at import.
- Reversible: yes

### D-0153 — Claims select from a `MATERIALIZED` CTE
- Date: 2026-10-13 · Spec/PR: SPEC-01 follow-up (#24) · Status: decided
- Decision: `claim_tasks` updates rows chosen by a `MATERIALIZED` CTE (`SELECT … LIMIT n FOR UPDATE SKIP LOCKED`), so the subquery runs once and a call never claims more than `n` tasks.
- Alternatives: `id = ANY(ARRAY(subquery))`.
- Why: Both force one evaluation; SQLAlchemy expresses the CTE directly, and `MATERIALIZED` is documented PostgreSQL behaviour (PG ≥ 12). `UPDATE … WHERE id IN (SELECT … LIMIT)` can be planned as a semi-join that re-runs the subquery.
- Reversible: yes

### D-0154 — Only keys under `captures/` expire
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 8 (#25) · Status: decided
- Decision: `expire_captures` filters on `expires_at < now()` and `object_key` starting with `captures/`; a row under `eval/` is kept whatever its `expires_at`.
- Alternatives: Filter on `expires_at` alone.
- Why: "Eval prefixes untouched" becomes structural rather than dependent on row data (C1).
- Reversible: yes

### D-0155 — Retention runs one bounded batch per transaction; a full batch runs again at once
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 8 (#25) · Status: decided
- Decision: Each run of `expire_captures`/`expire_candidates` deletes at most `RETENTION_BATCH` (1000) rows chosen by `id IN (SELECT … ORDER BY … LIMIT :batch)`. A run that returns a full batch makes the entry due again immediately (`Periodic.batch`), so a backlog drains as consecutive short transactions; the 1 h interval of §4.3 is kept, and a failed run waits its interval.
- Alternatives: Loop with commit inside the entry; run every minute; size the batch to expected ingest.
- Why: A partial failure strands at most one batch; progress is monotonic; capacity scales with backlog.
- Reversible: yes

### D-0156 — Retention deletes rows, then bundles, then commits
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 8 (#25) · Status: decided
- Decision: `DELETE … RETURNING object_key`, delete each object, then the scheduler commits. Until the next run, up to one batch of rows already past `expires_at` may name deleted bundles (stated in the docstring).
- Alternatives: Delete bundles after commit (a crash leaves orphan bundles nothing expires).
- Why: A failed delete or commit leaves the rows and the next run converges (store `delete` is idempotent); no bundle is left without the row that expires it (D-0144).
- Reversible: yes

### D-0157 — "Past" is strict
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 8 (#25) · Status: decided
- Decision: `expires_at < now()`, `created_at < now() - 30 days`.
- Alternatives: Inclusive comparisons.
- Why: Most conservative reading of "past `expires_at`" and "kept 30 days".
- Reversible: yes

### D-0158 — The scheduler table is built from the object store
- Date: 2026-10-13 · Spec/PR: SPEC-01 PR 8 (#25) · Status: decided
- Decision: `periodic(store)` replaces the `PERIODIC` constant; `expire_captures` gets the store through `functools.partial`. Retention lives in `crawlerai.scheduler.retention`.
- Alternatives: Open the store inside `expire_captures` from settings.
- Why: Keeps `Periodic.run` as `(conn) -> …` with the store explicit; retention needs both `db` and `storage`, independent siblings in the layering.
- Reversible: yes
