# Change: crawl strategies, web search and SDKs

## Why

A crawl visits pages breadth first and stops at `limit`, so on a large site a small `limit` spends itself on
navigation links, and a caller who wants "the pages about X" cannot say so. There is no way to find pages by query
(search), and callers integrate by hand against the OpenAPI document. The owner asked (owner delegation 2026-10-17)
for a robust, widely usable crawler product with features beyond the backlog.

## What Changes

- Crawl gains `strategy` (`bfs` default, `dfs`, `best_first`), `query` and `keywords`, `allow_subdomains`,
  `allow_external` and the `max_pages` alias of `limit`. Best first scores each candidate link (BM25 of anchor text and
  URL path against the query, the holding page's relevance, sitemap priority, depth) and the queue leases by the score
  stored on `url_task.score`.
- `POST /v1/search` and the MCP `search` tool: web results from an operator-configured provider (a SearXNG instance,
  or a URL template whose JSON or HTML answer is read generically), optionally scraped through the batch job. Without a
  provider the endpoint answers 503 `search_unavailable`. The playground gains a Search mode.
- A typed Python SDK (`sdk/python`, httpx and pydantic) and TypeScript SDK (`sdk/typescript`) generated from the OpenAPI
  document, with job polling, event streaming and webhook verification; CI checks they are current.

## Impact

- Capabilities: [jobs](../../specs/jobs/spec.md), [rest-api](../../specs/rest-api/spec.md),
  [frontend](../../specs/frontend/spec.md) (deltas in `specs/`).
- Design: `design/overview.md` §22 ("Web search" admitted) and owner decision #61.
- Files: `backend/src/crawlerai/crawl/`, `search/`, `services/search.py`, `api/routers/search.py`, `mcp_server/`,
  `db/` (baseline migration, `url_task.score`), `frontend/src/screens/playground/`, `sdk/`, `.github/workflows/ci.yml`.
