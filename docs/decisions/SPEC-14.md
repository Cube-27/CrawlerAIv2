# SPEC-14 decisions

Decisions for [SPEC-14 — Playground workspace](../specs/SPEC-14-playground-workspace.md).
Template, statuses and rules: [DECISIONS.md](../DECISIONS.md).

### D-0809 — The UI becomes one playground; the server attaches the API key
- Date: 2026-10-15 · Spec/PR: SPEC-14 · Status: decided (owner)
- Context: The owner found the UI's flow spread over screens and dialogs, settings in one long vertical column with the action at the bottom, no batch on the main screen, JSON not the main output, and an API-key prompt on every load. The owner gave a reference playground's screenshots (mode tabs above a URL bar, inline options, a Get code drawer) and v1's feature set as the target UX.
- Decision: SPEC-14. One playground for Scrape, Batch, Crawl, Map and Extract at `/`; primary action at the top; inline options panel with Advanced (fetch, limits) collapsed; no pop-up windows for runs. Clean JSON (schema fields only, metadata only when asked) is the default output and a new `json_values` export. Batch and crawl show a running table with a JSON side drawer and plain-language activity; CSV upload is an icon in the batch box. Get code is the second-to-last PR; additional fields are last (D-0810). `json_values` (the name `json` is taken by the records shape) has one item per task, `{url, outcome, records, metadata?}`, with `records` always an array (empty for a failed or schemaless task, several for a listing page), so the table, the drawer and the download share one shape (review of #178). The dev proxy attaches `CRAWLERAI_UI_API_KEY`; the Connect screen goes (ARCHITECTURE §18 rev 17, Appendix A #38).
- Alternatives: keep SPEC-12's screens; a login with sessions; remember the key in the browser; JSON built in the browser.
- Why: The owner's answers, 2026-10-15.
- Reversible: yes

### D-0811 — The UI's `.env` is read once at config load, from the package's parent directory
- Date: 2026-10-15 · Spec/PR: SPEC-14 §4.1, PR 1 (#189) · Status: decided
- Context: §4.1 says the dev config reads the repo-root `.env` with `loadEnv(mode, <repo root>, "")`. The frontend has no Node types to locate the repo root from the config file, and `vite.config.ts` is an object config that Vite+ also reads for lint and format settings.
- Decision: `vite.config.ts` calls `loadEnv("development", "..", "")` once at module scope and builds one proxy entry for `/v1` and `/healthz` from `CRAWLERAI_UI_API_KEY`; an empty value counts as unset. A variable exported in the shell wins over `.env` (Vite's `loadEnv`).
- Alternatives: add `@types/node` and resolve the root from `import.meta.url`; a function-form `defineConfig` that passes the real mode.
- Why: pnpm runs scripts in the package directory, so `..` is the repo root for `pnpm dev` and Vitest; no new dependency, and the config stays static.
- Reversible: yes

### D-0812 — A 401 replaces the routed screen with the setup notice until reload
- Date: 2026-10-15 · Spec/PR: SPEC-14 §4.1, PR 1 (#189) · Status: decided
- Context: The browser holds no key; every call uses the one key the dev proxy attaches, so a 401 on one call means every call fails the same way.
- Decision: The API client's middleware sets one `rejected` flag on any 401; the route element then shows the §4.1 `EmptyView` in place of the screen, the sidebar kept, until the page is reloaded.
- Alternatives: each screen shows its own 401 problem; clear the flag on the next successful call.
- Why: Only editing `.env` and restarting `pnpm dev` changes the key; per-screen errors would hide that fix.

### D-0813 — `json_values` records come from a task's `task_record` links
- Date: 2026-10-15 · Spec/PR: SPEC-14 PR 9 (#190) · Status: decided
- Decision: A task's clean records are the records its `task_record` rows link (stored by it, or its entities' latest versions found unchanged), not only its last extraction's. Within a task they are ordered by record id: `task_record` keeps no row position.
- Alternatives: the records of the task's last extraction (SPEC-14 §4.4 wording).
- Why: an unchanged page in a recurring run stores no record (SPEC-11 §4.2, §4.4), so its last extraction has none; the link still shows its entity's latest record, as `format=json` lists it.
- Reversible: yes

### D-0814 — `include` only with `json_values`; `metadata` absent rather than null
- Date: 2026-10-15 · Spec/PR: SPEC-14 PR 9 (#190) · Status: decided
- Decision: `include=metadata` is accepted only with `format=json_values` (422 otherwise). `metadata` is a member only for an `extracted` or `partial` task whose capture is still kept; it is never null.
- Alternatives: ignore `include` for other formats; answer `metadata: null` when there is none.
- Why: an ignored parameter hides caller mistakes; an absent member follows the page-format members (`format_member`), present only when asked for and available.
- Reversible: yes

### D-0815 — The `json_values` page carries a `format` discriminator
- Date: 2026-10-15 · Spec/PR: SPEC-14 PR 9 (#190) · Status: decided
- Decision: `JsonValuesPage` has `format: "json_values"`, as `ExportPage` has its format.
- Alternatives: no discriminator; clients tell the union's pages apart by their members.
- Why: the results endpoint answers a union; the member lets clients narrow it without inspecting items.
- Reversible: yes

### D-0816 — A clean record's fields are in name order, as the export columns
- Date: 2026-10-15 · Spec/PR: SPEC-14 §4.4, PR 9 (#190) · Status: decided
- Decision: A clean record lists the schema's fields sorted by name, the column order of `json_records` and `csv_records`.
- Alternatives: declaration order (SPEC-14 §4.4 "schema order"); the registry's stored key order.
- Why: `schema_def.fields` is JSONB, which keeps no declaration order (it orders keys by length, then bytes), so "schema order" is not recoverable from the registry; name order is stable and matches the other exports.
- Reversible: yes; keeping declaration order needs it stored.

### D-0817 — The mode switch and the sidebar list a mode once its PR builds it
- Date: 2026-10-15 · Spec/PR: SPEC-14 §4.2, §4.8, PR 2 (#191) · Status: decided
- Context: §4.2 names five modes; after PR 2 only Scrape exists, and Batch, Crawl, Map and Extract still run from the Jobs dialogs until PRs 4, 6 and 7.
- Decision: `screens/playground/modes.ts` is the one list of modes the mode switch and the sidebar show; it holds the built modes (Scrape now).
- Alternatives: all five tabs, disabled or with placeholder routes.
- Why: No tab opens a page that does nothing.
- Reversible: yes

### D-0818 — Scrape's Schema is a stored schema or none; a schema asks for records with its page kind
- Date: 2026-10-15 · Spec/PR: SPEC-14 §4.2, PR 2 (#191) · Status: decided
- Context: §4.2 gives the toolbar a `SchemaSelect` or "None" and no schema-source row for Scrape; SPEC-07 §4.4 makes `records` need a schema and a matching `page_kind`, and refuses listing records.
- Decision: Format lists the page formats only. Picking a stored schema adds `records`, and the request's page kind is the schema's, the only one the server accepts for it; Page kind offers no other. A schema with no page kind, or one whose records the server refuses, keeps the request unsent and says why under Page kind. Inline and prompt schemas leave Scrape mode; Extract keeps a schema source (§4.2).
- Alternatives: keep Records in Format and the schema-source choice.
- Why: Follows the §4.2 toolbar and sends no request the server must refuse.
- Reversible: yes

### D-0819 — The URL bar's `https://` prefix applies to text typed without a scheme
- Date: 2026-10-15 · Spec/PR: SPEC-14 §4.2, PR 2 (#191) · Status: decided
- Context: §4.2 shows an `https://` prefix in the URL field.
- Decision: Text that does not start with a scheme and `://` (RFC 3986 §3) is sent with `https://`, so `host:port/path` gets it too; a URL with one is sent as typed.
- Alternatives: a decorative prefix only.
- Why: What the bar shows is what is sent.
- Reversible: yes

### D-0825 — Scrape output tabs: fetch attempts move into Usage
- Date: 2026-10-15 · Spec/PR: SPEC-14 §4.3, PR 3 (#194) · Status: decided
- Decision: The Scrape tabs are JSON, Table, one per page format, Usage; the former Fetch tab's method, status and attempts sit under Usage, and the Draft schema tab goes (Scrape sends no prompt, D-0818).
- Alternatives: keep a Fetch tab beside Usage.
- Why: §4.3 lists those tabs and no Fetch tab.
- Reversible: yes

### D-0826 — Metadata in JSON is a view option for the JSON
- Date: 2026-10-15 · Spec/PR: SPEC-14 §4.4, PRs 3–4 (#194) · Status: decided
- Decision: The Scrape JSON item carries `metadata` only with Metadata in JSON on, even when Metadata is a page format (that shows the Metadata tab); the run table asks `include=metadata` from the current switch, so turning it on reads the table again.
- Alternatives: include metadata whenever the response has it.
- Why: The JSON shows what the switch says.
- Reversible: yes

### D-0827 — Name order on the client, and the SPEC-14 clarifying edit
- Date: 2026-10-15 · Spec/PR: SPEC-14 §4.4, §6, PR 3 (#194; post-merge review of #190) · Status: decided
- Decision: A clean record built on the client orders field names by code unit, the server's `sorted` order (D-0816), since schema names are ASCII (`NAME_PATTERN`). SPEC-14 §4.4 and §6 now say name order (D-0816) and `task_record` links (D-0813); no architecture change.
- Alternatives: `localeCompare` order.
- Why: The Scrape JSON tab and the batch drawer show the same item the export does.
- Reversible: yes

### D-0828 — Dev proxy Fetch Metadata check
- Date: 2026-10-15 · Spec/PR: SPEC-14 PR 1 follow-up (#194; post-merge review of #189) · Status: decided
- Decision: The Vite dev proxy refuses requests whose `Sec-Fetch-Site` (W3C Fetch Metadata) is other than `same-origin` or `none` before the key is attached; requests without the header (curl, scripts) pass; `server.cors` is off.
- Alternatives: an Origin allowlist.
- Why: A page on another site can't spend the server-side key through a developer's browser.
- Reversible: yes

### D-0829 — A batch run lives in the URL
- Date: 2026-10-15 · Spec/PR: SPEC-14 §4.2, PR 4 (#194) · Status: decided
- Decision: The run shows at `/batch?job=<id>`; the form stays editable (read-only requests and "Edit and re-run" are row 7).
- Alternatives: run state in memory only.
- Why: A reload or a shared link reopens the run.
- Reversible: yes

### D-0830 — A results row is keyed by its place in the job
- Date: 2026-10-15 · Spec/PR: SPEC-14 §4.4, PR 4 (#194) · Status: decided
- Decision: `json_values` items carry no task id; a row is keyed by its place in the job (task order is fixed, oldest first), which also names the drawer and its download (`page-<n>.json`).
- Alternatives: add a task id to `json_values` (an API change).
- Why: Stable without changing the results format.
- Reversible: yes

### D-0831 — Results refresh at most once a second
- Date: 2026-10-15 · Spec/PR: SPEC-14 §4.4, PR 4 (#194) · Status: decided
- Decision: `task_extracted` and `task_failed` read the results again at once when the last read is a second old, else once when it is; the end event reads at once and drops a pending refresh.
- Alternatives: refresh on every event; poll.
- Why: A large batch emits many events a second; one read a second keeps the table current without a request per event.
- Reversible: yes

### D-0832 — Activity wording
- Date: 2026-10-15 · Spec/PR: SPEC-14 §4.5, PR 5 (#194) · Status: decided
- Decision: `task_fetched` with a block class other than `ok` adds "Block class: X." rather than "Blocked" (a `shell` page is not blocked); `learning_finished` says "Learned this site's config." with a `config_id`, else "Learning ended without a config: {reason}."; an unknown kind, or one missing the data its line needs, shows its kind name; elapsed time shows once, in the activity header.
- Alternatives: drop events the feed can't word.
- Why: Each line says only what the event's data says.
- Reversible: yes

### D-0833 — Cancel stays in place
- Date: 2026-10-15 · Spec/PR: SPEC-14 §4.4, PR 4 (#194) · Status: decided
- Decision: On the run, Cancel is disabled, not removed, once the job can't be cancelled; `cancelState` in `api/jobs.ts` decides it for both job views.
- Alternatives: hide Cancel when the run ends.
- Why: The status row does not move (owner rule: no layout shift).
- Reversible: yes

### D-0834 — Sidebar order follows the mode switch
- Date: 2026-10-15 · Spec/PR: SPEC-14 §4.2, §4.8, PR 4 (#194; post-merge review of #191) · Status: decided
- Decision: The sidebar lists modes in `MODE_GROUPS` order (Pages, then Sites), the one list D-0817 names.
- Alternatives: a separate sidebar list.
- Why: One list, so the two can't disagree.
- Reversible: yes
