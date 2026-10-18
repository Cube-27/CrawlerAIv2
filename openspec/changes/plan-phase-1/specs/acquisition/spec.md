## MODIFIED Requirements

### Requirement: Browser on evidence
In `auto`, the system SHALL retry in the browser an HTTP `shell` or `blocked` result other than 429/503, and an HTTP
`error` whose reason is `network_error`, keeping the browser outcome only when `ok`; a 503 that
`classify.interstitial` judges to stand in for the page, after the site's pause (`politeness.backoff`), keeping the
browser outcome only when `ok`; and an HTTP `ok` page the caller's structural render check holds true for
(`services/scrape_steps.RenderNeed`, no extraction and no LLM): a detail page whose schema requires a `money` field and
whose capture holds no Offer entity and no `money` candidate, or a listing (`acquire/render_need.py`) whose DOM shows
fewer than `MIN_ITEMS` item blocks, whose text inside `hidden` or `display:none` containers outweighs its visible text,
or whose structured list names fewer entries than its DOM shows item blocks; that browser outcome is kept only when
`ok` and the check no longer holds. An HTTP listing shell kept with no browser outcome is `ok` when it is a shell by the
listing rule alone. Any later request of a fetch is sent only when `admit_next` allows. The browser MUST NOT be the
default. Role C runs once, on the kept capture. (Previously: a listing was rendered when its extraction, role C
included, gave no rows.)
Refs: §7.1, D-0009, D-0203, D-0865, D-0900, owner #49, D-1202, owner #54, D-1261, D-1263, D-1472, master plan
2026-10-18 §3.1.
#### Scenario: Client-rendered offer
- **WHEN** an `auto` fetch of such a detail page answers HTTP `ok` with no Offer and no price, and the browser render
  holds an Offer
- **THEN** the browser capture is kept and the result lists both attempts
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

### Requirement: HTTP and browser rungs
The HTTP rung SHALL use `curl_cffi` impersonating Chrome (`CRAWLERAI_IMPERSONATE`, else the profile nearest the
installed Patchright Chromium major, checked at startup by `acquire/impersonate.py`), at most 5 manual redirects, and
record headers without cookies or proxy credentials. The browser rung SHALL use Patchright's full Chromium build in
headless mode, a fresh context per fetch (the caller's cookies added before it navigates), one navigation, no scripted
actions (a listing scrape's browser actions and the caller's page steps excepted, below), capped by `browser_timeout_s`
(plus the steps' own timeouts); it aborts image, font and media requests by resource type, never by hostname, unless
the policy captures the page as a file or the site loads every resource (`site.load_all_resources`, set when a
resource-blocked render of its listing showed fewer item blocks than its HTTP page); it reads
the page after `load` once the DOM's structure and text are unchanged for 2 s or, for a 2xx/3xx document, the network
is idle, and keeps the main frame's latest document, following a navigation the document starts itself. A document
`classify.interstitial` judges to stand in for the page (403, 429 or 503; a script or refresh; no page of the site) is
first given up to 40% of `browser_timeout_s`, and at most 10 s, to navigate on, the wait ending at the main frame's
next commit, with nothing clicked or typed. The browser reads a body's wire size before the body. The JSON rung
(`fetch_json`, method `api`) SHALL send through the HTTP rung's client (`acquire/curl_client.py`: impersonation, guard,
caps, cookie jar, proxy pools, reasons) the headers a page's `fetch()` sends: Fetch Metadata of a CORS request,
`Referer`, `Origin`, in a `fetch()`'s order. (Previously: every resource loaded, and the interstitial wait had no
absolute bound.) Refs: §7.1, D-0130, D-0251, D-0268, owner #49, D-1200, D-1201, owner #50, D-1206, owner #52, D-1262,
D-1264, D-1265, owner #58, D-1320–D-1322, D-1325, D-1433, D-1437, master plan 2026-10-18 recommendation 12.
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

### Requirement: Structural outcome classification (INV-24)
The system SHALL classify each final response from status and structure (the classes and the shell, linkless page,
self-refreshing page and listing-shell rules in `acquire/classify.py`: a 2xx HTML page that is no shell and has no
hyperlink, or that declares a refresh and has no hyperlink to a web page, is `blocked`; a listing without repeated items
is a shell unless its structured data lists items), and from one kind of site data only: a 2xx HTML document that shows
a vendor's stand-in marker (`adapters/challenges.py`) is `blocked`. Generic code and the remembered fetch method MUST NOT
use vendor or challenge-page strings, and blocked and shell pages end with zero records. A body is decoded once at
acquisition by HTML encoding sniffing (`storage/capture_bundle.decode_html`, D-1152), and every rule reads that text.
(Previously: the rules parsed the raw bytes, and a non-UTF-8 attribute raised.) Refs: §7.1, C2, C3, D-0114, D-0932,
D-0993, D-1157, D-1158, D-1326, D-1380, D-1470, D-1471.
Enforced by: the site-literal scan (INV-03), classify and challenge tests and review; active.
#### Scenario: Status classes
- **WHEN** the final status is 410, 451 or 418
- **THEN** the class is `not_found`, `blocked` or `error` respectively
#### Scenario: Vendor stand-in served with 200
- **WHEN** a 200 HTML document shows a vendor's stand-in marker and links to pages of its site
- **THEN** the class is `blocked` with that vendor's challenge label
#### Scenario: Legacy encoding
- **WHEN** a 200 page declared `charset=euc-jp` carries non-ASCII bytes in a `meta` and an `a` attribute
- **THEN** it is classified from its decoded text without raising

### Requirement: Per-site rate and backoff
The system SHALL fetch every page and JSON request through one polite fetch (`services/polite.py`): robots.txt, then
the host's rate, then the fetch, then the observation and the back-off. It SHALL space requests to a host by
`crawl_delay_ms`, else 1 req/s, never below robots `Crawl-delay`, postponing a worker task rather than sleeping (a
caller that waits waits in place), and SHALL double a host's spacing on a 429, a 503 or a challenge (at most 15 min),
shrinking it by 10% after 20 `ok` answers in a row, never below that interval. On 429/503 it SHALL pause the host by
one rule (`acquire/politeness.backoff`): the `Retry-After`, else 30 s doubling per try, at most 15 min, a `Retry-After`
past 15 min ending the fetch `blocked`; each answer spends an attempt; a further request of a fetch (the 503
interstitial's one browser attempt) waits out that pause within the caller's bound for waiting in place (the worker's
`WAIT_MAX`, a service's one minute), and is not sent past it. (Previously: four front-ends, with three back-off
rules.) Refs: §7.1, D-0163, D-0165, D-0901, D-1263, D-1327, master plan 2026-10-18 §4 item 5.
#### Scenario: Spacing after a slow-down
- **WHEN** a host with a 1 s interval answers 429 with `Retry-After: 5`, then `ok`
- **THEN** the next request goes no sooner than 5 s after the 429, and the one after it 2 s later

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

## ADDED Requirements

### Requirement: Vendor blocks are an outcome
A fetch whose kept attempt is `blocked` with a vendor challenge label SHALL end `blocked` with reason
`challenge: <vendor>`; a worker task retries it at most once, after the back-off, and a caller that waits does not
retry it; no evasion is attempted (owner #50; master plan 2026-10-18 decision 7: managed access deferred).
#### Scenario: Vendor block in a batch
- **WHEN** a batch task's HTTP and browser attempts are both `blocked` with label `cloudflare`
- **THEN** the task is retried once after the back-off, then ends `blocked` with `last_error` `challenge: cloudflare`
