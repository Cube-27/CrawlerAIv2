# call-extract

Call the CrawlerAI extract endpoint to extract structured records from pages.

- Send `POST /v1/extract` with `Authorization: Bearer $CRAWLERAI_API_KEY` and a JSON body.
- Required: `urls` (a URL with a `*` is a glob, expanded through a map of its host), `schema` and `page_kind`.
- `schema` is `{"id": "<schema id>"}` (a stored schema), an inline schema, or `{"prompt": "<what to extract>"}`; a
  prompt is drafted from the first pages before the job is queued, and the draft is returned as `schema`.
- Optional: `limit`, `fetch.method_hint`, `budget.llm_calls`, `webhook_url`.
- The answer is `202` with a `job_id` and the `schema`. Follow the job with `GET /v1/jobs/{job_id}` or
  `GET /v1/jobs/{job_id}/events`, and read records with `GET /v1/jobs/{job_id}/results?format=json_values`.
- A field the engine could not establish has no value; never fill it in yourself.
- Errors are RFC 9457 problem documents; a 422 means nothing was queued.
- The full request and answer shapes are in the OpenAPI document at `/v1/openapi.json`.

# integrate-extract

Build an integration on the CrawlerAI extract endpoint (`POST /v1/extract`).

- Read the base URL and the API key from configuration (`CRAWLERAI_API_KEY`); never hard-code a key.
- Draft a schema once with a prompt, review it, store it, then send it by id, so every run has one shape.
- Wait for the job with `webhook_url` or the event stream (resume with `Last-Event-ID`), then page through the
  `json_values` results with `cursor` until `next_cursor` is null.
- Keep a field with no value as unknown, with its page's `outcome`, rather than an empty value.
- Retry the submit on 429 and 503 with backoff, honouring `Retry-After`; fix the request on 422.
- Generate the types from the OpenAPI document at `/v1/openapi.json`. Test against recorded answers.
