## ADDED Requirements

### Requirement: Request context and page actions members
`fetch` of scrape, batch, crawl and extract SHALL take `headers` and `cookies` (names to secret values; a Fetch
Standard forbidden request-header name, `User-Agent` or a `Cookie` header is 422), `proxy_pool` (a configured pool,
else 422), `wait_for` (milliseconds, a CSS selector or `network_idle`), `actions` (at most 20 steps,
`config_ir/page_actions.py`) and `cache` (`default`, `bypass`, `only`); `wait_for` and `actions` run in the browser
(422 with `method_hint` `http`), and `headers` go over HTTP only (422 with them). Answers and stored scrape requests
show every value as `**********`. The scrape answer's `fetch.attempts` carry each step's outcome. MCP tools take the
same members. Refs: owner delegation 2026-10-17, D-1430–D-1437.
#### Scenario: Forbidden header
- **WHEN** a scrape's `fetch.headers` names `User-Agent`
- **THEN** the answer is a 422 problem naming `fetch.headers` and no job is created

## MODIFIED Requirements

### Requirement: Synchronous scrape
`POST /v1/scrape` SHALL fetch one URL inline under a `job(kind='scrape')` with one task and return one member per
requested format (unrequested ones omitted); past `timeout_s` (≤ 120) it is 504 `timeout` and the job `failed`.
`budget` is optional, with no default ([jobs](../jobs/spec.md)). With `max_age > 0` and `fetch.cache` `default` it
reuses the latest `ok`, unexpired capture of the canonical URL that recent and made with the same actions and context
names, with no fetch, robots.txt check or usage; `bypass` always fetches; `only` serves such a capture (any age when
`max_age` is 0) or is 404 `not_cached` with the job `failed`. (Previously: no `cache`.) Refs: §13.1, D-0028, D-0427,
D-0431, D-0503, D-1435.
#### Scenario: Cache only, nothing stored
- **WHEN** a scrape with `fetch.cache` `only` names a URL with no stored capture
- **THEN** the answer is 404 `not_cached` and nothing is fetched
