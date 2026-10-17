## MODIFIED Requirements

### Requirement: Showing extraction results (INV-22, UI side)
Screens SHALL show a field only through `FieldValue`, `FieldStatusBadge`, `ConfidenceCell` and `LocatorText` (`frontend/src/components/`): a non-published value renders "—" with its reason, status is text plus icon, confidence a two-decimal number, and one "uncalibrated" badge per record, never per field, when a published field has `calibrated=false`; evidence and source kind read in words with the server's code on hover. INV-22 is owned by [resolution](../resolution/spec.md). Enforced by: component tests; active. (Previously: an uncalibrated badge on every field.) Refs: D-0368, D-0369, D-1390, D-1396.
#### Scenario: Conflict field
- **WHEN** a record field has status `conflict` and reason `disagree`
- **THEN** it renders "—", the status text "conflict" and the reason, with no value

### Requirement: Data screens
Jobs (`/jobs`, run history, filters in the URL), Records (one schema, at most six field columns, drawer inspector with Replay), Schemas (one form for create, adopt and edit; edit only on active non-preset), Sites and configs (host lookup, learn with `force`, correction via `PUT /v1/configs/{id}` with changed fields only, Approve and Reject (`POST /v1/configs/{id}/reject`) on a `pending_approval` config, absent fields named) and Settings (the project's "LLM call limit per run", "Draft call limit per key" and "Approve learned configs" via `/v1/project/settings`; LLM usage tables from `GET /v1/usage/llm`, unknown cost never guessed) SHALL live under `frontend/src/screens/`. (Previously: no reject, and no draft limit field.) Refs: D-0433, D-0656, D-0700, D-0978, D-0983, D-1342, D-1391, D-1394.
#### Scenario: Correction round-trip
- **WHEN** an operator edits a field's steps and submits
- **THEN** `PUT /v1/configs/{id}` carries only changed and confirmed fields and the validation report shows inline

### Requirement: Inputs and settings mirror the request DTOs
A URL without a scheme SHALL be sent with `https://` prepended (RFC 3986 §3); Batch takes one URL per line or a CSV (`url` column else first, RFC 4180), each line checked with the WHATWG URL parser. Scrape, Batch, Crawl and Extract take Max rows as `fetch.max_rows`. Each Options setting MUST map to a request member (except Metadata in JSON), empty limits are omitted, and an empty LLM call limit omits `budget`, so the project's cap applies. (Previously: no Max rows.) Refs: D-1395, D-0408, D-0819, D-0982, D-1006, D-1044, D-1121.
#### Scenario: Host and port typed
- **WHEN** the user types `example.com:8080/p`
- **THEN** the request's `url` is `https://example.com:8080/p`

### Requirement: Layout never shifts on interaction
Paging, tabs, filters, toggles, popovers, drawers and run-state changes SHALL move nothing around them: `PagedTable` pages by 20 in a fixed-height box with fixed column widths and truncation, and loading, empty and error states (including the playground output box) keep the content's footprint, and a toolbar select's error line hangs under it. (Previously: Schema's error line only.) Refs: D-1214, D-0751, D-0833, D-0985, DESIGN.md.
#### Scenario: Short last page
- **WHEN** the last page holds fewer than 20 rows
- **THEN** the table box and pager keep their size and place

## ADDED Requirements

### Requirement: A page's fetch trail
The scrape output's fetch view SHALL name the platform adapter that read the page, and a job page's drawer SHALL list the
page's fetch attempts (rung, status, block class, challenge label, duration, error), read from the results with
`include=fetch`, so a blocked page shows why. Refs: D-1392, D-1393.
#### Scenario: Blocked page
- **WHEN** a page's attempts end in `blocked` with a challenge label
- **THEN** its drawer shows each attempt's rung, status, block class and label
