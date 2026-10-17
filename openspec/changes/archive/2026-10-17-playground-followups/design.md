# Design

## Decisions

### D-1214 — Extract's toolbar Schema holds the schema's source
- Date: 2026-10-17 · Change/PR: playground-followups (#238) · Status: decided
- Decision: one toolbar select lists Inline JSON, From a prompt and From field names, then each stored schema; the Options panel keeps only the chosen source's JSON, prompt or names. A missing schema ("Choose a schema.") shows under the toolbar select and Options stays closed; an empty JSON, prompt or names list still opens Options, where its field is. A toolbar select's error line hangs under it (absolutely placed), so it moves nothing.
- Alternatives: a source select beside a stored-schema select in the toolbar (two controls, the toolbar width changes with the source); keep the source in Options and only stop it opening (the overlap stays).
- Why: UAT 2026-10-16: the toolbar Schema and the "Schema source" option overlapped (#214).
- Reversible: yes — `extract/SchemaSourceSelect.tsx`, `extract/form.ts`.

### D-1215 — A map's run lives in its browser history entry
- Date: 2026-10-17 · Change/PR: playground-followups (#238) · Status: decided
- Decision: a map's answer pushes a `/map` history entry whose state holds the form and the `MapResult`; showing an entry with one restores both, so back, forward and reload show the URLs again. A map job opened from Recent runs still says its URLs are not kept.
- Alternatives: persist the URLs on the server and put `?job=` in the address (the jobs spec keeps `POST /v1/map` unpersisted; an API and storage change); the request in query parameters (re-maps on every back).
- Why: backlog follow-up (#214); a 5000-URL answer does not fit an address, and the browser entry needs no server change.
- Reversible: yes — `map/mapRun.ts`.

### D-1216 — At phone width the action row comes first
- Date: 2026-10-17 · Change/PR: playground-followups (#238) · Status: decided
- Decision: from `sm` up the toolbar is one row as before; under `sm` it is a column whose first row is Get code and the primary button (CSS `order`), then Options and the tools, which may wrap. The button then sits under the input box at the same place in Scrape, Crawl, Extract and Map (checked at 375 px in Chromium).
- Alternatives: reserve the tools' height at phone width (unknown line count per mode).
- Why: backlog follow-up (D-1043, #218).
- Reversible: yes — `CommandBar.tsx`.

### D-1217 — Listing records are asked for like detail ones
- Date: 2026-10-17 · Change/PR: playground-followups (#238) · Status: decided
- Decision: the UI no longer refuses records for listing pages: a stored listing schema sets the page kind to listing, and field names may be drafted for listing pages, in every mode. `check_records` takes both page kinds since #206.
- Alternatives: none.
- Why: backlog follow-up (#206).
- Reversible: yes — `pageRequest.ts`.
