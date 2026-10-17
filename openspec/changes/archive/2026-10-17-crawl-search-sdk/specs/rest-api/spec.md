# Delta: rest-api

## MODIFIED Requirements

### Requirement: MCP tools
The MCP server SHALL use the official `mcp` SDK and expose exactly `scrape`, `map`, `search`, `crawl_start`,
`crawl_status`, `extract`, `extract_status`, `list_schemas`, `create_schema`, `get_site_config`, `export_config`,
`reject_config`, each one service call; long jobs return a `job_id` at once and status tools page 10 results. No
jobs-list or usage tool. (Previously: eleven tools, no `search`.) Refs: §13.3, D-0698, D-1391, D-1442.
#### Scenario: Tool list
- **WHEN** a client lists the tools
- **THEN** it gets exactly the twelve tools named above

## ADDED Requirements

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
