# Acquisition Specification

## Purpose

Acquisition gets pages and records what happened: the HTTP and browser rungs, outcome classification, politeness,
the SSRF guard, proxies, body bounds, per-fetch cookies and site sessions, and the capture bundle.

## Requirements

### Requirement: Pure fetch, separate persistence
The system SHALL fetch through a pure `acquire(...)` that returns a `FetchResult` (bundle, duration, at least one
attempt) and writes nothing; `store_capture` writes the bundle object before its `capture` row, eval captures never
go through it, and only `remember_fetch_method` and the re-check write `site_fetch_method`. Refs: §7.1, D-0144, D-0206,
D-1380.
(Previously: `site.fetch_method`, one per site.)

### Requirement: Rung order
The system SHALL try the detecting active adapter (only when the caller passes `send`), else the active config's API
recipe, else the page rung: `policy.method_hint` when `http`/`browser`, else the site's remembered method (`http` for
a new site). Every attempt is listed in the result and manifest. Refs: §7.1, D-0090; see [adapters](../adapters/spec.md).

### Requirement: Browser on evidence
In `auto`, the system SHALL retry in the browser an HTTP `shell` or `blocked` result other than 429/503, and an HTTP
`error` whose reason is `network_error` or `timeout` (never the same transport again), keeping the browser outcome only
when `ok`; a 503 that `classify.interstitial`
judges to stand in for the page, after the site's pause (`politeness.backoff`), keeping the browser outcome only when
`ok`; and an HTTP `ok` page the caller's render check holds true for (`services/scrape_steps.RenderNeed`, cheap
signals only: no collector pass, no extraction and no LLM): a detail page whose schema requires a `money` field and
whose document shows no sign of its offer (`content/render_need.offer_shown`: no schema.org Product with offers, OGP
`product:price:amount` or microdata Product with offers; no state document of at least `STATE_MIN_VALUES` scalar
values, whatever its name, `content/state.py`; no heading (`h1` to `h6`) with a digit beside a Unicode Sc currency
sign in the visible text), any page of a request that names `render_fields` (the fields the caller says only a render shows; that render
is kept when `ok`), or a listing (`content/render_need.py`) whose DOM shows fewer than `MIN_ITEMS` item blocks, whose
text inside `hidden` or `display:none` containers outweighs its visible text, or whose structured list names fewer
entries than its DOM shows item blocks (item blocks counted only when they show more than their link); that browser
outcome is kept only when `ok` and the check no longer holds, a listing's also when the render lists more items than the
HTTP page (owner #54: the capture with more rows is kept). An HTTP listing shell kept with no browser outcome is `ok`
when it is a shell by the listing rule alone. Any later request of a fetch is sent only when `admit_next` allows, and
no browser retry starts with less than `BROWSER_MIN_S` (20 s) left of the task's budget (a worker task's
`TASK_DEADLINE`, a scrape's `timeout_s`): the HTTP outcome is kept. No other 4xx (`auth_wall`, `not_found`, `error`)
and no redirect class is retried in the browser. The browser MUST NOT be the default. Role C runs once, on the kept
capture. (Previously: a detail page was rendered when a full collector pass found no Offer and no `money` candidate; a
listing was rendered when its extraction, role C included, gave no rows; an HTTP timeout was not retried in the
browser.) Refs: §7.1, D-0009, D-0203, D-0865, D-0900, owner #49, D-1202, owner #54, D-1261, D-1263, D-1472, master
plan 2026-10-18 §3.1, owner plan 2026-10-19 (crawl speed; P3 fetch classification and the browser decision).
#### Scenario: Client-rendered offer
- **WHEN** an `auto` fetch of such a detail page answers HTTP `ok` with none of the offer signals, and the browser render
  holds an Offer
- **THEN** the browser capture is kept and the result lists both attempts
#### Scenario: Offer signals present
- **WHEN** an `auto` fetch of such a detail page answers HTTP `ok` with a JSON-LD Product with offers
- **THEN** no browser attempt is made, unless the request names `render_fields`
#### Scenario: Budget nearly spent
- **WHEN** an HTTP `shell` arrives with 15 s of the task's budget left
- **THEN** no browser attempt is made and the HTTP outcome is kept
#### Scenario: Stream-rendered listing
- **WHEN** an `auto` fetch of a listing answers HTTP `ok` with its items inside `hidden` containers, and the render
  shows them
- **THEN** the browser capture is kept, the page is extracted once, and the result lists both attempts
#### Scenario: Listing shell whose render fails
- **WHEN** a listing answers HTTP with site structure but no repeated items, and the browser render is `blocked`
- **THEN** the HTTP capture is kept as `ok` and its attempt stays `shell`
#### Scenario: 503 interstitial
- **WHEN** HTTP answers 503 with `Retry-After: 7` and a script-only document
- **THEN** the browser attempt waits for a turn at least 7 s later, and its `ok` is kept
#### Scenario: Network error
- **WHEN** an `auto` fetch's HTTP attempt ends `error` with `network_error: curl 92` and the browser answers `ok`
- **THEN** the browser capture is kept and the result lists both attempts
#### Scenario: HTTP timeout
- **WHEN** an `auto` fetch's HTTP attempt ends `error` with `timeout` and the browser answers `ok`
- **THEN** HTTP is not tried again and the browser capture is kept

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

### Requirement: HTTP and browser rungs
The HTTP rung SHALL use `curl_cffi` impersonating Chrome (`CRAWLERAI_IMPERSONATE`, else the profile nearest the
installed Patchright Chromium major, checked at startup by `acquire/impersonate.py`), at most 5 manual redirects, and
record headers without cookies or proxy credentials, within `timeout_s` (10 s by default). The browser rung SHALL use Patchright's full Chromium build in
headless mode, one browser per process shared by its page fetches (worker, API, scheduler, eval) with at most
`BROWSER_CONTEXTS` (2) of them rendering at once (`acquire/shared_browser.py`; a listing scrape with browser actions
launches its own), a fresh context per fetch (the caller's cookies added before it navigates), one navigation, no scripted
actions (a listing scrape's browser actions and the caller's page steps excepted, below), capped by `browser_timeout_s`
(plus the steps' own timeouts); it aborts image, font and media requests by resource type, never by hostname, unless
the policy captures the page as a file or the site loads every resource (`site.load_all_resources`, set when a
resource-blocked render of its listing showed fewer item blocks than its HTTP page); it reads
the page after `load` once the DOM's structure and text are unchanged for 2 s or, for a 2xx/3xx document, the network
is idle, at most 5 s after that wait began whether or not it is quiet, and keeps the main frame's latest document, following a navigation the document starts itself. A document
`classify.interstitial` judges to stand in for the page (403, 429 or 503; a script or refresh; no page of the site) is
first given up to 40% of `browser_timeout_s`, and at most 10 s, to navigate on, the wait ending at the main frame's
next commit, with nothing clicked or typed. The browser reads a body's wire size before the body. The JSON rung
(`fetch_json`, method `api`) SHALL send through the HTTP rung's client (`acquire/curl_client.py`: impersonation, guard,
caps, cookie jar, proxy pools, reasons) the headers a page's `fetch()` sends: Fetch Metadata of a CORS request,
`Referer`, `Origin`, in a `fetch()`'s order. (Previously: every resource loaded, and the interstitial wait had no
absolute bound; the settle wait had none but the fetch's budget, a browser was launched per fetch outside the worker,
and the HTTP timeout was 30 s.) Refs: §7.1, D-0130, D-0251, D-0268, owner #49, D-1200, D-1201, owner #50, D-1206, owner #52, D-1262,
D-1264, D-1265, owner #58, D-1320–D-1322, D-1325, D-1433, D-1437, master plan 2026-10-18 recommendation 12, owner
plan 2026-10-19 (crawl speed).
#### Scenario: Interstitial that navigates on
- **WHEN** a 403 document with no site structure replaces itself after more than 2 s
- **THEN** the browser rung reads the document the navigation ends on
#### Scenario: Refusal that cannot navigate
- **WHEN** a 403 document has no script and no refresh
- **THEN** the browser rung does not wait for a navigation
#### Scenario: Images not loaded
- **WHEN** a page loads an image, a font and a JSON call, and the policy captures no file
- **THEN** the image and font requests are aborted and the JSON call is answered
#### Scenario: Cross-site JSON call
- **WHEN** a page on `https://jobs.example.com/` has its JSON fetched from `https://api.example.net/`
- **THEN** the request carries `Sec-Fetch-Site: cross-site`, `Sec-Fetch-Mode: cors`, `Origin: https://jobs.example.com`
  and no `Sec-Fetch-User`

### Requirement: Network JSON capture
When `capture_network_json` is set, the browser rung SHALL save, from any origin and in arrival order, the bodies of
fetch, XMLHttpRequest and document responses (not the main frame's navigation) that are JSON by media type or, labelled
`text/plain` or not at all, whose bytes are an RFC 8259 object or array (a guard prefix of at most 16 characters
stripped, `storage.capture_bundle.network_json`); each with its request's method, body and cookie-free headers, the
cookie-free response headers, the resource type and the count of browser actions before it, within the caps in
`acquire/browser.py`. A render whose content is quiet while a data call is in flight is read up to 3 s later, so a
late data call is kept; a data call is a fetch or XMLHttpRequest call to the page's own site (HTML §7.1.1) or one whose
`Accept` names a JSON MIME type, so another site's beacons and pings hold no read. (Previously: every fetch and
XMLHttpRequest call held the read.) A navigation the main frame commits while the render settles restarts the wait
on the new document (within the settle deadline), so the capture is the final document. Refs: §7.2, Appendix A #59, D-0010, D-0540, D-1311, D-1312, D-1369, owner plan 2026-10-19 (crawl speed).
#### Scenario: JSON under another label
- **WHEN** a page fetches `)]}'` and a JSON object labelled `text/plain`, and a text/plain body that is no JSON
- **THEN** the first is kept as received and the second is not

### Requirement: Structural outcome classification (INV-24)
The system SHALL classify each final response, before extraction, from status and structure (the classes and the shell,
linkless page, self-refreshing page and listing-shell rules in `acquire/classify.py`: a 2xx HTML page that is no shell
and has no hyperlink, or that declares a refresh and has hyperlinks but none to a web page (even one short enough to be
a shell), is `blocked`; a listing without repeated items is a shell unless its structured data lists items; a 401 is
`auth_wall`), and from one kind of site data only: a 2xx HTML document that shows a vendor's stand-in marker
(`adapters/challenges.py`) is `blocked`. A block needs corroboration and usable content beats it: a 403, or a 2xx
document with a stand-in marker, that carries the page's structured data (`classify.usable_content`: a schema.org
Product with offers, an OGP product price, a microdata Product with offers; on a listing the items its structured data
lists) is `ok`. A 2xx page fetched as a detail or listing page that a redirect (`classify.Redirect`) led away from the
page asked for (another host or path past a BCP 47 locale segment) is `geo_redirect` when the answering URL names
another region (a BCP 47 region subtag in its first path segment, else a two-letter ccTLD, RFC 1591) and another path,
`soft_404` when it is a site's or an edition's root, and, for a detail page, `redirected_to_listing` when it lists items,
states no product and its path does not keep the asked path's last segment as a word (a slug added); a fetch of no page
kind (a crawl's page) is never classed by its redirect. A redirect to a page whose query carries the asked path, as
given or base64-encoded (RFC 4648), is an interstitial that sends the client back once passed: `blocked`. These classes are the
transport outcome (the capture's `block_class`); a page in any of them yields zero records and ends its task with the
same-named outcome, never as a page without a price.
Generic code and the remembered fetch method MUST NOT use vendor or challenge-page strings, and blocked and shell pages
end with zero records. A body is decoded once at acquisition by HTML encoding sniffing
(`storage/capture_bundle.decode_html`, D-1152; a JSON body as UTF-8, RFC 8259 §8.1, whatever charset it is labelled
with), and every rule reads that text.
(Previously: the rules parsed the raw bytes, and a non-UTF-8 attribute raised.) Refs: §7.1, C2, C3, D-0114, D-0932,
D-0993, D-1157, D-1158, D-1326, D-1380, D-1470, D-1471.
Enforced by: the site-literal scan (INV-03), classify and challenge tests and review; active.
#### Scenario: Status classes
- **WHEN** the final status is 410, 451 or 418
- **THEN** the class is `not_found`, `blocked` or `error` respectively
#### Scenario: Vendor stand-in served with 200
- **WHEN** a 200 HTML document shows a vendor's stand-in marker and links to pages of its site
- **THEN** the class is `blocked` with that vendor's challenge label
#### Scenario: Usable content beats vendor noise
- **WHEN** a 403 HTML document carries a JSON-LD Product with offers
- **THEN** the class is `ok` and the page is extracted
#### Scenario: Detail page redirected home
- **WHEN** a detail page's HTTP fetch is redirected to its site's `/` and answers 200
- **THEN** the class is `soft_404`, no browser attempt is made, and the task ends `soft_404`
#### Scenario: Legacy encoding
- **WHEN** a 200 page declared `charset=euc-jp` carries non-ASCII bytes in a `meta` and an `a` attribute
- **THEN** it is classified from its decoded text without raising

### Requirement: Error outcomes and reasons
Every exception in a rung SHALL become an `error` attempt with a reason (`timeout`, `body_cap`, `network_error`, ...)
never containing the URL; it stores no body but keeps the last status and headers. Refs: §7.1, D-0127, D-0128.

### Requirement: Bounded bodies (INV-30)
The system SHALL bound untrusted bodies by `max_body_bytes` (compressed) and `max_decompressed_bytes` while streaming,
on every rung, before anything is kept; an oversize body MUST be `error`/`body_cap` with no capture body. A browser
capture keeps at most 10 MB of network bodies in all (`acquire/browser.py`), each read only once its request is done:
a body that never ends (a stream, a beacon held open) is left out, never waited for past the fetch's budget.
Enforced by: oversize and over-decompressing body tests, the per-page network cap test and the unending-body test;
active.
Refs: §7.1, §18, Appendix A #59, D-0320, D-1311.
#### Scenario: Compression bomb
- **WHEN** a gzip body decompresses past `max_decompressed_bytes`
- **THEN** the outcome is `error`/`body_cap` and the bundle has no body
#### Scenario: Network bodies of one page
- **WHEN** a page loads six JSON bodies of 1.9 MB each
- **THEN** the capture keeps the first five
#### Scenario: A data call whose body never ends
- **WHEN** a page's data call sends its headers and part of its body, then holds the rest past the fetch
- **THEN** the page is captured `ok` with its other JSON bodies, without that one

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
direct. An unknown pool MUST end `error`/`proxy_pool_unknown` sending nothing, and credentials never appear in errors.
Each attempt records the bytes it moved (the HTTP and JSON rungs' HTTP messages, CONNECT included; the bytes the
browser's guard relayed), counted as `proxy_bytes` usage of the pool for a fetch through one, a learning run's recipe
replays included. (Previously: no rung recorded `proxy_bytes`.) Refs: §7.1, D-0282, D-0286, D-1264, D-1323, D-1324,
D-1355, D-1381.

### Requirement: Cookies stay inside one fetch (INV-29)
Each fetch SHALL have its own HTTP session or browser context; cookies live in a per-fetch jar matched per RFC 6265
(public-suffix `Domain` ignored), are sent only on matching hops and are discarded at the end; the caller's cookies
(`RequestContext`) seed only that fetch's jar or context, for the fetched URL's host; the exceptions are the site
session and the stored cookie state (`acquire/session.py`, next requirement). A site session is the cookies of the
site's registrable domain that a browser `ok` held after a `blocked` or `shell` HTTP attempt, challenge and clearance
cookies left out, read without change with the user agent it sent; it seeds later HTTP and JSON fetches of that site
(`site.host`) in that domain through the same pool endpoint, and its browser contexts on a direct route (a pooled
context picks its own endpoint), in process memory, for at most 30 min and 200 fetches; `blocked` drops it, and one refused before any `ok` leaves the site without a session for
30 min. No cookie is logged or captured. (Previously: a vendor's clearance cookies were replayed when its signature
called them portable.) Enforced by: cross-fetch, cross-site, cross-domain, cross-proxy, expiry, no-persistence and
caller-cookie tests; active. Refs: §7.1, D-0321, D-0884, D-0902, owner #58, D-1350–D-1354, D-1433.
#### Scenario: Next fetch to the same host
- **WHEN** fetch A receives `Set-Cookie` from `example.com` and fetch B then requests `example.com`, with no site session
  and no stored cookie state
- **THEN** fetch B sends no cookie
#### Scenario: Site session on another site
- **WHEN** `shop.example.com` has a site session and a fetch requests `www.example.com`
- **THEN** the fetch sends none of the session's cookies

### Requirement: Stored cookie state
With `CRAWLERAI_COOKIE_KEY` set, the system SHALL keep per site (`site.host`) and browser engine (`patchright`) the
cookies of the site's registrable domain that a browser context held after an `ok` page with no challenge label, in
`site_cookie_state`, encrypted (Fernet) and rewritten only when the HMAC fingerprint of the plain state changes. Only
cookies are kept: no other storage. Before a write and after a load, challenge and clearance cookies (every vendor
signature's cookie names and cookie value markers, `adapters/challenges.py`) are dropped, as are cookies with an empty value or past their expiry;
cookies are de-duplicated by name, domain and path; session cookies stay; a state with nothing left is not written
and drops the kept one. A direct browser `ok` also refreshes the site's live session with its cookies.
A `shell`, `blocked` or `error` outcome writes nothing, and any `blocked` fetch of the site on a direct route clears
its state. A browser context of the site starts with its live site session's cookies, else the stored state; HTTP and
JSON fetches of the site take the live session, else the stored state's cookies (with their own identity). The flow is
browser to HTTP only: no cookie an HTTP response sets is kept or handed to the browser. The stored state serves and is
written by direct fetches only (no proxy pool); a fetch with the caller's context neither reads nor writes it. Refs:
owner 2026-10-19 (acquisition plan P2).
#### Scenario: Next job loads the state
- **WHEN** a browser fetch of `shop.example.com` ends `ok` holding `session=1` and `cf_clearance=x`, and a later job
  fetches `shop.example.com` over HTTP
- **THEN** the HTTP request carries `session=1` and not `cf_clearance`
#### Scenario: Block clears the state
- **WHEN** a fetch of a site with stored state ends `blocked`
- **THEN** the site has no stored state, and nothing is written

### Requirement: robots.txt
The system SHALL honour robots.txt by default per RFC 9309 for user agent `*`, cached per origin for 24 h in
`site.robots_snapshot`; a disallowed URL is `blocked`/`robots` without a request, an unreachable one (5xx or 429)
ends `blocked`/`robots_unreachable`, unless the job records a `respect_robots=false` override. A page an adapter would
serve is not held back by its own robots.txt: the adapter's request obeys its host's robots.txt, the page rungs are
not admitted, and an adapter answer that is not `ok` ends `robots`. Refs: §7.1, D-0159, D-0866,
D-1155, D-1156.

### Requirement: Per-site rate and backoff
The system SHALL fetch every page and JSON request through one polite fetch (`services/polite.py`): robots.txt, then
the host's rate, then the fetch, then the observation and the back-off. It SHALL space requests to a host by
`crawl_delay_ms`, else 1 req/s, never below robots `Crawl-delay`, postponing a worker task rather than sleeping (a
caller that waits waits in place up to one minute, a turn further off answering `blocked`, reason `slow_down`, with
nothing sent), and SHALL double a host's spacing on a 429, a 503 or a challenge (at most 15 min),
shrinking it by 10% after 20 `ok` answers in a row, never below that interval. On 429/503 it SHALL pause the host by
one rule (`acquire/politeness.backoff`): the `Retry-After`, else 30 s doubling per try, at most 15 min, a `Retry-After`
past 15 min ending the fetch `blocked`; each answer spends an attempt; a further request of a fetch (the 503
interstitial's one browser attempt) waits out that pause within the caller's bound for waiting in place (the worker's
`QUEUED` bound, a third of the task deadline; a service's one minute), and is not sent past it. (Previously: four front-ends, with three back-off
rules.) Refs: §7.1, D-0163, D-0165, D-0901, D-1263, D-1327, master plan 2026-10-18 §4 item 5.
#### Scenario: Spacing after a slow-down
- **WHEN** a host with a 1 s interval answers 429 with `Retry-After: 5`, then `ok`
- **THEN** the next request goes no sooner than 5 s after the 429, and the one after it 2 s later

### Requirement: Capture contents and the fetch CLI
A capture SHALL hold the body, network JSON bodies and a manifest (headers, timings, block class, attempts,
`page_kind`, and for a browser capture of a listing the rendered area of each block of its repeated item groups by
element path, `item_areas`, at most 2,000 blocks), with usage counted per attempt; `crawlerai fetch URL --out` writes a
bundle and exits 0 whenever one is written. Conditional GET is in [jobs](../jobs/spec.md). (Previously: no item areas.)
Refs: §15, D-0146, D-0250, owner #67.

### Requirement: Acquisition candidates stay unbuilt
The system SHALL NOT include residential proxies, unblockers, CAPTCHA solving, challenge clicking, behaviour emulation,
fingerprint spoofing or real Chrome until the owner admits one (C13); an authenticated crawl runs only on the caller's
own cookies or headers (above), and browser actions are a single-URL listing scrape's (owner #52) and the caller's page
actions (above); no action logs in, enters a credential or answers a CAPTCHA. (Previously: no authenticated crawl, no
browser action typed, and only a listing scrape's existed.) Refs: §7.2, §22, owner #52, owner #58, owner delegation
2026-10-17, D-1432, D-1438.

### Requirement: Patchright's documented browser setup (INV-42, INV-43, INV-44)
The browser rung SHALL follow the Patchright README's setup (owner #50): INV-42, it launches Patchright's full
Chromium build (`channel="chromium"`, installed with `patchright install --no-shell chromium`), never the headless
shell; INV-43, its only launch argument is the guard's WebRTC policy (no flag Patchright removes, none that changes
the fingerprint); INV-44, no context, page or CDP call sets a user agent, client hints, extra headers or init scripts,
and `evaluate` runs only in Patchright's isolated world. Refs: owner #50, D-1204, D-1205.
Enforced by: `tests/unit/test_browser_setup.py` (launch and context options, source scan); active.

### Requirement: Listing browser actions
For a scrape that asks for them, and by default for a single-URL listing scrape asking for `records` in `auto` whose
page is rendered (never for batch, crawl or the eval import), the browser rung SHALL run the caller's `fetch.actions`
and `wait_for` on the settled page first (the site's API recipe is not used then), and then act on the item group (the
`acquire/items.py` group with the largest rendered area; on a page with no linked items, the rows of the first series
of its latest data calls, `collect/network_match.py`) through Patchright's isolated world (`crawl/paging.py`): the
hinted mechanism, else next or numbered links, a numbered pager's integer controls, scroll (two rounds), then the
visible control after the last item; it waits up to 5 s per action for new items or a new first item, keeps a document
state before each page turn, and before each scroll or control click a state it drops again when the state after still
shows all its items, and stops at `records` distinct items (100 by default), at the list's end, at 40 actions or at its
time cap, with the reason. A control click that changes the URL is undone and not taken as load-more. (Previously:
only a scrape that asked for them.) Refs: owner #52, D-1218–D-1225, D-1404, D-1405, D-1513, master plan 2026-10-18
recommendation 11.
Enforced by: `tests/unit/test_paging_browser.py` (synthetic pages per mechanism) and `tests/property/test_paging.py`;
active.
#### Scenario: Load-more control
- **WHEN** a listing shows 20 items and a button after the last one adds 20 per click, and `records` is 50
- **THEN** the run clicks it twice, stops with reason `records`, and keeps one capture holding 60 items
#### Scenario: Nothing to page
- **WHEN** a listing shows 12 items and no next link, pager, growth on scroll or control after its items
- **THEN** the run stops with reason `no_mechanism` and keeps one capture
#### Scenario: Virtualised list
- **WHEN** a scroll listing of 48 items keeps only its last 16 in the document
- **THEN** the kept captures together hold all 48 items
#### Scenario: Consent layer
- **WHEN** a load-more listing sits under a layer whose button removes it, and the caller's first step clicks that button
- **THEN** the run clicks the control to the list's end, and the first kept state's attempt reports the step as `done`
#### Scenario: Default growth
- **WHEN** a listing scrape in `auto` without `browser_actions` is rendered because its HTTP page holds its items in
  `hidden` containers
- **THEN** the render grows the list toward 100 records and the answer reports the actions

### Requirement: Challenge labels
A `blocked` or `shell` attempt of any rung SHALL carry `challenge`: the vendor whose signature (`adapters/challenges.py`:
response header names, cookie names, also those a browser context holds, challenge resource paths, stand-in markers)
the response shows, else `structural` when `classify.interstitial` holds, else none; the label is counted per label and
rung and slows the host's rate. (Previously: no stand-in markers.) Refs: owner #58, D-1326, D-1355, D-1470.
#### Scenario: Structural challenge
- **WHEN** HTTP answers 403 with a script-only document that matches no vendor signature
- **THEN** the attempt is `blocked` with `challenge: structural`

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

### Requirement: Page artifacts from the browser rung (INV-45)
A fetch policy that asks for `screenshot` (viewport or full page, PNG) or `pdf` (print media) SHALL be fetched on the
browser rung, with no adapter or recipe, and the rung SHALL make the files from the rendered page by reading it only
(INV-42..44). A file the browser cannot make, or one over 25 MB, is left out and the fetch still stands. The files live
beside the capture's bundle, are output only (replay never reads them), and are deleted with the bundle by retention.
Enforced by: `tests/unit/test_browser_fetch.py`, `tests/db/test_output_formats.py`; active. Refs: D-1420, D-1421.
#### Scenario: Screenshot over HTTP
- **WHEN** a request asks for `screenshot` or `pdf` and the browser rung is off
- **THEN** it is refused before any job is made

### Requirement: Vendor blocks are an outcome
A fetch whose kept attempt is `blocked` with a vendor challenge label SHALL end `blocked` with reason
`challenge: <vendor>`; a worker task retries it at most once, after the back-off, and a caller that waits does not
retry it; no evasion is attempted (owner #50; master plan 2026-10-18 decision 7: managed access deferred).
#### Scenario: Vendor block in a batch
- **WHEN** a batch task's HTTP and browser attempts are both `blocked` with a vendor's label `V`
- **THEN** the task is retried once after the back-off, then ends `blocked` with `last_error` `challenge: V`
