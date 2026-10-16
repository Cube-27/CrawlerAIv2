# API and MCP server

Design rationale, split from the former `docs/ARCHITECTURE.md` with its section numbers kept (code and history cite `ARCHITECTURE §N`). Index: [README.md](README.md).

## 13. API and MCP server (Appendix A #21)

### 13.1 REST API (FastAPI, OpenAPI)

| Endpoint | Purpose |
|---|---|
| `POST /v1/scrape` | One URL → `formats` ∈ {markdown, html, raw_html, links, metadata, records}. Optional `schema` (id, inline, `prompt`, or field names `fields`, §5.4), `page_kind`, `max_age` to reuse a recent capture. Synchronous with a timeout. |
| `POST /v1/batch/scrape` | Many URLs, async. Optional `schema` (id, inline, or `fields`). |
| `POST /v1/map` | URL discovery: sitemaps (robots `Sitemap:`, `/sitemap.xml`, indexes) plus page links. Include/exclude, limit. |
| `POST /v1/crawl` | Async. Start URL, include/exclude globs, depth, limit, `formats`, optional `schema` (id, inline, or `fields`) with page-kind rules per URL pattern. |
| `POST /v1/extract` | Async. URLs (globs expanded through `map`) plus `schema`, `prompt` or `fields` → records, in progressive mode. Returns the drafted schema when a prompt was used. |
| `GET /v1/jobs` | Jobs, newest first, each with its status summary; optional `kind` and `status` filters; cursor-paginated. |
| `GET/DELETE /v1/jobs/{id}`, `GET /v1/jobs/{id}/results`, `GET /v1/jobs/{id}/events` | Status (with whether a cancel was requested), cancel, paginated results (a page output with its task's failure or block reason; or clean `json_values` items, §12.2), server-sent events for progress (from stored run events). A webhook on completion. |
| `/v1/schemas` | Create, read, update in place, delete (retire). `POST /v1/schemas/draft`: the draft of field names for a page kind, for review before a run (§5.4). |
| `/v1/sites/{host}/configs`, `/v1/configs/{id}` (read/update), `/v1/configs/{id}/export`, `/v1/sites/{host}/learn` | Configs, operator corrections (C5), exports, forcing learning. |
| `/v1/records`, `/v1/captures/{id}/replay` | Records with `field_meta`; replay a capture with the current engine. |
| `GET /v1/usage/llm`, `GET /v1/usage/llm/jobs` | LLM calls, tokens and estimated cost for a range of UTC days: totals, per day, per provider, model and prompt kind, and the costliest jobs; per job, cursor-paginated. An estimate for visibility, not billing (§1). |

Every field in a response carries `value`, `status`, `evidence`, `confidence`, `calibrated` and `locator`. Each
record carries `mode` and `complete`.

### 13.2 Crawl frontier

- Sources: sitemaps, page links and pagination.
- URLs are canonicalized and deduplicated, with include/exclude rules and politeness from §7.
- A URL that matches no page-kind rule is crawled for links only (`links_only`) and never extracted.

### 13.3 MCP server

- Official MCP Python SDK (MIT per the SPEC-10 check, 2026-10-12; re-check at adoption); stdio and streamable HTTP transports; API-key
  auth.
- **Tools:** `scrape`, `map`, `crawl_start`, `crawl_status`, `extract`, `extract_status`, `list_schemas`,
  `create_schema`, `get_site_config`, `export_config`. Each is a thin call into the service layer.
- **Output for agents:**
  - markdown is paginated;
  - records show `status` and `confidence`, so an abstention reads as "unknown", not as a value;
  - long jobs return an id plus a status tool.
- **Untrusted content.** Page text is returned as data, and the server never follows instructions found in pages.
