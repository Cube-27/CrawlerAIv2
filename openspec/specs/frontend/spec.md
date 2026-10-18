# Frontend Specification

## Purpose

The web UI is a thin client over the REST API: an app shell, the playground (Scrape, Batch, Crawl, Map, Extract) and the data screens (Jobs, Records, Schemas, Sites and configs, Labeling, Settings); visual conventions are in [DESIGN.md](../../conventions/DESIGN.md).

## Requirements

### Requirement: Thin client over the REST API
The UI SHALL call the API only through TanStack Query hooks over the client generated from `openapi.json` (`frontend/src/api/schema.d.ts`) and show server values as sent; it MUST NOT extract, normalize, infer field types or validate selectors or schema rules, showing server 422/409 problems where they apply. Stack: Vite+, React, TypeScript, HeroUI v3. Refs: §3, Appendix A #27, D-0409, D-0435, D-0472.
#### Scenario: Stale client
- **WHEN** a backend change alters `openapi.json` and `schema.d.ts` is not regenerated
- **THEN** the `frontend` CI job fails on the `make api-client` diff

### Requirement: Server-side API key, no key in the browser
The UI SHALL never ask for or hold an API key: the Vite dev proxy (`frontend/vite.config.ts`) attaches `Authorization: Bearer $CRAWLERAI_UI_API_KEY` to `/v1` and `/healthz`, binds `127.0.0.1` with CORS off, and refuses a `Sec-Fetch-Site` other than `same-origin` or `none` before attaching it (not built yet: a production server). Refs: §18, D-0809, D-0811, D-0828.
#### Scenario: Cross-site request
- **WHEN** a request reaches the proxy with `Sec-Fetch-Site: cross-site`
- **THEN** it is refused without the key; requests without the header (scripts) pass

### Requirement: Setup notice on 401
Any 401 SHALL replace the routed screen (sidebar kept) with a setup notice naming `CRAWLERAI_UI_API_KEY` and `crawlerai apikey create`, until reload; no Connect screen or redirect (`frontend/src/app/auth.tsx`). Refs: D-0812.

### Requirement: App shell and navigation
The shell SHALL have a sidebar with groups Playground (from `screens/playground/modes.ts`), Data (Jobs, Schedules, Records, Schemas, Sites), Evaluate (Labeling, only when `GET /healthz` reports `eval_ui: true`) and Settings plus theme toggle; the current entry carries `aria-current="page"`; routes are in `frontend/src/app/router.tsx`. (Previously: no Schedules.) Refs: D-0451, D-0452, D-0834, D-1418.
#### Scenario: Labeling hidden
- **WHEN** `/healthz` answers `eval_ui: false`, fails, or has not answered
- **THEN** the Labeling entry is not shown

### Requirement: Showing extraction results (INV-22, UI side)
Screens SHALL show a field only through `FieldValue`, `FieldStatusBadge`, `ConfidenceCell`, `EvidenceText`, `SourceKindText` and `LocatorText`, and a record's badge only through `UncalibratedBadge` (`frontend/src/components/`): a non-published value renders "—" with its reason, status is text plus icon, confidence a two-decimal number, and one "uncalibrated" badge per record, never per field, when a published field has `calibrated=false`; evidence and source kind read in words with the server's code on hover. INV-22 is owned by [resolution](../resolution/spec.md). Enforced by: component tests; active. (Previously: an uncalibrated badge on every field.) Refs: D-0368, D-0369, D-1390, D-1396.
#### Scenario: Conflict field
- **WHEN** a record field has status `conflict` and reason `disagree`
- **THEN** it renders "—", the status text "conflict" and the reason, with no value

### Requirement: Results tables are one row per record and paged
Every results view (scrape, batch, crawl, extract, jobs, records) SHALL show records as a table whose header row is the schema's field names and whose rows are the records, with a list or object value shown as its count and a View button that opens it in a drawer, never inline JSON. A table of stored results SHALL fetch one API page at a time (50 rows by default, 10, 25, 50 or 100 by a page-size selector) and show "Rows a–b of total" from the page's `total`; it SHALL NOT hold the whole result set. The URL input of the command bar SHALL be a plain input; a URL typed without a scheme is sent with `https://`. Enforced by: component tests; active.
#### Scenario: A long result
- **WHEN** a job holds 1,200 records
- **THEN** the table shows rows 1–50 of 1,200 and Next reads the page after `next_cursor`

### Requirement: Layout never shifts on interaction
Paging, tabs, filters, toggles, popovers, drawers and run-state changes SHALL move nothing around them: `PagedTable` pages by 20 in a fixed-height box with fixed column widths and truncation, and loading, empty and error states (including the playground output box) keep the content's footprint, and a toolbar select's error line hangs under it. (Previously: Schema's error line only.) Refs: D-1214, D-0751, D-0833, D-0985, DESIGN.md.
#### Scenario: Short last page
- **WHEN** the last page holds fewer than 20 rows
- **THEN** the table box and pager keep their size and place

### Requirement: Problems, toasts, theme and time
RFC 9457 problems SHALL render in `ProblemAlert`, button outcomes (including refused exports) as toasts; the theme follows `prefers-color-scheme` until chosen, storing only the explicit choice in `localStorage` inside try/catch; fonts are bundled with no third-party requests; times show in the viewer's zone, 24-hour. Refs: D-0054, D-0778, D-0779, D-0979.

### Requirement: Event stream consumption
Job events SHALL be read with `fetch` streaming, resumed with `Last-Event-ID`, reconnecting at 1 s doubling to 30 s, treating 35 s of silence as dropped and stopping on a 4xx other than 429 (`frontend/src/api/events.ts`); end events re-read summary and results. Refs: D-0702, D-0750.

### Requirement: Playground modes and command bar
The playground SHALL serve Scrape `/`, Batch `/batch`, Crawl `/crawl`, Map `/map`, Extract `/extract` and Search
`/search` behind a link-tab mode switch without visible group captions, with one centred command bar (input row, then Options, Format, Schema, Get code and the primary button) that does not move between the single-URL modes at desktop width, and at phone width puts Get code and the primary button on the row under the input; Batch's URL box shows ten lines and scrolls inside (`frontend/src/screens/playground/`). Search takes a query, shows Format and Schema only with Scrape results on, lists its results on the page and links to the batch run; Crawl's options include Strategy, Query, Keywords, Include subdomains and Follow external links (the query and keywords are sent only for Best first, and a stored crawl's keywords are restored, D-1596). (Previously: five modes, no Search.) Refs: Appendix A #38, #45, #51, #61, D-0817, D-1043, D-1213, D-1216, D-1447.
#### Scenario: Back and forward
- **WHEN** a user switches from Scrape to Crawl and presses back
- **THEN** the URL returns to `/` and Scrape mode shows

### Requirement: Inputs and settings mirror the request DTOs
A URL without a scheme SHALL be sent with `https://` prepended (RFC 3986 §3); Batch takes one URL per line or a CSV (`url` column else first, RFC 4180), each line checked with the WHATWG URL parser. Scrape, Batch, Crawl and Extract take Max rows as `fetch.max_rows`. Each Options setting MUST map to a request member (except Metadata in JSON), empty limits are omitted, and an empty LLM call limit omits `budget`, so the project's cap applies. (Previously: no Max rows.) Refs: D-1395, D-0408, D-0819, D-0982, D-1006, D-1044, D-1121.
#### Scenario: Host and port typed
- **WHEN** the user types `example.com:8080/p`
- **THEN** the request's `url` is `https://example.com:8080/p`

### Requirement: Schema, fields and format rules per mode
A stored schema in Scrape SHALL add `records` and fix the page kind, of either page kind; Batch and Crawl with a schema or field names send `formats: ["records"]`; Extract's toolbar Schema chooses its source (a stored schema, inline JSON, a prompt or field names) and reports a missing one there; fields (1–50 names, `[a-z][a-z0-9_]{0,63}`) and a stored schema are never sent together, and a fields run first shows the `POST /v1/schemas/draft` result for confirmation. Drafting is owned by [schemas](../schemas/spec.md). Refs: Appendix A #41, D-0752, D-0818, D-0925, D-0980, D-1214, D-1217.
#### Scenario: Batch with a schema
- **WHEN** a batch is started with a stored schema
- **THEN** the request's `formats` is `["records"]`

### Requirement: Clean JSON output and run view
Output SHALL be read as `json_values` items `{url, outcome, records, metadata?}` (endpoint owned by [jobs](../jobs/spec.md)); `JsonView`, shown first with line numbers and indent guides, holds a page's one record as an object or its records as an array, metadata under `data` beside it when asked for; a job run lives at `<route>?job=<id>` with status, Cancel, JSON/CSV exports, `RunProgress`, a `PagedTable` of items with per-row drawer, and a collapsed `ActivityFeed` worded in `activityText.ts`, where an unknown event shows its kind name. Refs: #51, D-0825, D-0826, D-0829, D-0832, D-0879, D-0984, D-1211, D-1212.
#### Scenario: Markdown-only crawl
- **WHEN** a crawl ran with `formats: ["markdown"]`
- **THEN** each row's drawer shows its markdown output and Export CSV is disabled

### Requirement: Recent runs, job routing and re-run
Each mode SHALL list its last 10 jobs before a run; `/jobs/:id` redirects to the kind's mode route with `?job=` (except `learn`, which keeps its page); a shown run is read-only from `GET /v1/jobs/{id}/request` until "Edit and re-run", which starts a new job. A map's request and URLs live in its browser history entry, so back and reload show them. Map or Crawl selections open Batch via navigation state. Refs: D-0855, D-0856, D-0861, D-0976, D-1215.
#### Scenario: Old job link
- **WHEN** `/jobs/<id>` is opened for an `extract` job
- **THEN** the UI redirects to `/extract?job=<id>`

### Requirement: Get code drawer
Get code SHALL show the endpoint (checked against `openapi.json` by a test), cURL, Python and MCP code generated from the exact request the primary action would send, the key's source without its value, and per-mode agent prompts (`screens/playground/getCode/`, `prompts/`). Refs: D-0890, D-0891, D-0894, D-0974.
#### Scenario: Incomplete request
- **WHEN** the mode's builder returns no request
- **THEN** each tab shows "Complete the request above to see its code." and Copy code is off

### Requirement: Data screens
Jobs (`/jobs`, run history, filters in the URL), Records (one schema, drawer inspector with Replay), Schemas (one form for create, adopt and edit; edit only on active non-preset), Sites and configs (host lookup, learn with `force`, correction via `PUT /v1/configs/{id}` with changed fields only, Approve and Reject (`POST /v1/configs/{id}/reject`) on a `pending_approval` config, absent fields named) and Settings (the project's "LLM call limit per run", "Draft call limit per key" and "Approve learned configs" via `/v1/project/settings`; LLM usage tables from `GET /v1/usage/llm`, unknown cost never guessed) SHALL live under `frontend/src/screens/`. (Previously: no reject, and no draft limit field.) Refs: D-0433, D-0656, D-0700, D-0978, D-0983, D-1342, D-1391, D-1394.
#### Scenario: Correction round-trip
- **WHEN** an operator edits a field's steps and submits
- **THEN** `PUT /v1/configs/{id}` carries only changed and confirmed fields and the validation report shows inline

### Requirement: Scope limits
The UI MUST NOT add review queues, site health dashboards, alerts, metric charts, users, roles, signup or billing (§22, C13); Labeling behaviour is owned by [evaluation](../evaluation/spec.md). Refs: D-0716.

### Requirement: No site literals in frontend code (INV-03, cross-link)
Frontend source and tests SHALL contain no hostnames; fixtures use RFC 2606 names such as `https://example.test/p`. Enforced by: the site-literal scan (`tools/site_literal_scan.py`, see `openspec/project.md`); active.

### Requirement: Scrape browser actions options
Scrape's Options SHALL hold a Browser actions switch, Records (empty: the server's 100) and Paging hint (Detect, or
one hint), enabled only for page kind Listing and kept in place, disabled, otherwise; the switch on sends
`browser_actions` with the filled members, and never for another page kind. Refs: owner #52, D-1227.
#### Scenario: Detail page kind
- **WHEN** the switch is on and the page kind is changed to Detail
- **THEN** the rows stay where they are, disabled, and the request has no `browser_actions`

### Requirement: A page's fetch trail
The scrape output's fetch view SHALL name the platform adapter that read the page, and a job page's drawer SHALL list the
page's fetch attempts (rung, status, block class, challenge label, duration, error), read from the results with
`include=fetch`, so a blocked page shows why. Refs: D-1392, D-1393.
#### Scenario: Blocked page
- **WHEN** a page's attempts end in `blocked` with a challenge label
- **THEN** its drawer shows each attempt's rung, status, block class and label

### Requirement: Advanced fetch options and actions editor
The Options of Scrape, Batch, Crawl and Extract SHALL hold an Advanced section after the common settings, shown at
once like every setting (no nested panel to open): headers and
cookies (one `Name: value` / `name=value` per line), proxy pool, wait for and cache, sent as the `fetch` members while
filled; and an actions editor that adds, edits, reorders and removes steps (at most 20), sent as `fetch.actions`.
A combination the server always refuses (a screenshot, PDF, wait for or actions with the HTTP method; headers with
the browser, wait for or actions) is named on its field and not sent.
Refs: owner delegation 2026-10-17, D-1430, D-1436, D-1595.
#### Scenario: A click step
- **WHEN** the user adds a Click step with selector `.more`
- **THEN** the request's `fetch.actions` is `[{"type": "click", "selector": ".more"}]`

### Requirement: Output formats in the playground
The playground SHALL offer the formats Markdown (fit), Chunks, Screenshot and PDF with their options, show the
screenshot, chunks and fit markdown in the scrape output and the screenshot in a job page's drawer, and a "More exports"
menu SHALL save JSON Lines, Excel, Parquet, `llms.txt` and `llms-full.txt` of a job. Refs: D-1429.

### Requirement: Schedules screen and Schedule this
`/schedules` SHALL list the schedules (name, kind, cadence, next run, last run and its job or error) with Edit, Pause or
Resume, Run now and Delete, and a schedule's page its jobs from `GET /v1/jobs?schedule_id=`; Edit changes the name,
cadence and request (JSON) and sends only what changed (`PATCH /v1/schedules/{id}`); Scrape, Batch, Crawl and Extract
offer "Schedule this", and a run of Batch, Crawl or Extract "Schedule this run" (its stored request), which create a
schedule (`frontend/src/screens/schedules/`). (Previously: no Edit, no Schedule this run.) Refs: D-1418, D-1514.
#### Scenario: Schedule a crawl
- **WHEN** a user fills Crawl, chooses "Schedule this" and an interval of 60 minutes
- **THEN** `POST /v1/schedules` carries `kind: "crawl"`, that crawl's request and `interval_s: 3600`
#### Scenario: Edit the cadence
- **WHEN** a user edits a schedule's name and changes its cadence to a cron expression
- **THEN** `PATCH` carries the new `name`, `cron` and `timezone`, and no `request`

### Requirement: Webhook options
The Options of Batch, Crawl and Extract SHALL hold Webhook URL, Events and Batch (events and seconds), mapping to
`webhook_url`, `webhook_events` and `webhook_batch`; an empty URL sends none of them. Refs: D-1419.

### Requirement: Webhook deliveries panel
A job's run page and a job's page SHALL show, for a job that has a `webhook_url`, a collapsed Deliveries panel listing
`GET /v1/jobs/{id}/webhook-deliveries` in a `PagedTable` (status, attempts, the receiver's HTTP status, events, last
error, created, next attempt), read again every 5 s while a delivery is pending; a job without a webhook has none
(`frontend/src/components/WebhookDeliveries.tsx`). Refs: D-1511, D-1512.
#### Scenario: A refused delivery
- **WHEN** a job's one delivery is `pending` after a 503
- **THEN** the panel's row shows `pending`, attempts, 503 and the error `status 503`

### Requirement: A listing's page fields and why it has no rows
The scrape output SHALL show the answer's `page` fields (a listing that kept no record) as a Page fields table under
the records in Table and as `page` beside `data` in JSON, and the `no_rows: not_asked` reason as a sentence with the
server's reason as its tooltip (`screens/playground/output/`). (Previously: each `no_rows: <cause>` had a sentence.)
Refs: D-1475, D-1476, D-1515, D-1605.
#### Scenario: Next page of an empty listing
- **WHEN** a scrape answers `records: []`, `page.next_page_url` and reason `no_rows: not_asked`
- **THEN** Table shows `next_page_url` under Page fields, JSON holds `"page"`, and the header says the row reader was
  not asked

### Requirement: Minimum confidence option
Scrape, Batch, Crawl and Extract Options SHALL hold a Minimum confidence (%) that sends `min_confidence` as a fraction
and nothing while empty, and a stored job's request SHALL fill it back (`screens/playground/rows.tsx`). Refs: D-1771.
