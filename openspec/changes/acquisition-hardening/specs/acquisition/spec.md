# Delta: acquisition

## MODIFIED Requirements

### Requirement: Browser on evidence
In `auto`, the system SHALL retry in the browser an HTTP `shell` or `blocked` result other than 429/503, keeping the
browser outcome only when `ok`; a 503 that `classify.interstitial` judges to stand in for the page, after the site's
pause (`Retry-After`, else the first backoff), keeping the browser outcome only when `ok`; an HTTP `ok` detail page
whose schema requires a `money` field and whose capture holds no Offer entity and no `money` candidate, keeping the
browser outcome only when `ok` and it holds either; and an HTTP `ok` listing whose extraction gives no rows, keeping
the browser outcome only when `ok` and its extraction gives rows. An HTTP listing shell kept with no browser outcome
is `ok` when it is a shell by the listing rule alone. Any later request of a fetch is sent only when `admit_next`
allows. The browser MUST NOT be the default. (Previously: no 503 was retried, and a listing shell stayed a shell.)
Refs: §7.1, D-0009, D-0203, D-0865, D-0900, owner #49, D-1202, owner #54, D-1246–D-1249, D-1261, D-1263.
#### Scenario: Client-rendered offer
- **WHEN** an `auto` fetch of such a detail page answers HTTP `ok` with no Offer and no price, and the browser render
  holds an Offer
- **THEN** the browser capture is kept and the result lists both attempts
#### Scenario: Client-rendered listing
- **WHEN** an `auto` fetch of a listing answers HTTP `ok` with repeated links but no rows, and the render's extraction
  gives rows
- **THEN** the browser capture is kept, its extraction gives the records, and the result lists both attempts
#### Scenario: Listing shell whose render fails
- **WHEN** a listing answers HTTP with site structure but no repeated items, and the browser render is `blocked`
- **THEN** the HTTP capture is kept as `ok` and its attempt stays `shell`
#### Scenario: 503 interstitial
- **WHEN** HTTP answers 503 with `Retry-After: 7` and a script-only document
- **THEN** the browser attempt waits for a turn at least 7 s later, and its `ok` is kept

### Requirement: Remembered fetch method and re-check
The system SHALL set `fetch_method='browser'` only when a browser `ok` was kept over an HTTP attempt of the same fetch
(an HTTP `shell`/`blocked`, or an HTTP `ok` that lacked what the caller reads); a scheduler re-check SHALL retry such
a site over HTTP after 7 days (its latest `ok` URL, robots allowing) and reset it to `http` on `ok`. (Previously: only
after an HTTP `shell`/`blocked`.) Refs: §7.1, D-0204, D-0205, D-1260.

### Requirement: HTTP and browser rungs
The HTTP rung SHALL use `curl_cffi` impersonating Chrome (`CRAWLERAI_IMPERSONATE`), at most 5 manual redirects, and
record headers without cookies or proxy credentials. The browser rung SHALL use Patchright's full Chromium build in
headless mode, a fresh context per fetch, one navigation, no scripted actions (a listing scrape's browser actions
excepted, below), capped by `browser_timeout_s`; it reads
the page after `load` once the DOM's structure and text are unchanged for 2 s or, for a 2xx/3xx document, the network
is idle, and keeps the main frame's latest document, following a navigation the document starts itself. A document
`classify.interstitial` judges to stand in for the page (403, 429 or 503; a script or refresh; no page of the site) is
first given up to 40% of `browser_timeout_s` to navigate on, the wait ending at the main frame's next commit, with
nothing clicked or typed. The browser reads a body's wire size before the body. The JSON rung (`fetch_json`, `httpx`,
method `api`) shares the HTTP rung's guard, caps, cookie jar, proxy pools and reasons. (Previously: any 403/429/503
lacking site structure waited, polled, and `fetch_json` used no pool.) Refs: §7.1, D-0130, D-0251, D-0268, owner #49,
D-1200, D-1201, owner #50, D-1206, owner #52, D-1262, D-1264, D-1265.
#### Scenario: Interstitial that navigates on
- **WHEN** a 403 document with no site structure replaces itself after more than 2 s
- **THEN** the browser rung reads the document the navigation ends on
#### Scenario: Refusal that cannot navigate
- **WHEN** a 403 document has no script and no refresh
- **THEN** the browser rung does not wait for a navigation

### Requirement: Proxy pools
A site's `proxy_pool` SHALL be used from `CRAWLERAI_PROXY_POOLS` over a CONNECT tunnel by every rung (`acquire/tunnel.py`
for the JSON rung and the browser's guard); an unknown pool MUST end `error`/`proxy_pool_unknown` sending nothing, and
credentials never appear in errors. (Previously: the JSON rung used no pool.) Refs: §7.1, D-0282, D-0286, D-1264.

### Requirement: Per-site rate and backoff
The system SHALL space requests to a host by `crawl_delay_ms`, else 1 req/s, never below robots `Crawl-delay`,
postponing rather than sleeping. On 429/503 it SHALL honour `Retry-After`, else back off exponentially (30 s to
15 min), each answer spending an attempt; a 503 interstitial's one browser attempt waits out that pause through the
host's limiter, within the caller's bound for waiting in place (the worker's `WAIT_MAX`, a service's
`SLOW_DOWN_WAIT_MAX`), and is not sent past it. (Previously: no request followed a 429/503 inside the fetch.)
Refs: §7.1, D-0163, D-0165, D-0901, D-1263.
