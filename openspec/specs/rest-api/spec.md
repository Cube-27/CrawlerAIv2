# REST API Specification

## Purpose

The FastAPI app under `/v1` and the MCP server: auth, rate limits, problem responses, the synchronous scrape, schema,
config, record, replay and usage endpoints, and the twelve MCP tools, all thin calls into `crawlerai.services`. Job
endpoints, `map` and `crawl` are in [jobs](../jobs/spec.md).

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
`budget` is optional, with no default ([jobs](../jobs/spec.md)). With `max_age > 0` and `fetch.cache` `default` it
reuses the latest `ok`, unexpired capture of the canonical URL that recent and made with the same actions, context
names (in any order, header names in any case) and, for a `screenshot`, the same area, with no fetch, robots.txt check or usage; `bypass` always fetches; `only` serves such a capture (any age when
`max_age` is 0) or is 404 `not_cached` with the job `failed`. (Previously: no `cache`.) Refs: §13.1, D-0028, D-0427,
D-0431, D-0503, D-1435.
#### Scenario: Cache only, nothing stored
- **WHEN** a scrape with `fetch.cache` `only` names a URL with no stored capture
- **THEN** the answer is 404 `not_cached` and nothing is fetched

### Requirement: Scrape outcomes, not errors, for page failures
A page not reached SHALL answer 200 with its outcome and no format or record; a robots.txt disallow is `blocked` with
null capture and `reason` `robots`, an unreadable robots.txt `blocked` with `reason` `robots_unreachable`, a host whose
turn at its rate is more than a minute off `blocked` with `reason` `slow_down` and nothing sent, and a page a vendor's
challenge kept from being reached `blocked` with `reason` `challenge: <vendor>`. A listing whose extraction gives no
rows answers `reason` `no_rows: no_blocks` (`resolve/pipeline.py`: no source stated rows and the page showed no
block of items, so role C, which fills the rows of blocks, had none to read), also the task's `last_error`, and a `page` member holding the page-scope fields in the record field
shape; `reason` is null for any other page fetched. Request-level failures are problems: an SSRF refusal (DNS failure
included) is 422 `ssrf_rejected` before any job is created; the guard is in [acquisition](../acquisition/spec.md)
(INV-16). (Previously: the no-rows cause was also role C's failure reason or `none_listed`, then `not_asked`.) Refs: §18, D-0423, D-0426,
D-0504, D-1451, D-1475, D-1476, D-1605.
#### Scenario: Robots disallow
- **WHEN** robots.txt disallows the URL
- **THEN** the answer is 200, outcome `blocked`, `reason` `robots`, with null `capture_id` and no format members
#### Scenario: Robots unreachable
- **WHEN** the URL's robots.txt answers 5xx
- **THEN** the answer is 200, outcome `blocked`, `reason` `robots_unreachable`, and the page is not fetched
#### Scenario: Listing without rows
- **WHEN** a listing whose schema has `next_page_url` and whose page has a `rel=next` link gives no rows
- **THEN** `records` is empty, `reason` is `no_rows: no_blocks` and `page.next_page_url` is published

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
`/v1/schemas` SHALL offer create, list, get, replace and retire (presets, retired schemas and taken names are 409),
`PUT /v1/schemas/{id}/labels` (the label synonyms, [schemas](../schemas/spec.md)) and `/v1/schemas/draft`; config endpoints expose [learning-configs](../learning-configs/spec.md), with
`POST /v1/configs/{id}/approve` and `POST /v1/configs/{id}/reject` (each 409 unless the config is the latest version
and `pending_approval`); `GET /v1/records` pages newest first by
keyset cursor (≤ 200) with `changed_since` (see [jobs](../jobs/spec.md)), and with `job_id` by the job's tasks, newest
task first, a record once; every paged answer (records, jobs, a job's results) carries `total`, the matching rows in all; `POST /v1/captures/{id}/replay` runs the current engine cold and persists nothing.
(Previously: no reject endpoint.) Refs: §13.1, §15, D-0396, D-0523, D-0950, D-1280, D-1342, D-1391.

### Requirement: Project settings
`GET/PATCH /v1/project/settings` SHALL read and set `llm_call_cap`, the LLM calls a job may make when its request sets
no `budget.llm_calls`, `draft_call_cap`, the uncharged role S calls one API key may make (null: no cap), and
`require_config_approval`, whether a learned config waits for approval (off until set). (Previously: the two caps
only.) Refs: §13.1, Appendix A #47, D-1121, D-1282, D-1342, D-1346.

### Requirement: LLM usage endpoints
`GET /v1/usage/llm?start&end` SHALL report estimated LLM cost per UTC day, provider, model and prompt kind with the 10
costliest jobs (default 30 days, at most 366, else 422), and `GET /v1/usage/llm/jobs` pages those jobs. REST only, an
estimate, not billing. Refs: §17, ARCHITECTURE rev 11.

### Requirement: MCP tools
The MCP server SHALL use the official `mcp` SDK and expose exactly `scrape`, `map`, `search`, `crawl_start`,
`crawl_status`, `extract`, `extract_status`, `list_schemas`, `create_schema`, `get_site_config`, `export_config`,
`reject_config`, `llms_txt`, `create_schedule`, `list_schedules`, `schedule_jobs`, `pause_schedule`, `resume_schedule`,
`run_schedule`, `delete_schedule` and `webhook_deliveries`, each one service call; long jobs return a `job_id` at once
and status tools page 10 results. No jobs-list or usage tool. (Previously: twenty tools, no `webhook_deliveries`.)
Refs: §13.3, D-0698, D-1391, D-1417, D-1442, D-1511.
#### Scenario: Tool list
- **WHEN** a client lists the tools
- **THEN** it gets exactly the twenty-one tools named above

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
`max_age` > 0, `method_hint` `http` or `fetch.cache` `only`; batch has no such member. A listing scrape asking for `records` in `auto` without
it grows its list with the default `browser_actions` when its page is rendered (owner decision 11 of the master plan,
2026-10-18). The request's `fetch.actions` and `wait_for` run first on the settled page. With `records` asked, each
further kept document state is a capture with its own extraction under its own URL, stored once the first state's did
not fail; the answer lists records once each (a failed further state makes it `partial`), `capture_id` and formats are
the first state's, and `browser_actions` reports the mechanism, stop reason, actions, pages and items. (Previously: only
a request naming `browser_actions` grew its list.) Refs: owner #52, D-1218, D-1222, D-1223, D-1513.
#### Scenario: Detail page
- **WHEN** a scrape with `page_kind` `detail` sets `browser_actions`
- **THEN** the answer is a 422 problem naming `browser_actions` and no job is created
#### Scenario: Steps before paging
- **WHEN** a listing scrape sets `browser_actions` and `fetch.actions` with a click on a consent button
- **THEN** the click runs before the paging driver reads the page, and `fetch.attempts` carries its outcome

### Requirement: The fetch names its adapter
A scrape answer's `fetch` SHALL carry `adapter`, the name of the platform adapter that read the page's `api` capture
(INV-39), null for any other fetch. Refs: D-1393.
#### Scenario: Adapter capture
- **WHEN** a page is served by a platform adapter's API request
- **THEN** `fetch.method` is `api` and `fetch.adapter` is that adapter's name

### Requirement: Request context and page actions members
`fetch` of scrape, batch, crawl and extract SHALL take `headers` and `cookies` (names to secret values; a Fetch
Standard forbidden request-header name, `User-Agent` or a `Cookie` header is 422), `proxy_pool` (a configured pool,
else 422), `wait_for` (milliseconds, a CSS selector or `network_idle`), `actions` (at most 20 steps,
`config_ir/page_actions.py`), `cache` (`default`, `bypass`, `only`) and `respect_robots` (default `false`: robots.txt
is neither requested nor obeyed; `true` obeys it, [acquisition](../acquisition/spec.md) "robots.txt", owner decision
#75; map takes it as a member of its own); `wait_for` and `actions` run in the browser
(422 with `method_hint` `http`), and `headers` go over HTTP only (422 with them). Answers and stored scrape requests
show every value as `**********`. The scrape answer's `fetch.attempts` carry each step's outcome. MCP tools take the
same members. (Previously: `respect_robots` defaulted to `true`, `false` needing a `robots_override_reason`.) Refs:
owner delegation 2026-10-17, D-1430–D-1437, owner decision #75.
A stored record answers `egress_country` and `egress_basis` ([acquisition](../acquisition/spec.md), "Egress country").
#### Scenario: Forbidden header
- **WHEN** a scrape's `fetch.headers` names `User-Agent`
- **THEN** the answer is a 422 problem naming `fetch.headers` and no job is created

### Requirement: Web search
`POST /v1/search` `{query, limit ≤ 50, scrape?}` SHALL answer the provider's results in its order (`position`, `url`,
`title`, `snippet`), where the provider is a SearXNG instance (`CRAWLERAI_SEARCH_SEARXNG_URL`) or a URL template
(`CRAWLERAI_SEARCH_URL_TEMPLATE`, `{query}`, `{limit}`) read by the shape of its JSON or HTML answer
(`CRAWLERAI_SEARCH_FIELDS` names members). Without a provider it is 503 `search_unavailable`, a provider that fails is
502 `search_failed`. With `scrape` (a batch's `formats`, `schema`, `page_kind`, `fetch`, `budget`, `webhook_url`) the
results the SSRF guard accepts are scraped by one `batch_scrape` job whose `job_id` the answer carries, the others
counted in `skipped` (INV-16). Refs: §22, D-1442, D-1443.
#### Scenario: No provider
- **WHEN** no search provider is configured and a client posts a query
- **THEN** the answer is 503 `search_unavailable`

### Requirement: SDKs
`sdk/python` and `sdk/typescript` SHALL wrap the API with typed requests and answers generated from
`frontend/openapi.json`, job polling, the event stream and webhook signature verification; `sdk/openapi.sha256` MUST
name the current document, which `tools/tests/test_sdk_digest.py` checks. Refs: D-1444.

### Requirement: Output format members and artifacts endpoint
Scrape, batch and crawl SHALL accept the formats `markdown_fit`, `chunks`, `screenshot` and `pdf`, with `fit`,
`chunking` and `fetch.screenshot` options valid only with their format; an answer names a screenshot or PDF as
`{url, content_type}`. `GET /v1/captures/{id}/artifacts/{name}` SHALL serve `screenshot.png` or `page.pdf` with
`nosniff`, behind the API key, and 404 once the capture is gone. `GET /v1/jobs/{id}/results` SHALL take the formats
`jsonl`, `xlsx` and `parquet` in the schema's columns (`xlsx` and `parquet` as one file, `parquet` 503
`format_unavailable` without pyarrow), and `GET /v1/jobs/{id}/llms.txt` and `llms-full.txt` SHALL answer the llmstxt.org
text of a job's pages (409 for none). The MCP `scrape` tool takes the new formats and returns a screenshot as an image
block; a further tool, `llms_txt`, answers the file. Refs: D-1424, D-1425, D-1428.
#### Scenario: Artifact served
- **WHEN** a scrape asked for `screenshot` and its URL is fetched with the key
- **THEN** it answers `image/png` bytes

### Requirement: Schedule endpoints
`/v1/schedules` SHALL create (201), list newest first, read, `PATCH` (name, cadence, or `kind` with `request`, checked
as at creation), delete (204, its jobs kept with `schedule_id` null), pause, resume and run now (202 with `job_id`)
schedules; a request the submission would refuse, a schema prompt, a scrape's browser actions or caller headers or
cookies is a 422, and `GET /v1/jobs?schedule_id=` lists a schedule's jobs; `crawlerai schedules list|pause|resume` does
the same from the command line. (Previously: no refusal of caller headers or cookies.) Refs: §22, D-1411, D-1412,
D-1417, D-1510.

### Requirement: Webhook payloads
A delivery SHALL POST `{delivery_id, job_id, attempt, events: [{id, type, created_at, data}]}` with
`X-CrawlerAI-Signature: sha256=<HMAC-SHA256 of the body>` and `X-CrawlerAI-Delivery`; `page` data is the task's id,
URL, status, outcome, capture and error, `record` and `record_changed` the stored version (id, entity, version,
`changed_fields`, `complete`, published `data`), `url_gone` the URL, and a job end event the job's summary as `job`
(`api/webhooks.py`). Refs: D-1414, D-1415.

### Requirement: Webhook deliveries of a job
`GET /v1/jobs/{id}/webhook-deliveries` SHALL list the job's deliveries newest first by cursor (`status`, `attempts`,
`next_attempt_at` while pending, `last_error`, `response_code`, `event_count`, `created_at`), 404 for an unknown job;
the MCP tool `webhook_deliveries` answers the same page (`services/webhook_deliveries.py`). Refs: D-1511.
#### Scenario: A refused delivery
- **WHEN** a receiver answered a delivery's last attempt with 503
- **THEN** it reads `pending`, `attempts` 1, `last_error` "status 503" and `response_code` 503

### Requirement: Minimum confidence
`POST /v1/scrape`, `/v1/batch/scrape`, `/v1/crawl` and `/v1/extract` (and the MCP tools that take their bodies) SHALL
accept an optional `min_confidence` from 0 to 1, with no default, outside which the request is 422; a `records` field
whose calibrated confidence is below it is `abstained` with reason `below_min_confidence`
([resolution](../resolution/spec.md)). Refs: D-1771.
#### Scenario: Unset
- **WHEN** a request sets no `min_confidence`
- **THEN** every chosen field publishes with its confidence

### Requirement: Render mode
`POST /v1/scrape`, `/v1/batch/scrape` and `/v1/crawl` (and the MCP tools that take their bodies) SHALL accept an
optional `render: {mode, fields}` (`services.scrape_steps.RenderOptions`): `mode` is `off` (the default: HTTP, the
browser only when HTTP is refused, [acquisition](../acquisition/spec.md) "Browser on block or by field source"),
`locate` (the surface's locate run finds where the fields the HTTP pages leave missing, or `fields`, live) or `always`
(every page rendered); `fields` holds at most `MAX_RENDER_FIELDS` names of the request's schema's fields (another name
is refused, `check_render`). It is validated and pinned with the request (INV-28), and stored as the surface's render
mode (`progressive_state.render_mode`) when a page of the job keeps a record or a caller-supplied listing lists nothing;
a request without `render` stores none and inherits the surface's mode. The mode drives the page's fetch plan
([acquisition](../acquisition/spec.md) "Browser on block or by field source": `always` renders every page) and, in
`locate` or `always`, starts the surface's locate run once per job ([learning-configs](../learning-configs/spec.md)
"Locate run") for `fields`, else the fields the page left unpublished (a listing without rows: each row field of its
schema). `render_fields` is refused (422), as is any other unknown member. A field
whose source in the site's config is the browser, missing from a page that was not rendered, is `interaction_required`
with reason `render_bound` ([resolution](../resolution/spec.md)). A task outcome or a scrape's `outcome` may be
`auth_wall`, `soft_404`, `geo_redirect`, `redirected_to_listing`, `unsupported_media`, `geo_blocked` or `timeout`
(the capture's block class,
`fetch.block_class`, is the transport outcome; the task outcome is the data outcome; the model is in
[jobs](../jobs/spec.md), "Page outcomes"). (Previously: `render_fields`, a list of schema field names stored with the
request with no effect on the fetch; a listing that listed nothing started no locate run.) Refs: owner plan 2026-10-19 P3, P9; architecture v3 a.1.
#### Scenario: A list of render fields
- **WHEN** a batch body names `render_fields: ["size"]`
- **THEN** the answer is 422 naming `render_fields`
#### Scenario: Locate
- **WHEN** a batch body names `render: {mode: "locate", fields: ["size"]}`
- **THEN** it is accepted and stored with the job's request; without `render` the mode is `off`
