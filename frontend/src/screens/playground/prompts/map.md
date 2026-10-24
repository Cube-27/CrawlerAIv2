# call-map

Call the Snowcrawl map endpoint to list a site's URLs without fetching every page.

- Send `POST /v1/map` with `Authorization: Bearer $SNOWCRAWL_API_KEY` and a JSON body.
- Required: `url`. Optional: `include` and `exclude` URL globs, `limit`, `use_sitemaps`, `use_links`.
- The URLs come from the site's sitemaps and the start page's links, canonical and in scope: the exact host of `url`,
  or the `include` globs, less the `exclude` globs.
- The answer comes at once: `urls`, their `sources`, and `truncated`, which says more were found than `limit`, or
  that reading stopped at a cap or the 60 s timeout.
- Errors are RFC 9457 problem documents; a 422 names the member that is wrong.
- The full request and answer shapes are in the OpenAPI document at `/v1/openapi.json`.

# integrate-map

Build an integration on the Snowcrawl map endpoint (`POST /v1/map`).

- Read the base URL and the API key from configuration (`SNOWCRAWL_API_KEY`); never hard-code a key.
- Use a map to choose pages, then scrape the ones you need with `POST /v1/batch/scrape`.
- Check `truncated`: when it is true the list is partial; narrow the scope with `include` globs rather than raising
  `limit` without bound.
- Retry on 429 with backoff, honouring `Retry-After`; fix the request on 422.
- Generate the types from the OpenAPI document at `/v1/openapi.json`. Test against recorded answers.
