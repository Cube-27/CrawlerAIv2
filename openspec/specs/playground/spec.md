# Playground Specification

## Purpose

The playground is the UI's main workspace: one page per run type (Scrape, Batch, Crawl, Map, Extract) with a mode
switch, a centred command bar holding the input and the primary action, an options popover, and the run's output on
the same page, mostly as clean JSON. It is a UI over the existing scrape, batch, crawl, map and extract APIs and holds
no extraction logic. The app shell, key handling and other screens are in [frontend-app](../frontend-app/spec.md);
the `json_values` export and the `fields` request member are server behaviour owned by [jobs](../jobs/spec.md) and
[schemas](../schemas/spec.md), summarized here where the UI depends on them.
Design rationale: [ARCHITECTURE §1, §3](../../design/overview.md), [§13.1](../../design/api.md),
[Appendix A #38, #41, #45](../../design/owner-decisions.md). History:
[SPEC-14](../../changes/archive/2026-10-16-spec-14-playground-workspace/SPEC-14-playground-workspace.md) and its
[decisions](../../changes/archive/2026-10-16-spec-14-playground-workspace/decisions.md).

## Requirements

### Requirement: Modes and routes
The playground SHALL serve Scrape at `/`, Batch at `/batch`, Crawl at `/crawl`, Map at `/map` and Extract at
`/extract`. The mode switch is HeroUI `Tabs` whose tabs are links, grouped "Pages" (Scrape, Batch, Extract) and "Sites"
(Map, Crawl), centred over the command bar; the switch and the sidebar read one list of modes (`modes.ts`).
Refs: SPEC-14 §4.2, §4.8, Appendix A #38, D-0817, D-0834.

#### Scenario: Back and forward
- **WHEN** a user switches from Scrape to Crawl and presses back
- **THEN** the URL returns to `/` and Scrape mode shows

### Requirement: Centred command bar with the primary action on top
The command bar SHALL be one `Card` centred in `--container-playground` (48rem) under the mode switch: row 1 is the
input in a box of at least `--height-playground-input` (5rem); row 2 is the toolbar with Options, Format
(Scrape/Batch/Crawl), Schema (stored schema or "None"; not Map) on the left and Get code then the primary button
("Scrape", "Start batch", "Start crawl", "Map", "Extract") on the right. Switching modes MUST move neither the card nor
the primary button at desktop width; the output below takes the content width.
Refs: SPEC-14 §4.2, Appendix A #45, D-1043.

#### Scenario: Mode switch keeps the button
- **WHEN** the user switches from Scrape to Batch
- **THEN** the primary button stays at the same place

### Requirement: URL input
In Scrape, Crawl, Map and Extract, row 1 SHALL be a URL field with an `https://` prefix: text without a scheme and
`://` (RFC 3986 §3) is sent with `https://` prepended, and a URL with a scheme is sent as typed.
Refs: SPEC-14 §4.2, D-0819, D-1045.

#### Scenario: Host and port typed
- **WHEN** the user types `example.com:8080/p`
- **THEN** the request's `url` is `https://example.com:8080/p`

### Requirement: Batch URL list and CSV upload
In Batch, row 1 SHALL be a text area of URLs, one per line, with a live "N URLs" count and a CSV upload icon. A CSV
fills the list from its `url` header column if present, else its first column (RFC 4180); uploaded URLs are appended
and exact duplicates dropped. Before sending, each line MUST be checked with the WHATWG URL parser for `http`/`https`,
and a bad one named as "Line N is not a web address: ..." (counted from 1).
Refs: SPEC-14 §4.2, D-0982.

#### Scenario: Quoted CSV without header
- **WHEN** a CSV with no `url` header and quoted first-column values is uploaded
- **THEN** the first column's URLs are appended, without duplicates

### Requirement: Options popover
Options SHALL open a HeroUI `Popover` overlay that moves nothing on the page, holding every setting at once (no nested
Advanced section) in a grid of label-over-control cells, four columns from `sm` and one at phone width, with "Reset
settings" on its top line. Escape, a click outside or Options closes it, and a number typed last is kept (focus is
blurred before closing). The Options button shows a dot exactly when any setting differs from its default.
Refs: SPEC-14 §4.2, Appendix A #45, D-1041, D-1042.

#### Scenario: Escape after typing a limit
- **WHEN** the user types 5 in a number field and presses Escape
- **THEN** the popover closes and the value 5 is kept
- **AND** the Options dot shows

### Requirement: Settings mirror the request DTOs
Each mode's settings SHALL be: Scrape — page kind, fetch method, max age, timeout, LLM call limit, Metadata in JSON,
Fields; Batch — page kind, fetch method, LLM call limit, Metadata in JSON, Fields, webhook URL; Crawl — include and
exclude globs, max depth, page limit, fetch method, Metadata in JSON, Fields, webhook URL, page-kind rules; Map —
include and exclude globs, use sitemaps, use links, page limit; Extract — more URLs or globs, schema source, page kind,
page limit, fetch method, LLM call limit, webhook URL. Apart from Metadata in JSON, a setting MUST exist only for a
request member, and empty limits are left out of the request (the server decides defaults).
Refs: SPEC-14 §4.2, D-0408.

#### Scenario: Map settings
- **WHEN** Map mode is shown
- **THEN** it offers no schema, LLM call limit or Fields setting, since `MapRequest` has none

### Requirement: LLM call limit
Scrape, Batch and Extract SHALL show "LLM call limit" for `budget.llm_calls`. Empty MUST leave `budget` out, and the
field says what that means: "No limit" for a batch, "10" (the server's default) for a scrape or an extract. Crawl and
Map have no limit field, since their requests have no `budget`.
Refs: SPEC-14 §4.2, D-1006, D-1044.

#### Scenario: Empty batch limit
- **WHEN** a batch is started with the limit empty
- **THEN** the request has no `budget` member

### Requirement: Schema and format rules per mode
Picking a stored schema in Scrape SHALL add `records` to formats with the schema's page kind as the only page kind
offered; a schema the server would refuse keeps the request unsent with the reason under Page kind. Batch and Crawl
with a schema or field names MUST send `formats: ["records"]` with Format disabled; Crawl with a schema fixes every
rule's page kind to the schema's and needs one rule. Extract's schema source is Stored, Inline JSON, From a prompt or
From field names; its `urls` are the bar's URL then the "More URLs or globs" list.
Refs: SPEC-14 §4.2, D-0752, D-0818, D-0857, D-0858, D-0980.

#### Scenario: Batch with a schema
- **WHEN** a batch is started with a stored schema
- **THEN** the request's `formats` is `["records"]`

### Requirement: Single-page output with JSON first
A scrape's output SHALL show tabs JSON (default), Table (fields through `FieldValue`/`RecordTable`, so status and
confidence stay visible), one tab per requested page format, and Usage (with fetch method, status and attempts). The
JSON tab shows the clean item `{url, outcome, records, metadata?}` in `JsonView` (two-space indent, theme-token
colors, Copy and Download `.json`, fixed-height scrolling box), with one "uncalibrated" badge above it exactly when a
published field has `calibrated=false`.
Refs: SPEC-14 §3, §4.3, §4.4, D-0825, D-0827.

#### Scenario: Unpublished field in JSON
- **WHEN** a schema field did not publish
- **THEN** the clean record has it as `null`, fields in name order, with no status, confidence or evidence

### Requirement: Clean JSON shape (json_values)
The playground SHALL read run output as `json_values` items: one per task, in task order, `{url, outcome, records,
metadata?}`, where a clean record holds the schema's fields in name order (published value or `null`), `records` is
always an array (empty for failed, blocked, `links_only` or schemaless tasks), and `metadata` appears only with
`include=metadata`. Metadata in JSON adds `metadata` to `formats` and `include=metadata` to the results request; the
UI shapes nothing beyond picking members. Endpoint behaviour is owned by [jobs](../jobs/spec.md).
Refs: SPEC-14 §4.4, D-0809, D-0813, D-0814, D-0816, D-0826.

#### Scenario: Metadata switch
- **WHEN** Metadata in JSON is on for a batch
- **THEN** the request's `formats` contains `metadata` and the table reads `results?format=json_values&include=metadata`

### Requirement: Run view for job modes
A started run SHALL live in the URL (`<route>?job=<id>`) and show one flow: a `Card` with status, a "cancel
requested" label while `cancel_requested` is true, Cancel (kept in place, disabled when not cancellable), JSON and CSV
exports, then `RunProgress` ("N of M pages done" with N = done + failed, ", K cancelled" when any, elapsed time,
outcomes reached); then a `PagedTable` over `json_values` (URL, Outcome, records count, JSON button opening a
right-side drawer with that page's item); then the activity, collapsed. Batch, Crawl, Extract and an opened scrape job
use it.
Refs: SPEC-14 §4.3, D-0829, D-0830, D-0833, D-0860, D-0975, D-0981.

#### Scenario: Results refresh
- **WHEN** `task_extracted` or `task_failed` events arrive while the run is running
- **THEN** the current results page re-reads at most once a second, and the end event re-reads at once

### Requirement: Run exports
Export JSON SHALL save every page's items as one array, equal to the drawers' items in task order; Export CSV asks for
`csv_records` with `csv_safe=true`. For a job without records (no `records` in its stored `formats`), the drawer shows
the page's outputs from `format=json` at the same cursor, Export JSON saves the page outputs, and Export CSV is
disabled. A refused export is a toast.
Refs: SPEC-14 §4.4, D-0879, D-0979, D-1010.

#### Scenario: Markdown-only crawl
- **WHEN** a crawl ran with `formats: ["markdown"]`
- **THEN** each row's drawer shows its markdown output and Export CSV is disabled

### Requirement: Live activity
`ActivityFeed` SHALL show the job's SSE events as plain-language lines worded in one module (`activityText.ts`) from
event data only, grouped by task URL, newest group first, in a fixed-height scrolling box inside a collapsed
"Activity" section with the stream state and elapsed time in its header. `progress` updates counts without a line. An
unknown event kind, or one missing the data its line needs, MUST show its kind name, never be dropped.
Refs: SPEC-14 §4.5, D-0832, D-0984.

#### Scenario: Shell page
- **WHEN** `task_fetched` has a block class other than `ok`
- **THEN** the line adds "Block class: X." rather than claiming the page was blocked

### Requirement: Crawl and Map output; batch from results
Crawl output SHALL use the run view; Map output is a `PagedTable` of links with row selection. Selecting URLs in a Map
or Crawl result and choosing "Scrape as batch" MUST open `/batch` with those URLs as its initial list, passed in
navigation state, not the query string.
Refs: SPEC-14 §2 item 8, §4.3, D-0861.

#### Scenario: Map to batch
- **WHEN** three map links are selected and "Scrape as batch" is chosen
- **THEN** Batch mode opens with those three URLs in its list

### Requirement: Recent runs and job routing
Before any run, each mode SHALL list its last 10 jobs (`GET /v1/jobs` by kind): target, status, started, duration,
an "Open" cue, and "All runs" opening Jobs filtered by kind; an empty list is an `EmptyView`, and loading keeps the
footprint. Job kinds map to routes `scrape` → `/`, `batch_scrape` → `/batch`, `crawl` → `/crawl`, `map` → `/map`,
`extract` → `/extract`; `/jobs/:id` redirects to `<route>?job=<id>`, except `learn`.
Refs: SPEC-14 §4.6, §4.8, D-0855, D-0976.

#### Scenario: Old job link
- **WHEN** `/jobs/<id>` is opened for an `extract` job
- **THEN** the UI redirects to `/extract?job=<id>`

### Requirement: Read-only shown run, edit and re-run
Loading a mode with `?job=` SHALL fill the bar and options from `GET /v1/jobs/{id}/request`, read-only (disabled
fieldsets; Options still opens). "Edit and re-run" takes the primary button's place, makes them editable, and sending
starts a new job (the URL moves to it); the old job is kept. A batch or crawl whose stored request has an inline schema
shows "No schema".
Refs: SPEC-14 §4.8, D-0855, D-0856, D-0859.

#### Scenario: Re-run
- **WHEN** the user opens a past crawl, chooses "Edit and re-run" and starts it
- **THEN** a new job is created and the URL shows the new job's id

### Requirement: Get code drawer
Get code SHALL open a right-side drawer showing, in order: the endpoint (its OpenAPI summary, `POST` path and the first
sentence of its description, checked against `openapi.json` by a test), code tabs cURL, Python (`httpx.request("POST", …, timeout=300.0)`) and MCP (a JSON-RPC
`tools/call` request) with Copy code, where the key comes from (`crawlerai apikey create`, read from
`$CRAWLERAI_API_KEY`, no key value shown), then "Prompts for coding agents" collapsed (two per mode, from
`prompts/<mode>.md`). The code MUST be generated from the request the primary action would send, values JSON-encoded
and cURL quoting per POSIX sh, base URL from `window.location.origin`.
Refs: SPEC-14 §4.7, D-0890, D-0891, D-0892, D-0893, D-0894, D-0974.

#### Scenario: Incomplete request
- **WHEN** the mode's builder returns no request (no format, schema or page kind)
- **THEN** each tab shows "Complete the request above to see its code." in the same box and Copy code is off

#### Scenario: Batch MCP tab
- **WHEN** Get code is opened in Batch
- **THEN** the MCP tab says Batch has no MCP tool and Copy code is off

### Requirement: Additional fields (chips)
A Fields setting (Scrape, Batch, Crawl; Extract's "From field names") SHALL take 1–50 distinct names matching
`[a-z][a-z0-9_]{0,63}`, refusing a bad entry in place with its reason; fields and a stored schema are never sent
together. The primary action MUST first show the draft from `POST /v1/schemas/draft` in a right-side drawer in
`SchemaForm`: Run as drafted sends `schema: {"fields": [...]}` (the body Get code shows); Run after an edit sends
`schema.inline` under a new name; closing sends nothing; a failed draft shows its problem in the drawer. A crawl uses
its rules' one page kind. Server drafting is owned by [schemas](../schemas/spec.md).
Refs: SPEC-14 §4.10, Appendix A #41, D-0810, D-0925, D-0928, D-0929.

#### Scenario: Edited draft keeps its name
- **WHEN** the user edits the draft and keeps the draft's name
- **THEN** the UI refuses to run it until it has a name of its own

### Requirement: Output area keeps its footprint
The output area SHALL appear from a mode's first run (or show recent runs before it) in a box of at least
`--height-playground-output`; pending, failed and done states, tabs, paging, the options popover and drawers MUST move
nothing around them.
Refs: SPEC-14 §4.2, §7, DESIGN.md "Playground output".

#### Scenario: Run fails
- **WHEN** a scrape request fails with a problem
- **THEN** the problem shows inside the same output box
