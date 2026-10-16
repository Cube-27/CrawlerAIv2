# Persistence and Storage Specification

## Purpose

Where CrawlerAI v2 keeps its state: two PostgreSQL databases (main and private eval), the data model tables other
capabilities read and write, the column conventions, the single baseline migration, the capture bundle format, the
two object stores, retention, replay as a pure function over stored captures, and the `engine_version` stamp. The
queue claim loop, job state machine and budgets are in [jobs](../jobs/spec.md); split access rules and eval tables'
use are in [evaluation](../evaluation/spec.md).
Design rationale: [ARCHITECTURE §6](../../design/data-model.md), [§15](../../design/recurring-and-storage.md),
[Appendix A #43](../../design/owner-decisions.md). History:
[SPEC-01](../../changes/archive/2026-10-13-spec-01-persistence-queue-storage/SPEC-01-persistence-queue-storage.md)
and its [decisions](../../changes/archive/2026-10-13-spec-01-persistence-queue-storage/decisions.md).

## Requirements

### Requirement: Two databases with separate roles
The system SHALL use two PostgreSQL 16 databases created by `infra/postgres/init.sql`: `crawlerai` (main, owned by
role `app`) and `crawlerai_eval_private` (owned by role `custodian`, `REVOKE ALL ... FROM PUBLIC`). The main database
SHALL hold everything except hidden and fresh evaluation data, and the `app` role MUST NOT be able to connect to the
private database. Locally `custodian` is `NOLOGIN` and the `CRAWLERAI_EVAL_PRIVATE_*` settings are empty.
Refs: §6, SPEC-01 §5, SPEC-03 §4.2, D-0067.

#### Scenario: App role refused
- **WHEN** a connection to `crawlerai_eval_private` is attempted with `app` credentials
- **THEN** it fails (`tests/db/test_eval_private_database.py`)

### Requirement: Main data model tables
The main database SHALL hold the §6 tables with the §6 column names: `project`, `api_key`, `site`, `schema_def`,
`extraction_config`, `progressive_state`, `job`, `url_task`, `url_state`, `capture`, `extraction`, `candidate`,
`record`, `eval_page`, `eval_run`, `usage_event`, plus the plumbing tables `job_event`, `task_record` and
`webhook_delivery`. It SHALL enforce: `site.host` exact, lowercased and UNIQUE (no public-suffix logic, so
`www.example.com` and `example.com` are two sites); `schema_def.name` UNIQUE (no schema version column);
`project.name` UNIQUE with a `default` project row created by the migration; at most one `active`
`extraction_config` per (`site_id`, `schema_id`, `page_kind`) by a partial unique index.
Refs: §6, SPEC-01 §4.2, D-0089, D-0091, D-0138, Appendix A #43.

#### Scenario: Second active config refused
- **WHEN** a second `extraction_config` row with status `active` is written for the same site, schema and page kind
- **THEN** the insert fails on `uq_extraction_config_active`

#### Scenario: Duplicate host refused
- **WHEN** a `site` row is inserted with a `host` that already exists
- **THEN** the insert fails; hosts are compared exactly as stored, lowercased

### Requirement: Enumerations as CHECK constraints
Every §6 enumeration SHALL be a `text` column with a CHECK constraint, using exactly the §6 values, including
`job.kind` (`scrape`, `batch_scrape`, `map`, `crawl`, `extract`, `learn`), `url_task.outcome` (`extracted`,
`partial`, `unchanged`, `links_only`, `blocked`, `shell`, `not_found`, `no_match`, `failed`), `capture.method`
(`http`, `browser`, `api`), `capture.block_class` (`ok`, `blocked`, `shell`, `not_found`, `error`), `job.status`
(`queued`, `running`, `completed`, `failed`, `cancelled`) and `url_task.status` (`queued`, `claimed`, `done`,
`failed`, `cancelled`). `job_event.kind` is free text.
Refs: §6, SPEC-01 §4.2, D-0102, D-0140.

#### Scenario: Unknown outcome
- **WHEN** a `url_task` is written with `outcome = 'skipped'`
- **THEN** the CHECK constraint rejects it

### Requirement: Column conventions
IDs SHALL be `uuid` values holding UUIDv7 generated in the repo (`crawlerai.core.ids.uuid7()`, RFC 9562 §5.7),
monotonic within one process (RFC 9562 §6.2); ordering across processes is not guaranteed. Times SHALL be
`timestamptz` in UTC, JSON SHALL be `jsonb`, and money SHALL be an exact decimal (`numeric`), never a float.
Refs: §6, SPEC-01 §4.2, D-0088, D-0103.

#### Scenario: Ordered event IDs
- **WHEN** one process generates two IDs in succession
- **THEN** the second sorts after the first, even within the same millisecond

### Requirement: One baseline migration (greenfield)
Each database SHALL have exactly one Alembic baseline revision holding its whole schema: `0001_baseline` for main
(including the deferred `record_committed` constraint trigger) and `p0001` in `migrations/private_versions` for the
private database, run through the same `env.py` (`[private]` section of `alembic.ini`). A model change SHALL edit the
baseline; databases are recreated, never migrated with data steps, and no versioning or compatibility shims are
added until the owner names a use case. Record versions, draft/active configs and `engine_version` are features
and stay.
Refs: Appendix A #43, SPEC-01 §9, D-0954, D-0169.

#### Scenario: Migration round trip
- **WHEN** CI runs `alembic upgrade head`, `alembic downgrade base`, `alembic upgrade head` on an empty database
- **THEN** all three succeed and the constraint names match `test_baseline_migration.py`

### Requirement: Capture bundle format
Each capture SHALL be stored as one zstd-compressed tar (`bundle_version: 1`) containing `manifest.json` (capture
id, url, final_url, fetched_at, method, status_code, block_class, request/response headers as ordered
`[name, value]` lists, `timings_ms`, `html_sha256`, `network_bodies`, `fetch_policy`, `engine_version`), the body
as received (`body.html`, or `body.json` for API captures) and, for browser captures only, `network/NNNN.json` bodies
in request order. `encode` SHALL be deterministic and `decode(encode(b)) == b`; a hash, naming or method mismatch
SHALL raise `CorruptBundle`. Replay reads everything it needs from the bundle, nothing from the `capture` row.
Refs: §15, SPEC-01 §4.5, D-0097, D-0098.

#### Scenario: Round trip
- **WHEN** any valid bundle is encoded and decoded (Hypothesis property test)
- **THEN** the result equals the original, and encoding it again gives the same bytes

#### Scenario: Inconsistent bundle
- **WHEN** a bundle's body does not match its `html_sha256`, or an HTTP capture carries network bodies
- **THEN** `decode` raises `CorruptBundle`

### Requirement: Object stores and key layout
The system SHALL store bundles through an `ObjectStore` protocol (`put`, `get`, `exists`, `delete`, `list`) with an
`fs` backend (dev, CI) and an `s3` backend configured only through boto3's standard environment chain; MinIO MUST
NOT be used. Keys are relative `/`-separated paths with non-empty segments not starting with `.` and without `\` or
NUL, else `ValueError`; deleting a missing key is a no-op; a missing `get` raises `ObjectNotFound`. Production
bundles go to `captures/{yyyy}/{mm}/{capture_id}.bundle.zst` and dev eval bundles to `eval/dev/{capture_id}.bundle.zst`
under `CRAWLERAI_OBJECT_STORE`; hidden and fresh bundles and their recorded LLM responses go only under the private
root `CRAWLERAI_EVAL_PRIVATE_OBJECT_STORE`, which the main `capture` table never references.
Refs: §15, SPEC-01 §4.4, D-0094, D-0095, D-0096.

#### Scenario: Escaping key refused
- **WHEN** `put("../x", data)` is called on either backend
- **THEN** it raises `ValueError` and writes nothing

### Requirement: Retention
Production captures SHALL expire 30 days after capture and candidates 30 days after creation; eval captures never
expire. `expire_captures` SHALL delete only rows whose `expires_at < now()` and whose `object_key` starts with
`captures/`, deleting the rows, then the bundles, then committing, in batches of at most 1000 per transaction (a
full batch runs again at once). Deleting a capture sets `url_task.capture_id` and `extraction.capture_id` to NULL;
tasks, extractions and records are kept.
Refs: §6, §15, SPEC-01 §4.3, D-0137, D-0154, D-0155, D-0156, D-0157.

#### Scenario: Eval bundle untouched
- **WHEN** a `capture` row under `eval/dev/` has an `expires_at` in the past
- **THEN** `expire_captures` keeps the row and its bundle

#### Scenario: Expired production capture
- **WHEN** a production capture's `expires_at` has passed
- **THEN** its row and bundle are deleted, and the extraction that used it keeps its row with `capture_id` NULL

### Requirement: Deterministic replay (INV-10)
Replay SHALL be a pure function `(capture, engine_version, config, schema) → record` sharing one code path with live
runs: the same (bundle, schema, config, calibration) yields byte-identical records, with LLM calls replayed from
recorded responses, so replay needs no network in CI. Enforced by: replay tests that run twice and diff
(`tests/replay/`, the SPEC-03 determinism test); status: SPEC-03 (harness and determinism test built).
Refs: §15, G7, SPEC-01 §4.5, SPEC-03 §4.5, D-0217.

#### Scenario: Two replays
- **WHEN** the same synthetic dev split is replayed twice with recorded LLM responses
- **THEN** the two JSON results are byte-identical

### Requirement: Engine version stamp
`ENGINE_VERSION` SHALL be `<git sha>+cal.<first 12 hex of sha256(calibration.json)>`, read from `backend/VERSION`
and `backend/data/calibration.json` (or the copy a wheel carries in `crawlerai/_engine`), and SHALL be stamped on
`job`, `extraction`, the capture manifest and `eval_run`. A missing `VERSION` reports `unknown` and a missing
calibration `none`; a malformed `VERSION` raises at import.
Refs: §15, SPEC-01 §4.7, D-0152.

#### Scenario: No calibration fitted
- **WHEN** `backend/data/calibration.json` does not exist
- **THEN** the engine version ends in `+cal.none`

### Requirement: Nothing stored in the repo
Captures, evaluation data and secrets MUST NOT enter the repository, which is public; commits carry only synthetic
fixtures on RFC 2606 names. Secrets come from the environment or a secret store and are redacted in logs.
Refs: §15, §18, Appendix A #26.

#### Scenario: Fixture capture
- **WHEN** a test needs a capture bundle
- **THEN** it builds a synthetic one on an `example.test` or `example.com` host
