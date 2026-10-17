# Design

## Decisions

### D-1390 One uncalibrated badge per record
- Date: 2026-10-17 · Change/PR: playground-ux (#257) · Status: decided (owner-delegated 2026-10-17)
- Decision: a record shows one `uncalibrated` badge (in its summary line, and once above a page's JSON) when a published field is uncalibrated; fields show their confidence as a number only. A field that did not publish has no value to qualify, so it does not raise the badge. `DESIGN.md` "Showing extraction results" and the frontend requirement say so. `openspec/design/` has no text on the badge, so no owner-decisions row is added.
- Alternatives: keep the badge on every field (173 badges on one live listing page); one badge per page.
- Why: backlog follow-up (#214): until the first dev fit every field is uncalibrated, so the per-field badge was noise.
- Reversible: yes — `components/UncalibratedBadge.tsx`.

### D-1391 A rejected config is `suspended`
- Date: 2026-10-17 · Change/PR: playground-ux (#257) · Status: decided (owner-delegated 2026-10-17)
- Decision: `POST /v1/configs/{id}/reject` (and the `reject_config` MCP tool, the eleventh) sets a config that is the latest version and `pending_approval` to `suspended`; any other config is 409, as approve answers. The state keeps its mode and its serving config; a cold state's `retry_at_pages` becomes `pages_extracted + 8`, as after a failed run, so the refused document is not learned again at once. `ConfigConflict` is a `Refusal`, so an MCP tool answers it with its message.
- Alternatives: a new `rejected` status (a CHECK change in the baseline migration, which another batch owns in this wave, for a status that behaves as `suspended`); deleting the row (loses what was refused).
- Why: backlog follow-up (#252): a waiting config could only be replaced by a forced run or a correction (D-1342).
- Reversible: yes — `config_ir/activation.py`, `services/configs.py`.

### D-1392 A job page's fetch attempts are read with `include=fetch`
- Date: 2026-10-17 · Change/PR: playground-ux (#257) · Status: decided (owner-delegated 2026-10-17)
- Decision: a page output (a job without a schema) carries `fetch`, the summary a scrape answers with, built from its capture row (`fetch_policy.attempts`, method, status, block class); a `json_values` item carries it only with `include=fetch`, and `include` repeats (`metadata`, `fetch`). A task with no capture, or a capture that kept no attempts, has none. The drawer reads `fetch` only while it is open.
- Alternatives: `fetch` on every `json_values` item (the JSON export saves whole items, so its files would change); a per-capture endpoint (a second read per drawer, and `json_values` items carry no capture id).
- Why: users could not see why a page was `blocked` or `shell` (item 5 of the batch).
- Reversible: yes — `services/jobs.py`, `components/FetchAttempts.tsx`.

### D-1393 The fetch names its adapter
- Date: 2026-10-17 · Change/PR: playground-ux (#257) · Status: decided (owner-delegated 2026-10-17)
- Decision: `FetchSummary.adapter` is the name of the active adapter that reads the page's `api` capture (`Registry.reader`, the lookup the collectors use), null for an HTTP or browser capture, an API recipe's, or when no registry is given. It is computed when the summary is made, not stored on the capture.
- Alternatives: record the adapter in the capture manifest when it serves (a change to the rungs and the manifest, which another batch edits in this wave).
- Why: a page served by a platform adapter read like any `api` capture.
- Reversible: yes — `services/scrape_steps.py`.

### D-1394 Settings has the draft call limit
- Date: 2026-10-17 · Change/PR: playground-ux (#257) · Status: decided (owner-delegated 2026-10-17)
- Decision: Settings shows "Draft call limit per key" beside the LLM call limit, a whole number, empty for no limit, saved with the other two settings in one PATCH; the approval switch was already there. The cap still counts a key's calls in all, with no window (the backlog line keeps that).
- Alternatives: a window with the field (a model and API change with no use case yet).
- Why: backlog follow-up (D-1282): the screen sent the loaded value back, so only the API set the cap.
- Reversible: yes — `screens/settings/LimitsSection.tsx`.

### D-1395 Max rows in Options
- Date: 2026-10-17 · Change/PR: playground-ux (#257) · Status: decided (owner-delegated 2026-10-17)
- Decision: Scrape, Batch, Crawl and Extract Options have "Max rows", sent as `fetch.max_rows` when filled (`FetchOptions` takes it in all four) and shown again from a stored request. It is a soft target for a list a platform adapter reads in pages; Scrape's "Records" stays `browser_actions.records`. Map has no fetch options.
- Alternatives: Scrape only (the other modes' APIs accept it too).
- Why: backlog follow-up (#248): `fetch.max_rows` was not in the playground.
- Reversible: yes — `screens/playground/rows.tsx` and each mode's form.

### D-1396 Evidence buckets and source kinds read in words
- Date: 2026-10-17 · Change/PR: playground-ux (#257) · Status: decided (owner-delegated 2026-10-17)
- Decision: field tables show each evidence bucket and source kind as words ("Page network call", "Network call", "Platform API"), the server's code as the cell's hover text; the two word lists are typed by the generated unions, so a code the API adds fails the type check. The Source column is as wide as Evidence.
- Alternatives: raw codes (a field read from a captured call showed `network` and `xhr`, which read as nothing).
- Why: the `network` evidence bucket is new (D-1316) and users read it in this table.
- Reversible: yes — `components/FieldOrigin.tsx`.

### D-1397 Toolbar error lines hang, and wrap at phone width
- Date: 2026-10-17 · Change/PR: playground-ux (#257) · Status: decided (owner-delegated 2026-10-17)
- Decision: Format's error line hangs under it as Schema's does (D-1214); both use one class set, `HANGING_ERROR`: one line from `sm`, a `w-64` column at phone width, where a long message passed the screen's edge and made the page scroll sideways (measured at 375 px).
- Alternatives: a shorter message (the text names every way to satisfy the rule); reserving a line in the toolbar (moves the layout whenever no error shows).
- Why: backlog follow-up (D-1214, #238).
- Reversible: yes — `components/OptionSelect.tsx`.
