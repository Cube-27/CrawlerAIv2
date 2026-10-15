# SPEC-12 decisions

Decisions for [SPEC-12 — Frontend application screens](../specs/SPEC-12-frontend-application.md).
Template, statuses and rules: [DECISIONS.md](../DECISIONS.md).

### D-0342 — Connect accepts the key without a probe request
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 1 (#68) · Status: decided
- Decision: The Connect screen stores the key as entered; the first 401 drops it and shows the problem on `/connect`.
- Alternatives: probe `GET /v1/schemas` (not in `openapi.json` yet, so untyped); a key-check endpoint (public API change, escalation).
- Why: The most conservative reading.
- Reversible: yes

### D-0343 — `ProblemSummary` is narrowed by hand until the generated schema has the problem type
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 1 (#68) · Status: decided
- Decision: `api/problem.ts` reads `title` and `detail` from an `application/problem+json` body; replaced by the generated type once SPEC-07's problem schema is in `schema.d.ts`.
- Alternatives: wait for SPEC-07 PR 1.
- Why: SPEC-12 §4.1's "no hand-written DTO" targets endpoint shapes; this reads two RFC 9457 members.
- Reversible: yes

### D-0344 — Labeling routes stay outside `RequireKey`
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 1 (#68) · Status: decided
- Decision: Only screens that call the API with the key sit behind the key gate; the labeling routes do not.
- Alternatives: gate them (their loaders take no key and would still run).
- Why: The eval API is unauthenticated (SPEC-03 §4.10); SPEC-12 PR 9 owns the labeling integration.
- Reversible: yes

### D-0345 — First shared compositions: `PageHeader` and `ProblemAlert`
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 1 (#68) · Status: decided
- Decision: `src/components/PageHeader` (h1 and badges left, primary actions right) and `ProblemAlert` (HeroUI `Alert`) are the one way to show a page title and an API problem; the existing screens' titles use `PageHeader`.
- Alternatives: per-screen headings and error markup.
- Why: Owner rule D-0341 and "one way per recurring job".
- Reversible: yes

### D-0367 — The field shape is narrowed by hand until the generated schema has records
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 2 (#73) · Status: decided
- Decision: `src/api/field.ts` declares `FieldStatus`, `FieldResult` (`status`, `reason`, `value`) and `FieldTypeSpec`; replaced by the generated types once SPEC-07's record and schema DTOs are in `schema.d.ts`.
- Alternatives: Wait for SPEC-07 records.
- Why: Same reasoning as D-0343; it reads only the documented SPEC-07 §4.4 members.
- Reversible: yes

### D-0368 — A published value that formats to nothing renders as "—"
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 2 (#73) · Status: decided
- Decision: An empty string or empty list shows "—" (named "No value"), and `remote_flag=true` shows as the text `remote` in a location.
- Alternatives: Render an empty span.
- Why: DESIGN.md forbids rendering an empty string; the flag is a server value shown as text, not inferred.
- Reversible: yes

### D-0369 — Field status tones
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 2 (#73) · Status: decided
- Decision: published → success, missing → neutral, abstained → warning, conflict → danger, in `FieldStatusBadge` next to the status type.
- Alternatives: Other mappings.
- Why: DESIGN.md "Status display": each domain maps its values to one tone, once.
- Reversible: yes

### D-0407 — `POST /v1/scrape` is declared by hand until SPEC-07 generates it
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 3 (#82) · Status: decided
- Decision: `src/api/scrape.ts` declares the SPEC-07 §4.3–4.4 request and response and adds the route to the generated `paths` by module augmentation, so the call uses the authenticated client and its 401 handling; deleted once `make api-client` generates it.
- Alternatives: Wait for SPEC-07 PRs 4–6; raw `fetch` outside the client (loses the 401 middleware).
- Why: Row-level readiness (D-0378); same reasoning as D-0343 and D-0367.
- Reversible: yes

### D-0408 — Empty scrape limits are left to the server
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 3 (#82) · Status: decided
- Decision: Empty `max_age`, `timeout_s` and `budget.llm_calls` are left out of the request; `fetch.method_hint` starts at `auto` (FetchPolicy's default).
- Alternatives: Prefill SPEC-07's example values.
- Why: The UI does not choose server defaults (§3).
- Reversible: yes

### D-0409 — Record field types come from the schema, else the value is shown as sent
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 3 (#82) · Status: decided
- Decision: Field types come from the response's draft schema, the inline schema sent, or `GET /v1/schemas/{schema_id}`; when none is readable, `FieldValue` gets `spec: null` and shows a string as is and anything else as JSON.
- Alternatives: Infer the type from the value (a client heuristic, §3).
- Why: Most conservative; review of #82 found the earlier text fallback hid published lists.
- Reversible: yes

### D-0410 — Scrape picks a schema by id; "Edit as schema" is SPEC-12 PR 4
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 3 (#82) · Status: decided
- Decision: The Scrape form takes a stored schema's id as text; a drafted schema is shown with its fields, and adopting or editing it is left to the Schemas screen.
- Alternatives: A schema list in the form; an "Edit as schema" link to a screen that does not exist yet.
- Why: SPEC-12 PR 4 owns schema editing and draft adoption.
- Reversible: yes

### D-0411 — Outcome tones
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 3 (#82) · Status: decided
- Decision: extracted → success, partial and shell → warning, not_found → neutral, blocked and failed → danger, in `components/OutcomeLabel` next to the outcome type.
- Alternatives: Other mappings.
- Why: DESIGN.md "Status display": each domain maps its values to one tone, once.
- Reversible: yes

### D-0432 — Drafts show no prompt hash until the API returns one
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 4 (#87) · Status: decided
- Decision: Draft schemas show origin `prompt_draft` but no prompt hash: `SchemaDef` has no such member until SPEC-06 PR 6 (role S, prompt-hash reuse) adds it.
- Alternatives: Hash the prompt client-side; declare the member by hand.
- Why: The UI shows only server values (§3); no hand-written DTOs (SPEC-12 §4.1).
- Reversible: yes

### D-0433 — Schema routes for create, adopt and edit
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 4 (#87) · Status: decided
- Decision: Routes `/schemas/new` (adoption is `/schemas/new?from=<id>`, a create prefilled from that schema) and `/schemas/:id/edit`, beside `/schemas` and `/schemas/:id`.
- Alternatives: Modal editors on the detail page.
- Why: DESIGN.md "few modals"; one form for create, adopt and edit.
- Reversible: yes

### D-0434 — The query cache belongs to one API key
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 4 (#87) · Status: decided
- Decision: `ApiQueryProvider` starts a new TanStack `QueryClient` when the key changes or is dropped; queries and mutations do not retry; a create, save or retire invalidates every `schemas` query.
- Alternatives: The key in every query key.
- Why: Nothing read with one key is shown under another (§18), with no key material in cache keys.
- Reversible: yes

### D-0435 — The schema form checks only what a request needs
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 4 (#87) · Status: decided
- Decision: The form checks the JSON shape, a chosen page kind and unique field names; every schema rule is the server's 422, shown next to the input it names. Changing a field's type drops the old type's `vocab`, `scheme`, `item` or `fields`; empty optional texts send null.
- Alternatives: Client-side schema validation.
- Why: The UI holds no logic (§3).
- Reversible: yes

### D-0436 — Schema actions follow the server's rules
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 4 (#87) · Status: decided
- Decision: Edit is offered only on the latest active non-preset version and retire on any active non-preset version (SPEC-07 §4.6); refusals still render as problems. Status tones: active → success, retired → neutral (`SchemaStatusLabel`).
- Alternatives: Always show the buttons.
- Why: Fewer dead ends; DESIGN.md "Status display".
- Reversible: yes

### D-0451 — The labeling nav entry reads `/healthz` once per query cache
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 9 (#93) · Status: decided
- Decision: The shell reads `/healthz` with the same-origin client and no key, once per query cache (`staleTime: Infinity`); an unknown or failed answer hides the Labeling entry. `/labeling` itself still says when the labeling API is off.
- Alternatives: Poll the flag; show the entry by default.
- Why: The flag is fixed for the backend's lifetime; hiding is the conservative reading of "shown only when" (SPEC-12 §4.3). The cache is per key, so a key change reads it again (review Consider item, left for a follow-up).
- Reversible: yes

### D-0452 — The current nav entry is marked with `aria-current` and styled in theme.css
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 9 (#93) · Status: decided
- Decision: The main nav's entry for the page shown carries WAI-ARIA `aria-current="page"`; one rule in `src/app/theme.css` (`.link[aria-current="page"]`) underlines it, HeroUI's own hover treatment.
- Alternatives: A per-component className (a visual value outside theme.css); HeroUI Tabs as nav (wrong role).
- Why: Owner rule: a visual change is an edit to theme.css only (DESIGN.md, Theming); the underline marks the state without relying on color.
- Reversible: yes

### D-0453 — Test stubs answer the shell's `/healthz` by default
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 9 (#93) · Status: decided
- Decision: `stubApi` (and the test setup through it) answers `GET /healthz` with `healthReply()` (`eval_ui: false`), unrecorded unless a test names it.
- Alternatives: A `/healthz` reply in every screen test.
- Why: Every screen now sends it; screen tests assert only their own calls.
- Reversible: yes

### D-0469 — Records and replay shapes are declared by hand until SPEC-07 PR 8
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 5 (#97) · Status: decided
- Decision: `frontend/src/api/records.ts` declares SPEC-07 §4.6's records list and replay and adds them to the generated `paths` by module augmentation: a listed record is the §4.4 record plus `capture_id`, `schema_id` and `version`; a page is `{items, next_cursor}` (`next_cursor` null on the last page); a replay answers `{records: [...]}` and is sent an empty body. Deleted once SPEC-07 PR 8 is in `openapi.json`; that PR matches these shapes or updates the module.
- Alternatives: Wait for SPEC-07 PR 8; raw `fetch` outside the client.
- Why: Row-level readiness (D-0378), as D-0407; the fewest members the screen needs, and the page envelope follows `SchemaList.items`.
- Reversible: yes

### D-0470 — Records are listed by schema, with filters in the URL
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 5 (#97) · Status: decided
- Decision: The Records screen requires a schema version; job and site narrow the list. The filters live in the URL query (`/records?schema_id=…&job_id=…&site=…`).
- Alternatives: Columns from the union of the fields on a page; filters in `localStorage`.
- Why: SPEC-12 §4.3 asks for one column per schema field, which needs one schema; URL filters can be reloaded and shared and need no storage.
- Reversible: yes

### D-0471 — The record inspector is a bottom drawer
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 5 (#97) · Status: decided
- Decision: The inspector is a HeroUI `Drawer` placed at the bottom, opened by row action (click or Enter), with no route of its own.
- Alternatives: A right drawer (too narrow for the eight-column field table); a `/records/:id` route (no single-record endpoint in SPEC-07).
- Why: SPEC-12 §4.3 "row click opens the inspector"; few modals (DESIGN.md).
- Reversible: yes

### D-0472 — The replay diff compares status and value, for one replayed record
- Date: 2026-10-13 · Spec/PR: SPEC-12 PR 5 (#97) · Status: decided
- Decision: The replay diff compares each field's `status` and `value` (JSON equality, member order ignored per RFC 8259 §4); confidence and locator are shown, not compared. It diffs only when the replay made exactly one record; with several it lists them without a diff. Tones: changed → warning, same → neutral.
- Alternatives: Match records by position; compare every attribute.
- Why: A replayed record has no id of the stored one, and the UI holds no matching logic (§3); the same value can be published from another source.
- Reversible: yes

### D-0657 — "Learn now" sends `force: false`; "Learn anyway" re-sends with `force: true` after a refusal
- Date: 2026-10-14 · Spec/PR: SPEC-12 PR 6 (#134) · Status: decided
- Decision: The config screen's "Learn now" posts `{schema_id, force: false}`; after a failure the problem is shown and a "Learn anyway" button posts `force: true`.
- Alternatives: A force switch beside the button; always force; show "Learn anyway" only on a 409 (needs the HTTP status on the shared `Problem` type).
- Why: The server's 409 says why it refused (an active config, or a run in flight); the operator forces only after reading it.
- Reversible: yes

### D-0658 — A correction sends only changed fields, `null` for a field whose steps were all removed, and CSS steps without `xpath`
- Date: 2026-10-14 · Spec/PR: SPEC-12 PR 6 (#134) · Status: decided
- Decision: `PUT /v1/configs/{id}` carries the steps of each field whose steps changed, `null` for a configured field left with no steps, and the confirmed fields. A CSS step is sent as `{css, post}`; a normalize post op as `{"<field type>": {}}`. Two casts in `frontend/src/components/steps.ts` cover generated input types that differ from what the server accepts (`CssStep-Input.xpath` required; `NormalizeOp-Input` as `{type}`, which `_post_op_kind` refuses).
- Alternatives: Send every field; a separate remove control.
- Why: Unchanged fields stay as stored (D-0593 activates only on operated fields); `CssStep`'s validator derives `xpath` from `css`; the post-op discriminator reads the op's one key.
- Reversible: yes

### D-0659 — The correction form lists every top-level schema field
- Date: 2026-10-14 · Spec/PR: SPEC-12 PR 6 (#134) · Status: decided
- Decision: The form shows each field of the config's schema version, configured or not, with the configured ones' steps prefilled.
- Alternatives: Only the fields the config has.
- Why: A correction may give steps to a field the config lacks (`config_ir.corrections` accepts any schema field).
- Reversible: yes

### D-0660 — A config export is saved from a Blob as `<site>-v<version>-<format>.json`, with its release report shown
- Date: 2026-10-14 · Spec/PR: SPEC-12 PR 6 (#134) · Status: decided
- Decision: `POST /v1/configs/{id}/export`'s `export` member is saved as a JSON file through a Blob; the release report is shown under the form, `manual` fields marked.
- Alternatives: Open a link to the endpoint.
- Why: SPEC-12 §4.1: every request carries the bearer header, so exports are fetched with it and saved as files.
- Reversible: yes

### D-0687 — Records' "Changed since" is entered and shown in UTC
- Date: 2026-10-14 · Spec/PR: SPEC-12 PR 8 (#141) · Status: decided
- Decision: The changed-since filter is a HeroUI `DateField` at minute granularity in the UTC zone, shown with its zone, and sent as `toAbsoluteString()` (ISO 8601, `Z`).
- Alternatives: The viewer's local zone (the instant sent would depend on the browser's zone, and tests on the machine's zone). A free-text ISO field (no validation from React Aria).
- Why: The most conservative reading. The instant on screen is exactly the one sent, whoever opens the shared URL. SPEC-12 §4.1 keeps the filters in the URL.
- Reversible: yes. Change the zone constant in `RecordFilters.tsx`.

### D-0688 — `@internationalized/date` as a direct frontend runtime dependency
- Date: 2026-10-14 · Spec/PR: SPEC-12 PR 8 (#141) · Status: decided
- Decision: Pin `@internationalized/date` 3.12.4 and allow it in `tools/theme_only_check.py`. It is not UI; it is the value type HeroUI's `DateField` takes.
- Alternatives: A native `datetime-local` input via HeroUI `Input` (local zone only, uneven browser support).
- Why: DESIGN.md: a new runtime dependency is added to the theme-only list in the PR that adds it. It is Apache-2.0 and already resolved as HeroUI's peer.
- Reversible: yes

### D-0700 — The `/jobs` screen opens a job by id; a jobs table needs a `GET /v1/jobs` endpoint
- Date: 2026-10-14 · Spec/PR: SPEC-12 PR 7 (#143) · Status: decided (owner, 2026-10-14): add GET /v1/jobs; built in SPEC-10 PR 9 (#146) and SPEC-12 PR 10
- Decision: `/jobs` has the create dialogs and an "Open job" form by id; a new job opens on its own page. SPEC-12 §4.3's jobs table (kind, status, counts, created) is not built: ARCHITECTURE §13.1 has no endpoint that lists jobs.
- Alternatives: (a) add `GET /v1/jobs` to §13.1 and SPEC-10 (a public API change); (b) amend SPEC-12 §4.3 to the id lookup.
- Why: Adding an endpoint changes the public API, which is the owner's call (CLAUDE.md §4). Same shape as D-0656 for sites. Recommendation: (a) when operators need the list; (b) until then. Blocks nothing.
- Reversible: yes

### D-0701 — A job export is saved as one file per server page
- Date: 2026-10-14 · Spec/PR: SPEC-12 PR 7 (#143) · Status: decided
- Decision: An export reads `GET /v1/jobs/{id}/results?format=…&limit=200` page by page and saves each page's `content` as its own file, `job-<id>.<ext>` or `job-<id>-<n>.<ext>` when there are several.
- Alternatives: Join the pages in the browser; export only the page shown.
- Why: Each page is a whole document (its own CSV header or JSON array); joining them is format logic the UI does not hold (§3). 200 is the largest page the API allows.
- Reversible: yes

### D-0702 — The event log lists stored events; `progress` re-reads the job, the end event re-reads job and results
- Date: 2026-10-14 · Spec/PR: SPEC-12 PR 7 (#143) · Status: decided
- Decision: `EventLog` lists each stored event (kind, id, data as sent). A `progress` event invalidates the job summary query; the end event (`completed`, `failed`, `cancelled`) invalidates the summary and the results. Reconnect waits 1 s doubling to 30 s, back to 1 s after a connection that delivered an event; a 4xx other than 429 stops the stream and shows its problem.
- Alternatives: Patch the cached summary from `progress` data (a hand-checked shape); poll the job.
- Why: The counts shown stay the server's typed answer; RFC 9110 §15.5: a 4xx won't succeed if repeated.
- Reversible: yes

### D-0703 — Job create flows are HeroUI Modals; map shows its URLs in its dialog
- Date: 2026-10-14 · Spec/PR: SPEC-12 PR 7 (#143) · Status: decided
- Decision: Batch, crawl, extract and map open as Modal dialogs from the page header (SPEC-12 §4.3 "create dialogs"). Map makes no job, so its URLs show in the dialog, one per line in a read-only text area, with the source counts and a `truncated` warning.
- Alternatives: Separate create routes.
- Why: The spec names dialogs; the text area lets a viewer copy URLs into a batch.
- Reversible: yes

### D-0704 — The job results table follows the results page's shape
- Date: 2026-10-14 · Spec/PR: SPEC-12 PR 7 (#143) · Status: decided
- Decision: A `format=json` results page whose items have `fields` is a records page (RecordTable in the columns of the first record's schema, rows open the record inspector); otherwise the page outputs table (URL, task status, outcome, fetched at). An empty page is shown as "No records yet".
- Alternatives: Read the job's schema first (the job summary has no `schema_id`).
- Why: The endpoint's union answer is the only signal the UI has.
- Reversible: yes

### D-0710 — The jobs table's Tasks column is one line: the total, then each status some task has
- Date: 2026-10-14 · Spec/PR: SPEC-12 PR 10 (#147) · Status: decided
- Decision: The `/jobs` table's Tasks column reads "N tasks: a queued, b done, …", the total and then each `url_task.status` some task has, in SPEC-01 §4.2 order; the per-outcome counts stay on the job page.
- Alternatives: One column per task status; done/total only.
- Why: Five count columns crowd the table at phone width, and done/total hides failures.
- Reversible: yes
