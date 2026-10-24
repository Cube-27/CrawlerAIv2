# call-crawl

Call the Snowcrawl crawl endpoint to crawl a site from a start URL.

- Send `POST /v1/crawl` with `Authorization: Bearer $SNOWCRAWL_API_KEY` and a JSON body.
- Required: `url` (the start page) and `formats`, a non-empty list of `markdown`, `html`, `raw_html`, `links`,
  `metadata` and `records`.
- Scope: `include` and `exclude` URL globs, `max_depth` and `limit`. The crawl stays on the start URL's host (and the
  subdomains an `include` names) and reads its sitemaps and each page's links.
- `strategy`: `bfs` (default), `dfs` or `best_first`; best first with a `query` (and `keywords`) fetches the links that
  match it first, so a small `limit` still reaches the relevant pages. `allow_subdomains` and `allow_external` widen the
  scope; `max_pages` is an alias of `limit`.
- `page_kind_rules` (`[{"pattern": "<glob>", "page_kind": "<kind>"}]`): a page a rule matches is extracted; with
  rules, every other page is fetched for its links only. With `schema`, ask for `records`.
- The answer is `202` with a `job_id`. Follow it with `GET /v1/jobs/{job_id}` or `GET /v1/jobs/{job_id}/events`, and
  read pages with `GET /v1/jobs/{job_id}/results?format=json_values`. Cancel with `DELETE /v1/jobs/{job_id}`.
- Errors are RFC 9457 problem documents; a 422 means nothing was queued.
- The full request and answer shapes are in the OpenAPI document at `/v1/openapi.json`.

# integrate-crawl

Build an integration on the Snowcrawl crawl endpoint (`POST /v1/crawl`).

- Read the base URL and the API key from configuration (`SNOWCRAWL_API_KEY`); never hard-code a key.
- Keep crawls bounded: always set `limit`, and narrow them with `include` and `exclude` globs. To read only what
  matters on a large site, use `strategy: best_first` with a `query`.
- Use `page_kind_rules` so only the pages you need are extracted; the others are read for links only.
- Wait for the job with `webhook_url` or the event stream (resume with `Last-Event-ID`), then page through the
  `json_values` results with `cursor` until `next_cursor` is null.
- Retry the submit on 429 and 503 with backoff, honouring `Retry-After`; fix the request on 422.
- Generate the types from the OpenAPI document at `/v1/openapi.json`. Test against recorded answers.
