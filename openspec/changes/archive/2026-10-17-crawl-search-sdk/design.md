# Design: crawl strategies, web search and SDKs

## Decisions

### D-1440 — A crawl's strategy orders its frontier; best first scores candidates generically
- Date: 2026-10-17 · Change/PR: crawl-search-sdk (#261) · Status: decided (owner-delegated 2026-10-17)
- Decision: `strategy` is `bfs` (default, no score), `dfs` (score grows with depth) or `best_first`. Best first scores a
  link from 0 to 1 as `0.8^depth × (0.5·match + 0.3·inherited + 0.2·prior)`: `match` is Okapi BM25 of the link's anchor
  text and URL path tokens against the `query` and `keywords`, with IDF among the candidates one page contributes and
  normalised by the best a document could reach; `inherited` is the holding page's relevance (mean `tf/(tf+k1)` of the
  terms in its visible text, as in shark-search); `prior` is the sitemap `priority` (0.5 default), halved outside the
  start URL's directory. Terms are UAX #29 words, case-folded; no stopword or synonym list (C4). The score is stored on
  `url_task.score` and `claim_tasks` leases `priority`, then score (NULL last), then id.
- Alternatives: embeddings or an LLM to rank links (needs keys, not generic); a link-count prior (PageRank-like, needs
  the graph); score only by depth.
- Why: BM25 is the standard term-weighting model (Robertson and Zaragoza 2009), inheritance is the standard fix for a
  link whose own text says nothing (Hersovici et al. 1998), and the sitemap priority is protocol data (sitemaps.org).
- Reversible: yes — the strategy is a request member; the score column is nullable.

### D-1441 — Scope options widen the host bound; globs still decide
- Date: 2026-10-17 · Change/PR: crawl-search-sdk (#261) · Status: decided (owner-delegated 2026-10-17)
- Decision: `allow_subdomains` keeps the start host's subdomains without an `include`; `allow_external` keeps any host;
  `include` and `exclude` still apply to both. `max_pages` is an alias of `limit` (both together is a 422).
- Why: D-0037 required an `include` for subdomains, which is awkward for the common case; the globs stay the one place
  a caller bounds hosts.
- Reversible: yes

### D-1442 — Web search is admitted; the provider is the operator's
- Date: 2026-10-17 · Change/PR: crawl-search-sdk (#261) · Status: decided (owner-delegated 2026-10-17)
- Decision: §22 "Web search" is admitted (owner decision #61). `CRAWLERAI_SEARCH_SEARXNG_URL` names a SearXNG
  instance (JSON API, paged up to 5 pages) or `CRAWLERAI_SEARCH_URL_TEMPLATE` a URL with `{query}` and `{limit}`; with
  neither, `POST /v1/search` is 503 `search_unavailable`. The provider's own endpoint is trusted (it may be on a
  private network) and asked without redirects, cookies or a page's headers; result URLs are the web's, so each is
  checked by the SSRF guard (INV-16) before a `scrape` job is queued and an unfetchable one is counted in `skipped`.
  `scrape` takes a batch's members and queues one `batch_scrape` job; the answer carries its `job_id`.
- Alternatives: a built-in scraping of a search engine's result pages (brittle, against most terms of service); a
  vendor search API with a key in code.
- Why: no free search provider is dependable, and operators already run SearXNG; a URL template covers the paid APIs.
- Reversible: yes

### D-1443 — A provider's answer is read by its shape, with operator-named members as the override
- Date: 2026-10-17 · Change/PR: crawl-search-sdk (#261) · Status: decided (owner-delegated 2026-10-17)
- Decision: a JSON answer's results are its array with the most objects that carry an absolute http(s) URL; the first
  such string is the URL, the first other string the title and the longest remaining the snippet. An HTML answer's
  results are its anchors with an absolute http(s) `href` after resolution (RFC 3986 §5); an anchor on the answering
  host counts only as a redirect, the result being the absolute URL on another host that one of its query parameters
  holds. `CRAWLERAI_SEARCH_FIELDS` names the members when the shape reads a provider wrongly. SearXNG's JSON is read by
  the same code.
- Alternatives: a per-provider adapter list (hostnames outside `adapters/`, C3); CSS selectors per engine (C4).
- Why: structural properties (RFC 3986, HTML §4.6) need no site knowledge; the override covers the rest.
- Reversible: yes

### D-1444 — The SDKs are generated from the OpenAPI document and checked in CI
- Date: 2026-10-17 · Change/PR: crawl-search-sdk (#261) · Status: decided (owner-delegated 2026-10-17)
- Decision: `sdk/python` (httpx and pydantic at runtime; models by `datamodel-code-generator`, run through `uvx` by
  `sdk/python/generate.sh`) and `sdk/typescript` (no runtime dependency; types by `openapi-typescript`) read
  `frontend/openapi.json`. The `sdk` CI job regenerates both, fails on a diff, then runs each SDK's checks and tests.
  Both give `scrape`, `map`, `search`, `crawl`, `batch_scrape`, `extract`, `job`, `cancel_job`, job results paging,
  `wait_for_job`, the event stream and webhook verification (HMAC-SHA256 of the raw body, constant-time compare). The
  packages carry the repository's license (AGPL-3.0-only) and are not published.
- Alternatives: hand-written models (drift); one generator for both languages (heavier output).
- Why: the generated files cannot drift, and a thin hand-written client is all a caller needs.
- Reversible: yes

### D-1445 — The command line gets no search or crawl commands
- Date: 2026-10-17 · Change/PR: crawl-search-sdk (#261) · Status: decided (owner-delegated 2026-10-17)
- Decision: `crawlerai` stays the operator's tool (migrations, keys, workers, data); callers use REST, MCP, the
  playground or the SDKs. The search provider is configured by environment variables.
- Why: a second client of the API in the same package would duplicate the SDKs.
- Reversible: yes

### D-1446 — A scored crawl spends its limit by rank, and a full frontier keeps its best
- Date: 2026-10-17 · Change/PR: crawl-search-sdk (#261) · Status: decided (owner-delegated 2026-10-17)
- Decision: a scored crawl queues up to 5 × `limit` candidates; past that a better candidate replaces the weakest
  queued one. A worker runs the tasks it leased together best first, so a task is skipped (cancelled, unfetched) once
  the pages finished, plus those leased ahead of it, reach `limit`; when it finishes the last page the queued
  candidates are cancelled. A best-first task defers (back to the queue) when a better candidate was queued after it
  was leased. Cancelled candidates are listed in the job's results with status `cancelled`.
- Alternatives: a task row per candidate without a bound (unbounded rows on large sites); one lease at a time.
- Why: it keeps `limit` an exact bound on fetched pages and lets a late-found link outrank early ones.
- Reversible: yes

### D-1447 — Search mode in the playground keeps no run
- Date: 2026-10-17 · Change/PR: crawl-search-sdk (#261) · Status: decided (owner-delegated 2026-10-17)
- Decision: Search is a mode under its own caption; it makes no job of its own (`Mode.kind` is null), shows its answer
  on the page until the next search and links to the batch run when Scrape results is on.
- Why: the answer is cheap to repeat and the scrape is an ordinary batch job with its own run view.
- Reversible: yes
