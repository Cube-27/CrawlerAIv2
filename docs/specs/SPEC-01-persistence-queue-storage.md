# SPEC-01 — Persistence, job queue and capture storage

Layer: L0. Architecture refs: §4, §6, §15, §17 (usage counters), §19 (DB/queue row).

## 1. Summary

The data model (§6) as Alembic migrations and SQLAlchemy models, the `FOR UPDATE SKIP LOCKED` task queue with
the three process roles (§4), the object-store abstraction and the capture bundle format (§15), and usage events
(§17). Everything later writes through this layer. The private eval store (hidden/fresh) is a separate database
owned by SPEC-03; this spec provides the shared DDL it reuses.

## 2. Scope

Core:
- Tables from §6 with the columns listed there, plus the plumbing columns listed in 4.2 (each marked
  "implementation detail, not architecture").
- Queue: claim, lease, retry, cancel; `api`, `worker`, `scheduler` roles in one image.
- Object storage backends: `fs` (dev, CI) and `s3`; capture bundle write/read.
- Retention: capture expiry at 30 days in production; candidates kept 30 days (§6).
- `usage_event` write API and per-job budget check hook (§11, §17).

Out of scope:
- Redis, Celery, procrastinate (decision: thin loop, see 4.3).
- WARC format (§22).
- Any eval tables' *content* or custodian role grants beyond DDL reuse (SPEC-03).
- Multi-tenancy, billing (§1 non-goals).

## 3. Dependencies

- SPEC-00.
- OPEN_QUESTIONS #13 (region/retention): default 30 days production captures, eval forever. #10 (proxy pool):
  `site.proxy_pool` is a free-text pool name resolved from settings.

## 4. Design

### 4.1 Modules

- `crawlerai.db.models` — SQLAlchemy 2.0 declarative models, one class per §6 table.
- `crawlerai.db.session` — async engine/session factory; `get_session()` dependency.
- `crawlerai.db.queue` — `claim_tasks`, `complete_task`, `fail_task`, `release_expired_leases`.
- `crawlerai.db.jobs` — job state machine helpers.
- `crawlerai.db.usage` — `record_usage(job_id, resource, provider, model_or_pool, quantity, metadata)`,
  `budget_remaining(job_id, resource)`.
- `crawlerai.storage.base` — `ObjectStore` protocol: `put(key, bytes)`, `get(key) -> bytes`, `exists`, `delete`,
  `list(prefix)`.
- `crawlerai.storage.fs`, `crawlerai.storage.s3`.
- `crawlerai.storage.capture_bundle` — bundle encode/decode (4.5).
- `crawlerai.worker.loop`, `crawlerai.scheduler.loop` — process entry points.
- `migrations/` — Alembic, async env, one revision per PR.

### 4.2 Tables

All §6 tables and columns are implemented with the names written there, including `site.host` (exact,
lowercased, UNIQUE), `schema_def.name` (UNIQUE), `progressive_state.pages_extracted`,
`url_state.missing_runs` and `gone_at`, `candidate.independent`, and `record.version`, `changed_fields`,
`complete`, `mode`, `fingerprint`. Types: ids are `uuid` (v7 generated in Python, stored as `uuid`); money
`numeric(18,6)`; times `timestamptz` in UTC; JSON is `jsonb`. Enumerations are Postgres `text` with a CHECK
constraint (easier migrations than native enums).

Plumbing columns (implementation detail, not architecture; §6 delegates them here), with the reason each is
needed:

| Table | Column | Reason |
|---|---|---|
| `project` | `created_at` | bookkeeping |
| `api_key` | `created_at`, `revoked_at` | §18 "revocable" (SPEC-07 4.2) |
| `api_key` | `webhook_secret` | webhook signatures (SPEC-10 4.2) |
| `site` | `created_at`, `fetch_method_checked_at` | §7.1 "re-checked periodically against HTTP" needs a timestamp |
| `extraction_config` | UNIQUE partial index on (`site_id`,`schema_id`,`page_kind`) WHERE status='active' | §6 "one `active` per (site, schema, page_kind)" |
| `job` | `created_at`, `started_at`, `finished_at`, `cancel_requested` | status/cancel (§13.1) |
| `url_task` | `claimed_by`, `lease_until`, `next_attempt_at`, `priority`, `depth`, `parent_task_id` | queue leases, backoff, crawl depth (§13.2) |
| `url_task` | INDEX (`status`, `next_attempt_at`, `priority`) | claim query |
| `record` | `supersedes_record_id` | links a record version to the one it replaces (§14) |
| `record` | INDEX (`site_id`,`entity_key`,`schema_id`) | fingerprint comparison on recurring runs |
| `job_event` (new table) | `id`, `job_id`, `ts`, `kind`, `payload` (jsonb) | §17 run events stored in Postgres and streamed over SSE; reconnects need storage; no Redis |
| `candidate` | `created_at` | 30-day expiry (§6) |
| `capture` | `size_bytes`, `duration_ms`, `fetch_policy` (jsonb: proxy, robots override) | outcome recording (§7.1) |

Other specs add plumbing of their own and say so where they do: `progressive_state` timestamps and
`extraction_config.drift_window` (SPEC-08 4.4, 4.9), `extraction.diagnostics` (SPEC-05 4.14),
`url_task.record_id` and `url_state.last_seen_job_id` (SPEC-11), `eval_page.config_snapshot` (SPEC-03 4.5).

Enumerations exactly as §6: `site.fetch_method`, `schema_def.origin/status`, `extraction_config.status/origin`,
`progressive_state.mode`, `job.kind` (`scrape`, `batch_scrape`, `map`, `crawl`, `extract`, `learn`), `job.status`,
`url_task.status`, `url_task.outcome` (`extracted`, `partial`, `unchanged`, `links_only`, `blocked`, `shell`,
`not_found`, `no_match`, `failed`), `capture.method`, `capture.block_class` (§7.1: `ok`, `blocked`, `shell`,
`not_found`, `error`), `extraction.mode`, `candidate.normalize_status/source_kind`, `record.mode`,
`eval_page.split`, `eval_page.category` (§16.1).

`job.status` ∈ {`queued`, `running`, `completed`, `failed`, `cancelled`}. `url_task.status` ∈ {`queued`, `claimed`,
`done`, `failed`, `cancelled`}.

A migration creates the `default` project row (one deployment, one organization; every site and job needs a
project).

### 4.3 Queue (thin loop, no procrastinate)

§19 specifies a thin `FOR UPDATE SKIP LOCKED` loop: `url_task` is already the work table (§6) and the scheduler
role covers periodic work, so no queue library is added.

Claim (one statement):

```sql
UPDATE url_task SET status='claimed', claimed_by=:worker, lease_until=clock_timestamp()+:lease, attempts=attempts+1
WHERE id IN (SELECT id FROM url_task
             WHERE status='queued' AND next_attempt_at <= now()
             ORDER BY priority DESC, id
             FOR UPDATE SKIP LOCKED LIMIT :n)
RETURNING *;
```

- Lease default 10 min; `scheduler` requeues tasks whose lease expired (`status='claimed' AND lease_until < now()`).
- Retry policy: `attempts` ≤ 3 for `failed` outcomes caused by transient errors; `next_attempt_at` grows
  exponentially (base 30 s). Every other outcome (`blocked`, `shell`, `not_found`, `no_match`, and the successful
  ones) is terminal for the task.
- Politeness is enforced by the worker per site (SPEC-02), not by the claim query. The claim query takes `n`
  tasks; the worker groups them by site and respects `site.crawl_delay_ms`.
- Job completion: when a job has no `queued`/`claimed` tasks, the worker that finishes the last task marks the job
  `completed` (or `failed` if every task failed) and emits a `job_event(kind='completed')`. Webhooks (SPEC-10)
  hook here.
- Cancel: `job.cancel_requested=true`; workers skip claimed tasks of cancelled jobs and mark them `cancelled`.

Worker loop signature: `async def run_worker(settings, handlers: dict[JobKind, TaskHandler], stop: Event)`,
`TaskHandler = Callable[[UrlTask, Session], Awaitable[TaskResult]]`. Handlers are registered by later specs.

Scheduler loop: a table-driven list of `(name, interval, coroutine)`; initial entries: `release_expired_leases`
(1 min), `expire_captures` (1 h), `expire_candidates` (1 h). Later specs register `recheck_fetch_method`,
`evaluate_drift`, `trigger_learning`.

### 4.4 Object storage

Key layout (`CRAWLERAI_OBJECT_STORE` prefix is prepended):

```
captures/{yyyy}/{mm}/{capture_id}.bundle.zst          # production (30-day expiry)
eval/dev/{capture_id}.bundle.zst                      # dev eval captures, never expire
```

Hidden and fresh bundles live under a different root (`CRAWLERAI_EVAL_PRIVATE_OBJECT_STORE`), never under the
main store (INV-01). The main `capture` table never references them.

`fs` backend: files under a directory; `s3` backend: boto3 with lifecycle rules documented but not managed by
the app (expiry is enforced by `expire_captures`, which deletes rows and objects past `expires_at`).

### 4.5 Capture bundle format (§15)

A zstd-compressed tar containing:

```
manifest.json      # {bundle_version:1, capture_id, url, final_url, fetched_at, method, status_code,
                   #  block_class, headers: {request, response}, timings_ms, html_sha256, network_bodies: [{url, status, content_type, sha256, file}],
                   #  fetch_policy, engine_version}
body.html          # response body bytes as received (decoded from transfer/content encoding), or body.json for API captures
network/0001.json  # captured JSON bodies, in request order (browser only)
```

`CaptureBundle` is a frozen pydantic model with `manifest: CaptureManifest`, `body: bytes`, `network: list[NetworkBody]`;
`encode(bundle) -> bytes` and `decode(bytes) -> CaptureBundle` are pure and round-trip exactly. Everything the
engine needs to replay is in the bundle; nothing is read from the `capture` row during replay (INV-10).

### 4.6 Usage events and budgets

- `record_usage` inserts a `usage_event` and increments `job.usage[resource]` atomically.
- Resources: `llm_calls`, `llm_tokens_in`, `llm_tokens_out`, `browser_seconds`, `proxy_bytes`, `http_requests`.
- Budget: `job.request.budget` (optional): `{llm_calls?: int, browser_seconds?: int, pages?: int}`. `budget_remaining`
  is checked by the caller before expensive work; exhaustion fails the task with `last_error='budget_exhausted'`
  and the job finishes with the pages it has.

### 4.7 Engine version

`crawlerai.core.engine_version.ENGINE_VERSION = f"{git_sha}+cal.{calibration_hash}"` computed at import from
`backend/VERSION` written by the build (git SHA) and the hash of `backend/data/calibration.json` (SPEC-05). It is
stamped on `job`, `extraction`, `capture.manifest` and `eval_run`.

### 4.8 Error handling

- DB errors propagate; the worker loop catches per task, records `last_error` (truncated to 2 KB, URLs redacted
  when `CRAWLERAI_LOG_REDACT_URLS`), and continues.
- Storage `get` of a missing key raises `ObjectNotFound`; the caller decides (replay fails the eval page).
- Bundle decode errors raise `CorruptBundle` and the capture row is marked `block_class='error'` by the
  scheduler's integrity pass (not in core; just log).

## 5. Invariants

INV-01 (physical separation of hidden/fresh), INV-10 (bundle round-trip exactness), INV-23 (usage events).
Tests: role `app` cannot `SELECT` from the private database (SPEC-03 provisions it; this spec's test asserts the
main DB has no table or column that could hold a hidden URL beyond `capture`/`site`, and that the eval-private
store is a different DSN).

## 6. Testing strategy

- Migrations: upgrade/downgrade round trip in CI.
- Queue: concurrency test with 8 async workers claiming 1,000 tasks; each task claimed exactly once; expired
  leases are reclaimed; cancelled jobs' tasks are not executed.
- Bundle: Hypothesis property test `decode(encode(b)) == b` over random bodies/headers/network lists.
- Storage: contract test suite run against `fs` and (optionally, when credentials exist) `s3`.
- No site names: fixtures use `example.test` hosts.

## 7. Acceptance criteria

- All §6 tables exist with the listed columns; `alembic upgrade head` from empty succeeds.
- 10k synthetic tasks drain through 4 workers with zero double-claims (test).
- `expire_captures` removes bundles and rows past `expires_at` and never touches `eval/` prefixes.
- Bundle round-trip property test passes.

## 8. PR plan

| # | Title | Scope | Checks | Done when |
|---|---|---|---|---|
| 1 | Core tables: project, api_key, site, schema_def | models + migration + default project | migrations, mypy | Tables exist; unique(host) enforced. |
| 2 | Job, url_task, job_event tables and state machine | models, `db.jobs`, migration | unit | Transitions tested. |
| 3 | Queue claim/lease/retry + worker loop skeleton | `db.queue`, `worker.loop`, `crawlerai worker` CLI | concurrency test | No double claims. |
| 4 | Scheduler loop + lease release | `scheduler.loop`, `crawlerai scheduler` | unit | Expired leases requeued. |
| 5 | Object store (fs, s3) + capture bundle format | `storage/*`, property test | property | Round trip exact. |
| 6 | capture, extraction, candidate, record, url_state, progressive_state, extraction_config tables | models + migration | migrations | Indexes present. |
| 7 | usage_event + budgets + engine_version | `db.usage`, `core.engine_version` | unit | Atomic increments tested. |
| 8 | Retention jobs | `expire_captures`, `expire_candidates` | unit | Eval prefixes untouched. |

## 9. Open issues

- **Review finding (C1 leak via `capture`/`site`).** Resolved in ARCHITECTURE rev 5 C1, §6 and §15: hidden and
  fresh pages, captures and site metadata live only in the private database and store.
- **Review finding (§14 without columns).** Resolved in ARCHITECTURE rev 5 §6 (`url_state.missing_runs`,
  `gone_at`; `record.version`, `changed_fields`). Only `supersedes_record_id` remains plumbing.
- **Review finding (§17 SSE source).** Resolved in ARCHITECTURE rev 5 §17 (run events stored in Postgres) and §6
  (plumbing in SPEC-01): `job_event`.
- **Site identity.** Resolved in ARCHITECTURE rev 5 §6: `host` is exact, lowercased, unique. `www.example.com`
  and `example.com` are therefore two sites; no public-suffix logic.
- **Config ↔ schema.** ARCHITECTURE rev 22 §5.2 and §6 (Appendix A #43): schemas have no versions; configs
  reference `schema_id`, and an edit suspends the schema's active configs so its sites learn again.
- **Migrations.** The project is greenfield (Appendix A #43): one baseline revision holds the whole schema and
  is edited when the models change; databases are recreated, never migrated with data steps.
