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
   - A `json_values` results format: one object per page with `url` and the schema's published fields only, plus
     `metadata` when the job asked for it.
   - The download and the on-screen JSON are this shape.
10. **Get code** (second to last; the owner shared the reference). A right-side drawer for the current request
    (§4.7).
11. **Additional fields** (last; discussed with the owner before it is built, D-0810). Field names typed as chips
    for an ad-hoc extraction.

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
- No open questions block PRs 1–10. PR 11 waits on D-0810.

## 4. Design

### 4.1 Access (§18 rev 17)

- `vite.config.ts`'s proxy for `/v1` and `/healthz` sets the `Authorization` header from `CRAWLERAI_UI_API_KEY`,
  read from the environment (`.env`, documented in `.env.example`). The key never reaches the browser bundle: the
  proxy adds it server-side.
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
   captions ("Extract": Scrape, Batch, Extract; "Discover": Map, Crawl). Each tab is a link to its route, so the
   mode is in the URL and back/forward work.
2. **Command bar.** One bordered surface (a HeroUI `Card`):
   - Row 1, Scrape/Crawl/Map/Extract: a URL `TextField` with an `https://` prefix.
   - Row 1, Batch: a `TextArea` for URLs, one per line, with a live "N URLs" count. It ends in an icon button that
     uploads a CSV: a `url` header column if present, else the first column (RFC 4180). Uploaded URLs are appended,
     and duplicates are dropped by exact string.
   - Row 2 (toolbar):
     - left: an Options toggle button (icon), which shows a dot when any setting differs from its default; Format
       (a `Select` with checkboxes, Scrape/Batch/Crawl only); Schema (`SchemaSelect`, or "None");
     - right: Get code (PR 10), then the primary button: "Scrape", "Start batch", "Start crawl", "Map", "Extract".

   The primary button is at the top in every mode (owner).
3. **Options panel.** An inline region directly under the command bar, toggled by Options; it is not an overlay
   (owner: no pop-up windows). Rows of label, help icon and control (HeroUI `Switch`, `NumberField`, tag list, or
   `Select`), in two columns from the `md` breakpoint and one column at phone width. Then a collapsed "Advanced"
   `Disclosure` and a "Reset settings" button. Per mode:

   | Mode | Main rows | Advanced |
   |---|---|---|
   | Scrape | Page kind; Metadata in JSON | Fetch method; max age; LLM budget |
   | Batch | Page kind; Metadata in JSON; webhook URL | Fetch method; LLM budget |
   | Crawl | Include and Exclude globs (tag lists with Add); page-kind rules (rows of glob and page kind); Metadata in JSON | Max depth; page limit; fetch method; webhook URL |
   | Map | Include and Exclude globs; Use sitemap | Page limit |
   | Extract | URLs or globs (tag list); schema source (stored, inline JSON, prompt) | Fetch method; webhook URL |

   The rows mirror the request DTOs in `schema.d.ts`. A row exists only for a request member, and none is invented.
4. **Output area.** It appears after the first run and keeps its footprint across states: a loading or error state
   fills the same box (CLAUDE.md, global UI rule).

### 4.3 Output

- **Single page (Scrape).** `Tabs`: JSON (default), Table (the record's fields via `FieldValue`/`RecordTable`, so
  status and confidence stay visible there, INV-22), one tab per requested page format, Usage. The JSON tab shows
  the page's clean JSON (§4.4) in a `JsonView`.
- **`JsonView`.** A `<pre>` of the value pretty-printed with two-space indent. Keys, strings, numbers, booleans and
  null are coloured with theme tokens defined in `theme.css` (DESIGN.md, Theming). A Copy button and a Download
  (`.json`) button sit at its top right. Long output scrolls inside a fixed-height box.
- **Batch and Crawl.** No inline JSON (owner). A `PagedTable` of pages, newest first:
  - Columns: URL (truncated, a link), Outcome (`OutcomeLabel`), fields found (`published/total`), confidence (lowest
    published, `ConfidenceCell`), JSON.
  - The JSON column's button opens a HeroUI `Drawer` from the right with that page's clean JSON in a `JsonView`.
  - While the job runs, the table refreshes as events arrive. The first page re-fetches on `task_extracted` and
    `task_failed`, at most once a second.
  - Above the table: `OutcomeCounts`, elapsed time, Cancel, and export buttons for JSON and CSV.
- **Map.** A `PagedTable` of links with row selection, and the "Scrape as batch" action (PR 8).
- **Extract.** As Batch.

### 4.4 Clean JSON (`json_values` results format)

- **On screen.** One page's JSON is `{"url": <page URL>, <field>: <value>, …}` with the schema's fields in schema
  order: a published value, or `null` for a field that did not publish. Field status, confidence and evidence are
  never in it (they stay in the Table and the record inspector). With "Metadata in JSON" on and the metadata format
  requested, the object gains `"metadata": {…}`, the page's metadata format as the API returned it. Without a
  schema, the object is `{"url", "metadata"?}` plus each requested text format under its format name.
- **Export.** `GET /v1/jobs/{id}/results?format=json_values` returns a JSON array of these objects, built by the record
  exporter module (SPEC-08 §4.11; C8: one module for record export shapes). `include=metadata` adds `metadata`.
  `json_records` and `csv_records` stay unchanged for existing callers.
- **Single scrape.** The UI saves the object it shows; there is no job to export.
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
  | `task_extracted` | Extracted {published} of {total} fields ({mode}). / Used {n} LLM call(s). |
  | `task_abstained` | Left out {fields}: not found on the page. |
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
run on the page (`?job=`). Scrape keeps no job, so its list is empty and the section is not shown. The section keeps
its footprint while loading.

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
- `/` is Scrape. `/jobs/:id` redirects to `/<mode>?job=<id>`. A job row on Jobs links there.
- Loading a playground URL with `?job=` shows that job's output, and its request in the bar and options, read-only.
  "Edit and re-run" makes them editable and starts a new job; the old one is kept.

### 4.9 What goes

- The `connect` screen, `auth.tsx`'s key state, the 401 redirect, and their tests.
- The Scrape screen layout, replaced by the playground.
- `JobDialog`, `CrawlDialog`, `BatchDialog`, `MapDialog` and `ExtractDialog`. Their field components (`JobFields`,
  `PageKindRules`) move into the options panel.
- The Overview (`home`) screen.

## 5. Invariants

No new invariant. INV-03 (no hostnames in frontend source or tests) and INV-22 (every rendered field shows its
status, evidence, confidence, calibrated and locator) still hold. INV-22 is met by the Table and inspector; the clean
JSON is an export shape, as `json_records` is.

## 6. Testing strategy

- Vitest + Testing Library + MSW, as SPEC-12.
- Proxy: a test that the dev proxy config sets `Authorization` from `CRAWLERAI_UI_API_KEY` and leaves it unset when
  the variable is missing.
- Playground:
  - each mode's request body equals the DTO built from its bar and options (literal expected bodies);
  - mode tabs are links;
  - the options dot shows exactly when a setting differs from its default;
  - CSV upload: header and no-header files, quoted fields (RFC 4180) and duplicates.
- Output:
  - the JSON tab is the default;
  - the clean-JSON member order and `null` for unpublished fields;
  - metadata is present only with the option on;
  - the drawer shows a row's JSON.
- Activity: every event kind in SPEC-10 §4.2 maps to a line (a table-driven test over the kinds); an unknown kind
  renders its name.
- Get code: for each mode, the cURL body parsed back as JSON equals the request the primary action sends; quoting
  survives values with quotes and newlines.
- Backend (PR 9): an exporter property test (every object has `url` plus exactly the schema's fields, in schema order;
  no `_status_` key) and an endpoint test for `format=json_values` with and without `include=metadata`.

## 7. Acceptance criteria

- Opening the app shows the Scrape playground with no key prompt; with no key configured it shows the setup notice.
- In every mode the primary action sits in the command bar, and settings open inline under it (no modal).
- A single scrape shows JSON first. A batch of 50 URLs shows a running table, a JSON drawer per row and plain-language
  activity, without leaving the page.
- A CSV of URLs fills the batch list.
- Selecting map results and choosing "Scrape as batch" opens Batch mode with those URLs.
- The JSON download of a job equals the objects its drawer shows.
- Paging, tabs, options and the drawer move nothing around them (global UI rule).

## 8. PR plan

| # | Title | Scope | Checks | Done when | Layer |
|---|---|---|---|---|---|
| 1 | Server-side key; drop Connect | `vite.config.ts`, `.env.example`, `app/auth`, `app/router`, `screens/connect` | vitest | No key prompt; 401 shows the setup notice. | L1 |
| 2 | Playground shell + Scrape mode + options panel | `screens/playground`, `app/shell`, `app/router`, `theme.css` | vitest | `/` is the Scrape playground; options inline with Advanced; Overview removed. | L1 |
| 3 | Single-page output with JSON default | `components/JsonView`, `screens/playground/output` | vitest | JSON tab default, Copy and Download; Table and format tabs. | L1 |
| 4 | Batch mode + running results table + JSON drawer + CSV upload | `screens/playground/batch` | vitest | A batch runs on the page; the table fills as the run goes; the drawer shows JSON. | L3 |
| 5 | Live activity feed | `components/ActivityFeed`, `activityText.ts` | vitest | Every event kind has a line; grouped per URL. | L3 |
| 6 | Crawl and Map modes inline | `screens/playground/crawl`, `map` | vitest | Crawl and Map run from the playground; the dialogs are gone. | L3 |
| 7 | Extract mode; Jobs as history; `/jobs/:id` redirect; edit and re-run; recent runs | `screens/playground/extract`, `screens/jobs` | vitest | No create dialogs remain; a job opens in its mode; each mode lists its recent runs. | L3 |
| 8 | Batch from results | `screens/playground/map`, `crawl` | vitest | Selected URLs open Batch mode filled. | L3 |
| 9 | `json_values` results format + clean-JSON export (with backend) | `config_ir/exporters/records.py`, `api/routers/jobs.py`, `frontend` export buttons, `make api-client` | pytest, vitest | Download equals the drawer's objects; `include=metadata`. | L3 |
| 10 | Get code drawer | `screens/playground/getCode`, `prompts/` | vitest | cURL, Python and MCP for the current request match the body the primary action sends; agent prompts copy. | L1 |
| 11 | Additional fields (chips) | to be specified | — | Blocked on D-0810: the owner discusses it first. | — |

PR 9 can run in parallel with PRs 3–8. The UI uses `json_records` until PR 9 lands, then switches.

## 9. Open issues

- D-0810 (needs-owner): how typed field names become an extraction (a `fields` request member, a prompt, or a pick
  from stored schemas). Blocks PR 11 only.
- A production server for the UI does not exist; when one is added it must attach the key as §4.1 does and listen
  only on localhost or a private network (§18).
