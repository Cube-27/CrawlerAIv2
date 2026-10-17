## MODIFIED Requirements

### Requirement: Network JSON capture
When `capture_network_json` is set, the browser rung SHALL save, from any origin and in arrival order, the bodies of
fetch, XMLHttpRequest and document responses (not the main frame's navigation) that are JSON by media type or, labelled
`text/plain` or not at all, whose bytes are an RFC 8259 object or array (a guard prefix of at most 16 characters
stripped, `storage.capture_bundle.network_json`); each with its request's method, body and cookie-free headers, the
cookie-free response headers, the resource type and the count of browser actions before it, within the caps in
`acquire/browser.py`. Refs: §7.2, Appendix A #57, D-0010, D-0540, D-1311, D-1312.
(Previously: bodies labelled JSON only, with the request's method, body and headers.)
#### Scenario: JSON under another label
- **WHEN** a page fetches `)]}'` and a JSON object labelled `text/plain`, and a text/plain body that is no JSON
- **THEN** the first is kept as received and the second is not

### Requirement: Bounded bodies (INV-30)
The system SHALL bound untrusted bodies by `max_body_bytes` (compressed) and `max_decompressed_bytes` while streaming,
on every rung, before anything is kept; an oversize body MUST be `error`/`body_cap` with no capture body. A browser
capture keeps at most 10 MB of network bodies in all (`acquire/browser.py`).
Enforced by: oversize and over-decompressing body tests and the per-page network cap test; active.
Refs: §7.1, §18, Appendix A #57, D-0320, D-1311.
(Previously: no bound on a page's network bodies in all.)
#### Scenario: Compression bomb
- **WHEN** a gzip body decompresses past `max_decompressed_bytes`
- **THEN** the outcome is `error`/`body_cap` and the bundle has no body
#### Scenario: Network bodies of one page
- **WHEN** a page loads six JSON bodies of 1.9 MB each
- **THEN** the capture keeps the first five
