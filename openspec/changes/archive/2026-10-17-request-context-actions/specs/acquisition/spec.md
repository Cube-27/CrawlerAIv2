## ADDED Requirements

### Requirement: Caller request context
A fetch policy MAY carry the caller's headers and cookies (`acquire/types.py` `RequestContext`): the HTTP and JSON rungs
SHALL send the headers only on requests to the fetched URL's host and seed the fetch's jar with the cookies as
host-only cookies of that host; the browser rung SHALL add the cookies to its context before the navigation and set no
header (INV-44). A fetch with a caller context neither takes nor opens a site session, and its values are never
captured or logged (manifests and recorded headers show `**********`). Refs: owner delegation 2026-10-17, D-1430–D-1434.
#### Scenario: Header to another host
- **WHEN** a fetch with header `Authorization` is redirected from `https://a.example/` to `https://b.example/`
- **THEN** the request to `b.example` carries no `Authorization`, and the capture records none of its value

### Requirement: Page actions
A browser fetch policy MAY carry at most 20 steps (`acquire/page_steps.py`: wait for milliseconds, an element or no
data call in flight; click an element or visible text; scroll to the end, by pixels or until the height stops growing;
press a key; type into an element), run in order after the settle and before the read, each bounded by its own timeout;
the first step that does not complete ends the run, the rest `skipped`, and the page is read as it is. Each step's
outcome is recorded on the attempt. A `type` into a password field or one whose autofill names a credential (HTML
Standard §4.10.18.7) MUST be refused. Refs: owner delegation 2026-10-17, D-1436–D-1439.
Enforced by: `tests/unit/test_page_steps_browser.py` (synthetic pages); active.
#### Scenario: Password field
- **WHEN** a step types into an `input type=password`
- **THEN** the step is `refused`, nothing is typed and the remaining steps are `skipped`

## MODIFIED Requirements

### Requirement: HTTP and browser rungs
The HTTP rung SHALL use `curl_cffi` impersonating Chrome (`CRAWLERAI_IMPERSONATE`, else the profile nearest the
installed Patchright Chromium major, checked at startup by `acquire/impersonate.py`), at most 5 manual redirects, and
record headers without cookies or proxy credentials. The browser rung SHALL use Patchright's full Chromium build in
headless mode, a fresh context per fetch (the caller's cookies added before it navigates), one navigation, no scripted
actions (a listing scrape's browser actions and the caller's page steps excepted, below), capped by `browser_timeout_s`
(plus the steps' own timeouts); it reads
the page after `load` once the DOM's structure and text are unchanged for 2 s or, for a 2xx/3xx document, the network
is idle, and keeps the main frame's latest document, following a navigation the document starts itself. A document
`classify.interstitial` judges to stand in for the page (403, 429 or 503; a script or refresh; no page of the site) is
first given up to 40% of `browser_timeout_s` to navigate on, the wait ending at the main frame's next commit, with
nothing clicked or typed. The browser reads a body's wire size before the body. The JSON rung (`fetch_json`, method
`api`) SHALL send through the HTTP rung's client (`acquire/curl_client.py`: impersonation, guard, caps, cookie jar,
proxy pools, reasons) the headers a page's `fetch()` sends: Fetch Metadata of a CORS request, `Referer`, `Origin`, in a
`fetch()`'s order. (Previously: no caller cookies or page steps.) Refs: §7.1,
D-0130, D-0251, D-0268, owner #49, D-1200, D-1201, owner #50, D-1206, owner #52, D-1262, D-1264, D-1265, owner #58,
D-1320–D-1322, D-1325, D-1433, D-1437.
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

### Requirement: Cookies stay inside one fetch (INV-29)
Each fetch SHALL have its own HTTP session or browser context; cookies live in a per-fetch jar matched per RFC 6265
(public-suffix `Domain` ignored), are sent only on matching hops and are discarded at the end; the caller's cookies
(`RequestContext`) seed only that fetch's jar or context, for the fetched URL's host; the one exception is a
site session (`acquire/session.py`): the cookies of the site's registrable domain that a browser `ok` held after a
`blocked` or `shell` HTTP attempt with a portable or no challenge label, read without change with the user agent it
sent, seed later HTTP and JSON fetches of that site (`site.host`) in that domain through the same pool endpoint, in
process memory, for at most 30 min and 200 fetches; `blocked` drops it, and one refused before any `ok` leaves the site
without a session for 30 min. None are stored, logged or captured. (Previously: caller cookies were not taken.)
Enforced by: cross-fetch, cross-site, cross-domain, cross-proxy, expiry, no-persistence and caller-cookie tests; active.
Refs: §7.1, D-0321, D-0884, D-0902, owner #58, D-1350–D-1354, D-1433.
#### Scenario: Next fetch to the same host
- **WHEN** fetch A receives `Set-Cookie` from `example.com` and fetch B then requests `example.com`, with no site session
- **THEN** fetch B sends no cookie
#### Scenario: Site session on another site
- **WHEN** `shop.example.com` has a site session and a fetch requests `www.example.com`
- **THEN** the fetch sends none of the session's cookies

### Requirement: Acquisition candidates stay unbuilt
The system SHALL NOT include residential proxies, unblockers, CAPTCHA solving, challenge clicking, behaviour emulation,
fingerprint spoofing or real Chrome until the owner admits one (C13); an authenticated crawl runs only on the caller's
own cookies or headers (above), and browser actions are a single-URL listing scrape's (owner #52) and the caller's page
actions (above); no action logs in, enters a credential or answers a CAPTCHA. (Previously: no authenticated crawl, no
browser action typed, and only a listing scrape's existed.) Refs: §7.2, §22, owner #52, owner #58, owner delegation
2026-10-17, D-1432, D-1438.
