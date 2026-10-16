# Frontend Specification

## Purpose

The web UI is a thin client over the REST API: an app shell, the playground (Scrape, Batch, Crawl, Map, Extract) and the data screens (Jobs, Records, Schemas, Sites and configs, Labeling, Settings); visual conventions are in [DESIGN.md](../../conventions/DESIGN.md). Rationale: ARCHITECTURE §1, §3, §13.1, §18, Appendix A #27, #38, #41, #45 ([archived](../../changes/archive/2026-10-16-architecture-rev26/ARCHITECTURE.md)); history: SPEC-12, SPEC-14.

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
The shell SHALL have a sidebar with groups Playground (from `screens/playground/modes.ts`), Data (Jobs, Records, Schemas, Sites), Evaluate (Labeling, only when `GET /healthz` reports `eval_ui: true`) and Settings plus theme toggle; the current entry carries `aria-current="page"`; routes are in `frontend/src/app/router.tsx`. Refs: D-0451, D-0452, D-0834.
#### Scenario: Labeling hidden
- **WHEN** `/healthz` answers `eval_ui: false`, fails, or has not answered
- **THEN** the Labeling entry is not shown

### Requirement: Showing extraction results (INV-22, UI side)
Screens SHALL show a field only through `FieldValue`, `FieldStatusBadge`, `ConfidenceCell` and `LocatorText` (`frontend/src/components/`): a non-published value renders "—" with its reason, status is text plus icon, confidence a two-decimal number, `calibrated=false` an "uncalibrated" badge. INV-22 is owned by [resolution](../resolution/spec.md). Enforced by: component tests; active. Refs: D-0368, D-0369.
#### Scenario: Conflict field
- **WHEN** a record field has status `conflict` and reason `disagree`
- **THEN** it renders "—", the status text "conflict" and the reason, with no value

### Requirement: Layout never shifts on interaction
Paging, tabs, filters, toggles, popovers, drawers and run-state changes SHALL move nothing around them: `PagedTable` pages by 20 in a fixed-height box with fixed column widths and truncation, and loading, empty and error states (including the playground output box) keep the content's footprint. Refs: D-0751, D-0833, D-0985, DESIGN.md.
#### Scenario: Short last page
- **WHEN** the last page holds fewer than 20 rows
- **THEN** the table box and pager keep their size and place

### Requirement: Problems, toasts, theme and time
RFC 9457 problems SHALL render in `ProblemAlert`, button outcomes (including refused exports) as toasts; the theme follows `prefers-color-scheme` until chosen, storing only the explicit choice in `localStorage` inside try/catch; fonts are bundled with no third-party requests; times show in the viewer's zone, 24-hour. Refs: D-0054, D-0778, D-0779, D-0979.

### Requirement: Event stream consumption
Job events SHALL be read with `fetch` streaming, resumed with `Last-Event-ID`, reconnecting at 1 s doubling to 30 s, treating 35 s of silence as dropped and stopping on a 4xx other than 429 (`frontend/src/api/events.ts`); end events re-read summary and results. Refs: D-0702, D-0750.

### Requirement: Playground modes and command bar
The playground SHALL serve Scrape `/`, Batch `/batch`, Crawl `/crawl`, Map `/map`, Extract `/extract` behind a link-tab mode switch, with one centred command bar (input row, then Options, Format, Schema, Get code and the primary button) that does not move between modes at desktop width (`frontend/src/screens/playground/`). Refs: Appendix A #38, #45, D-0817, D-1043.
#### Scenario: Back and forward
- **WHEN** a user switches from Scrape to Crawl and presses back
- **THEN** the URL returns to `/` and Scrape mode shows

### Requirement: Inputs and settings mirror the request DTOs
A URL without a scheme SHALL be sent with `https://` prepended (RFC 3986 §3); Batch takes one URL per line or a CSV (`url` column else first, RFC 4180), each line checked with the WHATWG URL parser. Each Options setting MUST map to a request member (except Metadata in JSON), empty limits are omitted, and an empty LLM call limit omits `budget`, so the project's cap applies. Refs: D-0408, D-0819, D-0982, D-1006, D-1044, D-1121.
#### Scenario: Host and port typed
- **WHEN** the user types `example.com:8080/p`
- **THEN** the request's `url` is `https://example.com:8080/p`

### Requirement: Schema, fields and format rules per mode
A stored schema in Scrape SHALL add `records` and fix the page kind; Batch and Crawl with a schema or field names send `formats: ["records"]`; fields (1–50 names, `[a-z][a-z0-9_]{0,63}`) and a stored schema are never sent together, and a fields run first shows the `POST /v1/schemas/draft` result for confirmation. Drafting is owned by [schemas](../schemas/spec.md). Refs: Appendix A #41, D-0752, D-0818, D-0925, D-0980.
#### Scenario: Batch with a schema
- **WHEN** a batch is started with a stored schema
- **THEN** the request's `formats` is `["records"]`

### Requirement: Clean JSON output and run view
Output SHALL be read as `json_values` items `{url, outcome, records, metadata?}` (endpoint owned by [jobs](../jobs/spec.md)) shown in `JsonView` first; a job run lives at `<route>?job=<id>` with status, Cancel, JSON/CSV exports, `RunProgress`, a `PagedTable` of items with per-row drawer, and a collapsed `ActivityFeed` worded in `activityText.ts`, where an unknown event shows its kind name. Refs: D-0825, D-0826, D-0829, D-0832, D-0879, D-0984.
#### Scenario: Markdown-only crawl
- **WHEN** a crawl ran with `formats: ["markdown"]`
- **THEN** each row's drawer shows its markdown output and Export CSV is disabled

### Requirement: Recent runs, job routing and re-run
Each mode SHALL list its last 10 jobs before a run; `/jobs/:id` redirects to the kind's mode route with `?job=` (except `learn`, which keeps its page); a shown run is read-only from `GET /v1/jobs/{id}/request` until "Edit and re-run", which starts a new job. Map or Crawl selections open Batch via navigation state. Refs: D-0855, D-0856, D-0861, D-0976.
#### Scenario: Old job link
- **WHEN** `/jobs/<id>` is opened for an `extract` job
- **THEN** the UI redirects to `/extract?job=<id>`

### Requirement: Get code drawer
Get code SHALL show the endpoint (checked against `openapi.json` by a test), cURL, Python and MCP code generated from the exact request the primary action would send, the key's source without its value, and per-mode agent prompts (`screens/playground/getCode/`, `prompts/`). Refs: D-0890, D-0891, D-0894, D-0974.
#### Scenario: Incomplete request
- **WHEN** the mode's builder returns no request
- **THEN** each tab shows "Complete the request above to see its code." and Copy code is off

### Requirement: Data screens
Jobs (`/jobs`, run history, filters in the URL), Records (one schema, at most six field columns, drawer inspector with Replay), Schemas (one form for create, adopt and edit; edit only on active non-preset), Sites and configs (host lookup, learn with `force`, correction via `PUT /v1/configs/{id}` with changed fields only) and Settings (the project's "LLM call limit per run" via `/v1/project/settings`; LLM usage tables from `GET /v1/usage/llm`, unknown cost never guessed) SHALL live under `frontend/src/screens/`. Refs: D-0433, D-0656, D-0700, D-0978, D-0983.
#### Scenario: Correction round-trip
- **WHEN** an operator edits a field's steps and submits
- **THEN** `PUT /v1/configs/{id}` carries only changed and confirmed fields and the validation report shows inline

### Requirement: Scope limits
The UI MUST NOT add review queues, site health dashboards, alerts, metric charts, users, roles, signup or billing (§22, C13); Labeling behaviour is owned by [evaluation](../evaluation/spec.md). Refs: D-0716.

### Requirement: No site literals in frontend code (INV-03, cross-link)
Frontend source and tests SHALL contain no hostnames; fixtures use RFC 2606 names such as `https://example.test/p`. Enforced by: the site-literal scan (`tools/site_literal_scan.py`, see `openspec/project.md`); active.
