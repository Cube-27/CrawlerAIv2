# REST API Specification

## Purpose

The FastAPI application under `/v1`: API-key authentication and rate limiting, RFC 9457 problem responses, the
synchronous `POST /v1/scrape`, and the schema, config, record, replay and LLM-usage endpoints. Every endpoint is a
thin translation into the `crawlerai.services` layer, which the MCP server and the UI also call. Async job endpoints
are in [jobs](../jobs/spec.md); `map` and `crawl` discovery in [crawl-map](../crawl-map/spec.md).
Design rationale: [ARCHITECTURE §13](../../design/api.md), [§17, §18](../../design/operations.md). History:
[SPEC-07](../../changes/archive/2026-10-13-spec-07-api-foundation-and-scrape/SPEC-07-api-foundation-and-scrape.md)
and its [decisions](../../changes/archive/2026-10-13-spec-07-api-foundation-and-scrape/decisions.md);
[SPEC-10](../../changes/archive/2026-10-14-spec-10-jobs-crawl-extract-mcp/SPEC-10-jobs-crawl-extract-mcp.md) and its
[decisions](../../changes/archive/2026-10-14-spec-10-jobs-crawl-extract-mcp/decisions.md).

## Requirements

### Requirement: One service layer
Routers SHALL only translate HTTP to and from the service models of `crawlerai.services`; REST, MCP and the UI SHALL
call the same service functions, and the services SHALL hold no HTTP types. `services` is its own import layer under
`api | mcp_server`, and request models (e.g. `NewSchema`, `SchemaContent`) live in the service.
Refs: §3, SPEC-07 §4.7, D-0398, D-0697.

#### Scenario: Service tested without HTTP
- **WHEN** a service function is tested
- **THEN** it is called directly, not through the HTTP app

### Requirement: API keys from the CLI only
API keys SHALL be `ck_` + 32 random bytes in base62, stored only as `sha256(key)`, shown once at creation and sent as
`Authorization: Bearer ck_…`. `crawlerai apikey create --label …` prints `{id, label, key, webhook_secret}`; `apikey
revoke <id>` prints `{id, revoked}` (`false` when already revoked, keeping the first `revoked_at`) and exits 2 for an
unknown id. An unknown or revoked key SHALL get 401 `unauthorized` with `WWW-Authenticate: Bearer`. `last_used_at` is
updated at most once per minute. Every operation but `/healthz` declares `HTTPBearer` in OpenAPI.
Refs: §18, SPEC-07 §4.2, D-0382, D-0641, D-0807, D-0886.

#### Scenario: Revoked key
- **WHEN** a request carries a key whose `revoked_at` is set
- **THEN** the answer is 401 `unauthorized`

### Requirement: Rate limit before any lookup
Authenticated routes SHALL be rate limited before any DB lookup by an in-process token bucket per API process
(default 20 requests/s, burst 40), keyed by `sha256(key)[:16]` for a request with a bearer key (so unknown keys are
limited too) and by client address for one without. An exceeded limit SHALL answer 429 `rate_limited` with
`Retry-After` in whole seconds, rounded up. `/healthz` is not limited; the eval API requires the key and is limited.
Refs: §18, SPEC-07 §4.2, D-0380, D-0716.

#### Scenario: Burst exceeded
- **WHEN** a key sends more requests than the bucket holds
- **THEN** the next request gets 429 with `Retry-After` and no database query is made for it

### Requirement: Trusted proxies and no key creation at startup (INV-32)
`Forwarded`/`X-Forwarded-*` headers SHALL be honoured only when the peer is in `CRAWLERAI_TRUSTED_PROXIES` (a JSON
list of addresses or networks, empty by default); hops are read right to left through trusted proxies, the first
untrusted hop is the client, an unreadable hop stops the walk at the last readable address, and `Forwarded` is
preferred to `X-Forwarded-For`. API and worker startup MUST NOT create, reactivate or reset API keys; keys come only
from the CLI.
Refs: §18, RFC 7239 §8.1, Appendix A #32, SPEC-07 §4.2, D-0381.
Enforced by: router test with spoofed headers; startup test that no key is created; review; status: SPEC-07 (tests:
SPEC-07 PR 2).

#### Scenario: Spoofed forwarded header
- **WHEN** a peer that is not a trusted proxy sends `X-Forwarded-For: 192.0.2.7`
- **THEN** the rate limiter uses the peer's own address

#### Scenario: Startup leaves keys alone
- **WHEN** the app is created and a worker starts
- **THEN** the `api_key` table is unchanged

### Requirement: No browser session surface
The API SHALL issue no cookies and no sessions, so it has no CSRF surface. The web UI never handles a key: whatever
serves it attaches the bearer key from `CRAWLERAI_UI_API_KEY`, and the UI is served on localhost or a private network
only (see [frontend-app](../frontend-app/spec.md)).
Refs: §18, Appendix A #38.

#### Scenario: No cookie
- **WHEN** any endpoint answers
- **THEN** the response sets no cookie

### Requirement: Problem responses
Every error SHALL be `application/problem+json` `{type, title, status, detail, instance, errors?: [{field, reason}]}`
with `instance` the request path. Types: `validation` (422), `unauthorized` (401), `rate_limited` (429), `not_found`
(404, also for an unknown path), `conflict` (409), `timeout` (504), `fetch_failed` (listed in SPEC-07; no endpoint
answers it, since fetch errors are outcomes), `budget_exhausted` (422),
`ssrf_rejected` (422), `records_unavailable` (503), `llm_unavailable` (503), `llm_refused` (502), `llm_output_invalid`
(502); any other HTTP error is `about:blank` with the status phrase, and a 500 withholds the message. Validation
errors use one wording: a dotted path with list indexes in brackets (`urls[0]`) and the validator's own message.
Refs: SPEC-07 §4.3, D-0362, D-0364, D-0397, D-0467, D-0505, D-0885, D-1056, Appendix A #44.

#### Scenario: Bad URL in a list
- **WHEN** a batch body's second URL is not absolute
- **THEN** the answer is 422 `validation` with an error on field `urls[1]`

### Requirement: Health and OpenAPI
`GET /healthz` (unauthenticated) SHALL answer `{status: "ok", eval_ui, llm}` after a `SELECT 1` bounded at 5 s, with
`llm` one of `checking | ok | unavailable` while staying 200; without a database it answers 503 `unavailable`. The
OpenAPI document SHALL be served at `/v1/openapi.json` and committed as `frontend/openapi.json`.
Refs: SPEC-07 §4.6, D-0365, D-0366, D-0935.

#### Scenario: LLM setup refused
- **WHEN** the configured model is refused at startup
- **THEN** `/healthz` answers 200 with `llm: "unavailable"`

### Requirement: Synchronous scrape
`POST /v1/scrape` `{url, formats, schema?, page_kind?, max_age=0, fetch, locale?, timeout_s=60, budget}` SHALL fetch
one URL inline in the API process under a `job(kind='scrape')` with one `url_task`, and answer 200 with `job_id,
capture_id, url, final_url, fetched_at, outcome, fetch, usage` plus one member per requested format (`markdown`,
`html`, `raw_html`, `links`, `metadata`, `records`); a format not requested is omitted, never null. `timeout_s` is at
most 120; past it the answer is 504 `timeout`, the job is `failed` and nothing partial is returned.
`budget.llm_calls` defaults to 10. Formats are built per [extraction](../extraction/spec.md).
Refs: §13.1, SPEC-07 §4.4, D-0028, D-0427, D-0428, D-0431.

#### Scenario: Timeout
- **WHEN** a scrape exceeds its `timeout_s`
- **THEN** the answer is 504 `timeout` and the job is `failed`

### Requirement: Scrape outcomes, not errors, for page failures
A page that was not reached SHALL answer 200 with its `outcome` (`blocked`, `shell`, `not_found`, `failed`) and no
format, record or draft. A robots.txt disallow or unreachable robots.txt is `blocked` (task `last_error` `robots` /
`robots_unreachable`) with `capture_id`, `final_url`, `fetched_at` and `fetch` null. A reached page without `records`
is `extracted`. A resolution failure is `failed` (`extraction_error`); an undeclared exception fails task and job with
`internal_error`. Request-level failures (validation, timeout, SSRF, budget, LLM) are problems.
Refs: SPEC-07 §4.8, D-0423, D-0424, D-0425, D-0504, D-0749.

#### Scenario: Robots disallow
- **WHEN** robots.txt disallows the URL
- **THEN** the answer is 200, outcome `blocked`, with null `capture_id` and no format members

### Requirement: SSRF refusal is a problem
Every SSRF refusal (DNS failure included) of a request target SHALL be a 422 `ssrf_rejected` with the guard's reason
as `detail`, checked before any job is created; a refused redirect hop fails the job and stores no capture. The guard
itself is in [acquisition](../acquisition/spec.md) (INV-16).
Refs: §18, SPEC-07 §5, D-0426, D-0655.

#### Scenario: Private target
- **WHEN** `url` resolves to a private address
- **THEN** the answer is 422 `ssrf_rejected` and no job row exists

### Requirement: Scrape records and schema
`records` SHALL need a `schema` and a `page_kind`, and the schema's page kind MUST equal `page_kind` (else 422 on
`schema`, before any job). `schema` is `{id}`, `{inline}`, `{prompt}` or `{fields}`. An inline schema is stored once
as `origin=user` or matched to its name when the document is equal (a different document under the name is 409;
concurrent first uses share one row). A `prompt` is drafted by role S only from a page reached `extracted` and is
returned as `schema`; `fields` is drafted before the job (see [schemas](../schemas/spec.md)). Records run in the
site's progressive mode with role C, a page whose required fields don't all publish returns `complete=false` with
outcome `partial` (a listing with no rows is `partial` with no record), and each listing record carries the page's
record confidence. Without the engine data files `records` is 503 `records_unavailable`.
Refs: §5.4, §10, SPEC-07 §4.4, D-0466, D-0501, D-0502, D-0505, D-0714, D-0904, D-0930, D-0931.

#### Scenario: Schema of another page kind
- **WHEN** `schema.id` names a listing schema and `page_kind` is `detail`
- **THEN** the answer is 422 `validation` on `schema` and no job is created

### Requirement: Capture reuse with max_age
With `max_age > 0` a scrape SHALL reuse the latest `ok`, unexpired capture of the request's canonical URL in the same
site fetched within `max_age` seconds; a reused capture skips robots.txt and the rate limit, counts no usage, and
`fetch` is its original fetch. A capture whose bundle is gone is fetched anew.
Refs: §13.1, SPEC-07 §4.4, D-0503.

#### Scenario: Recent capture
- **WHEN** the URL was fetched `ok` 30 s ago and `max_age` is 60
- **THEN** no request is sent and the answer carries that capture's id

### Requirement: Response field shape
Every record field in a response SHALL carry `value, status, evidence, confidence, calibrated, locator` plus `reason,
source_kind, derived_by`, and each record `mode` and `complete`; a row-mapped field also carries `items` and
`dropped`. Values are serialized unchanged (INV-22, INV-27; see [resolution](../resolution/spec.md)). `usage` returns
`llm_calls, llm_tokens_in, llm_tokens_out, browser_seconds, http_requests`, counting every fetch attempt, robots.txt
included (INV-23).
Refs: §13.1, §17, SPEC-07 §4.4, D-0430.

#### Scenario: Abstained field
- **WHEN** a field does not publish
- **THEN** it is present with its `status` and `reason` and a null `value`

### Requirement: Schema endpoints
`/v1/schemas` SHALL offer `POST` (201 with `Location`, `origin=user`), `GET` (`{items}` by name, filters `name`,
`status`), `GET /{id}`, `PUT /{id}` (replaces the document in place, see [schemas](../schemas/spec.md)) and `DELETE
/{id}` (204, retires, idempotent; records keep their rows). A preset, a retired schema or a taken name SHALL answer
409 `conflict`. `POST /v1/schemas/draft {fields, page_kind}` returns the field-name draft (502/503 on LLM failure).
Refs: §5.2, §13.1, SPEC-07 §4.6, D-0396, D-0397, D-0398, D-0950, D-0927.

#### Scenario: Edit a preset
- **WHEN** `PUT /v1/schemas/{id}` names a preset
- **THEN** the answer is 409 `conflict`

### Requirement: Config endpoints
`GET /v1/sites/{host}/configs`, `GET` and `PUT /v1/configs/{id}` (operator corrections, C5), `POST
/v1/configs/{id}/export` and `POST /v1/sites/{host}/learn` (202) SHALL expose the config behaviour of
[learning-configs](../learning-configs/spec.md).
Refs: §13.1, SPEC-08.

#### Scenario: Force learning
- **WHEN** a caller posts to `/v1/sites/{host}/learn`
- **THEN** the answer is 202 and a learn job is started

### Requirement: Records and replay endpoints
`GET /v1/records?job_id|site|schema_id|changed_since&cursor&limit` SHALL page records newest first by id (keyset
cursor, `limit` default 50, at most 200; `site` compared without case), each the scrape record plus `capture_id`
(null once expired), `schema_id` and `version`. `POST /v1/captures/{id}/replay {allow_llm=false}` SHALL run the
current engine cold on the capture against its records' schemas and return `records`, unpersisted, without role C; a
capture with no record is 409, an unknown or expired one 404.
Refs: §13.1, §15, SPEC-07 §4.6, D-0523, D-0524, D-0525; `changed_since` in [recurring](../recurring/spec.md).

#### Scenario: Replay is not stored
- **WHEN** a capture is replayed
- **THEN** records are returned without ids and nothing is written

### Requirement: LLM usage endpoints
`GET /v1/usage/llm?start&end` SHALL return `{start, end, currency: "USD", total, days, breakdown, top_jobs}` for the
UTC days `start`–`end` inclusive (default the 30 days through today, at most 366; a reversed or longer range is 422):
each part with `calls, tokens_in, tokens_out, unpriced_tokens, estimated_usd` (null when some tokens have no price),
`days` every day of the range, `breakdown` per provider, model and `prompt_kind`, `top_jobs` the 10 costliest.
`GET /v1/usage/llm/jobs` pages the jobs with LLM calls in the range as `/v1/jobs` does. It is an estimate, not
billing; there is no MCP tool.
Refs: §1, §13.1, §17, SPEC-10 §4.2, ARCHITECTURE rev 11.

#### Scenario: Range too long
- **WHEN** `start` and `end` are 400 days apart
- **THEN** the answer is 422 `validation`
