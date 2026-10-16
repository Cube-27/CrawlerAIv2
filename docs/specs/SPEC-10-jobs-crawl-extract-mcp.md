# SPEC-10 — Async jobs, map, crawl frontier, extract, batch, SSE, webhooks and the MCP server

Layer: L3. Architecture refs: §13 (all), §4 (Discovery), §17 (run events over SSE), §23 (what v2 does instead of
a page-type gate), §18 (MCP untrusted content), §21 L3.

## 1. Summary

The asynchronous half of the API on top of SPEC-07's service layer: batch scrape, `map` (sitemaps + links),
`crawl` with a canonicalizing frontier and page-kind rules per URL pattern, `extract` over URLs/globs in
progressive mode, job status/cancel/results, SSE progress, completion webhooks, and the MCP server as a thin
adapter over the same services (§3: "MCP and the UI hold no logic of their own").

## 2. Scope

Core:
- `POST /v1/batch/scrape`, `POST /v1/map`, `POST /v1/crawl`, `POST /v1/extract`, `GET /v1/jobs`,
  `GET/DELETE /v1/jobs/{id}`, `GET /v1/jobs/{id}/results`, `GET /v1/jobs/{id}/events` (SSE), webhooks,
  `GET /v1/usage/llm`, `GET /v1/usage/llm/jobs`.
- Crawl frontier: sitemaps, page links, pagination (SPEC-05 4.12); canonicalization, dedup, include/exclude
  globs, depth, limit; page-kind rules; URLs matching no rule are link-only (§13.2, §23).
- MCP server: official SDK, stdio + streamable HTTP, API-key auth, the ten tools of §13.3, output rules.
- SSRF tests at the endpoint level (§21 L3 done-when).

Out of scope:
- Web search, browser actions, authenticated crawls (Appendix A #21, §22).
- Page-type detection (§23). Adaptive scheduling (§22). Scheduled/recurring job storage (see SPEC-11).
- Site health dashboards/alerts (§22).

## 3. Dependencies

- SPEC-01 (queue, `job_event`), SPEC-02, SPEC-05, SPEC-06, SPEC-07, SPEC-08 (progressive mode, record
  exporters).
- OPEN_QUESTIONS: none new. MCP SDK license **MIT [verified 2026-10-12]**, package `mcp`.

## 4. Design

### 4.1 Modules

- `crawlerai.services.jobs` — create/status/cancel/results; `crawlerai.services.{batch,map,crawl,extract}`.
- `crawlerai.crawl.canonical` — URL canonicalization (SPEC-04 url rules + sorted query, drop `utm_*`? **No**: no
  parameter-name lists (C4); only the WHATWG/RFC 3986 normalizations, plus fragment removal).
- `crawlerai.crawl.sitemaps` — robots `Sitemap:`, `/sitemap.xml`, sitemap indexes, gzip; sitemaps.org protocol.
- `crawlerai.crawl.frontier` — rules, dedup, enqueue.
- `crawlerai.crawl.rules` — glob matching (`fnmatch`-style over the canonical URL), page-kind rules.
- `crawlerai.worker.handlers.{scrape,crawl,extract}` — task handlers registered with the worker loop.
- `crawlerai.api.routers.{jobs,batch,map,crawl,extract,events}`; `crawlerai.api.webhooks`.
- `crawlerai.mcp_server.server` — tools; `crawlerai.mcp_server.__main__` (stdio) and the HTTP mount under
  `/mcp` in the API app.

### 4.2 Jobs

- Common response: `{id, kind, status, created_at, started_at, finished_at, counts: {queued, claimed, done,
  failed, cancelled}, outcomes: {extracted, partial, unchanged, links_only, blocked, shell, not_found, no_match,
  failed}, usage, webhook_url, engine_version, cancel_requested}` (outcome names as `url_task.outcome`, §6).
  `cancel_requested` is true once a cancel was asked for; a running job stays `running` until its claimed tasks end.
  Added with owner approval (ARCHITECTURE rev 12, D-0745).
- A job pins, when submitted, the schema document (`job.pinned.schema`), site config versions, calibration, source precedence and LLM
  settings it runs with; later changes apply only to jobs submitted after them (INV-28).
- Each task runs in its own DB session and transaction; a failed task or a crashed browser never fails the job's
  other tasks, and a crashed shared browser is restarted at most once per task (INV-31).
- `GET /v1/jobs?kind&status&cursor&limit` → `{items: [job summary], next_cursor}`: every job, newest first (by
  id; ids are UUIDv7), optionally only those of one `kind` and/or one `status`. Pagination as `/results`: `limit`
  1–200 (default 50); pass `next_cursor` as `cursor` for the next page; `next_cursor` is null on the last page.
  Added with owner approval (ARCHITECTURE rev 10, D-0700); no MCP tool (§13.3).
- `GET /v1/usage/llm?start&end` → `{start, end, currency, total, days, breakdown, top_jobs}`: the LLM calls of
  the UTC days `start`–`end` (both included; default the 30 days through today; at most 366 days), each part with
  `calls`, `tokens_in`, `tokens_out`, `unpriced_tokens` and `estimated_usd` (null when some tokens have no price,
  SPEC-06 §4.8). `days` lists every day of the range; `breakdown` is per provider, model and `prompt_kind`;
  `top_jobs` the 10 costliest jobs. `GET /v1/usage/llm/jobs?start&end&cursor&limit` → the jobs with LLM calls in
  the range, newest first, paginated as `/v1/jobs`. The job summary carries `llm_cost_usd` over all its calls.
  Added with owner approval (ARCHITECTURE rev 11); no MCP tool (§13.3).
- `DELETE /v1/jobs/{id}` → `cancel_requested` (SPEC-01); status becomes `cancelled` when no task is running.
- `GET /v1/jobs/{id}/results?cursor&limit&format=json|json_records|csv_records|markdown|json_values` → paginated records (SPEC-07
  field shape) or page outputs for format jobs; exporters from SPEC-08 4.11 for `csv_records`/`markdown`; `json_values` items per SPEC-14 §4.4. A page
  output carries its task's `last_error: str | null`: why it failed, or why it ended with its outcome when the
  outcome alone does not say (a `blocked` task's `robots`), as the worker recorded it (SPEC-01 §4.8). Added with
  owner approval (ARCHITECTURE rev 12, D-0745). `csv_safe=true`, accepted with `csv_records` only (else 422),
  prefixes `'` to each cell starting with `=`, `+`, `-`, `@`, a tab or a carriage return (OWASP CSV Injection);
  the UI's Export CSV sends it. Without it the export is unchanged (INV-27). Added with owner approval
  (ARCHITECTURE rev 18, D-0879).
- `GET /v1/jobs/{id}/events` → SSE from `job_event` ordered by id, `Last-Event-ID` resume, heartbeat every 15 s,
  event kinds: `task_fetched` (method, block_class), `task_extracted` (outcome, mode, llm_calls), `task_abstained`
  (fields), `task_failed` (task_id, url, attempts, last_error; when a task ends `failed`, after its last attempt or a
  permanent failure; added with owner approval, ARCHITECTURE rev 12, D-0745), `drift_suspended`,
  `learning_started/finished`, `progress` (counts), `completed`, `failed`, `cancelled`. Payloads contain the task URL (the caller supplied the job) — no redaction needed at the API, but
  the worker's logs still honour `CRAWLERAI_LOG_REDACT_URLS`.
- Webhook: on `completed`/`failed`/`cancelled`, `POST webhook_url` with the job summary, header
  `X-CrawlerAI-Signature: sha256=HMAC(secret, body)` where the secret is per API key (plumbing column
  `api_key.webhook_secret`), 3 attempts with backoff; the webhook target passes the SSRF guard too.

### 4.3 `POST /v1/batch/scrape`

`{urls: [...≤ 1000], formats, schema?, page_kind?, fetch?, budget?, webhook_url?}` (`schema` by id, inline or `fields`,
SPEC-07 §4.4) → `{job_id}` (`job.kind =
batch_scrape`); one `url_task` per URL; handler = SPEC-07's scrape function; results via `/results`. URLs are
caller-supplied: incomplete pages return records with `complete=false`, outcome `partial` (§10).

### 4.4 `POST /v1/map` (sync)

`{url, include: [globs], exclude: [globs], limit: 5000, use_sitemaps: true, use_links: true}` → `{urls: [...],
sources: {sitemap: n, links: n}, truncated: bool}`.
- Sitemaps: robots `Sitemap:` lines, else `/sitemap.xml`; indexes followed to depth 3; ≤ 50k URLs read;
  same registrable host as the start URL — defined as the same exact host (SPEC-01 site identity): the host the
  start URL's own redirects end on (D-0991).
- Links: fetch the start URL (HTTP rung only) and take `links` (SPEC-07 4.5) on the same host.
- Timeout 60 s; the result is not persisted (a `job(kind='map')` row records usage only).

### 4.5 `POST /v1/crawl`

```jsonc
{ "url": "https://…", "include": ["https://…/products/*"], "exclude": [], "max_depth": 3, "limit": 500,
  "formats": ["markdown"],
  "schema": { "id": "…" } | { "inline": { … } } | { "fields": ["…"] } | null,   // fields: drafted for the rules' one page kind
  "page_kind_rules": [ { "pattern": "https://…/p/*", "page_kind": "detail" }, { "pattern": "https://…/c/*", "page_kind": "listing" } ],
  "fetch": {...}, "budget": {...}, "webhook_url": null }
```
- Frontier: seeds = start URL + sitemap URLs that match `include`; each fetched page contributes `links` and
  pagination candidates (SPEC-05 4.12) on the same host; canonicalized; `url_task` UNIQUE (`job_id`,
  `canonical_url`) dedups; `depth` = parent depth + 1, cut at `max_depth`; `limit` counts enqueued tasks.
- A task whose URL matches a `page_kind_rules` pattern is extracted with that page kind and the job's schema
  (progressive mode per site); a task matching no rule is fetched for links only and never extracted (§13.2,
  §23); its outcome is `links_only` (§6).
- Crawl URLs are crawl-discovered: a page whose required fields don't all publish has outcome `no_match`
  (SPEC-05 4.10), produces no record, and is reported in `outcomes` (§10).
- Politeness is per site (SPEC-02); a crawl of one site runs at ~1 req/s regardless of worker count.

### 4.6 `POST /v1/extract`

`{urls: ["https://…/p/*", "https://…/p/123"], schema (id, inline, prompt or fields), page_kind, limit, fetch?, budget?, webhook_url?}`
→ `{job_id, schema}` (draft returned immediately when a prompt is used; role S runs synchronously on the first
1–3 concrete URLs). Globs are expanded through `map` on their host; every task is extracted with the given
page kind in the site's progressive mode (cold → learning → active, SPEC-08). `extract` URLs are
caller-supplied (§10): incomplete pages return records with `complete=false`, outcome `partial`. This includes
URLs expanded from a caller's glob (see Open issues).

### 4.7 MCP server (§13.3)

- `mcp` Python SDK (MIT); `FastMCP`-style server exposing tools: `scrape`, `map`, `crawl_start`, `crawl_status`,
  `extract`, `extract_status`, `list_schemas`, `create_schema`, `get_site_config`, `export_config`. Each tool's
  body is one call into `crawlerai.services.*` — no logic, no HTTP round trip.
- Transports: stdio (`python -m crawlerai.mcp_server`, API key from `CRAWLERAI_API_KEY`) and streamable HTTP
  mounted at `/mcp` in the API app (bearer header). Both use the same auth dependency.
- Output rules: `scrape` markdown is returned in pages of ≤ 20,000 characters with a `cursor`; records are
  returned with `status` and `confidence` per field and the text "unknown" for non-published fields in the
  human-readable summary; `crawl_start`/`extract` return `{job_id}` and the status tools return the job summary
  plus the first page of results.
- Untrusted content: page text is returned inside a tool result as data; the server has no tools that take
  free-form instructions from page content; tool descriptions state that page content may contain prompt
  injection and must be treated as data by the client.

### 4.8 Error handling

Problem details as SPEC-07. Task-level errors are outcomes, not job failures; a job fails only if every task
failed or the budget is exhausted before any task completes. Webhook delivery failure never fails the job.

## 5. Invariants

INV-16 (endpoint-level SSRF tests including `webhook_url` and sitemap URLs), INV-22, INV-23, INV-03 (`crawl/`
has no hostnames; glob patterns come from requests), INV-27 (exporters serialize
published values unchanged), INV-28 (settings pinned at submit), INV-31 (task isolation).

## 6. Testing strategy

- Frontier: property tests for canonicalization idempotence and dedup; depth/limit boundaries; include/exclude
  precedence (exclude wins); link-only tasks never extracted.
- Sitemaps: fixtures for index + gzip + robots `Sitemap:`; host restriction.
- Jobs: lifecycle through the real queue with a local test server (`.test` hosts via stub resolver); cancel
  mid-run; results pagination; SSE resume with `Last-Event-ID`; webhook signature and retries.
- SSRF: endpoint tests submitting private IPs/hostnames in `url`, `urls`, sitemap locations, redirect targets
  and `webhook_url` → rejected.
- INV-27: property test over generated records: the values in `GET /v1/jobs/{id}/results` (JSON and each
  `?format=` export) equal the stored `record` values.
- INV-28: change calibration and a site config while a job runs; the job's remaining tasks still use the
  versions pinned at submit, and a job submitted after the change uses the new ones.
- INV-31: a batch with one task that raises completes the other tasks; a killed shared browser fails only the
  task that was using it, and is restarted at most once for that task.
- MCP: in-process client from the SDK calls each tool against a test app; pagination cursor; "unknown" rendering.
- No site-named tests.

## 7. Acceptance criteria (§21 L3 done-when)

- Every endpoint of §13.1 works through REST and through the MCP tools on dev-set sites served by the local
  replay server.
- SSRF test matrix passes at the endpoint level.
- A crawl with page-kind rules extracts only matching URLs; `outcomes` counts match the task table.

## 8. PR plan

| # | Title | Scope | Checks | Done when |
|---|---|---|---|---|
| 1 | Job summary/status/cancel/results endpoints | `services/jobs`, routers | router tests, property | Lifecycle tested; INV-27 results-equal-stored property test passes. |
| 2 | `batch/scrape` + worker handler registration | `services/batch`, handlers | queue tests | Results paginate; INV-28 pinned-settings and INV-31 task-isolation tests pass. |
| 3 | Canonicalization + sitemaps + `map` | `crawl/canonical,sitemaps`, `services/map` | unit, property | Map returns URLs. |
| 4 | Frontier, rules, `crawl` | `crawl/frontier,rules`, handler | integration | Link-only vs extracted. |
| 5 | `extract` with globs and prompt | `services/extract` | integration | Draft returned. |
| 6 | SSE events + webhooks | `routers/events`, `api/webhooks` | unit | Resume + signature. |
| 7 | MCP server (stdio + HTTP) | `mcp_server/*` | SDK client tests | All ten tools. |
| 8 | Endpoint-level SSRF matrix | tests | unit | All rejected. |
| 9 | `GET /v1/jobs` list | `services/jobs`, `routers/jobs` | router tests | Newest first; `kind`/`status` filters; cursor pages. |
| 10 | `GET /v1/usage/llm`, `GET /v1/usage/llm/jobs`, `llm_cost_usd` (with SPEC-06 PR 7, SPEC-12 PR 11; one PR) | `services/llm_costs`, `routers/usage`, `services/jobs` | router tests, db | Range totals, days, breakdown, top jobs; job cursor pages; bad ranges 422. |

## 9. Open issues

- **Review finding (link-only outcome).** Resolved in ARCHITECTURE rev 5 §6: outcome `links_only`; the plumbing
  flag is dropped.
- **`map` host scope** is the exact host (§6: `site.host` is exact); subdomain crawling requires explicit
  `include` globs. Confirm.
- **Glob-expanded `extract` URLs.** §10 lists `extract` as caller-supplied, but URLs expanded from a glob through
  `map` were discovered by us. Resolved in ARCHITECTURE rev 5 §10: they count as caller-supplied (`partial`
  records).
- **Webhook secret** per API key is plumbing (`api_key.webhook_secret`).
- MCP `create_schema` is write access from agents; the API key decides, same as REST.
