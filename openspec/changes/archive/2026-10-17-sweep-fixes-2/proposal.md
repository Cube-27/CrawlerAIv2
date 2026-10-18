# Change: sweep fixes 2 — 200 interstitials, network errors, JSON formats, empty listings, job locations, role C rows

## Why

The QA sweep of `POST /v1/scrape` (#263) left six generic defects in `openspec/backlog.md`: a 200 anti-bot stand-in
page kept as the product page; an HTTP transport error (curl 92, an HTTP/2 stream a bot filter resets) ending the
scrape with no browser attempt; the `markdown` and `html` of an adapter's JSON answer read as HTML; a listing with no
rows answering `records: []` with nothing saying why and its resolved page fields dropped; `location` of a job listing
publishing `conflict` for every posting that states several places; and role C giving 3 rows of a client-rendered
collection page that shows over a hundred items, because it reads 80,000 characters of menus and items and stops early.
The owner delegated the decisions (2026-10-17).

## What Changes

- A 2xx document that shows a vendor's stand-in marker (`adapters/challenges.py`, site data) is `blocked` with that
  vendor's challenge label, so `auto` gives it one browser attempt and ends `blocked` if the render is still the
  stand-in; generically, a 2xx document that declares a refresh and links to no web page is `blocked`. INV-24 is amended:
  vendor data may select the block class of a 2xx page, from the adapter package only.
- In `auto`, an HTTP `error` whose reason is `network_error` gets one browser attempt, kept only when `ok`.
- A JSON body's `markdown` (and `markdown_fit`, `chunks`) is the answer pretty-printed in a fenced `json` code block; its
  `html` is empty; `raw_html` stays the body as received.
- A listing whose extraction gives no rows says why: the scrape's `reason` (and the task's `last_error`) is `no_rows`
  with its cause, and the answer's `page` member keeps the page-scope fields the page resolved (`next_page_url`).
- `job_listing.location` becomes `locations`, a list of locations, as in `job_detail`: an API's primary and secondary
  places publish together.
- Role C on a listing reads the text of the page's repeated item blocks (`acquire.items.item_blocks`), cut from the
  cleaned text and mapped back to its offsets, instead of the whole cleaned text, when the page shows such blocks.

## Impact

- Capabilities: [acquisition](../../../specs/acquisition/spec.md), [extraction](../../../specs/extraction/spec.md),
  [llm](../../../specs/llm/spec.md), [rest-api](../../../specs/rest-api/spec.md), [schemas](../../../specs/schemas/spec.md)
  (deltas in `specs/`); owner decision row in `openspec/design/owner-decisions.md`.
- Files: `backend/src/crawlerai/adapters/challenges.py`, `acquire/{challenge,classify,http,browser,rungs}.py`,
  `content/{markdown,fit,html}.py`, `content/item_text.py` (new), `llm/roles/c_extract.py`, `config_ir/role_c.py`,
  `resolve/pipeline.py`, `resolve/types.py`, `services/scrape.py`, `services/records.py`,
  `schemas/presets/job_listing.json`, `frontend/openapi.json`, `frontend/src/api/schema.d.ts`, `sdk/`.
