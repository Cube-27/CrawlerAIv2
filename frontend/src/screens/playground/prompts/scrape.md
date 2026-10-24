# call-scrape

Call the Snowcrawl scrape endpoint to read one web page.

- Send `POST /v1/scrape` with `Authorization: Bearer $SNOWCRAWL_API_KEY` and a JSON body.
- Required: `url` (the page) and `formats`, a non-empty list of `markdown`, `html`, `raw_html`, `links`, `metadata`
  and `records`. The answer has a member only for each format asked for.
- For structured data, set `schema` to `{"id": "<schema id>"}` (a stored schema), an inline schema, or
  `{"prompt": "<what to extract>"}`, and ask for `records`. A prompt is drafted into a schema, returned as `schema`.
- Optional: `page_kind`, `max_age` (seconds; a capture fetched within it is read instead of fetching again),
  `timeout_s`, `fetch.method_hint` (`auto`, `http` or `browser`), `budget.llm_calls`.
- The answer holds the page's `outcome`, the formats asked for, `records` (each field with its value and status) and
  `usage`. A field the engine could not establish has no value and a reason; never fill it in yourself.
- Errors are RFC 9457 problem documents: read `title`, `detail` and the per-field `errors`. A 422 names the member
  that is wrong; a 429 says to retry after `Retry-After` seconds.
- The full request and answer shapes are in the OpenAPI document at `/v1/openapi.json`.

# integrate-scrape

Build an integration on the Snowcrawl scrape endpoint (`POST /v1/scrape`).

- Read the base URL and the API key from configuration (`SNOWCRAWL_API_KEY`); never hard-code a key.
- Wrap the call in one function that takes the URL, the formats and an optional schema and returns a typed result.
  Generate the types from the OpenAPI document at `/v1/openapi.json` rather than writing them by hand.
- Treat a field with no value as unknown, not as empty: keep its status and reason next to the value.
- Handle problems by status: 422 (fix the request), 409 (the inline schema differs from the stored schema of its name), 429 and
  503 (retry with backoff, honouring `Retry-After`), 502 and 504 (the page could not be fetched in time).
- Send a stored schema by id for repeated scrapes of the same kind of page, so every result has one shape.
- Set `max_age` when a recent capture is good enough; it saves a fetch.
- Test the integration against recorded answers, not the live service.
