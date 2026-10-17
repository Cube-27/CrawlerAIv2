# Change: playground and config UX gaps

## Why

Live use of the playground left five gaps: Format's error line moves the layout (D-1214), field tables repeat the
`uncalibrated` badge on every field (#214), a waiting config can only be approved, never refused (#252), Settings has
no field for `draft_call_cap` (D-1282), and a page's fetch (which rung served it, why it was blocked, which platform
adapter read it) and the new `network` evidence are not visible. The API carries most of this already.

## What Changes

- Playground: Format's error line hangs under it like Schema's; Options gain Max rows (`fetch.max_rows`) in Scrape,
  Batch, Crawl and Extract.
- Field tables: one `uncalibrated` badge per record, not per field; evidence buckets and source kinds read in words
  (`network`, `xhr`, `api`, `adapter`), the code on hover.
- Configs: `POST /v1/configs/{id}/reject` and the `reject_config` MCP tool; a Reject button beside Approve.
- Settings: a "Draft call limit per key" field beside the existing approval switch.
- Fetch trail: `fetch.adapter` names the platform adapter that read a page; a job page's drawer shows each fetch
  attempt (rung, status, block class, challenge label, duration, error), from `fetch` on page outputs and on
  `json_values` items asked for with `include=fetch`.

## Impact

- Capabilities: [frontend](../../../specs/frontend/spec.md), [rest-api](../../../specs/rest-api/spec.md),
  [jobs](../../../specs/jobs/spec.md), [learning-configs](../../../specs/learning-configs/spec.md).
- `frontend/openapi.json` and `schema.d.ts` regenerate; `DESIGN.md` "Showing extraction results" changes.
