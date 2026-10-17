# Delta: acquisition

## MODIFIED Requirements

### Requirement: HTTP and browser rungs
The HTTP rung SHALL use `curl_cffi` impersonating Chrome (`CRAWLERAI_IMPERSONATE`, else the profile nearest the
installed Patchright Chromium major, checked at startup by `acquire/impersonate.py`), at most 5 manual redirects, and
record headers without cookies or proxy credentials. The browser rung SHALL use Patchright's full Chromium build in
headless mode, a fresh context per fetch, one navigation, no scripted actions (a listing scrape's browser actions
excepted, below), capped by `browser_timeout_s`; it reads
the page after `load` once the DOM's structure and text are unchanged for 2 s or, for a 2xx/3xx document, the network
is idle, and keeps the main frame's latest document, following a navigation the document starts itself. A document
`classify.interstitial` judges to stand in for the page (403, 429 or 503; a script or refresh; no page of the site) is
first given up to 40% of `browser_timeout_s` to navigate on, the wait ending at the main frame's next commit, with
nothing clicked or typed. The browser reads a body's wire size before the body. The JSON rung (`fetch_json`, method
`api`) SHALL send through the HTTP rung's client (`acquire/curl_client.py`: impersonation, guard, caps, cookie jar,
proxy pools, reasons) the headers a page's `fetch()` sends: Fetch Metadata of a CORS request, `Referer`, `Origin`, in a
`fetch()`'s order. (Previously: the JSON rung used `httpx`, and the impersonation target was not checked.) Refs: §7.1,
D-0130, D-0251, D-0268, owner #49, D-1200, D-1201, owner #50, D-1206, owner #52, D-1262, D-1264, D-1265, owner #58,
D-1320–D-1322, D-1325.
#### Scenario: Interstitial that navigates on
- **WHEN** a 403 document with no site structure replaces itself after more than 2 s
- **THEN** the browser rung reads the document the navigation ends on
#### Scenario: Refusal that cannot navigate
- **WHEN** a 403 document has no script and no refresh
- **THEN** the browser rung does not wait for a navigation
#### Scenario: Cross-site JSON call
- **WHEN** a page on `https://jobs.example.com/` has its JSON fetched from `https://api.example.net/`
- **THEN** the request carries `Sec-Fetch-Site: cross-site`, `Sec-Fetch-Mode: cors`, `Origin: https://jobs.example.com`
  and no `Sec-Fetch-User`

### Requirement: Structural outcome classification (INV-24)
The system SHALL classify each final response from status and structure only (the classes and the shell, linkless
page and listing-shell rules in `acquire/classify.py`: a 2xx HTML page that is no shell and has no hyperlink is
`blocked`; a listing without repeated items is a shell unless its structured data lists items); classification and
`site.fetch_method` MUST NOT use vendor or challenge-page strings, and blocked and shell pages end with zero records. A
challenge label (below) is recorded only and changes neither. Bodies are decoded by HTML encoding sniffing (D-1152).
(Previously: no label was recorded.) Refs: §7.1, C2, C3, D-0114, D-0932, D-0993, D-1157, D-1158, D-1326.
Enforced by: the site-literal scan (INV-03), classify tests and review; active.
#### Scenario: Status classes
- **WHEN** the final status is 410, 451 or 418
- **THEN** the class is `not_found`, `blocked` or `error` respectively

### Requirement: Public targets only (INV-16)
Every outbound connection target SHALL be a public IP: the guard in `acquire/ssrf.py` resolves once, rejects
non-global addresses, odd schemes, ports and IPv4 forms, connects to the checked IP and re-checks every redirect hop
(also through each endpoint of a proxy pool); the browser does the same through a per-fetch SOCKS5 guard. A rejection
is `error`/`ssrf_rejected`, never retried. (Previously: a pool had one endpoint.) Enforced by: SSRF tests with a stub
resolver and pool tests over every endpoint; active. Refs: §7.1, §18, D-0115, D-0249, D-1323.
#### Scenario: Redirect to a private address
- **WHEN** `https://example.com/` answers 302 to a host resolving to 10.0.0.5
- **THEN** the hop is rejected with `ssrf_rejected` and nothing is fetched from it

### Requirement: Proxy pools
A site's `proxy_pool` SHALL be used from `CRAWLERAI_PROXY_POOLS` (a proxy URL, or endpoints with mode `rotate` or
`sticky`) over a CONNECT tunnel by every rung, which reports each fetch's endpoint health; an endpoint failing 3 times
in a row SHALL be left out for a quarantine doubling from 1 to 30 min (`core/proxy_health.py`), and a pool never sends
direct. An unknown pool MUST end
`error`/`proxy_pool_unknown` sending nothing, and credentials never appear in errors. (Previously: one endpoint per
pool.) Refs: §7.1, D-0282, D-0286, D-1264, D-1323, D-1324, D-1355.

### Requirement: Per-site rate and backoff
The system SHALL space requests to a host by `crawl_delay_ms`, else 1 req/s, never below robots `Crawl-delay`,
postponing rather than sleeping, and SHALL double a host's spacing on a 429, a 503 or a challenge (at most 15 min),
shrinking it by 10% after 20 `ok` answers in a row, never below that interval. On 429/503 it SHALL honour
`Retry-After`, else back off exponentially (30 s to 15 min), each answer spending an attempt; a 503 interstitial's one
browser attempt waits out that pause through the host's limiter, within the caller's bound for waiting in place (the
worker's `WAIT_MAX`, a service's `SLOW_DOWN_WAIT_MAX`), and is not sent past it. (Previously: the spacing did not
adapt.) Refs: §7.1, D-0163, D-0165, D-0901, D-1263, D-1327.
#### Scenario: Spacing after a slow-down
- **WHEN** a host with a 1 s interval answers 429 with `Retry-After: 5`, then `ok`
- **THEN** the next request goes no sooner than 5 s after the 429, and the one after it 2 s later

### Requirement: Cookies stay inside one fetch (INV-29)
Each fetch SHALL have its own HTTP session or browser context; cookies live in a per-fetch jar matched per RFC 6265
(public-suffix `Domain` ignored), are sent only on matching hops and are discarded at the end; the one exception is a
site session (`acquire/session.py`): the cookies of the site's registrable domain that a browser `ok` held after a
`blocked` or `shell` HTTP attempt with a portable or no challenge label, read without change with the user agent it
sent, seed later HTTP and JSON fetches of that site (`site.host`) in that domain through the same pool endpoint, in
process memory, for at most 30 min and 200 fetches; `blocked` drops it, and one refused before any `ok` leaves the site
without a session for 30 min. None are stored, logged or captured. (Previously: no cookie outlived its fetch.)
Enforced by: cross-fetch, cross-site, cross-domain, cross-proxy, expiry and no-persistence cookie tests; active.
Refs: §7.1, D-0321, D-0884, D-0902, owner #58, D-1350–D-1354.
#### Scenario: Next fetch to the same host
- **WHEN** fetch A receives `Set-Cookie` from `example.com` and fetch B then requests `example.com`, with no site session
- **THEN** fetch B sends no cookie
#### Scenario: Site session on another site
- **WHEN** `shop.example.com` has a site session and a fetch requests `www.example.com`
- **THEN** the fetch sends none of the session's cookies

### Requirement: Remembered fetch method and re-check
The system SHALL set `fetch_method='browser'` only when a browser `ok` was kept over an HTTP attempt of the same `auto`
fetch (an HTTP `shell`/`blocked`, or an HTTP `ok` that lacked what the caller reads) and did not open a site session; a
scheduler re-check SHALL retry such a site over HTTP after 7 days (its latest `ok` URL, robots allowing) and reset it to
`http` on `ok`. (Previously: a browser `ok` that opened a site session also set it.) Refs: §7.1, D-0204, D-0205, D-1260,
D-1353.

### Requirement: Acquisition candidates stay unbuilt
The system SHALL NOT include residential proxies, unblockers, CAPTCHA solving, challenge clicking, behaviour emulation,
fingerprint spoofing, real Chrome, authenticated crawls or browser actions beyond a single-URL listing scrape's (owner
#52) until the owner admits one (C13); no browser action types, submits a form, logs in or answers a CAPTCHA.
(Previously: anti-bot identities, cookie handoff and vendor strategies were also unbuilt; owner #58 admitted them in
the form above.) Refs: §7.2, §22, owner #52, owner #58.

## ADDED Requirements

### Requirement: Challenge labels
A `blocked` or `shell` attempt of any rung SHALL carry `challenge`: the vendor whose signature (`adapters/challenges.py`:
response header names, cookie names, also those a browser context holds, challenge resource paths) the response shows,
else `structural` when `classify.interstitial` holds, else none; the label is counted per label and rung and slows the
host's rate. Refs: owner #58, D-1326, D-1355.
#### Scenario: Structural challenge
- **WHEN** HTTP answers 403 with a script-only document that matches no vendor signature
- **THEN** the attempt is `blocked` with `challenge: structural`
