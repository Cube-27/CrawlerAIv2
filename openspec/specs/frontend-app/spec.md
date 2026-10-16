# Frontend Application Specification

## Purpose

The web UI is a thin client over the REST API: an app shell with navigation, and the screens other than the
playground (Jobs, Records, Schemas, Sites and configs, Labeling, Settings). It shows server values only and holds no
extraction, normalization or heuristic logic. The playground (Scrape, Batch, Crawl, Map, Extract) is
[its own capability](../playground/spec.md); visual and component conventions are in
[DESIGN.md](../../conventions/DESIGN.md).
Design rationale: [ARCHITECTURE §1, §3](../../design/overview.md), [§13.1](../../design/api.md),
[§18](../../design/operations.md), [Appendix A #27, #38](../../design/owner-decisions.md). History:
[SPEC-12](../../changes/archive/2026-10-14-spec-12-frontend-application/SPEC-12-frontend-application.md) and its
[decisions](../../changes/archive/2026-10-14-spec-12-frontend-application/decisions.md).

## Requirements

### Requirement: Thin client over the REST API
The UI SHALL call the REST API through the client generated from `openapi.json` (`src/api/schema.d.ts`) and SHALL
display server values as sent. It MUST NOT extract, normalize, infer field types or validate selectors or schema
rules itself; server refusals (422, 409) are shown where they apply.
Refs: §3, SPEC-12 §2, §4.1, D-0409, D-0435, D-0472.

#### Scenario: Schema rule left to the server
- **WHEN** a schema form is saved with a rule the server refuses
- **THEN** the form sends it and shows the server's 422 next to the input it names
- **AND** the form itself checks only the JSON shape, a chosen page kind and unique field names

#### Scenario: Field type unknown
- **WHEN** no schema for a record is readable
- **THEN** a string value is shown as is and any other value as JSON, with no type inferred from the value

### Requirement: Stack and generated client
The frontend SHALL be Vite + React + TypeScript + HeroUI v3, with server state only through TanStack Query hooks over
the generated client. All endpoint data shapes MUST come from `schema.d.ts`; CI fails when `make api-client` produces
a diff.
Refs: Appendix A #27, SPEC-12 §4.1, §6.

#### Scenario: Stale client
- **WHEN** a backend change alters `openapi.json` and `schema.d.ts` is not regenerated
- **THEN** the `frontend` CI job fails

### Requirement: Server-side API key, no key in the browser
The UI SHALL never ask for an API key or hold one: the server that serves it (today the Vite dev proxy) attaches
`Authorization: Bearer $CRAWLERAI_UI_API_KEY` to `/v1` and `/healthz` requests. The dev server MUST bind
`127.0.0.1` with CORS off, and the proxy MUST refuse requests whose `Sec-Fetch-Site` is other than `same-origin` or
`none` before attaching the key; a future production server serves the UI on localhost or a private network only
(not built yet: no production server exists). No cookies or sessions.
Refs: §18, Appendix A #38, SPEC-14 §4.1, D-0809, D-0811, D-0828.

#### Scenario: Key from the environment
- **WHEN** `CRAWLERAI_UI_API_KEY` is set (shell export wins over the repo-root `.env`)
- **THEN** proxied requests carry it as a bearer header and the browser bundle never contains it

#### Scenario: Cross-site request
- **WHEN** a request reaches the proxy with `Sec-Fetch-Site: cross-site`
- **THEN** it is refused without the key attached
- **AND** requests without the header (curl, scripts) pass

### Requirement: Setup notice on 401
When any API call answers 401, the UI SHALL replace the routed screen (sidebar kept) with an `EmptyView`: "The API
rejected the request. Set `CRAWLERAI_UI_API_KEY` in `.env` to a key from `crawlerai apikey create`, then restart
`pnpm dev`." until the page is reloaded. There is no Connect screen and no redirect.
Refs: SPEC-14 §4.1, D-0812.

#### Scenario: Unset key
- **WHEN** the variable is unset and the API answers 401
- **THEN** the content area shows the setup notice in the content's footprint
- **AND** later screens keep showing it until reload

### Requirement: App shell and navigation
The shell SHALL have a left sidebar with labelled groups: Playground (the modes, from the one modes list), Data (Jobs,
Records, Schemas, Sites), Evaluate (Labeling, only when `GET /healthz` reports `eval_ui: true`), and Settings and the
dark-theme toggle at its foot. The current entry MUST carry `aria-current="page"`. `/` opens the playground.
Refs: SPEC-14 §4.8, SPEC-12 §4.3, D-0451, D-0452, D-0834.

#### Scenario: Labeling hidden
- **WHEN** `/healthz` answers `eval_ui: false`, fails, or has not answered
- **THEN** the Labeling entry is not shown
- **AND** `/healthz` is read once per query cache

#### Scenario: Routes
- **WHEN** the app routes
- **THEN** it serves `/schemas`, `/schemas/new`, `/schemas/:id`, `/schemas/:id/edit`, `/records`, `/sites`,
  `/sites/:host`, `/configs/:id`, `/jobs`, `/jobs/:id`, `/labeling`, `/labeling/:pageId` and `/settings`, beside the
  playground routes

### Requirement: Showing extraction results (INV-22, UI side)
Screens SHALL show a field only through the shared compositions `FieldValue`, `FieldStatusBadge`, `ConfidenceCell` and
`LocatorText`, so status, reason, evidence, confidence, `calibrated` and locator stay visible. A non-published or empty
value MUST render as "—" with its `reason` on hover, never as an empty string; status is text and icon (published →
success, missing → neutral, abstained → warning, conflict → danger), never color alone; confidence is a two-decimal
number, never a bar; `calibrated=false` shows a visible "uncalibrated" badge. INV-22 itself is owned by
[resolution](../resolution/spec.md).
Refs: SPEC-12 §4.2, §5, §7, DESIGN.md "Showing extraction results", D-0368, D-0369.

#### Scenario: Conflict field
- **WHEN** a record has a field with status `conflict` and reason `disagree`
- **THEN** it renders "—", the status text "conflict", the reason, and no value

#### Scenario: Uncalibrated confidence
- **WHEN** a published field has `calibrated=false`
- **THEN** its confidence shows as a number with an "uncalibrated" badge

### Requirement: Layout never shifts on interaction
Paging, tabs, filters, toggles, drawers and run state changes SHALL move nothing around them. `PagedTable` MUST page by
20 (`limit=20`, cursor previous/next) in a fixed-height box with fixed column widths and truncation; loading, empty and
error states fill the same box; a fixed-width table at phone width scrolls inside its box, not the page.
Refs: D-0751, D-0985, D-0833, DESIGN.md "Data tables".

#### Scenario: Short last page
- **WHEN** the last page holds fewer than 20 rows
- **THEN** the table box and pager keep their size and place

### Requirement: Problems, toasts and theme
An RFC 9457 problem SHALL render in `ProblemAlert` (title, detail, per-field lines next to inputs); a 429 shows its
retry time; the outcome of a pressed button (including a refused export) is a toast. The theme MUST follow
`prefers-color-scheme` until the viewer chooses, then persist only the explicit choice in `localStorage`
(`crawlerai.theme`, every access in try/catch); fonts are bundled, with no third-party requests; timestamps show in the
viewer's zone on a 24-hour clock with the exact instant in a tooltip.
Refs: SPEC-12 §4.4, §4.5, D-0054, D-0778, D-0779, D-0979.

#### Scenario: Storage unavailable
- **WHEN** `localStorage` throws
- **THEN** the page renders with the system theme

### Requirement: Jobs screen as run history
`/jobs` SHALL list every job from `GET /v1/jobs`, newest first, paged, with kind and status filters in the URL and a
job-id lookup; columns kind, target (start URL or URL count), status, tasks ("N tasks: a queued, b done, …" in
`url_task.status` order), created, and an "Open" cue. A row opens its run in its playground mode; runs are started only
in the playground.
Refs: SPEC-14 §4.8, SPEC-12 §4.3, D-0700, D-0710, D-0976.

#### Scenario: Open a batch job
- **WHEN** a `batch_scrape` row is opened, or `/jobs/<id>` is loaded for it
- **THEN** the UI goes to `/batch?job=<id>` (mapping in [playground](../playground/spec.md))

### Requirement: Learn job page
A `learn` job, which has no playground mode, SHALL keep its `/jobs/:id` page: status, a "cancel requested" label beside
it while `cancel_requested` is true, a Cancel button kept in place (disabled when the job cannot be cancelled),
`RunProgress`, usage with `llm_cost_usd`, and the `EventLog` of stored events, `task_failed` with its data.
Refs: SPEC-12 §4.3, D-0745, D-0761, D-0833, D-0975.

#### Scenario: Cancel pending
- **WHEN** a running learn job has `cancel_requested: true`
- **THEN** "cancel requested" shows beside its status and the disabled Cancel button stays where it was

### Requirement: Event stream consumption
The job event stream SHALL be read with `fetch` streaming and resumed with `Last-Event-ID`. Reconnect MUST wait 1 s,
doubling to 30 s, reset after a connection that delivered an event; 35 s without a byte counts as dropped; a 4xx other
than 429 stops the stream and shows its problem. `progress` re-reads the job summary, a reconnect re-reads it, and an
end event (`completed`, `failed`, `cancelled`) re-reads summary and results; the UI shows a reconnecting state.
Refs: SPEC-12 §4.2, §4.5, D-0702, D-0750.

#### Scenario: Silent stream
- **WHEN** no byte arrives for 35 s
- **THEN** the UI reconnects with the last event id and re-reads the job summary

### Requirement: Records screen
`/records` SHALL list records of one chosen schema, narrowed by job, site and "changed since" (a UTC minute, sent as
ISO 8601 with `Z`), with filters in the URL. The table shows at most six field columns (scalar fields first, then lists
and objects) plus mode, version, changed and confidence, with "Showing 6 of N fields. Open a record to see all of
them."; a row opens a bottom-drawer inspector with every `field_meta` attribute, `changed_fields`, the capture id and
"Replay".
Refs: SPEC-12 §4.3, D-0470, D-0471, D-0687, D-0978.

#### Scenario: Replay diff
- **WHEN** Replay calls `POST /v1/captures/{id}/replay` and it returns exactly one record
- **THEN** each field's `status` and `value` are compared to the stored record (member order ignored)
- **AND** with several records they are listed without a diff

### Requirement: Schemas screens
`/schemas` SHALL list schemas (name, origin, status, page kind); detail shows a fields table and JSON. Create, adopt
and edit share one form (`/schemas/new`, `/schemas/new?from=<id>`, `/schemas/:id/edit`). Edit and Retire are offered
only on an active non-preset schema; an edit updates the schema in place and the server sends its configs back to
learning. Adopting a `prompt_draft` creates a `user` schema via `POST`, prefilled without the draft's name.
Refs: SPEC-12 §4.3, Appendix A #43, D-0433, D-0436, D-0771.

#### Scenario: Adopt a draft
- **WHEN** "Adopt as user schema" is chosen on a draft
- **THEN** the form opens with the draft's document and an empty name that must be unique

### Requirement: Sites and configs screens
`/sites` SHALL be a host lookup opening `/sites/{host}` (no sites table until a `GET /v1/sites` exists). A site page
lists configs with status and field status counts and offers "Learn a config" for any stored schema; "Learn now" posts
`force: false`, and after a refusal "Learn anyway" posts `force: true`; a started learning job's status and link show
on the page. A config page shows per-field steps, status, yield and validity, the validation report and a correction
form.
Refs: SPEC-12 §4.3, D-0656, D-0657, D-0753, D-0983.

#### Scenario: Correction round-trip
- **WHEN** an operator edits a field's steps and submits
- **THEN** `PUT /v1/configs/{id}` carries only changed fields (`null` for a field left with no steps, CSS steps as
  `{css, post}`) and the confirmed fields
- **AND** the response's validation report shows inline and the new version appears in the list

#### Scenario: Config export
- **WHEN** Export is chosen with a format
- **THEN** the export is saved as `<site>-v<version>-<format>.json` and the release report shows with `manual` fields
  marked

### Requirement: Settings with LLM usage and cost
`/settings` SHALL show an "LLM usage & cost" section from `GET /v1/usage/llm` for the last 7, 30, 90 or 365 UTC days:
totals, a breakdown by model and role, the top jobs by cost linking to each job, and a per-day table. Tables only, no
charts; an unknown cost reads "Unknown" with its unpriced token count, never a guessed price.
Refs: §1, SPEC-12 §2 item 8, §4.3.

#### Scenario: Range change
- **WHEN** the range changes from 30 to 90 days
- **THEN** the request's range changes and every table reloads in place

### Requirement: Labeling integration and scope limits
The Labeling screen (behaviour in [evaluation](../evaluation/spec.md)) SHALL be reachable from the shell when
`eval_ui` is on and uses the same proxied key. The UI MUST NOT add review queues, site health dashboards, alerts,
production-metric charts, users, roles, signup or billing (§22, non-goals).
Refs: SPEC-12 §2, §9, D-0716.

#### Scenario: Dashboard request
- **WHEN** a change would add a site health dashboard
- **THEN** it is out of scope until the owner admits it (§22, C13)

### Requirement: No site literals in frontend code (INV-03, cross-link)
Frontend source and tests SHALL contain no hostnames; fixtures use `example.test` / `example.com`. Enforcement is
owned by [repo-checks](../repo-checks/spec.md).
Refs: SPEC-12 §5, C3.

#### Scenario: Fixture host
- **WHEN** a frontend test needs a URL
- **THEN** it uses an RFC 2606 name such as `https://example.test/p`
