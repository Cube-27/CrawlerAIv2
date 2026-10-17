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
fingerprint spoofing, real Chrome or authenticated crawls until the owner admits one (C13); browser actions are a
single-URL listing scrape's (owner #52) and the caller's page actions (above); no action logs in, enters a credential
or answers a CAPTCHA. (Previously: no browser action typed, and only a listing scrape's existed.) Refs: §7.2, §22,
owner #52, owner #58, owner delegation 2026-10-17, D-1438.
