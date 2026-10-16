# SPEC-14 — Playground workspace

Layer: L1–L3 (a UI over the existing scrape, batch, crawl, map and extract APIs; one export format added).
Architecture refs: §1 (web UI), §3 (UI holds no logic), §13.1 (endpoints), §18 (UI access, rev 17), §22 (what the UI
must not become), `docs/DESIGN.md`. Revises SPEC-12 (Connect screen, job create dialogs, Overview, Scrape screen).
Owner decisions: Appendix A #38, D-0809.

## 1. Summary

The UI's main job is to run a scrape, batch, crawl, map or extract and read its output, mostly as JSON. Today that
flow is spread over a Scrape screen, create dialogs on Jobs, a job page and Records. Every setting sits in its own
row in a long vertical form, and the primary button is at the bottom. The app also asks for an API key on every load.

This spec replaces that with one **playground**:
- The run type is a mode switch at the top.
- A command bar holds the URL (or URL list) and the primary action, with a toolbar under it.
- Settings open in an inline options panel under the bar. Common settings come first; Advanced (fetch, limits) is
  collapsed.
- Output appears below on the same page. A single page shows clean JSON. A batch or crawl shows a running table of
  pages, filled in as the run goes, with each page's JSON one click away.

The UI never asks for a key: whatever serves it attaches one (§18 rev 17). The layout follows the owner's reference
(a hosted scraping playground: mode tabs above a URL bar, options as rows with a control on the right). Visual values
stay HeroUI defaults with this app's theme (DESIGN.md).

## 2. Scope

1. **No key prompt.** The dev proxy attaches `Authorization: Bearer $CRAWLERAI_UI_API_KEY` to proxied API requests.
   The Connect screen, the key context and the 401 redirect go. A 401 shows a setup notice in the content area.
2. **Playground shell.** Routes `/` (Scrape), `/batch`, `/crawl`, `/map`, `/extract` render one workspace:
   - the mode switch;
   - the command bar;
   - the toolbar: Options, Format, Schema, then the primary action on the right;
   - the inline options panel;
   - the output area.

   The sidebar gets a "Playground" group with one entry per mode. The Overview screen goes; its numbers already
   live on Jobs and Settings.
3. **Single-page output (Scrape).**
   - Tabs: JSON (default), Table, then one tab per page format asked for (Markdown, HTML, Raw HTML, Links,
     Metadata), and Usage.
   - The JSON view is pretty-printed and coloured with theme tokens, with Copy and Download.
4. **Batch mode.**
   - The command bar becomes a URL list: one URL per line, with a count.
   - A CSV upload icon inside the box fills the list from a file.
   - The run stays on the page (`/batch?job=<id>`), shown as a running results table and the live activity feed.
5. **Live activity.** Run events (SSE) are shown as plain-language lines grouped per URL, with progress counts and
   elapsed time.
6. **Crawl and Map modes inline.**
   - Their settings move from dialogs into the options panel.
   - Crawl output uses the batch results table.
   - Map output is a table of links.
7. **Extract mode inline.**
   - The create dialogs leave Jobs, and Jobs becomes run history.
   - A run opens in the playground in its mode; `/jobs/:id` redirects there.
8. **Batch from results.** In a Map or Crawl result, the user selects URLs and chooses "Scrape as batch", which
   opens Batch mode with those URLs.
9. **Clean JSON export.**
   - A `json_values` results format: one item per page (task) with its `url`, `outcome` and clean records (the
     schema's published fields only), plus `metadata` when the job asked for it (§4.4).
   - The batch and crawl table, the JSON drawer and the download all read this one shape.
10. **Get code** (second to last; the owner shared the reference). A right-side drawer for the current request
    (§4.7).
11. **Additional fields** (last; D-0810 option (a), §4.10). Field names typed as chips
    for an ad-hoc extraction: the server drafts a schema from them, shown for editing before the run.

Out of scope:
- Search (no search API).
- Login, users and sessions.
- Charts.
- Any client-side extraction or normalization (§3).
- The Records, Schemas, Sites and Labeling screens beyond their nav position.
- A production web server for the UI (none exists yet; §18 says what it must do when added).

## 3. Dependencies

- SPEC-12 (screens and shared components it reuses: `FieldValue`, `RecordTable`, `EventLog`, `PagedTable`,
  `ProblemAlert`).
- SPEC-07 (scrape), SPEC-10 (batch, crawl, map, extract, results, events, cancel), SPEC-08 §4.11 (record exporters).
- No open questions block the PRs. PR 11 builds D-0810 option (a) (owner, 2026-10-16).

## 4. Design

### 4.1 Access (§18 rev 17)

- `vite.config.ts`'s proxy for `/v1` and `/healthz` sets the `Authorization` header from `CRAWLERAI_UI_API_KEY`.
  Vite does not read the repo-root `.env` by itself, so the config reads it with `loadEnv(mode, <repo root>, "")`
  (documented in `.env.example`). The key never reaches the browser bundle: the proxy adds it server-side, and the
  variable has no `VITE_` prefix, so Vite never exposes it to client code.
- The dev server binds `server.host: "127.0.0.1"` explicitly, so the localhost-only claim below does not rest on a
  default.
- When the variable is unset, the proxy forwards requests unchanged and the API answers 401.
- The app has no key state. On a 401 the content area shows an `EmptyView`: "The API rejected the request. Set
  `CRAWLERAI_UI_API_KEY` in `.env` to a key from `crawlerai apikey create`, then restart `pnpm dev`." The 401 has the
  same footprint as content (no layout shift).
- SSE and exports go through the same proxy, so the bearer-header workarounds in SPEC-12 §4.1 stay correct but are no
  longer needed for auth. Same-origin `EventSource` would now work; keep `fetch` streaming, which already resumes
  with `Last-Event-ID`.
- Anyone who can reach the UI can use the API with that key. The dev server listens on localhost only. A future
  production server serves the UI on localhost or a private network only (§18).

### 4.2 Layout

Top to bottom, in the content column (max 1280px), centred:

1. **Mode switch.** HeroUI `Tabs` (secondary variant) with Scrape, Batch, Crawl, Map, Extract, grouped under small
   captions ("Pages": Scrape, Batch, Extract; "Sites": Map, Crawl). Each tab is a link to its route, so the
   mode is in the URL and back/forward work.
2. **Command bar.** One bordered surface (a HeroUI `Card`):
   - Row 1, Scrape/Crawl/Map/Extract: a URL `TextField` with an `https://` prefix.
   - Row 1, Batch: a `TextArea` for URLs, one per line, with a live "N URLs" count. It ends in an icon button that
     uploads a CSV: a `url` header column if present, else the first column (RFC 4180). Uploaded URLs are appended,
     and duplicates are dropped by exact string.
   - Row 2 (toolbar):
     - left: an Options toggle button (icon), which shows a dot when any setting differs from its default; Format
       (a `Select` with checkboxes, Scrape/Batch/Crawl only); Schema (`SchemaSelect`, or "None"; Scrape, Batch,
       Crawl and Extract only, as `MapRequest` has no `schema`);
     - right: Get code (PR 10), then the primary button: "Scrape", "Start batch", "Start crawl", "Map", "Extract".

   The primary button is at the top in every mode (owner).
3. **Options panel.** An inline region directly under the command bar, toggled by Options; it is not an overlay
   (owner: no pop-up windows). Rows of label, help icon and control (HeroUI `Switch`, `NumberField`, tag list, or
   `Select`), in two columns from the `md` breakpoint and one column at phone width. Then a collapsed "Advanced"
   `Disclosure` and a "Reset settings" button. Per mode:

   | Mode | Main rows | Advanced |
   |---|---|---|
   | Scrape | Page kind; Metadata in JSON; Fields (§4.10) | Fetch method; max age; timeout; LLM budget |
   | Batch | Page kind; Metadata in JSON; Fields; webhook URL | Fetch method |
   | Crawl | Include and Exclude globs (tag lists with Add); page-kind rules (rows of glob and page kind); Metadata in JSON; Fields | Max depth; page limit; fetch method; webhook URL |
   | Map | Include and Exclude globs; use sitemaps; use links | Page limit |
   | Extract | URLs or globs (tag list); schema source (stored, inline JSON, prompt, field names) | Page limit; fetch method; LLM budget; webhook URL |

   The rows mirror the request DTOs in `schema.d.ts`: apart from Metadata in JSON, a row exists only for a request
   member, and none is invented. Metadata in JSON is a view option. When it is on, the request's `formats` gains
   `metadata`, and the export asks for `include=metadata`.
4. **Output area.** It appears after the first run and keeps its footprint across states: a loading or error state
   fills the same box (CLAUDE.md, global UI rule).

### 4.3 Output

- **Single page (Scrape).** `Tabs`: JSON (default), Table (the record's fields via `FieldValue`/`RecordTable`, so
  status and confidence stay visible there, INV-22), one tab per requested page format, Usage. The JSON tab shows
  the page's clean JSON (§4.4) in a `JsonView`. When any published field is `calibrated=false`, one "uncalibrated"
  badge sits above the view (DESIGN.md, Showing extraction results).
- **`JsonView`.** A `<pre>` of the value pretty-printed with two-space indent. Keys, strings, numbers, booleans and
  null are coloured with theme tokens defined in `theme.css` (DESIGN.md, Theming). A Copy button and a Download
  (`.json`) button sit at its top right. Long output scrolls inside a fixed-height box.
- **Batch and Crawl.** No inline JSON (owner). A `PagedTable` over `results?format=json_values` (§4.4), one row per
  page, in task order:
  - Columns: URL (truncated, a link), Outcome (`OutcomeLabel`), records (count of `records`), JSON.
  - The JSON column's button opens a HeroUI `Drawer` from the right with that page's item in a `JsonView`.
  - While the job runs, the table refreshes as events arrive. The current page re-fetches on `task_extracted` and
    `task_failed`, at most once a second.
  - Above the table: `OutcomeCounts`, elapsed time, Cancel, and export buttons for JSON and CSV.
- **Map.** A `PagedTable` of links with row selection, and the "Scrape as batch" action (PR 8).
- **Extract.** As Batch.

### 4.4 Clean JSON (`json_values` results format)

- **Item.** One item per page (task) of a job:

  ```
  {"url": <task URL>, "outcome": <task outcome>, "records": [<clean record>, …], "metadata": {…}}
  ```

  - A **clean record** is an object of the schema's fields in name order (D-0816; JSONB keeps no declaration order):
    the published value, or `null` for a field that did not publish. Field status, confidence and evidence are never
    in it; they stay in the Table and the record inspector.
  - `records` is always an array, so every item has one shape: one entry for a detail page, one per row record for a
    listing page, and empty when the task has no record (failed, blocked, `links_only`, or a job without a schema).
  - `metadata` is present only with `include=metadata`: the page's metadata format from its capture.
- **Export.** `GET /v1/jobs/{id}/results?format=json_values[&include=metadata]` returns these items, oldest task
  first, paged with the task id as cursor. It works for jobs with and without a schema (today a schemaless job answers
  409 to every export).
  - `services/jobs.py` joins each task to the records its `task_record` links name (D-0813) and its capture's
    metadata.
  - The record exporter module turns records into clean records (SPEC-08 §4.11; C8: one module for record export
    shapes).
  - `json_records` and `csv_records` stay unchanged for existing callers.
- **Download.** The JSON download of a job is the items of every page, saved as one array. The drawer shows one item,
  so the download equals the drawers' items in order.
- **Single scrape.** A scrape keeps a job (`ScrapeResult.job_id`). The JSON tab shows the same item shape from the
  scrape response (`url`, `outcome`, each record's `data`, `metadata`), and Download saves it.
- The UI shapes nothing itself beyond picking members out of the server's response (§3).

### 4.5 Live activity

- `ActivityFeed` consumes the job's SSE stream (the existing `EventLog` consumer, with reconnect via
  `Last-Event-ID`). It groups events by task URL, newest group first, in a fixed-height scrolling box beside the
  results table from `lg` up and under it below `lg`.
- Each event kind maps to one sentence in one module, `activityText.ts`. Examples (exact text is settled in the PR):

  | Event | Line |
  |---|---|
  | `task_fetched` (method `http`) | Fetched over HTTP. |
  | `task_fetched` (method `browser`) | Fetched with a browser. |
  | `task_fetched` (`block_class` set) | Blocked: {block_class}. |
  | `task_extracted` | Extracted: {outcome} ({mode}). / Used {llm_calls} LLM call(s). |
  | `task_abstained` | Did not publish {fields}. |
  | `task_failed` | Failed after {attempts} attempts: {last_error}. |
  | `drift_suspended` | Paused this site's config: its output changed. |
  | `learning_started` / `learning_finished` | Learning this site's config… / Learned this site's config. |
  | `progress` | (updates the counts, no line) |
  | `completed` / `failed` / `cancelled` | Run finished. / Run failed. / Run cancelled. |

- An unknown event kind renders as its kind name, never dropped silently.
- Text comes from event data only, so no line claims something the event does not say.

### 4.6 Recent runs

Under the command bar, before any run on this page, the playground lists the last 10 jobs of its mode (`GET
/v1/jobs` filtered by kind): start URL or URL count, status (`JobStatusLabel`), started (`Timestamp`). A row opens that
run on the page (`?job=`). Scrape lists its runs like the other modes (a scrape keeps a job). The section keeps its
footprint while loading.

### 4.7 Get code

A Get code button in the toolbar opens a HeroUI `Drawer` from the right (a side panel, not a modal window). Top to
bottom:

1. **Prompts for coding agents.** Two rows, each with a title, a short name and Copy:
   - "Use it with coding agents": how to call this endpoint;
   - "Build on top of it": how to build an integration on this endpoint.

   The texts are static Markdown files in `frontend/src/screens/playground/prompts/`, one per mode, written from the
   endpoint's OpenAPI description. They hold no site literals (C3).
2. **API key.** The UI does not hold the key (§4.1), so this section says where the key comes from
   (`crawlerai apikey create`) and that snippets read it from `$CRAWLERAI_API_KEY`. It shows no key value.
3. **Endpoint.** The mode's title and one sentence from its OpenAPI summary.
4. **Code.** `Tabs`: cURL, Python, MCP, then a Copy code button. A code block with line numbers shows the current
   request built from the bar and options: the same body the primary action would send, with the base URL from
   `window.location.origin`. Python uses `httpx`. MCP shows the tool call with the same arguments. The text is
   generated from the request object, never by string concatenation of user input into code: values are JSON-encoded,
   and cURL single-quote escaping follows POSIX sh.

### 4.8 Navigation

- Sidebar groups:
  - Playground: Scrape, Batch, Crawl, Map, Extract.
  - Data: Jobs (history), Records, Schemas, Sites.
  - Labeling, when `eval_ui` is on.
  - Settings stays at the foot.
- `/` is Scrape. A job's kind maps to its mode's route:

  | Job kind | Route |
  |---|---|
  | `scrape` | `/` |
  | `batch_scrape` | `/batch` |
  | `crawl` | `/crawl` |
  | `map` | `/map` |
  | `extract` | `/extract` |

  `/jobs/:id` redirects to `<route>?job=<id>`, and a job row on Jobs links there. A `learn` job has no mode, so it
  keeps today's job page.
- Loading a playground URL with `?job=` shows that job's output, and its request in the bar and options, read-only.
  "Edit and re-run" makes them editable and starts a new job; the old one is kept.

### 4.9 What goes

- The `connect` screen, `auth.tsx`'s key state, the 401 redirect, and their tests.
- The Scrape screen layout, replaced by the playground.
- `JobDialog`, `CrawlDialog`, `BatchDialog`, `MapDialog` and `ExtractDialog`. Their field components (`JobFields`,
  `PageKindRules`) move into the options panel.
- The Overview (`home`) screen.

### 4.10 Additional fields (D-0810, ARCHITECTURE §5.4 rev 20)

Field names typed as chips become an extraction, by one path for every run type (owner, option (a)):

- **Request.** `schema: {"fields": [names]}` on `ScrapeRequest`, `BatchScrapeRequest`, `CrawlRequest` and
  `ExtractRequest`: 1–50 distinct schema field names (`[a-z][a-z0-9_]{0,63}`, SPEC-04 §4.2). The page kind is the
  request's `page_kind`, or for a crawl its rules' one page kind. The server drafts a schema with exactly those
  top-level fields with role S (SPEC-06 §4.5) before the job is stored, and the run extracts with it. A draft the
  LLM could not give is a 502 or 503 problem and stores nothing.
- **Review.** `POST /v1/schemas/draft` `{fields, page_kind}` returns the same draft (`SchemaDef`): the stored one when
  these names were drafted for that page kind before, else a new one, stored.
- **UI.** A Fields row in the options panel (Scrape, Batch, Crawl; Extract's schema source "From field names"): a
  tag list whose entries are checked against the name pattern as they are added; a refused entry stays in the field
  with the reason. Fields and a stored schema are not sent together. Fields ask for `records` like a schema does.
- The primary action with fields opens the draft in a right-side `Drawer` (as the JSON drawer) in the schema editor
  (`SchemaForm`), with Run and Cancel. Run as drafted sends the request with `schema.fields`, the body Get code
  shows. Run after an edit sends the edited document as `schema.inline`; it needs a name of its own, since the
  server keeps one document per name. Closing the drawer sends nothing. A failed draft shows its problem in the
  drawer.

## 5. Invariants

No new invariant. These still hold:
- INV-03: no hostnames in frontend source or tests.
- INV-22: "Every candidate carries a locator; every published field carries `evidence`, `confidence`, `calibrated`,
  `source_kind` and `locator`."

The records keep all of that; the Table and the inspector show it (SPEC-12 §4.2). The clean JSON is an export shape
that leaves `field_meta` out, as `json_records` does.

## 6. Testing strategy

- Vitest + Testing Library + MSW, as SPEC-12.
- Proxy: a test that the dev proxy config sets `Authorization` from `CRAWLERAI_UI_API_KEY` and leaves it unset when
  the variable is missing, and that the dev server binds 127.0.0.1.
- Playground:
  - each mode's request body equals the DTO built from its bar and options (literal expected bodies);
  - mode tabs are links;
  - the options dot shows exactly when a setting differs from its default;
  - CSV upload: header and no-header files, quoted fields (RFC 4180) and duplicates.
- Output:
  - the JSON tab is the default;
  - a clean record's member order and `null` for unpublished fields;
  - Metadata in JSON adds `metadata` to `formats` and `include=metadata` to the export;
  - the drawer shows a row's item;
  - the uncalibrated badge shows exactly when a published field has `calibrated=false`.
- Activity: every event kind in SPEC-10 §4.2 maps to a line (a table-driven test over the kinds); an unknown kind
  renders its name.
- Get code: for each mode, the cURL body parsed back as JSON equals the request the primary action sends; quoting
  survives values with quotes and newlines.
- Additional fields (PR 11):
  - backend, with a scripted role S provider: names drafted into a stored schema with exactly those fields; the same
    names in another order reuse it without a call; a draft with other fields is retried, then refused; every run
    type extracts with the draft of its names; a run whose names cannot be drafted stores no job;
  - vitest: a refused chip stays in the field with its reason; the draft shows before the run; Run as drafted posts
    `schema.fields`, the body Get code shows; an edited draft posts inline; a failed draft shows its problem and
    closing the drawer sends nothing.
- Backend (PR 9):
  - an exporter property test: every clean record has exactly the schema's fields, in name order, and no `_status_`
    key;
  - endpoint tests for `format=json_values`: one item per task in task order; `records` empty for failed, blocked and
    schemaless tasks; several records for a listing page; `metadata` only with `include=metadata`; a schemaless job
    answers 200; cursor paging.

## 7. Acceptance criteria

- Opening the app shows the Scrape playground with no key prompt; with no key configured it shows the setup notice.
- In every mode the primary action sits in the command bar, and settings open inline under it (no modal).
- A single scrape shows JSON first. A batch of 50 URLs shows a running table, a JSON drawer per row and plain-language
  activity, without leaving the page.
- A CSV of URLs fills the batch list.
- Selecting map results and choosing "Scrape as batch" opens Batch mode with those URLs.
- The JSON download of a job equals its drawers' items, in task order.
- Paging, tabs, options and the drawer move nothing around them (global UI rule).

## 8. PR plan

| # | Title | Scope | Checks | Done when | Layer |
|---|---|---|---|---|---|
| 1 | Server-side key; drop Connect | `vite.config.ts`, `.env.example`, `app/auth`, `app/router`, `screens/connect` | vitest | No key prompt; 401 shows the setup notice. | L1 |
| 2 | Playground shell + Scrape mode + options panel | `screens/playground`, `app/shell`, `app/router`, `theme.css`, `docs/DESIGN.md` (options panel) | vitest | `/` is the Scrape playground; options inline with Advanced; Overview removed. | L1 |
| 3 | Single-page output with JSON default | `components/JsonView`, `screens/playground/output`, `docs/DESIGN.md` (JSON view) | vitest | JSON tab default, Copy and Download; Table and format tabs. | L1 |
| 4 | Batch mode + running results table + JSON drawer + CSV upload + JSON/CSV export buttons | `screens/playground/batch`, `docs/DESIGN.md` (side drawer) | vitest | A batch runs on the page; the table fills from `json_values` as the run goes; the drawer shows the item; the download equals the drawers. Needs PRs 3 and 9. | L3 |
| 5 | Live activity feed | `components/ActivityFeed`, `activityText.ts`, `docs/DESIGN.md` (activity feed) | vitest | Every event kind has a line; grouped per URL. | L3 |
| 6 | Crawl and Map modes inline | `screens/playground/crawl`, `map` | vitest | Crawl and Map run from the playground; the dialogs are gone. | L3 |
| 7 | Extract mode; Jobs as history; `/jobs/:id` redirect; edit and re-run; recent runs | `screens/playground/extract`, `screens/jobs` | vitest | No create dialogs remain; a job opens in its mode; each mode lists its recent runs. | L3 |
| 8 | Batch from results | `screens/playground/map`, `crawl` | vitest | Selected URLs open Batch mode filled. | L3 |
| 9 | `json_values` results format (backend) | `services/jobs.py`, `config_ir/exporters/records.py`, `api/routers/jobs.py`, `make api-client` | pytest | One item per task for jobs with and without a schema; `include=metadata`; task-id cursor. | L3 |
| 10 | Get code drawer | `screens/playground/getCode`, `prompts/` | vitest | cURL, Python and MCP for the current request match the body the primary action sends; agent prompts copy. | L1 |
| 11 | Additional fields (chips) | `schema.fields` on scrape, batch, crawl and extract; `POST /v1/schemas/draft` (role S); `screens/playground/fields`, the Fields rows; `make api-client` | pytest, vitest | Field names run on every run type through a draft shown for editing first; Get code shows the `fields` body. | L3 |

PR 9 is backend only and can start now, beside PRs 1–3. PR 4 needs it.

## 9. Open issues

- D-0810 (confirmed 2026-10-16): option (a), a `fields` request member drafted by role S and shown for editing
  (§4.10).
- A production server for the UI does not exist; when one is added it must attach the key as §4.1 does and listen
  only on localhost or a private network (§18).
