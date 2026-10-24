# call-batch

Call the Snowcrawl batch endpoint to scrape many web pages in one job.

- Send `POST /v1/batch/scrape` with `Authorization: Bearer $SNOWCRAWL_API_KEY` and a JSON body.
- Required: `urls` (a URL given twice is scraped once) and `formats`, a non-empty list of `markdown`, `html`,
  `raw_html`, `links`, `metadata` and `records`.
- For structured data, set `schema` to `{"id": "<schema id>"}`, an inline schema or `{"prompt": "<what to extract>"}`,
  and ask for `records`. Optional: `page_kind`, `fetch.method_hint`, `webhook_url` (called when the job ends).
- The answer is `202` with a `job_id`. Follow the job with `GET /v1/jobs/{job_id}` (status and counts) or its event
  stream `GET /v1/jobs/{job_id}/events` (server-sent events).
- Read the output with `GET /v1/jobs/{job_id}/results?format=json_values`: one item per page with its `url`,
  `outcome` and clean `records`, paged with `next_cursor`.
- Cancel with `DELETE /v1/jobs/{job_id}`. Errors are RFC 9457 problem documents; a 422 means nothing was queued.
- The full request and answer shapes are in the OpenAPI document at `/v1/openapi.json`.

# integrate-batch

Build an integration on the Snowcrawl batch endpoint (`POST /v1/batch/scrape`).

- Read the base URL and the API key from configuration (`SNOWCRAWL_API_KEY`); never hard-code a key.
- Submit, keep the `job_id`, then wait: prefer `webhook_url` or the event stream (resume it with `Last-Event-ID`
  after a disconnect) over polling `GET /v1/jobs/{job_id}`.
- Page through `GET /v1/jobs/{job_id}/results?format=json_values` with `cursor` until `next_cursor` is null.
- A page whose `outcome` is not `extracted` has no records; keep its outcome rather than retrying blindly.
- Retry the submit on 429 and 503 with backoff, honouring `Retry-After`; fix the request on 422.
- Generate the types from the OpenAPI document at `/v1/openapi.json`. Test against recorded answers.
