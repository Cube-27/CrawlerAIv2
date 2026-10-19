# Persistence and Storage Specification

## Purpose

Where CrawlerAI v2 keeps its state: one PostgreSQL database, the data model in one baseline migration, capture
bundles in an object store, retention, deterministic replay and the engine version stamp. Queue and job state are in [jobs](../jobs/spec.md); the golden set in
[evaluation](../evaluation/spec.md).

## Requirements

### Requirement: One database
The system SHALL use one database, `crawlerai` (role `app`), created by `infra/postgres/init.sql`; eval pages,
captures and runs live in it. Refs: owner (2026-10-18, master plan decision 2).

### Requirement: Main data model tables
The main database SHALL hold the §6 tables as defined in the baseline migration, with `site.host` exact, lowercased
and UNIQUE (no public-suffix logic), `schema_def.name` and `project.name` UNIQUE, and at most one `active`
`extraction_config` per (site, schema, page kind). A `site_contract` row holds the contract alone (acquisition spec,
"Acquisition contract and block history"): `method`, `engine`, `handoff`, `coverage`, beside its key, `failures` and
`checked_at`. (Previously: also `settle_on`, `needs_render`, `needs_xhr` and `needs_traversal`.) Refs: §6, D-0089,
D-0091, D-0138, architecture v3 (e).
#### Scenario: Second active config refused
- **WHEN** a second `active` `extraction_config` is written for the same site, schema and page kind
- **THEN** the insert fails on `uq_extraction_config_active`

### Requirement: Enumerations and column conventions
Every §6 enumeration SHALL be a `text` column with a CHECK constraint. IDs SHALL be UUIDv7 from
`crawlerai.core.ids.uuid7()` (RFC 9562, monotonic within one process), times `timestamptz` UTC, JSON `jsonb`, money
`numeric`, never a float. Refs: §6, D-0088, D-0102, D-0103, D-0140.

### Requirement: One baseline migration (greenfield)
The database SHALL have exactly one Alembic baseline revision (`0001_baseline`); a model change edits it and
databases are recreated, never migrated with data steps or compatibility shims. (Previously: a private `p0001` too.)
Refs: Appendix A #43, D-0954.
#### Scenario: Migration round trip
- **WHEN** CI runs upgrade head, downgrade base, upgrade head on an empty database
- **THEN** all three succeed and constraint names match `test_baseline_migration.py`

### Requirement: Capture bundle format
Each capture SHALL be one deterministic zstd tar (manifest, body as received, network bodies as received: a render's
captured calls, or the data calls an HTTP page was joined with, acquisition spec "Data calls"; an `api` capture has
none) as
defined in the bundle codec; `decode(encode(b)) == b`, and an inconsistent bundle raises `CorruptBundle`. A network
entry's response headers, resource type and action index decode as None in bundles written before they were kept.
Replay reads only the bundle, never the `capture` row. Refs: §15, Appendix A #59, D-0097, D-0098, D-1311.
#### Scenario: Round trip
- **WHEN** any valid bundle is encoded and decoded (Hypothesis property test)
- **THEN** the result equals the original and re-encoding gives the same bytes

### Requirement: Object stores and key layout
Bundles SHALL go through the `ObjectStore` protocol (`fs` and `s3` backends, S3 via boto3's environment chain, no
MinIO); escaping or malformed keys raise `ValueError`. (Previously: hidden and fresh bundles under a private root.)
Refs: §15, D-0094, D-0095, D-0096.
#### Scenario: Escaping key refused
- **WHEN** `put("../x", data)` is called on either backend
- **THEN** it raises `ValueError` and writes nothing

### Requirement: Retention
Production captures and candidates SHALL expire after 30 days; eval captures never expire. `expire_captures` deletes
only expired rows under `captures/`, in batches, nulling `capture_id` on tasks and extractions, which are kept.
Refs: §15, D-0137, D-0154, D-0157.

### Requirement: Deterministic replay (INV-10)
Replay SHALL be a pure function `(capture, engine_version, config, schema) → record` sharing the live code path, with
LLM calls replayed from recorded responses, so the same inputs give byte-identical records with no network.
Enforced by: replay tests that run twice and diff (`tests/replay/`); active. Refs: §15, G7, D-0217.
#### Scenario: Two replays
- **WHEN** the synthetic dev split is replayed twice with recorded LLM responses
- **THEN** the two JSON results are byte-identical

### Requirement: Engine version stamp
`ENGINE_VERSION` SHALL be `<git sha>+cal.<12 hex of sha256(calibration.json)>` (`unknown` without `VERSION`, `none`
without calibration), stamped on `job`, `extraction`, the capture manifest and `eval_run`. Refs: §15, D-0152.
#### Scenario: No calibration fitted
- **WHEN** `backend/data/calibration.json` does not exist
- **THEN** the engine version ends in `+cal.none`

### Requirement: Nothing stored in the repo
Captures, evaluation data and secrets MUST NOT enter the public repository; tests build synthetic bundles on RFC 2606
hosts, and secrets come from the environment and are redacted in logs. Refs: §15, §18, Appendix A #26.

### Requirement: Capture artifacts
Artifacts SHALL be objects keyed from the capture's bundle key (`captures/Y/M/<id>.<name>`), written before the
capture row, listed by name from the object store, and deleted with the bundle; no table holds them. Refs: D-1421.
