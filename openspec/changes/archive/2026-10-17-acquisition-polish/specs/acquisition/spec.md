## MODIFIED Requirements

### Requirement: Pure fetch, separate persistence
The system SHALL fetch through a pure `acquire(...)` that returns a `FetchResult` (bundle, duration, at least one
attempt) and writes nothing; `store_capture` writes the bundle object before its `capture` row, eval captures never
go through it, and only `remember_fetch_method` and the re-check write `site_fetch_method`. Refs: §7.1, D-0144, D-0206,
D-1380.
(Previously: `site.fetch_method`, one per site.)

### Requirement: Remembered fetch method and re-check
The system SHALL remember `browser` for a site's pages of one kind (`site_fetch_method`; a fetch with no page kind is
the detail pages') only when a browser `ok` was kept over an HTTP attempt of the same `auto` fetch of that kind (an
HTTP `shell`/`blocked`, or an HTTP `ok` that lacked what the caller reads) and did not open a site session; its other
kind keeps its own memory. A scheduler re-check SHALL retry each such memory over HTTP after 7 days (the latest `ok`
URL of that kind, robots allowing) and reset it to `http` on `ok`. (Previously: one memory per site, so a listing's
render sent the site's detail pages to the browser.) Refs: §7.1, D-0204, D-0205, D-1260, D-1353, D-1380.
#### Scenario: Listing render
- **WHEN** a site's listing is kept from its render because its HTTP page gave no rows
- **THEN** the site's listings are fetched in the browser and its detail pages still over HTTP

### Requirement: Structural outcome classification (INV-24)
The system SHALL classify each final response from status and structure only (the classes and the shell, linkless
page and listing-shell rules in `acquire/classify.py`: a 2xx HTML page that is no shell and has no hyperlink is
`blocked`; a listing without repeated items is a shell unless its structured data lists items); classification and
the remembered fetch method MUST NOT use vendor or challenge-page strings, and blocked and shell pages end with zero
records. A challenge label (below) is recorded only and changes neither. Bodies are decoded by HTML encoding sniffing
(D-1152). Refs: §7.1, C2, C3, D-0114, D-0932, D-0993, D-1157, D-1158, D-1326, D-1380.
Enforced by: the site-literal scan (INV-03), classify tests and review; active.
#### Scenario: Status classes
- **WHEN** the final status is 410, 451 or 418
- **THEN** the class is `not_found`, `blocked` or `error` respectively

### Requirement: Proxy pools
A site's `proxy_pool` SHALL be used from `CRAWLERAI_PROXY_POOLS` (a proxy URL, or endpoints with mode `rotate` or
`sticky`) over a CONNECT tunnel by every rung, which reports each fetch's endpoint health; an endpoint failing 3 times
in a row SHALL be left out for a quarantine doubling from 1 to 30 min (`core/proxy_health.py`), and a pool never sends
direct. An unknown pool MUST end `error`/`proxy_pool_unknown` sending nothing, and credentials never appear in errors.
Each attempt records the bytes it moved (the HTTP and JSON rungs' HTTP messages, CONNECT included; the bytes the
browser's guard relayed), counted as `proxy_bytes` usage of the pool for a fetch through one, a learning run's recipe
replays included. (Previously: no rung recorded `proxy_bytes`.) Refs: §7.1, D-0282, D-0286, D-1264, D-1323, D-1324,
D-1355, D-1381.
