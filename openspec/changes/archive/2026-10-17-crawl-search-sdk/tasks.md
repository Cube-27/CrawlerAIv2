# Tasks

## 1. Crawl strategies

- [x] 1.1 `strategy`, `query`, `keywords`, `allow_subdomains`, `allow_external` and `max_pages` on `POST /v1/crawl`; the best-first score (`crawl/scoring.py`) and the sitemap priorities. (#261)
- [x] 1.2 `url_task.score` in the baseline migration; the queue leases by score; a scored crawl spends its `limit` on the best candidates and keeps the best of a full frontier. (#261)
- [x] 1.3 Crawl options in the playground, the MCP `crawl_start` description, the crawl agent prompt. (#261)

## 2. Search

- [x] 2.1 Providers (SearXNG, URL template), generic result reading, the search service. (#261)
- [x] 2.2 `POST /v1/search` (503 `search_unavailable`) and the MCP `search` tool. (#261)
- [x] 2.3 The playground's Search mode and its Get code entry. (#261)

## 3. SDKs

- [x] 3.1 Python SDK: client, async client, polling, event stream, webhook verification, generated models. (#261)
- [x] 3.2 TypeScript SDK: client, polling, event stream, webhook verification, generated types. (#261)
- [x] 3.3 The `sdk` CI job, `make sdk` and `make check-sdk`, READMEs with examples. (#261)
