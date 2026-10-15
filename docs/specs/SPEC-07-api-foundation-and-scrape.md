# SPEC-07 — API foundation, authentication, page content formats and `scrape`

Layer: L1. Architecture refs: §13.1 (`scrape`, `/v1/schemas`, `/v1/records`, `/v1/captures/{id}/replay`, field
response shape), §8.5 (content outputs), §18 (access, secrets), §17 (usage), §3 (one service layer).

## 1. Summary

The FastAPI application, API-key authentication, the service layer that REST, MCP and the UI all call (§3), the
generic page-content formats (§8.5), and the synchronous `POST /v1/scrape` with `records` for L1's end-to-end
extraction (§21). Async jobs, map/crawl/extract, SSE, webhooks and MCP are SPEC-10; configs endpoints are SPEC-08.

## 2. Scope

Core:
- App factory, routers, OpenAPI export (SPEC-00 4.5), RFC 9457 problem-details errors, `/healthz`.
- API keys: create/revoke CLI, hashed storage, bearer auth, rate limit before DB lookup (§18).
- Service layer `crawlerai.services.*` with the operations the endpoints expose (MCP reuses them in SPEC-10).
- `POST /v1/scrape` (sync, timeout), formats `markdown`, `html`, `raw_html`, `links`, `metadata`, `records`;
  `schema` by id, inline, or `prompt` (role S); `page_kind`; `max_age`.
- `/v1/schemas` CRUD; `/v1/records` list; `POST /v1/captures/{id}/replay`.
- Content formats: trafilatura markdown, cleaned html, links, metadata.

Out of scope:
- Multi-tenancy, users, roles, billing, signup (§1 non-goals). UI session cookies and CSRF tokens (§18: none).
- Async endpoints, SSE, webhooks, MCP (SPEC-10). Config endpoints (SPEC-08).
- Per-site cleaning in content formats (C2).
- Web search, browser actions (Appendix A #21).

## 3. Dependencies

- SPEC-01, SPEC-02, SPEC-04, SPEC-05, SPEC-06 (role S and role C for records).
- OPEN_QUESTIONS #13: one region (no behaviour here).

## 4. Design

### 4.1 Modules

- `crawlerai.api.app` — `create_app(settings) -> FastAPI`; middleware (request id, auth, rate limit, problem
  details); OpenAPI metadata.
- `crawlerai.api.auth` — `require_api_key` dependency; `RateLimiter`.
- `crawlerai.api.routers.{scrape,schemas,records,captures,health}`.
- `crawlerai.api.dto` — request/response pydantic models (the OpenAPI contract).
- `crawlerai.services.{scrape,schemas,records,captures}` — the service layer; pure functions over sessions and
  the engine; no HTTP types.
- `crawlerai.content.{markdown,html,links,metadata}` — §8.5 formats. Each takes the `ParsedPage` (SPEC-05
  `content.page`); `scrape` builds one per capture and shares it with `records`, and trafilatura gets the page's
  lxml tree rather than the body (INV-26).
- `crawlerai.cli` — `crawlerai apikey create --label …`, `apikey revoke <id>`.

### 4.2 Authentication and rate limiting (§18)

- Key format: `ck_` + 32 random bytes base62; stored as `api_key.hashed_key = sha256(key)`; shown once at
  creation. Sent as `Authorization: Bearer ck_…`. `last_used_at` updated at most once per minute.
- Rate limit before any DB lookup: in-process token bucket keyed by `sha256(key)[:16]` (so unknown keys are
  limited too), default 20 req/s burst 40; exceeded → 429 with `Retry-After`. Multiple API replicas each keep
  their own bucket (implementation detail; the design point is one deployment).
- Revoked keys (`revoked_at` set — plumbing column, SPEC-01 4.2) → 401.
- Client identity: `Forwarded`/`X-Forwarded-*` headers are honoured only when the peer is a configured trusted
  proxy; otherwise they are ignored (RFC 7239 §8.1: the header is client-controlled). API and worker startup never
  create, reactivate or reset API keys; keys come only from the CLI (INV-32).
- UI (§18): the frontend holds the key in memory only and sends it as the bearer header. No cookies or sessions
  are issued by the API, so there is no CSRF surface.

### 4.3 Errors

RFC 9457 `application/problem+json`: `{type, title, status, detail, instance, errors?: [{field, reason}]}`.
Problem types: `validation`, `unauthorized`, `rate_limited`, `not_found`, `timeout`, `fetch_failed`,
`budget_exhausted`, `ssrf_rejected`.

### 4.4 `POST /v1/scrape`

Request:
```jsonc
{ "url": "https://…", "formats": ["markdown","records"],
  "schema": { "id": "…" } | { "inline": { …SchemaDef… } } | { "prompt": "…" } | null,
  "page_kind": "detail" | "listing" | null,            // required when formats includes records
  "max_age": 0,                                        // seconds; reuse a capture of this URL fetched within max_age
  "fetch": { "method_hint": "auto"|"http"|"browser", "respect_robots": true, "robots_override_reason": null, "proxy_pool": null },
  "locale": null, "timeout_s": 60, "budget": { "llm_calls": 10 } }
```
Response (200):
```jsonc
{ "job_id": "…", "capture_id": "…", "url": "…", "final_url": "…", "fetched_at": "…",
  "outcome": "extracted"|"partial"|"blocked"|"shell"|"not_found"|"failed",      // url_task.outcome (§6)
  "fetch": { "method": "http", "status_code": 200, "block_class": "ok", "attempts": [...] },
  "markdown": "…", "html": "…", "raw_html": "…", "links": ["…"],
  "metadata": { "title": "…", "description": "…", "language": "…", "canonical": "…", "og": {...}, "structured_data_types": ["Product","Offer"] },
  "schema": { "id": "…", "name": "…", "version": 1, "origin": "prompt_draft", "fields": {...} },   // when a prompt was used
  "records": [ { "id": "…", "mode": "adhoc", "complete": true, "confidence": 0.97,
                 "fields": { "price": { "value": {"amount":"19.90","currency":"EUR"}, "status": "published", "reason": null,
                                        "evidence": "structured", "confidence": 0.98, "calibrated": true,
                                        "source_kind": "jsonld", "locator": "jsonld:0:$.offers.price", "derived_by": null } } } ],
  "usage": { "llm_calls": 1, "llm_tokens_in": 1200, "llm_tokens_out": 80, "browser_seconds": 0, "http_requests": 1 } }
```
Every field carries `value, status, evidence, confidence, calibrated, locator` (§13.1) plus `reason`,
`source_kind`, `derived_by` (from `field_meta`). A row-mapped field (SPEC-13 §4.8) also carries `items`, one per
published row with each sub-field's `status, reason, evidence, confidence, calibrated, source_kind, locator`, and
`dropped`, the rows that did not publish (`locators`, `reason`); other fields have neither key.

Behaviour:
1. Create `job(kind='scrape', request=frozen body)` and one `url_task` (for usage/events bookkeeping), executed
   **inline** in the API process (no queue hop — implementation detail; the worker handler is the same function).
2. `max_age > 0` and a `capture` for the canonical URL within the window → reuse; else `acquire` (SPEC-02).
3. Formats computed from the request's single `ParsedPage` (4.5, INV-26). `records` → `extract_page` (SPEC-05) in the site's progressive mode
   (cold until SPEC-08 exists; `mode` = `adhoc`), with role C when required fields are missing (SPEC-06).
   A page whose required fields don't all publish returns its record with `complete=false` and outcome
   `partial` (§10; `scrape` URLs are caller-supplied). `progressive_state.pages_extracted` is incremented when
   the outcome is `extracted` or `partial` (§8.3; SPEC-08 reads it).
4. Timeout: the whole request is bounded by `timeout_s` (max 120); on timeout → 504 problem `timeout`, the job
   is marked `failed`, nothing partial is returned.
5. `schema.prompt` → role S (SPEC-06) → the draft schema is used and returned.

### 4.5 Content formats (§8.5)

- `markdown`: trafilatura `extract(<the ParsedPage's lxml tree>, output_format="markdown", include_links=True, include_images=True)`
  with `favor_precision=True`; no per-site rules. Browser captures use the rendered body.
- `html`: body with `script`, `style`, `noscript`, `template`, event-handler attributes and `javascript:` URLs
  removed; everything else intact (no readability cleaning — that is `markdown`).
- `raw_html`: the bundle body as captured.
- `links`: every `a[href]`, `link[rel=canonical|next|prev|alternate]`, absolutized and canonicalized
  (SPEC-04 url rules), deduplicated, document order.
- `metadata`: `title` (`<title>`), `description` (`meta[name=description]`), `language` (`<html lang>` else
  `og:locale`), `canonical`, `og` (all `og:*`/`product:*` as a flat map), `structured_data_types` (distinct
  `@type` values in JSON-LD + microdata `itemtype` names).

### 4.6 Other endpoints

- `/v1/schemas`: `POST` (inline SchemaDef → `origin=user`), `GET /v1/schemas`, `GET /v1/schemas/{id}`,
  `PUT /v1/schemas/{id}` (creates version+1; schemas are immutable per version), `DELETE` (sets `status=retired`;
  rows referenced by records are never deleted).
- `GET /v1/records?job_id|site|schema_id&cursor&limit` → records with full `field_meta` in the field shape above.
- `POST /v1/captures/{id}/replay` → runs `replay_page` with the current engine and the site's active config and
  returns the `records` array (not persisted; for debugging — §13.1). `max_age` and replay never call the LLM
  unless `allow_llm=true` in the body (default false, so replays stay cheap and deterministic).
- `GET /healthz` (DB ping), `GET /v1/openapi.json`.

### 4.7 Service layer (§3)

`services.scrape.scrape(session, stores, engine, request: ScrapeRequest, api_key) -> ScrapeResult` and the
schema/record/capture equivalents. Routers only translate HTTP ↔ DTO; the MCP server (SPEC-10) calls the same
functions. Tests for the service layer do not go through HTTP.

### 4.8 Error handling

Fetch errors map to `outcome` in a 200 response (the request succeeded; the page was blocked/not found);
request-level failures (validation, timeout, SSRF, budget) are problem responses. Partial formats are never
returned on failure.

## 5. Invariants

INV-16 (SSRF rejection surfaces as a problem, never a fetch), INV-22 (field shape), INV-23 (usage returned),
INV-03 (no literals in `api/`, `content/`), INV-26 (one parse per parser per request), INV-27 (responses serialize
published values unchanged), INV-32 (trusted-proxy headers; no key creation at startup).

## 6. Testing strategy

- INV-26: a `scrape` with several formats plus `records` constructs each parser at most once per capture
  (counting test).
- Router tests with `httpx.AsyncClient` against the app and a local test server for target pages (`.test`
  hosts resolved by a stub resolver): each format, `max_age` reuse, timeout, problem responses, unknown key 401,
  rate limit 429.
- Service tests without HTTP.
- INV-32: router test with spoofed `Forwarded`/`X-Forwarded-For` headers; they change the client address used
  for rate limiting only when the peer is a configured trusted proxy. A startup test: creating the app and
  starting the worker leave the `api_key` table unchanged (no key created, reactivated or reset).
- Content formats: property test that `links` are absolute http(s) URLs; `html` contains no `<script>`;
  `metadata.language` falls back as specified.
- OpenAPI snapshot test (the committed `frontend/openapi.json` matches).
- No site-named tests.

## 7. Acceptance criteria (§21 L1: "`scrape` endpoint with records and markdown")

- `POST /v1/scrape` with `formats=[markdown, records]` and `schema.id=<commerce_detail>` on a dev capture
  URL returns records whose fields carry all six §13.1 attributes.
- A prompt schema returns the draft and reuses it on the second call.
- The frontend's generated client compiles against the exported OpenAPI.

## 8. PR plan

| # | Title | Scope | Checks | Done when |
|---|---|---|---|---|
| 1 | App factory, problem details, healthz, OpenAPI export wiring | `api/app`, `api/dto` | unit | `/healthz` 200; openapi.json committed. |
| 2 | API keys: CLI, hashing, bearer auth, rate limiter | `api/auth`, `cli` | unit, router | 401/429 tested; INV-32 spoofed-header and startup-creates-no-keys tests pass. |
| 3 | Content formats | `content/markdown,html,links,metadata` | unit, property | Formats correct on fixtures. |
| 4 | Service layer + `POST /v1/scrape` (formats only) | `services/scrape`, router | router tests | Sync scrape works. |
| 5 | `records` format with schema id/inline + `max_age` | same | router + replay, parser-count test | Field shape complete; INV-26 across formats + records. |
| 6 | `schema.prompt` via role S | same | unit | Draft returned and reused. |
| 7 | `/v1/schemas` CRUD | `services/schemas`, router | unit | Versioning rules enforced. |
| 8 | `/v1/records`, `/v1/captures/{id}/replay` | `services/records,captures` | unit | Replay returns records. |

## 9. Open issues

- **Review finding (§18 UI sessions/CSRF).** Resolved in ARCHITECTURE rev 5 §18: bearer API key held in memory,
  no cookies, no sessions, no CSRF surface (4.2).
- **Sync `scrape` with a prompt** performs role S + fetch + role C inside one request; 60 s default may be
  tight with the browser rung. `timeout_s` is caller-controlled up to 120 s; beyond that use `extract` (SPEC-10).
- **Partial records on `scrape`.** Resolved in ARCHITECTURE rev 5 §10: `complete=false`, outcome `partial`.
- `api_key.revoked_at` is a plumbing column not in §6 (listed in SPEC-01 4.2).
