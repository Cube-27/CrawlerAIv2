# SPEC-14 decisions

Decisions for [SPEC-14 — Playground workspace](SPEC-14-playground-workspace.md).
Template, statuses and rules: [decisions/README.md](../../../decisions/README.md).

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

### D-0855 — A job's stored request has its own endpoint; summaries carry its target
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.6, §4.8, PR 7 (#198) · Status: decided
- Decision: `GET /v1/jobs/{id}/request` returns the stored `job.request` as validated (defaults filled in); the UI reads it once (`staleTime: Infinity`). `JobSummary` gains `start_url` (the request's `url`) and `url_count` (the length of `urls`), both computed in SQL.
- Alternatives: the whole request inside `JobSummary`, which puts up to 1,000 URLs in every list item and re-sends them on every `progress` refetch.
- Why: §4.6 shows a run's URL or URL count, and §4.8 shows its request again. Both additions are additive.
- Reversible: costly (public members)

### D-0856 — A shown run is read-only until "Edit and re-run"
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.8, PR 7 (#198) · Status: decided
- Decision: `?job=` fills the bar and options from the job's stored request (D-0855); inputs are disabled through disabled fieldsets (HTML §4.10.15), and tag lists drop their remove action. Options and Advanced still open. "Edit and re-run" takes the primary button's place; sending starts a new job and the URL moves to it.
- Alternatives: per-control `isReadOnly`.
- Why: One mechanism for every mode.
- Reversible: yes

### D-0857 — Crawl with a schema asks for records alone
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.2, PR 6 (#198) · Status: decided
- Decision: With a stored schema, Crawl sends `formats: ["records"]`, disables Format, fixes every rule's page kind to the schema's and needs at least one rule; Metadata in JSON only adds `include=metadata` to the results request.
- Alternatives: let the server refuse the request.
- Why: `CrawlRequest` rejects records with other formats, records without rules, and rules of another page kind (SPEC-10 §4.5).
- Reversible: yes

### D-0858 — Extract's schema source
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.2, PR 7 (#198) · Status: decided
- Decision: An options row picks Stored (the toolbar's Schema), Inline JSON or From a prompt. The page kind is the stored schema's own, or chosen for inline and prompt schemas. The bar's URL comes first in `urls`, then the "More URLs or globs" tag list.
- Alternatives: a URL list in the bar.
- Why: §4.2 gives Extract a URL field in the bar and a tag list in its options.
- Reversible: yes

### D-0859 — Batch and crawl requests with an inline schema show "No schema"
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.2, PR 7 (#198) · Status: decided
- Decision: A batch or crawl job whose stored request names an inline schema (sent through the API) shows without a schema, since the toolbar holds stored schemas only; Extract shows inline schemas as JSON.
- Alternatives: an inline-JSON source in every mode.
- Why: §4.2 gives Batch and Crawl the stored-schema select only.
- Reversible: yes

### D-0860 — A past scrape opens as a run
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.6, PR 7 (#198) · Status: decided
- Decision: A scrape job opened from `?job=` shows the run view (results table and drawer over `json_values`), not the scrape response view, which needs the full `ScrapeResult`.
- Alternatives: store the response.
- Why: §4.6 says a row opens that run on the page; the JSON item shape is the same.
- Reversible: yes

### D-0861 — Selection passes to Batch in navigation state
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.2, PR 8 (#198) · Status: decided
- Decision: "Scrape as batch" navigates to `/batch` with the selected URLs in the history state, which Batch reads once as its initial list.
- Alternatives: URLs in the query string, which is length-bound for large maps.
- Why: Nothing persists, and back returns to the result.
- Reversible: yes

### D-0862 — Testing Library's async timeout is 5 s
- Date: 2026-10-16 · Spec/PR: SPEC-14 PR 6 (#198) · Status: decided
- Decision: `configure({ asyncUtilTimeout: 5000 })` in `frontend/src/test/setup.ts`.
- Alternatives: per-call timeouts.
- Why: A playground run is three requests deep (submit, job, results); on a busy runner that exceeds the 1 s default.
- Reversible: yes

### D-0890 — Get code's MCP tab shows a `tools/call` request
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.7, PR 10 (#201) · Status: decided
- Decision: The MCP tab shows the JSON-RPC `tools/call` request (MCP 2025-06-18) naming the mode's tool, with the request body as its `request` argument. Batch has no MCP tool (SPEC-10 §4.7), so its tab says so and Copy code is off.
- Alternatives: an MCP client config; hiding the tab for Batch.
- Why: §4.7 asks for the tool call with the same arguments, independent of the client; a fixed set of tabs moves nothing.
- Reversible: yes

### D-0891 — One prompts file per mode, two level-1 sections
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.7, PR 10 (#201) · Status: decided
- Decision: `frontend/src/screens/playground/prompts/<mode>.md` holds `# call-<mode>` and `# integrate-<mode>`; the heading is the prompt's short name, and its prefix picks the row title.
- Alternatives: two files per mode.
- Why: §4.7 says one file per mode.
- Reversible: yes

### D-0892 — The Python snippet calls `httpx.request("POST", …)` with a 300 s timeout
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.7, PR 10 (#201) · Status: decided
- Decision: `httpx.request("POST", url, headers=…, json=…, timeout=300.0)`.
- Alternatives: `httpx.post` with httpx's default timeout.
- Why: httpx's 5 s default is shorter than many scrapes; `httpx.post` in a string trips the C3 scan's dotted-word rule (`.post`).
- Reversible: yes

### D-0893 — Endpoint title and sentence copied from `openapi.json`, checked by a test
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.7, PR 10 (#201) · Status: decided
- Decision: `getCode/endpoints.ts` holds each mode's path, OpenAPI summary and the first sentence of its description; a test asserts they equal `openapi.json`.
- Alternatives: import `openapi.json` into the bundle.
- Why: Keeps the 250 KB document out of the app.
- Reversible: yes

### D-0894 — Get code shows what the builder would send
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.7, PR 10 (#201) · Status: decided
- Decision: Get code shows the request the mode's builder returns, the same value the primary action sends. When the builder returns null (no format, no schema or page kind), each tab shows "Complete the request above to see its code." in the same box and Copy code is off. An empty URL is not checked by the builders (the bar's required field blocks the send), so the snippet then shows `"url": ""`.
- Alternatives: disable the button; a URL check in every builder.
- Why: The snippet is exactly the body sent; the prompts and key help stay reachable; nothing moves.
- Reversible: yes

### D-0925 — At most 50 distinct field names per draft
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.10, PR 11 (#205) · Status: decided
- Decision: `schema.fields` takes 1 to 50 distinct schema field names (`MAX_FIELD_NAMES`), checked by the request model (`SchemaFields`), a 422 otherwise.
- Alternatives: no bound; the schema's own field limit.
- Why: It bounds the role S request, far above any page's fields.
- Reversible: yes

### D-0926 — One draft per set of names and page kind, charged to no job
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.10, SPEC-06 §4.5, PR 11 (#205) · Status: decided
- Decision: A field-name draft is named `draft_` + `sha256("fields\n" + page_kind + "\n" + sorted names joined by "\n")[:12]`; a normalized prompt holds no line feed, so no prompt draft shares the name. The call has `job_id` null: it runs before any job exists, and usage still records it.
- Alternatives: hash the names in the order given; charge the job created afterwards.
- Why: The same names in any order give one stable schema (ARCHITECTURE §5.4).
- Reversible: yes, with a re-draft

### D-0927 — Field names are drafted before the job, for every run type
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.10, PR 11 (#205) · Status: decided
- Decision: `named_schema` drafts `schema.fields` (through `fields_schema`) while the caller waits, before anything is stored, on scrape, batch, crawl and extract. An LLM failure is its problem (502, 503); a draft of another page kind or a retired one is a 422. `POST /v1/schemas/draft` uses the same helper.
- Alternatives: draft in the worker; fail the job.
- Why: The caller sees the problem at once, and no job exists without its schema.
- Reversible: yes

### D-0928 — What Run sends after the draft review
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.10, PR 11 (#205) · Status: decided
- Decision: An unchanged draft runs as `schema.fields`, so the request equals Get code and the server reads the stored draft. An edited draft runs as `schema.inline` under a name of its own; the UI refuses an edit that keeps the draft's name, since the server keeps one document per name (409).
- Alternatives: always send the draft inline; store the edit as a new version of the draft.
- Why: The request stays reproducible, and drafts get no edited versions.
- Reversible: yes

### D-0929 — A crawl's field names use its rules' one page kind
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.10, SPEC-10 §4.5, PR 11 (#205) · Status: decided
- Decision: `CrawlRequest` has no `page_kind`; its field names are drafted for the one page kind of its `page_kind_rules`, which the records validator already requires. The UI refuses fields with no rules or with rules of two kinds.
- Alternatives: add a `page_kind` member to crawl.
- Why: No new request member.
- Reversible: yes

### D-1041 — Playground settings in a popover, every setting at once
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.2, owner feedback after #214 (#218) · Status: decided (owner)
- Decision: Options opens a HeroUI `Popover` (modal, so Escape, a click outside or Options closes it) holding every setting in a grid of label-over-control cells, four columns from `sm`, one at phone width; no nested Advanced section. ARCHITECTURE Appendix A #45 replaces #38's inline panel.
- Alternatives: keep the inline panel without Advanced (it pushes the output down when opened).
- Why: Owner asked for all settings visible in a compact two-row grid; an overlay moves nothing on the page.
- Reversible: yes

### D-1042 — Closing the options blurs the focused control first
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.2 (#218) · Status: decided
- Decision: `OptionsPopover` blurs the focused element inside the popover before it closes, so a React Aria `NumberField`, which commits its text on blur, keeps the number typed last when Escape closes the popover.
- Alternatives: commit on every keystroke in `NumberRow` (bypasses the field's own parsing).
- Why: In a browser, a limit typed then Escape was lost.
- Reversible: yes

### D-1043 — A centred, narrower command bar whose input box has a fixed minimum height
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.2 (#218) · Status: decided
- Decision: The mode switch is centred; the command bar sits centred in `--container-playground` (48rem). Its input is in a box of at least `--height-playground-input` (5rem), which holds a URL and its error line or Batch's two-line list and count, and the toolbar is at least `h-10`, so the primary button is at the same place in every mode at desktop width. The output keeps the content's width.
- Alternatives: a taller box for a six-line batch list (leaves Scrape with empty space).
- Why: Owner's reference layout; switching modes must not move the card or the run button.
- Reversible: yes

### D-1044 — The LLM call limit is shown where the request takes a `budget`
- Date: 2026-10-16 · Spec/PR: SPEC-14 §4.2, D-1006 (#218) · Status: decided
- Decision: One `LlmCallsRow` ("LLM call limit", `budget.llm_calls`) in Scrape, Batch and Extract. Empty leaves `budget` out; its placeholder and help say what that means per request: "No limit" for a batch (D-1006), "10" (the server's default) for a scrape or an extract. Crawl and Map get none: their requests have no `budget`.
- Alternatives: add `budget` to `CrawlRequest` here (backend scope, left as a follow-up).
- Why: A row exists only for a request member (§4.2); the hint must state what the server does.
- Reversible: yes

### D-1045 — An input group's prefix reads as part of the field
- Date: 2026-10-16 · Spec/PR: DESIGN.md Components (#218) · Status: decided
- Decision: theme.css drops HeroUI's divider after an `InputGroup` prefix, and a text prefix has no end padding, so `https://` runs into the typed host; an icon prefix keeps its gap.
- Alternatives: drop the prefix and show `https://` as a placeholder.
- Why: The divider read as a stray "|" after `https://` (owner).
- Reversible: yes
