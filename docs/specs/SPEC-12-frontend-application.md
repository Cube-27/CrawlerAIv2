# SPEC-12 — Frontend application screens

Layer: L1–L4 (each screen lands with the API it uses). Architecture refs: §1 (web UI), §3 (UI holds no logic),
§13.1 (endpoints), §5.4 (schema editing), §18 (UI auth), C5 (config correction through the API), §22 (what the
UI must not become), `docs/DESIGN.md` (SPEC-00).

> **Revised by SPEC-14 (ARCHITECTURE rev 17, Appendix A #38).** The Connect screen and key context, the job create
> dialogs, the Overview screen and the Scrape screen's layout are replaced by SPEC-14's playground and server-side
> key. The rest of this spec stands.

## 1. Summary

The web UI is a thin client over the REST API: it submits requests, shows jobs, records with `field_meta`,
schemas (including prompt drafts for editing), site configs with validation reports and operator corrections,
and hosts the labeling screen from SPEC-03. It holds no extraction logic (§3). Screens are built in the order
their APIs appear (SPEC-07 → SPEC-08 → SPEC-10 → SPEC-11).

## 2. Scope

Core screens:
1. **Connect** (API key entry; held in memory only and sent as a bearer header, no cookies (§18); SPEC-07 auth).
2. **Scrape** (form for `POST /v1/scrape`; shows formats and records) — L1.
3. **Schemas** (list, view versions, create/edit as form + JSON, edit a prompt draft into a user schema) — L1.
4. **Records** (browse by job/site/schema; field inspector with status, reason, evidence, confidence,
   calibrated, source kind, locator, derived_by; change feed with `changed_fields` once SPEC-11 exists) — L1/L4.
5. **Sites & configs** (site list with fetch method and mode; config versions; per-field steps, status and
   validation report; correction form → `PUT /v1/configs/{id}`; learn button; export download with release
   report) — L2.
6. **Jobs** (create batch/map/crawl/extract; list; detail with live events over SSE, outcome counts, usage,
   results table and export) — L3.
7. **Labeling** — from SPEC-03 (already built in L0; this spec only integrates navigation and shared components).
8. **Settings** — an "LLM usage & cost" section from `GET /v1/usage/llm` (owner, 2026-10-14; ARCHITECTURE rev 11):
   a range (last 7, 30, 90 or 365 days), totals, a breakdown by model and role, the top jobs by cost linking to
   each job, and a per-day table. Tables only (DESIGN.md: no charts). An unknown cost reads "Unknown" with its
   unpriced token count.

Out of scope (§22 and non-goals):
- Review queue UI beyond labeling and config correction; site health dashboard; alerts; any chart of
  production metrics.
- Users, roles, signup, billing.
- Any client-side extraction, normalization or heuristics (the UI calls `/normalize` from the labeling API and
  otherwise displays server values).

## 3. Dependencies

- SPEC-00 (skeleton, DESIGN.md, generated client), SPEC-03 (labeling screen), SPEC-07, SPEC-08, SPEC-10,
  SPEC-11.
- No open questions; HeroUI v3.2.x per SPEC-00.

## 4. Design

### 4.1 Structure

```
frontend/src/
  app/        router.tsx, shell.tsx (top bar, nav, theme toggle), theme.css, auth.tsx (key context)
  api/        schema.d.ts (generated), client.ts, hooks/ (TanStack Query hooks per endpoint)
  components/ FieldValue, FieldStatusBadge, ConfidenceCell, LocatorText, RecordTable, SchemaForm, StepsEditor,
              JsonView, EventLog, OutcomeCounts, UsageSummary, ProblemAlert
  screens/    connect/ scrape/ schemas/ records/ sites/ jobs/ labeling/
```

- Routing: `/connect`, `/scrape`, `/schemas`, `/schemas/:id`, `/records`, `/sites`, `/sites/:host`,
  `/configs/:id`, `/jobs`, `/jobs/:id`, `/labeling`. Unauthenticated → `/connect`.
- State: server state only via TanStack Query; the API key in a React context (memory only, never persisted, so a
  reload returns to `/connect`; §18); per-viewer conveniences (theme, last filters) in `localStorage` wrapped in
  try/catch.
- Every request carries the bearer header, so nothing relies on the browser attaching credentials: SSE is read
  with `fetch` streaming (the browser `EventSource` cannot send an `Authorization` header), and exports are
  fetched with the header and saved as a file rather than opened as plain links.
- All data shapes come from `schema.d.ts`; no hand-written DTO types.

### 4.2 Shared components (rules from DESIGN.md)

- `FieldValue`: renders a typed value by `type` (money as `amount currency`, location as `locality, region,
  country`, dates ISO, lists as chips); non-published fields render "—" with the `reason` in a tooltip and the
  `status` as text in the badge.
- `FieldStatusBadge`: `published` / `missing` / `conflict` / `abstained` as text + icon (never color only).
- `ConfidenceCell`: number with two decimals; `calibrated=false` → visible "uncalibrated" badge; never a bar.
- `LocatorText`: monospace, copy button.
- `StepsEditor`: list editor for IR steps (`xpath`, `css`, `jsonld`, `jsonpath`, `regex`, `attr`, post ops) with
  validation feedback from the server's `PUT` response; the UI does not validate selectors itself.
- `EventLog`: SSE consumer with reconnect using `Last-Event-ID`.

### 4.3 Screens (behaviour)

- **Scrape**: URL, formats (checkbox group), schema (select: presets/user/draft, inline JSON, or prompt), page
  kind, max age, fetch hints, budget; result tabs: records (RecordTable with inspector drawer), markdown,
  html, links, metadata, fetch attempts, usage. A prompt result shows the draft with "Edit as schema".
- **Schemas**: table (name, version, origin, status, page kind); detail: fields table + JSON tab; edit creates a
  new version (server rule); drafts (`origin=prompt_draft`) show the originating prompt hash and an "Adopt as
  user schema" action (creates a `user` schema via `POST`).
- **Records**: filters (job, site, schema, changed since); RecordTable with one column per schema field
  (FieldValue) plus mode, version, confidence; row click opens the inspector (every `field_meta` attribute,
  the capture id with a "Replay" action calling `/v1/captures/{id}/replay` and diffing the result against the
  stored record).
- **Sites & configs**: a host lookup that opens `/sites/{host}` (ARCHITECTURE §13.1 has no endpoint that lists
  sites; a sites table with host, fetch method, mode per schema and pages extracted waits for a `GET /v1/sites`,
  added when operators need it: D-0656, owner answer 2026-10-16); site detail lists config
  versions with status and field status counts; config detail shows per-field steps, status, yield/validity,
  the validation report, and the correction form (StepsEditor per field + "confirm" checkboxes) submitting
  `PUT`; the response's validation report is shown inline; "Learn now" → `POST …/learn`; "Export" → format
  choice → download + release report with `manual` fields highlighted.
- **Jobs**: create dialogs for batch/map/crawl/extract mirroring the request DTOs (page-kind rules as a small
  table editor); jobs table (kind, status, counts, created); job detail: OutcomeCounts, UsageSummary, EventLog,
  results table (RecordTable or page outputs) with export actions (`json_records`, `csv_records`, `markdown`),
  cancel button. Page outputs show each page's `last_error` as a reason, truncated in a fixed-width column and in
  full on hover or focus; the EventLog shows `task_failed` events with their data. While a running or queued job's
  `cancel_requested` is true, the job page shows "cancel requested" beside its status in place of the cancel
  button (owner, 2026-10-14; ARCHITECTURE rev 12, D-0745).
- **Settings**: last nav entry; the LLM cost section described in §2 item 8. The job detail shows its
  `llm_cost_usd` under usage.
- **Labeling**: SPEC-03's screen; nav entry shown only when the backend reports `eval_ui: true` in
  `/healthz` (plumbing field).

### 4.4 Accessibility and theming

Per DESIGN.md: HeroUI components only for interactive elements; keyboard navigation in tables; focus visible;
`jsx-a11y` lint; `data-theme` light/dark with `prefers-color-scheme` default; 16px gutters at phone width.

### 4.5 Error handling

Problem-details responses render in `ProblemAlert` with `title`/`detail` and per-field errors next to inputs;
401 redirects to `/connect`; 429 shows the retry time; SSE disconnects reconnect with backoff and show a
"reconnecting" state.

## 5. Invariants

INV-03 (no hostnames in frontend source or tests — fixtures use `example.test`), INV-22 (every field rendered
shows status/evidence/confidence/calibrated/locator). The UI never changes server values (§3).

## 6. Testing strategy

- Vitest + Testing Library with MSW (MIT) mocking the API from `openapi.json` examples; tests per screen for:
  rendering of each field status, uncalibrated badge, abstention rendering ("—"), correction form submission
  payload, SSE reconnect, problem-details rendering, keyboard navigation of RecordTable.
- Type-level: the build fails if `schema.d.ts` is stale (SPEC-00 4.5).
- No end-to-end browser suite in core (would need a running backend in CI; not gated).
- CI gates: `frontend` job.

## 7. Acceptance criteria

- Every §13.1 endpoint has a screen or action that calls it; the labeling screen is reachable.
- A record with a `conflict` field renders "—" with reason `disagree`, status text, and no value.
- A config correction round-trips: edit a step, submit, see the server's validation report, see the new
  version in the list.
- Lighthouse/axe (manual) shows no critical a11y violations on the five main screens (documented in the PR).

## 8. PR plan

| # | Title | Scope | Checks | Done when | Layer |
|---|---|---|---|---|---|
| 1 | Connect screen + auth context + 401 handling | `app/auth`, `screens/connect` | vitest | Key gate works. | L1 |
| 2 | Shared field components | `components/FieldValue,…` | vitest | Status rendering tests. | L1 |
| 3 | Scrape screen | `screens/scrape` | vitest | Records + formats shown. | L1 |
| 4 | Schemas screens | `screens/schemas`, `SchemaForm` | vitest | Draft adoption. | L1 |
| 5 | Records screen + inspector + replay | `screens/records` | vitest | Inspector complete. | L1 |
| 6 | Sites & configs + StepsEditor + corrections + export | `screens/sites`, `StepsEditor` | vitest | PUT payload correct. | L2 |
| 7 | Jobs screens + EventLog (SSE) + exports | `screens/jobs`, `EventLog` | vitest | Reconnect tested. | L3 |
| 8 | Change feed in Records | `screens/records` | vitest | `changed_fields` shown. | L4 |
| 9 | Labeling nav integration + shared shell polish | `app/shell` | vitest | Nav gated by `eval_ui`. | L1 |
| 10 | Jobs table on /jobs | `screens/jobs` | vitest | Table of kind, status, counts, created from `GET /v1/jobs`, paged. | L3 |
| 11 | Settings screen with LLM usage & cost (with SPEC-06 PR 7, SPEC-10 PR 10; one PR) | `screens/settings`, `app/shell` | vitest | Totals, breakdown, top jobs linking to jobs, per day; range changes the request. | L3 |

## 9. Open issues

- `/healthz.eval_ui` is a plumbing field for nav gating.
- The architecture lists no UI screens explicitly; this set is derived from §13.1 endpoints and C5. Anything
  beyond it (dashboards, review queues) is §22 and must not be added here.
