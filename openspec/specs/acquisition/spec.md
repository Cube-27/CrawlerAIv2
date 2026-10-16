# Acquisition Specification

## Purpose

Acquisition gets pages and records what happened: the HTTP and browser rungs, outcome classification, politeness,
the SSRF guard, proxies, body bounds, per-fetch cookies and the capture bundle. Rationale: ARCHITECTURE §7, §15, §18
([archived](../../changes/archive/2026-10-16-architecture-rev26/ARCHITECTURE.md)); history: SPEC-02.

## Requirements

### Requirement: Pure fetch, separate persistence
The system SHALL fetch through a pure `acquire(...)` that returns a `FetchResult` (bundle, duration, at least one
attempt) and writes nothing; `store_capture` writes the bundle object before its `capture` row, eval captures never
go through it, and only `remember_fetch_method` writes `site.fetch_method`. Refs: §7.1, D-0144, D-0206.

### Requirement: Rung order
The system SHALL try the detecting active adapter (only when the caller passes `send`), else the active config's API
recipe, else the page rung: `policy.method_hint` when `http`/`browser`, else the site's remembered method (`http` for
a new site). Every attempt is listed in the result and manifest. Refs: §7.1, D-0090; see [adapters](../adapters/spec.md).

### Requirement: Browser on evidence
In `auto`, the system SHALL retry in the browser an HTTP `shell` or `blocked` result other than 429/503, keep the
browser outcome only when `ok`, and send any later request of a fetch only when `admit_next` allows. The browser MUST
NOT be the default. Refs: §7.1, D-0009, D-0203, D-0865, D-0900.

### Requirement: Remembered fetch method and re-check
The system SHALL set `fetch_method='browser'` only when a browser `ok` followed an HTTP `shell`/`blocked` in the same
fetch; a scheduler re-check SHALL retry such a site over HTTP after 7 days (its latest `ok` URL, robots allowing) and
reset it to `http` on `ok`. Refs: §7.1, D-0204, D-0205.

### Requirement: HTTP and browser rungs
The HTTP rung SHALL use `curl_cffi` impersonating Chrome (`CRAWLERAI_IMPERSONATE`), at most 5 manual redirects, and
record headers without cookies or proxy credentials. The browser rung SHALL use Patchright headless Chromium, a fresh
context per fetch, one navigation, no scripted actions, capped by `browser_timeout_s`. The JSON rung (`fetch_json`,
`httpx`, method `api`) shares the HTTP rung's guard, caps, cookie jar and reasons. Refs: §7.1, D-0130, D-0251, D-0268.

### Requirement: Network JSON capture
When `capture_network_json` is set, the browser rung SHALL save JSON response bodies from any origin, in order, with
each request's method, body and cookie-free headers, within the caps in `acquire/browser.py`. Refs: §7.2, D-0010, D-0540.

### Requirement: Structural outcome classification (INV-24)
The system SHALL classify each final response from status and structure only (the classes and the shell, linkless
page and listing-shell rules in `acquire/classify.py`: a 2xx HTML page that is no shell and has no hyperlink is
`blocked`; a listing without repeated items is a shell unless its structured data lists items); classification and `site.fetch_method` MUST NOT
use vendor or challenge-page strings, and blocked and shell pages end with zero records. Bodies are decoded by HTML
encoding sniffing (D-1152). Refs: §7.1, C2, C3, D-0114, D-0932, D-0993, D-1157, D-1158.
Enforced by: the site-literal scan (INV-03), classify tests and review; active.
#### Scenario: Status classes
- **WHEN** the final status is 410, 451 or 418
- **THEN** the class is `not_found`, `blocked` or `error` respectively

### Requirement: Error outcomes and reasons
Every exception in a rung SHALL become an `error` attempt with a reason (`timeout`, `body_cap`, `network_error`, ...)
never containing the URL; it stores no body but keeps the last status and headers. Refs: §7.1, D-0127, D-0128.

### Requirement: Bounded bodies (INV-30)
The system SHALL bound untrusted bodies by `max_body_bytes` (compressed) and `max_decompressed_bytes` while streaming,
on every rung, before anything is kept; an oversize body MUST be `error`/`body_cap` with no capture body.
Enforced by: oversize and over-decompressing body tests; active. Refs: §7.1, §18, D-0320.
#### Scenario: Compression bomb
- **WHEN** a gzip body decompresses past `max_decompressed_bytes`
- **THEN** the outcome is `error`/`body_cap` and the bundle has no body

### Requirement: Public targets only (INV-16)
Every outbound connection target SHALL be a public IP: the guard in `acquire/ssrf.py` resolves once, rejects
non-global addresses, odd schemes, ports and IPv4 forms, connects to the checked IP and re-checks every redirect hop
(also through a proxy); the browser does the same through a per-fetch SOCKS5 guard. A rejection is
`error`/`ssrf_rejected`, never retried. Enforced by: SSRF tests with a stub resolver; active. Refs: §7.1, §18, D-0115, D-0249.
#### Scenario: Redirect to a private address
- **WHEN** `https://example.com/` answers 302 to a host resolving to 10.0.0.5
- **THEN** the hop is rejected with `ssrf_rejected` and nothing is fetched from it

### Requirement: Proxy pools
A site's `proxy_pool` SHALL be used from `CRAWLERAI_PROXY_POOLS` over a CONNECT tunnel; an unknown pool MUST end
`error`/`proxy_pool_unknown` sending nothing, and credentials never appear in errors. Refs: §7.1, D-0282, D-0286.

### Requirement: Cookies stay inside one fetch (INV-29)
Each fetch SHALL have its own HTTP session or browser context; cookies live in a per-fetch jar matched per RFC 6265
(public-suffix `Domain` ignored), are sent only on matching hops and are discarded at the end; none are stored.
Enforced by: cross-fetch and cross-domain cookie tests; active. Refs: §7.1, D-0321, D-0884, D-0902.
#### Scenario: Next fetch to the same host
- **WHEN** fetch A receives `Set-Cookie` from `example.com` and fetch B then requests `example.com`
- **THEN** fetch B sends no cookie

### Requirement: robots.txt
The system SHALL honour robots.txt by default per RFC 9309 for user agent `*`, cached per origin for 24 h in
`site.robots_snapshot`; a disallowed URL is `blocked`/`robots` without a request, an unreachable one (5xx or 429)
ends `blocked`/`robots_unreachable`, unless the job records a `respect_robots=false` override. A page an adapter would
serve is not held back by its own robots.txt: the adapter's request obeys its host's robots.txt, the page rungs are
not admitted, and an adapter answer that is not `ok` ends `robots`. Refs: §7.1, D-0159, D-0866,
D-1155, D-1156.

### Requirement: Per-site rate and backoff
The system SHALL space requests to a host by `crawl_delay_ms`, else 1 req/s, never below robots `Crawl-delay`,
postponing rather than sleeping. On 429/503 it SHALL honour `Retry-After`, else back off exponentially (30 s to
15 min), each answer spending an attempt. Refs: §7.1, D-0163, D-0165, D-0901.

### Requirement: Capture contents and the fetch CLI
A capture SHALL hold the body, network JSON bodies and a manifest (headers, timings, block class, attempts,
`page_kind`), with usage counted per attempt; `crawlerai fetch URL --out` writes a bundle and exits 0 whenever one is
written. Conditional GET is in [jobs](../jobs/spec.md). Refs: §15, D-0146, D-0250.

### Requirement: Acquisition candidates stay unbuilt
The system SHALL NOT include anti-bot identities, cookie handoff, vendor strategies, residential proxies, unblockers,
CAPTCHA solving, authenticated crawls or browser actions until the owner admits one (C13). Refs: §7.2, §22.
