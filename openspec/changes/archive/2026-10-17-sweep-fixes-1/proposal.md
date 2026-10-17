# Change: sweep fixes 1 — links of API answers, why a scrape was blocked

## Why

A QA sweep of `POST /v1/scrape` on main against 36 real pages (2026-10-17) found two generic defects. The `links` of
every page a platform adapter served were fragments of the API answer's escaped strings (`<api>/%5C%22https:/...`):
the content formats read the JSON body as HTML, so markup inside a string value became the page's anchors. And a page
whose robots.txt could not be read (a 5xx) answered `blocked` with no capture and nothing saying why, which a caller
cannot tell from a disallow, although the task records `robots_unreachable` (RFC 9309 §2.3.1.4).

## What Changes

- `ParsedPage` knows when its body is a JSON document (an `api` capture's `body.json`). The `links` format of such a
  page is its string values that are absolute http(s) URLs, canonicalized, deduplicated, in document order; it has no
  link elements, so `anchor_texts` (crawl scoring) is empty for it. Crawl discovery and map read the same `links`.
- The scrape answer gains `reason`: `robots` or `robots_unreachable` for a page robots.txt kept from being fetched (the
  task's `last_error`), null for a page that was fetched. The playground shows it beside the outcome; the API client
  and SDKs are regenerated.

## Impact

- Capabilities: [extraction](../../../specs/extraction/spec.md), [rest-api](../../../specs/rest-api/spec.md) (deltas in
  `specs/`).
- Files: `backend/src/crawlerai/content/page.py`, `content/links.py`, `services/scrape.py`, `frontend/openapi.json`,
  `frontend/src/api/schema.d.ts`, `frontend/src/screens/playground/output/ScrapeOutput.tsx`, `sdk/`.
