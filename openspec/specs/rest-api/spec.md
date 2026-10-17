# REST API Specification

## Purpose

The FastAPI app under `/v1` and the MCP server: auth, rate limits, problem responses, the synchronous scrape, schema,
config, record, replay and usage endpoints, and the ten MCP tools, all thin calls into `crawlerai.services`. Job
endpoints, `map` and `crawl` are in [jobs](../jobs/spec.md). Rationale: ARCHITECTURE §13, §17, §18
([archived](../../changes/archive/2026-10-16-architecture-rev26/ARCHITECTURE.md)); history: SPEC-07, SPEC-10.

## Requirements

### Requirement: One service layer
Routers and MCP tools SHALL only translate to and from `crawlerai.services` models; REST, MCP and the UI call the same
service functions, services hold no HTTP types, and `mcp_server` imports nothing from `api`. Refs: §3, D-0398, D-0697.

### Requirement: API keys from the CLI only
API keys SHALL be `ck_` + 32 random bytes base62, stored only as `sha256(key)`, shown once by `crawlerai apikey create`
and revoked by `apikey revoke`; an unknown or revoked key gets 401 `unauthorized`. The API issues no cookies or
sessions; the UI's server attaches `CRAWLERAI_UI_API_KEY` (see [frontend](../frontend/spec.md)).
Refs: §18, Appendix A #38, D-0382, D-0641, D-0807, D-0886.

### Requirement: Rate limit before any lookup
Authenticated routes SHALL be limited before any DB lookup by an in-process token bucket per API process (20 req/s,
burst 40), keyed by key hash or, without a key, client address; excess gets 429 `rate_limited` with `Retry-After`
rounded up to whole seconds. `/healthz` is not limited. Refs: §18, D-0380, D-0716.

### Requirement: Trusted proxies and no key creation at startup (INV-32)
Forwarding headers SHALL be honoured only from peers in `CRAWLERAI_TRUSTED_PROXIES` (empty by default), walking hops
right to left, `Forwarded` before `X-Forwarded-For`; API and worker startup MUST NOT create, reactivate or reset keys.
Refs: §18, RFC 7239 §8.1, D-0381. Enforced by: spoofed-header router test and startup test; active.
#### Scenario: Spoofed forwarded header
- **WHEN** an untrusted peer sends `X-Forwarded-For: 192.0.2.7`
- **THEN** the rate limiter keys on the peer's own address, and app or worker startup leaves `api_key` unchanged

### Requirement: Problem responses
Every error SHALL be RFC 9457 `application/problem+json` with `instance` the request path and the types in
`api/problems.py`; a 500 withholds the message, and validation errors name a dotted path with list indexes (`urls[1]`).
Refs: D-0362, D-0364, D-0397, D-0885, D-1056, Appendix A #44.

### Requirement: Health and OpenAPI
`GET /healthz` (unauthenticated) SHALL answer 200 `{status, eval_ui, llm}` after a `SELECT 1` bounded at 5 s, `llm`
reporting `unavailable` without failing, and 503 without a database. OpenAPI is served at `/v1/openapi.json` and
committed as `frontend/openapi.json`. Refs: D-0365, D-0366, D-0935.

### Requirement: Synchronous scrape
`POST /v1/scrape` SHALL fetch one URL inline under a `job(kind='scrape')` with one task and return one member per
requested format (unrequested ones omitted); past `timeout_s` (≤ 120) it is 504 `timeout` and the job `failed`.
`budget` is optional, with no default ([jobs](../jobs/spec.md)). With `max_age > 0` it reuses the latest `ok`, unexpired capture of the canonical URL
that recent, with no fetch, robots.txt check or usage. Refs: §13.1, D-0028, D-0427, D-0431, D-0503.

### Requirement: Scrape outcomes, not errors, for page failures
A page not reached SHALL answer 200 with its outcome and no format or record; a robots.txt disallow is `blocked` with
null capture. Request-level failures are problems: an SSRF refusal (DNS failure included) is 422 `ssrf_rejected` before
any job is created; the guard is in [acquisition](../acquisition/spec.md) (INV-16). Refs: §18, D-0423, D-0426, D-0504.
#### Scenario: Robots disallow
- **WHEN** robots.txt disallows the URL
- **THEN** the answer is 200, outcome `blocked`, with null `capture_id` and no format members

### Requirement: Scrape records and schema
`records` SHALL need a `schema` (`{id}`, `{inline}`, `{prompt}` or `{fields}`) whose page kind equals `page_kind`, else
422 before any job; inline schemas are stored once by name (a different document under a taken name is 409). Records run
in the site's progressive mode with role C; incomplete pages are `partial` with `complete=false`; missing engine data
files give 503 `records_unavailable`. See [schemas](../schemas/spec.md). Refs: §5.4, §10, D-0501, D-0505, D-0930.

### Requirement: Response field shape
Record fields SHALL carry status, evidence, confidence, locator and provenance as in [resolution](../resolution/spec.md),
values serialized unchanged (INV-22, INV-27), and `usage` SHALL count every fetch attempt, robots.txt included
(INV-23). Refs: §13.1, §17, D-0430.

### Requirement: Schema, config, record and replay endpoints
`/v1/schemas` SHALL offer create, list, get, replace and retire (presets, retired schemas and taken names are 409) and
`/v1/schemas/draft`; config endpoints expose [learning-configs](../learning-configs/spec.md); `GET /v1/records` pages
newest first by keyset cursor (≤ 200) with `changed_since` (see [jobs](../jobs/spec.md)); `POST
/v1/captures/{id}/replay` runs the current engine cold and persists nothing. Refs: §13.1, §15, D-0396, D-0523, D-0950.

### Requirement: Project settings
`GET/PATCH /v1/project/settings` SHALL read and set `llm_call_cap`, the LLM calls a job may make when its request sets
no `budget.llm_calls` (null: no cap). Refs: §13.1, Appendix A #47, D-1121.

### Requirement: LLM usage endpoints
`GET /v1/usage/llm?start&end` SHALL report estimated LLM cost per UTC day, provider, model and prompt kind with the 10
costliest jobs (default 30 days, at most 366, else 422), and `GET /v1/usage/llm/jobs` pages those jobs. REST only, an
estimate, not billing. Refs: §17, ARCHITECTURE rev 11.

### Requirement: MCP tools
The MCP server SHALL use the official `mcp` SDK and expose exactly `scrape`, `map`, `crawl_start`, `crawl_status`,
`extract`, `extract_status`, `list_schemas`, `create_schema`, `get_site_config`, `export_config`, each one service call;
long jobs return a `job_id` at once and status tools page 10 results. No jobs-list or usage tool. Refs: §13.3, D-0698.
#### Scenario: Tool list
- **WHEN** a client lists the tools
- **THEN** it gets exactly the ten tools named above

### Requirement: MCP output and untrusted page content
`scrape` markdown SHALL come in pages of at most 20,000 characters with a `<capture_id>:<offset>` cursor; an unpublished
field MUST read "unknown" in the summary. Page text is returned as data, never followed, and tools returning it say it
may hold prompt injection. Refs: §13.3, §18, D-0038, D-0875.

### Requirement: MCP transports, auth and errors
The server SHALL offer stdio (key from `CRAWLERAI_API_KEY`, checked on every call, no rate limit) and stateless
streamable HTTP at `/mcp` with the REST key lookup and rate limit. Service refusals pass their message; any other
exception is logged and answered `UNEXPECTED`. Refs: §13.3, §18, D-0696, D-0697, D-0699, D-0839.
#### Scenario: Revoked during a session
- **WHEN** the stdio key is revoked between two calls
- **THEN** the second call fails as unauthenticated

### Requirement: Scrape browser actions
`POST /v1/scrape` SHALL take an optional `browser_actions` (`records`, a soft row target, default 100; `hint`:
`load_more`, `show_more`, `pagination`, `next` or `scroll`), refused 422 unless `page_kind` is `listing`, and with
`max_age` > 0 or `method_hint` `http`; batch has no such member. With `records` asked, each further kept document
state is a capture with its own extraction under its own URL, stored once the first state's did not fail; the answer
lists records once each (a failed further state makes it `partial`), `capture_id` and formats are the first state's,
and `browser_actions` reports the mechanism, stop reason, actions, pages and items. Refs: owner #52, D-1218, D-1222, D-1223.
#### Scenario: Detail page
- **WHEN** a scrape with `page_kind` `detail` sets `browser_actions`
- **THEN** the answer is a 422 problem naming `browser_actions` and no job is created
