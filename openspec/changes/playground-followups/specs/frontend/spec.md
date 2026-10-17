## MODIFIED Requirements

### Requirement: Playground modes and command bar
The playground SHALL serve Scrape `/`, Batch `/batch`, Crawl `/crawl`, Map `/map`, Extract `/extract` behind a link-tab mode switch without visible group captions, with one centred command bar (input row, then Options, Format, Schema, Get code and the primary button) that does not move between the single-URL modes at desktop width, and at phone width puts Get code and the primary button on the row under the input; Batch's URL box shows ten lines and scrolls inside (`frontend/src/screens/playground/`). Refs: Appendix A #38, #45, #51, D-0817, D-1043, D-1213, D-1216.
(Previously: the action stayed put at desktop width only.)
#### Scenario: Back and forward
- **WHEN** a user switches from Scrape to Crawl and presses back
- **THEN** the URL returns to `/` and Scrape mode shows

### Requirement: Schema, fields and format rules per mode
A stored schema in Scrape SHALL add `records` and fix the page kind, of either page kind; Batch and Crawl with a schema or field names send `formats: ["records"]`; Extract's toolbar Schema chooses its source (a stored schema, inline JSON, a prompt or field names) and reports a missing one there; fields (1–50 names, `[a-z][a-z0-9_]{0,63}`) and a stored schema are never sent together, and a fields run first shows the `POST /v1/schemas/draft` result for confirmation. Drafting is owned by [schemas](../schemas/spec.md). Refs: Appendix A #41, D-0752, D-0818, D-0925, D-0980, D-1214, D-1217.
(Previously: listing records were refused, and Extract's source was an Options setting beside the toolbar's Schema.)
#### Scenario: Batch with a schema
- **WHEN** a batch is started with a stored schema
- **THEN** the request's `formats` is `["records"]`

### Requirement: Recent runs, job routing and re-run
Each mode SHALL list its last 10 jobs before a run; `/jobs/:id` redirects to the kind's mode route with `?job=` (except `learn`, which keeps its page); a shown run is read-only from `GET /v1/jobs/{id}/request` until "Edit and re-run", which starts a new job. A map's request and URLs live in its browser history entry, so back and reload show them. Map or Crawl selections open Batch via navigation state. Refs: D-0855, D-0856, D-0861, D-0976, D-1215.
(Previously: a map's URLs were lost on navigation.)
#### Scenario: Old job link
- **WHEN** `/jobs/<id>` is opened for an `extract` job
- **THEN** the UI redirects to `/extract?job=<id>`
