# Acquisition Specification

## Purpose

Acquisition gets pages and records what happened: the HTTP rung, the Patchright browser rung on evidence, outcome
classification, politeness (rate, backoff, robots.txt), the SSRF guard, proxy pools, body bounds, per-fetch cookies
and the capture bundle a fetch produces. Adapters and API recipes are rungs that run before the page rungs; their
behaviour is in [adapters](../adapters/spec.md) and [api-backed-pages](../api-backed-pages/spec.md). Storing and
expiring captures is [persistence-storage](../persistence-storage/spec.md).
Design rationale: [ARCHITECTURE §7](../../design/acquisition.md), [§15](../../design/recurring-and-storage.md),
[§18](../../design/operations.md). History: [SPEC-02](../../changes/archive/2026-10-13-spec-02-acquisition/SPEC-02-acquisition.md)
and its [decisions](../../changes/archive/2026-10-13-spec-02-acquisition/decisions.md).

## Requirements

### Requirement: Pure fetch, separate persistence
The system SHALL fetch through a pure `acquire(url, policy, remembered, rungs, ...)` that returns a `FetchResult`
(the `CaptureBundle`, its duration and at least one `AttemptRecord`) and writes nothing. Persisting is a separate
step: `store_capture` writes the bundle object before the `capture` row, in the caller's transaction; eval captures
never go through `store_capture`. `site.fetch_method` is written only by `remember_fetch_method`.
Refs: §7.1, SPEC-02 §4.1, §4.10, D-0144, D-0206.

#### Scenario: Persisting after a fetch
- **WHEN** a fetch returns and the caller stores it
- **THEN** the bundle object exists before the `capture` row that names it
- **AND** a failed insert leaves only an unreferenced object, never a row without a bundle

### Requirement: Rung order
The system SHALL try, in order: the active adapter that detects the URL (when the caller gives a JSON `send`), else
the active config's API recipe, else the page rungs. The page rung is `policy.method_hint` when it is `http` or
`browser`, otherwise the site's remembered `fetch_method` (a new site starts at `http`). Every attempt is listed in
`FetchResult.attempts` and in the manifest's `fetch_policy.attempts`; the capture's `block_class` is the kept one's.
Refs: §7.1, SPEC-02 §4.4, SPEC-15 §4.6, D-0090.

#### Scenario: No adapter, no recipe
- **WHEN** neither an adapter nor a recipe serves `https://example.com/p/1` and the site remembers `http`
- **THEN** the page is fetched over HTTP

### Requirement: Browser on evidence
In `auto`, the system SHALL retry in the browser an HTTP result that is `shell` or `blocked`, except a 429 or 503,
and SHALL keep the browser's outcome only when it is `ok`, listing both attempts. Each request after a fetch's first
(the browser retry, the page after an adapter or recipe) waits for `admit_next`; when it refuses, the request is not
sent and the fetch keeps its outcome. The browser MUST NOT be used by default.
Refs: §7.1, Appendix A #12, SPEC-02 §4.4, D-0009, D-0203, D-0865, D-0900.

#### Scenario: Shell over HTTP
- **WHEN** an `auto` fetch gets an HTTP `shell` and the browser returns `ok`
- **THEN** the browser result is kept and both attempts are recorded

#### Scenario: Slow-down is not retried
- **WHEN** the HTTP rung is answered 429
- **THEN** no browser attempt is made and the 429 `blocked` outcome is kept

### Requirement: Remembered fetch method and re-check
The system SHALL set `site.fetch_method='browser'` only when the kept result is a browser `ok` and an HTTP attempt of
the same fetch was `shell` or `blocked`; a `method_hint` browser fetch changes nothing. A scheduler re-check SHALL
take sites with `fetch_method='browser'` whose `fetch_method_checked_at` is null or older than 7 days, oldest first,
fetch the site's latest `ok` capture URL over HTTP after robots.txt, reset to `http` on `ok`, and stamp
`fetch_method_checked_at` on every re-check. No `ok` capture, a robots disallow or an unreachable robots.txt keeps
`browser`.
Refs: §7.1, SPEC-02 §4.4, D-0204, D-0205.

#### Scenario: Flip and flip back
- **WHEN** a site's fetch goes HTTP shell then browser ok, and a re-check 7 days later gets HTTP `ok`
- **THEN** `fetch_method` becomes `browser` and then `http` again

### Requirement: HTTP rung
The system SHALL fetch pages with `curl_cffi` impersonating Chrome (`CRAWLERAI_IMPERSONATE`, a curl_cffi profile
name, default `chrome150`, validated when settings load), following up to 5 redirects manually. Request and response
headers are recorded in the manifest without `Cookie`, `Set-Cookie` and `Proxy-Authorization`.
Refs: §7.1, SPEC-02 §4.7, D-0130, D-0742.

#### Scenario: Too many redirects
- **WHEN** a URL redirects a sixth time
- **THEN** the outcome is `error` with reason `too_many_redirects`

### Requirement: Browser rung
The system SHALL fetch in Patchright headless Chromium with a fresh context per fetch (one browser per worker
process; the API process launches one per browser fetch), a user agent with `HeadlessChrome` replaced by `Chrome`
and `Sec-CH-UA*` client hints that agree with it. It makes one navigation (`domcontentloaded`), no scripted actions
and no scrolling; `browser_timeout_s` (default 45) caps the whole fetch, the network-idle wait ends at 90% of it, and
a page that never goes idle is read then. Past the cap the outcome is `error`/`timeout`.
Refs: §7.1, Appendix A #20, SPEC-02 §4.8, D-0251, D-0429.

#### Scenario: JS-only page
- **WHEN** a page renders its content by script
- **THEN** the capture body is the rendered DOM and the raw navigation body is stored beside it as `body.raw.html`

### Requirement: Network JSON capture
When `capture_network_json` is set (default true), the browser rung SHALL save response bodies whose `content-type`
contains `json`, from any origin, in order, at most 2 MB each and 50 per page, into `bundle.network`, with each
request's method, UTF-8 request body (else none) and headers (without cookies). An entry whose request body exceeds
2 MB is skipped; the navigation response is not a network entry.
Refs: §7.1, §7.2 step 1, SPEC-02 §4.8, D-0010, D-0252, D-0540, D-0562.

#### Scenario: XHR page
- **WHEN** a page loads its values from a JSON endpoint
- **THEN** that JSON body, its request method and headers are in the capture's network entries

### Requirement: Structural outcome classification (INV-24)
The system SHALL classify each final response from status and structure only: `not_found` for 404 or 410;
`blocked` for 401, 403, 407, 429, 451 or 503; `error` for any other 4xx or 5xx, a network failure, timeout, too many
redirects, size or decode failure; `shell` and the small-document rule below for 2xx HTML; `ok` otherwise (a 3xx
reaching `classify` is `ok`). `site.fetch_method` and block classification MUST NOT use vendor or challenge-page
strings; 200-status challenge pages are not detected by content. Blocked and shell pages end with zero records.
Enforced by: the INV-03 site-literal scan; review; status: scan active, classification built (SPEC-02).
Refs: §7.1, C2, C3, SPEC-02 §4.3, D-0114.

#### Scenario: Status classes
- **WHEN** the final status is 410, 451 or 418
- **THEN** the class is `not_found`, `blocked` or `error` respectively

### Requirement: Shell rule
A 2xx response whose last `Content-Type` is `text/html`, `application/xhtml+xml` or absent SHALL be `shell` when,
after removing `script`, `style`, `noscript` and `template`, `<body>` has fewer than 200 non-whitespace characters
(`<title>` not counted) and fewer than 5 `<a href>` links. Over HTTP, a page fetched with `page_kind` listing is also
`shell` when it has no JSON-LD, microdata or `application/json` data block and no group of 3 or more same-shape linked
siblings outside `nav`/`header`/`footer`/`aside` and their landmark roles; siblings group by parent and tag, then by
the class tokens more than half of them carry. The browser rung classifies without the page kind. The thresholds are
unmeasured starting points to confirm on dev.
Refs: §7.1, SPEC-02 §4.3, D-0008, D-0112, D-0113, D-0933, D-0993.

#### Scenario: Visible text or links
- **WHEN** a 2xx HTML body has 200 or more visible characters or 5 or more links, and is not a listing that lists nothing
- **THEN** it is never `shell`

#### Scenario: Empty listing
- **WHEN** a listing fetched over HTTP lists nothing structurally
- **THEN** it is `shell` and `auto` retries it in the browser

### Requirement: Small terminal document is blocked
A 2xx HTML body of at most 1024 bytes, with enough visible text not to be a shell, and with no element that links,
loads, runs or embeds anything (`a`/`area[href]`, `script`, `link`, `img`, `picture`, `video`, `audio`, `iframe`,
`embed`, `object`, `svg`, `canvas`, `form`) SHALL be `blocked`.
Refs: §7.1, D-0932.

#### Scenario: Bare text answer
- **WHEN** a 2xx answer is 300 bytes of plain HTML text with no links or resources
- **THEN** the class is `blocked`, so `auto` retries it in the browser

### Requirement: Error outcomes and reasons
Every exception inside a rung SHALL become an `AttemptRecord` with `block_class='error'` and one of the reasons
`timeout`, `body_cap`, `decode_error`, `too_many_redirects`, `ssrf_rejected: <reason>`, `network_error: curl <code>`
(HTTP) or `network_error: net::ERR_*` (browser), `proxy_pool_unknown`. Reasons MUST NOT contain the URL. An `error`
outcome stores an empty body but keeps the last response's status and headers; with no status line the manifest
`status_code` is 0 and the attempt status null.
Refs: §7.1, SPEC-02 §4.11, D-0127, D-0128, D-0252.

#### Scenario: Connection refused
- **WHEN** the target refuses the connection
- **THEN** the attempt is `error`, `network_error: curl 7`, status 0, no body

### Requirement: Bounded bodies (INV-30)
The system SHALL bound untrusted request and response bodies before they are fully read: `max_body_bytes` (default
10,000,000, compressed) and `max_decompressed_bytes` (default 50,000,000) on the HTTP and JSON rungs while streaming,
and both on the browser's navigation body before anything is kept. An oversize body MUST be an `error` outcome with
reason `body_cap` and no capture body, never content.
Enforced by: tests in which an oversize and an over-decompressing body each end in an error outcome with no capture
body; status: implemented (SPEC-02, tests: SPEC-02 PR 10).
Refs: §7.1, §18, Appendix A #32, SPEC-02 §4.7, D-0320.

#### Scenario: Compression bomb
- **WHEN** a gzip body decompresses past `max_decompressed_bytes`
- **THEN** the outcome is `error`/`body_cap` and the bundle has no body

### Requirement: Public targets only (INV-16)
Every outbound connection target SHALL be a public IP: the guard resolves A/AAAA once and rejects any address that is
not `is_global` or is multicast or IANA-reserved IPv6, unwrapping IPv4-mapped and NAT64 addresses; it also rejects
non-http(s) schemes, ports other than 80, 443, 8080 and 8443, hosts that cannot be IDNA-encoded, and non-dotted-quad
IPv4 forms (`2130706433`, `0x7f.1`, `127.1`). The connection goes to the checked IP (`CURLOPT_RESOLVE "*:<port>:<ip>"`),
redirects are followed manually and each hop is re-checked; a `Location` to a non-http(s) scheme is `error`. A
rejection is `error`, `ssrf_rejected: <reason>`, never retried. Through a proxy the hostname is still checked before
each hop. Callers check the target before fetching (422 in [rest-api](../rest-api/spec.md), a failed task in
[jobs](../jobs/spec.md)).
Enforced by: SSRF tests with a stub resolver; status: built (SPEC-02).
Refs: §7.1, §18, SPEC-02 §4.5, D-0115, D-0116, D-0117, D-0129, D-0145, D-0426, D-0705.

#### Scenario: Redirect to a private address
- **WHEN** `https://example.com/` answers 302 to a host resolving to 10.0.0.5
- **THEN** the hop is rejected with `ssrf_rejected` and nothing is fetched from it

### Requirement: Browser SSRF guard
The browser rung SHALL send every connection of a fetch's context through a per-fetch loopback SOCKS5 guard (RFC
1928) that checks each (host, port) once per fetch and connects only to the checked address, covering every redirect
hop, frame and worker. Chromium's implicit loopback bypass is disabled (`<-loopback>`), WebRTC non-proxied UDP is
disabled, and the first URL is checked before the context opens (refusing `file:` and `data:`).
Refs: §7.1, SPEC-02 §4.5, D-0249.

#### Scenario: Frame to loopback
- **WHEN** a public page embeds a frame from `http://127.0.0.1/`
- **THEN** the guard refuses that connection

### Requirement: Proxy pools
A site with `site.proxy_pool` SHALL be fetched through that pool from `CRAWLERAI_PROXY_POOLS` (JSON
`{pool_name: proxy_url}`), an HTTP proxy `http://[user[:password]@]host[:port]` always used through a CONNECT tunnel
(curl's tunnel; the browser's guard chains each checked connection through it). A configured endpoint is the SSRF
allowlist entry. A policy naming an unconfigured pool MUST end with `error`, `proxy_pool_unknown`, fetching nothing.
Proxy credentials never appear in settings errors or reprs; a refused tunnel reports as `network_error: curl 7`.
Refs: §7.1, SPEC-02 §4.5, D-0282, D-0283, D-0284, D-0285, D-0286.

#### Scenario: Unknown pool
- **WHEN** a policy names pool `p9` that settings do not define
- **THEN** the outcome is `error`/`proxy_pool_unknown` and no request is sent

### Requirement: Cookies stay inside one fetch (INV-29)
Each fetch SHALL have its own HTTP session or browser context. The HTTP and JSON rungs keep cookies in one per-fetch
jar matched on each hop's host name (RFC 6265 §5.3 steps 5 and 6, §5.4), ignoring a `Domain` that is a public suffix
other than the setting host (Public Suffix List, a pinned manifest entry) and dropping one whose `Domain` is not an
IDNA name. Cookies are sent on later hops only when they match and are discarded when the fetch ends; none are stored.
Enforced by: tests that a cookie set by one fetch is absent from the next, and a cookie for another domain or path is
not sent on a hop; status: implemented (SPEC-02, tests: SPEC-02 PR 10).
Refs: §7.1, Appendix A #32, D-0321, D-0884, D-0902.

#### Scenario: Next fetch to the same host
- **WHEN** fetch A receives `Set-Cookie` from `example.com` and fetch B then requests `example.com`
- **THEN** fetch B sends no cookie

### Requirement: robots.txt
The system SHALL honour robots.txt by default, matching per RFC 9309 (longest match, `allow` on a tie, `*` and `$`)
for user agent `*` only, with `Crawl-delay` and `Sitemap:` read. robots.txt is fetched over the HTTP rung once per
origin per 24 h, outside the rate limiter, and kept in `site.robots_snapshot` as a map `{robots_url: {fetched_at,
status_code, body}}`. A 2xx is parsed (first 500 KiB, UTF-8); 4xx or more than 5 redirects allows all; 5xx, network
error, timeout or SSRF rejection is unreachable: a transient failure with nothing stored, `blocked`
(`robots_unreachable`) once attempts run out. A disallowed URL is `blocked` with reason `robots` without fetching,
unless the job's `respect_robots=false` override, with its reason, is recorded on `job.request`.
Refs: §7.1, SPEC-02 §4.6, D-0159, D-0160, D-0161, D-0162, D-0425, D-0634, D-0866.

#### Scenario: Disallowed path
- **WHEN** robots.txt for `https://example.com` disallows `/private` and a job fetches `/private/x`
- **THEN** the outcome is `blocked` with reason `robots` and no request is sent to the page

### Requirement: Per-site rate
The system SHALL space requests to a host by the site's `crawl_delay_ms`, else 1 s, never below the robots
`Crawl-delay`. A worker's first request that must wait is postponed (the attempt given back), never slept; a fetch's
further requests wait in place, and one more than `LEASE / 2` away is not sent. Limiter state is per process.
Refs: §7.1, SPEC-02 §4.6, D-0010, D-0165, D-0865, D-0900.

#### Scenario: Faster than robots
- **WHEN** a site sets `crawl_delay_ms=200` and robots.txt states `Crawl-delay: 2`
- **THEN** requests to that host are at least 2 s apart

### Requirement: Backoff on 429 and 503
On 429 or 503 the system SHALL honour `Retry-After` (seconds, or an HTTP-date measured from `fetched_at`), read per
attempt, else back off exponentially from 30 s up to 15 min, requeueing the task with `next_attempt_at`. Each such
answer spends an attempt; once attempts run out the task ends `blocked` (`last_error` e.g. `http 429`). A
`Retry-After` beyond 15 min ends the task `blocked` at once and pauses the host for 15 min.
Refs: §7.1, SPEC-02 §4.6, D-0163, D-0164, D-0901.

#### Scenario: Retry-After honoured
- **WHEN** a page answers 503 with `Retry-After: 120`
- **THEN** the task is requeued no sooner than 120 s later

### Requirement: JSON rung
The system SHALL fetch JSON (for adapters and API recipes) with `httpx` through `fetch_json(JsonRequest)`: method,
headers and body as given, `Accept: application/json`, the fetch's own Host and cookies winning, a redirected POST
following WHATWG Fetch §4.4, and the same SSRF guard, body caps, cookie jar and reasons as the HTTP rung. Its result
has method `api` and the JSON as body, recorded under the page URL.
Refs: §7.1, SPEC-02 §4.9, D-0268, D-0562.

#### Scenario: Private endpoint
- **WHEN** a JSON request targets a host resolving to a loopback address
- **THEN** the result is `error`/`ssrf_rejected` and nothing is sent

### Requirement: Capture contents and the fetch CLI
A capture SHALL record the response body, captured network JSON bodies, and a JSON manifest (headers, method,
timings, block class, attempts, `page_kind`), with the browser's raw navigation body as `body.raw.html`. Usage is
counted per attempt (`http_requests`, `proxy_bytes`, `browser_seconds`). `crawlerai fetch URL --out bundle.zst`
writes a bundle that `decode` reads, refuses (exit 2) an `--out` outside the working directory, and exits 0 whenever
a bundle is written, reporting `block_class` and `error` in its JSON summary. Conditional GET is in
[recurring](../recurring/spec.md).
Refs: §15, SPEC-02 §4.7, §4.8, §7, D-0146, D-0147, D-0250.

#### Scenario: Error outcome from the CLI
- **WHEN** `crawlerai fetch` gets a timeout
- **THEN** it writes the bundle, prints `block_class: error`, and exits 0

### Requirement: Acquisition candidates stay unbuilt
The system SHALL NOT include anti-bot identities, cookie handoff, vendor strategies, real Chrome with a behaviour
layer, residential proxies, unblockers, CAPTCHA solving, a detection bench, authenticated crawls or browser actions
until the owner admits one (C13).
Refs: §7.2, §22, SPEC-02 §2.

#### Scenario: Challenge page
- **WHEN** a 200 challenge page is fetched
- **THEN** it is classified only structurally and counts in the outcome mix as §22 evidence
