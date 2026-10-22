# Acquisition Specification

## Purpose

Acquisition gets pages and records what happened: the HTTP and browser rungs, outcome classification, politeness,
the SSRF guard, proxies, body bounds, per-fetch cookies and site sessions, and the capture bundle.

## Requirements

### Requirement: Pure fetch, separate persistence
The system SHALL fetch through a pure `acquire(...)` that returns a `FetchResult` (bundle, duration, at least one
attempt) and writes nothing; `store_capture` writes the bundle object before its `capture` row, and only
 `acquire/memory.py` and the re-check write the domain memory (`site_contract`, `site_block`).
Refs: §7.1, D-0144, D-0206, D-1380.

### Requirement: Rung order
The system SHALL try the detecting active adapter (only when the caller passes `send`), else the active config's API
recipe, else the page rung: `policy.method_hint` when `http`/`browser`, else the method the site's domain memory says
(`http` for a new site). Every attempt is listed in the result and manifest. Refs: §7.1, D-0090; see [adapters](../adapters/spec.md).

### Requirement: Browser on block or by field source
In `auto`, the system SHALL retry in the browser exactly the HTTP outcomes in which the server did not give the page to
this client, and keep the browser outcome only when `ok`:

| HTTP outcome | Browser retry | Kept |
|---|---|---|
| `blocked` other than 429/503 | yes | browser `ok` only |
| 503 that `classify.interstitial` judges to stand in for the page | yes, after the site's pause (`politeness.backoff`) | browser `ok` only |
| `shell` that a challenge names (`acquire/challenge.py`) | yes | browser `ok` only |
| `error` whose reason is `network_error` or `timeout` | yes (never the same transport again) | browser `ok` only |
| `shell` with no challenge (a script-only document) | yes, once per page (owner #72), after its adapter referral ([adapters](../adapters/spec.md) "Referral from a tenant's own host") serves nothing | the referral's `ok`, with no render; else browser `ok` only; else the HTTP `shell` |
| `ok`, whatever it lacks (offer, rows, a requested field) | **no** | HTTP |
| `auth_wall`, `not_found`, `soft_404`, other `error`, redirect classes | no | HTTP |

An HTTP listing shell kept with no browser outcome is `ok` when it is a shell by the listing rule alone. Any later
request of a fetch is sent only when `admit_next` allows, and no browser retry starts with less than `BROWSER_MIN_S`
(20 s) left of the task's budget (a worker task's `TASK_DEADLINE`, a scrape's `timeout_s`): the HTTP outcome is kept.
The browser MUST NOT be the default: it is also used when `method_hint` is `browser`, the block history says
browser-first, the site's contract says `browser`, or the page's fetch plan does (`acquire/rungs.FetchPlan`, from the
surface's active config alone, `config_ir/active.fetch_plan`): a running field of the config needs the render
(`needs: browser`, [learning-configs](../learning-configs/spec.md) "Locate run"), or the surface's `render_mode` is
`always`. Role C runs once, on the kept capture. Refs: §7.1, D-0009, D-0203, D-0865, D-0900, D-1202,
D-1261, D-1263, D-1472, owner #70, owner #72, architecture v3 a.3.
#### Scenario: Script-rendered offer over HTTP
- **WHEN** an `auto` fetch of a detail page answers HTTP `ok` with no JSON-LD, Open Graph tag or price
- **THEN** no browser attempt is made and the HTTP capture is kept
#### Scenario: Budget nearly spent
- **WHEN** an HTTP `shell` arrives with 15 s of the task's budget left
- **THEN** no browser attempt is made and the HTTP outcome is kept
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

### Requirement: Acquisition contract and block history
The system SHALL keep a two-tier domain memory (`acquire/memory.py`), apart because a durable strategy and a
short-lived safety bias age differently, both in Postgres so every process reads the same memory. Memory is advisory
and is learned in short transactions of its own, never in a task's (D-1786):
- An acquisition contract per site and page kind (`site_contract`; a fetch with no page kind is the detail pages'):
  the method the pages start with, the browser engine that taught it, `handoff`, and the field coverage (`found`,
  `missing`) of the last extraction with a record; the site's platform is `site.platform` ("Platform fingerprints").
  It is learned only from an `auto` fetch that tried HTTP and kept an `ok`: an HTTP `ok` teaches the default (and
  leaves a contract on HTTP as it is); a browser `ok` teaches `browser`, unless HTTP was refused, the render ran no
  browser steps, and its cookies went on to HTTP (a site session, D-1353): then it was needed only to pass the block,
  `handoff` is set and the pages stay on `http`, their later fetches carrying the site session's cookies (browser to
  HTTP only). A site's API is replayed by its learned config's API recipe alone
  ([adapters](../adapters/spec.md), "Recipe execution and fallback"), never by the contract. An unchanged contract is
  not rewritten. A contract is stale after `STALE_FAILURES` (2) consecutive caller-supplied pages extracted without a
  record, and a block (never extracted) is never one; a stale contract is kept but not used, and an extraction with a
  record makes it fresh again. A scheduler re-check SHALL retry each `browser` contract over HTTP after 7 days (the
  latest `ok` URL of that kind, with no robots.txt request) and reset it to `http` on `ok`.
- A block history per site (`site_block`): each HTTP request the site refused (`blocked` other than 429/503, or a
  `shell` a challenge names) counts, the count starting over when the last block is older than `BLOCK_TTL` (15 min);
  at `BROWSER_FIRST_BLOCKS` (2), by a fetch whose browser attempt then kept an `ok`, the site's pages start in the
  browser for one `BLOCK_TTL`; a browser attempt the site refuses too (`blocked`, or a `shell` a challenge names) starts
  no such window and ends a running one. A kept HTTP `ok` clears it.
Precedence: a job's own `method_hint` beats memory; the block history's browser-first beats the contract's method; a
fresh contract beats the default (`http`). A learned config's fetch method is the contract's
alone: a block bias it kept would outlive the block history. An `ok` page's platform
("Platform fingerprints") is recorded on `site.platform`. Refs: §7.1, D-0204, D-0205,
D-1260, D-1353, D-1380, owner plan 2026-10-19 P4 (domain memory), architecture v3 (e).
#### Scenario: Browser needed only to pass a block
- **WHEN** an `auto` fetch's HTTP attempt is `blocked`, the browser's `ok` opens a site session, and its document has
  the offer
- **THEN** the contract says `http` with `handoff`, and the site's next fetch goes over HTTP with the site session's
  cookies; in another process, an HTTP fetch the site refuses is retried in the browser, whose profile holds the
  site's cookies, and that `ok` opens the process's session
#### Scenario: Two blocks
- **WHEN** two HTTP requests to a site are refused within 15 min
- **THEN** when the browser then keeps an `ok`, its pages start in the browser until 15 min after the second, unless an
  HTTP `ok` clears the history first; when the browser is refused too, they keep starting over HTTP
#### Scenario: Stale contract
- **WHEN** two consecutive caller-supplied pages of a `browser` contract's kind are extracted without a record
- **THEN** the next fetch of that kind starts over HTTP

### Requirement: Platform fingerprints
The system SHALL tell a page's commerce platform (Shopify, Salesforce Commerce Cloud, Magento, BigCommerce,
WooCommerce, Next.js) from platform-level signals only: the platform's asset paths and script globals in the markup, and
response header names only its servers send (`adapters/platforms.py`), never from a table of sites (C4); the storefront
platforms are tried before Next.js, which may front any of them. Where a platform documents a public, tokenless product
JSON endpoint on the shop's own host (Shopify's Online Store Ajax API `/products/{handle}.js`, only on a page with the
Online Store's `Shopify.shop` global; WooCommerce's Store API `wc/store/v1/products?slug=` at the REST root the page
links to, WordPress REST API discovery), that endpoint is a detail page's data call; the other platforms are recorded
only. A platform that addresses a variant by its page URL's query states the parameter (Shopify `variant`, Salesforce
Commerce Cloud `dwvar_` prefix, WooCommerce `attribute_` prefix), by which a variant row of URLs only is still the
page's own ([variants](../variants/spec.md), "Own variants"). Refs: owner plan 2026-10-19 P4 (platform fingerprints),
P6.
#### Scenario: Headless storefront
- **WHEN** a page shows the Shopify asset CDN but not the Online Store's global
- **THEN** its platform is `shopify` and no Ajax API request is sent

### Requirement: Data calls
A data call is a request for one product's JSON made beside its page: a platform's documented product JSON
("Platform fingerprints"), or a detail API recipe's request ([adapters](../adapters/spec.md), "Recipe execution and
fallback"), the one replay of a site's API. Its answer SHALL be used only when it states the requested product (the
identity check, `acquire/identity.py`: a string or number equal to a key the request was made with, at least 4
characters, or a URL whose path is the page's path); otherwise it is dropped and its attempt is an `error`,
`not_the_product`, as an endpoint that ignores its key answers one product for every page. Every kept HTTP `ok` detail
page whose platform documents its product JSON is joined with it, always, whether or not any field is missing (a
companion call, owner #73): one request per page, sent after the page with the fetch's JSON sender (none for a page
captured as a file), waiting for the site's rate (`politeness`), an `api` attempt marked `data_call` (the platform);
an answer that passes joins the HTTP capture as one more network body marked with its platform. The extraction reads
such a body as structured evidence of the requested product, as the platform documents its members
([extraction](../extraction/spec.md), "Structured-data collectors"). A joined answer adds evidence and never replaces
the page's values. A kept HTTP `ok` page whose surface's active config has running `call` field sources is also
joined with the answer of each one's recipe ([learning-configs](../learning-configs/spec.md) "Locate run"), bound from
the page URL and documents, a header it references taken from the caller's request context (sent only to the page's
own host), sent the same way and marked `data_call: located`; its answer joins only when it states the page's product
(the identity check, with the values the request was bound with), and a recipe that binds nothing on the page sends
nothing. Refs: owner plan 2026-10-19 P4 (API replay
with a product-identity check), owner decision 2026-10-19 on #326, owner #73.
#### Scenario: Another product's answer
- **WHEN** a data call answers JSON that names neither the requested key nor the page's path
- **THEN** the answer is not joined, the attempt says `not_the_product`, and the HTTP page is kept as it is
#### Scenario: Documented answer states the offer
- **WHEN** an HTTP detail page of the Online Store states its offer and its platform's product JSON passes the identity
  check with one price for every variant
- **THEN** the answer is joined all the same, no browser attempt is made, and the price is read from both

### Requirement: Eager fragments
A kept HTTP `ok` page SHALL fetch each eager HTML fragment it declares as a companion call: a `<turbo-frame id src>`
without `loading="lazy"` (Hotwire Turbo handbook, Frames: it loads "as soon as the tag appears"), at most 8 per page,
planned by `content/fragments.py` and sent by `acquire/rungs.py` with the fetch's JSON sender as raw (no JSON parse),
with the `Accept` and `Turbo-Frame` headers the frame's own request carries. Only a `src` on the page's own site
(Fetch Metadata §2.1 same-origin or same-site) is fetched, through the SSRF guard, each request waiting for the site's
rate (`politeness`) like any further request of the fetch. Each answer's attempt is added (an `api` attempt); a 2xx
answer joins the HTTP capture as one more network body at the frame's URL, which the parse includes in the frame
([extraction](../extraction/spec.md), "Source documents"). A lazy frame, a frame on another site and a browser capture
(whose frames the browser loaded) send nothing. Refs: architecture v3 a.2 (iii), a.4 item 1.
#### Scenario: Eager and lazy frames
- **WHEN** an HTTP detail page holds `<turbo-frame id="x" src="/f">` and a frame with `loading="lazy"`
- **THEN** one companion GET of `/f` is sent and its `#x` element's children replace the frame's; the lazy frame is
  not fetched

### Requirement: HTTP and browser rungs
The HTTP rung SHALL use `curl_cffi` impersonating Chrome (`CRAWLERAI_IMPERSONATE`, else the profile nearest the
installed Patchright Chromium major, checked at startup by `acquire/impersonate.py`), at most 5 manual redirects, and
record headers without cookies or proxy credentials, within `timeout_s` (10 s by default). The browser rung SHALL use Patchright's full Chromium build in
headless mode, one Playwright driver per process shared by its page fetches (worker, API, scheduler) with at
most `BROWSER_CONTEXTS` (2) of them rendering at once (`acquire/shared_browser.py`; a listing scrape with browser actions
renders in it too, holding one of them, and its render ends as a page's does: classified with the redirect rules, its
challenge labelled, its `blocked` profile deleted, the site's sessions and the pool endpoint told), the browser's user
agent read once per process, each site profile's browser a process of its own (one that crashes ends only its own page;
the driver is restarted only when it disconnects), each page in a tab of its own, one navigation, no scripted
actions (a listing scrape's browser actions and the caller's page steps excepted, below), capped by `browser_timeout_s`
(plus the steps' own timeouts).

Profiles (owner #50 as amended 2026-10-21, `acquire/browser_profiles.py`): a site's pages render in a persistent
Chromium profile of the site's own (`launch_persistent_context`, no incognito context), one per registrable domain,
proxy pool and endpoint, kept under `CRAWLERAI_BROWSER_PROFILES` across jobs and processes (unset: a profile lasts
while its browser is open; deleting the directory resets every profile), its directory named by a digest, never by
the host. A profile renders one page at a time and is opened by one process at a time (an OS file lock); a page whose
profile is held elsewhere, and a fetch with the caller's cookies (added before it navigates), get a temporary profile,
deleted when it closes. At most `_OPEN_PROFILES` (2) are open in a process, rendering or idle (the least recently used
idle one closed first); an idle one closes after 60 s, all close with the session, one whose page ended with an
error or a 4xx/5xx document closes, and a profile whose page was `blocked` is deleted; a temporary profile is never
kept in a site profile's place. Before each launch a kept profile's HTTP cache and service workers (with their Cache
Storage) are deleted, so no capture is served from an earlier job's visit; cookies and storage stay. The
profile's preferences get Chromium's WebRTC IP handling policy `disable_non_proxied_udp` (non-proxied UDP and
multiple routes off), so WebRTC sends no UDP around the guard (INV-16). Every connection of the profile's browser,
its own background requests included, goes through the guard.

No request interception: the browser rung SHALL NOT route, abort or block a page's requests (no `route`, no CDP
`Network.setBlockedURLs`), so every request the page makes loads as in a user's browser. Playwright's request routing
turns the HTTP cache off, which makes every request carry `Cache-Control: no-cache` and `Pragma: no-cache`, a header
pair no user's browser sends on a first load.

The ready wait, the one wait for a page, a fixed condition: the page is read once it has fired `DOMContentLoaded` and
(a) every endpoint the surface's located `call` field sources name (`FetchPolicy.ready_calls`, from the fetch plan) has
answered in full, else (b) no data call has been in flight for `_STEP_QUIET_S` (0.5 s); a listing is read when the wait
ends (its item-area read). The rendered document is read with its open shadow roots: `Element.getHTML` with
`serializableShadowRoots` and every open root found by walking `shadowRoot`, run with `evaluate` in Patchright's
isolated world (no init script), giving declarative `<template shadowrootmode="open">` markup; closed roots stay out.
The wait ends `READY_MAX_S` (3.5 s) after `load` whatever is still in flight (before `load`, only the 90% bound below
ends it), and what is there is read; a document the main frame navigates
to meanwhile (not a same-document navigation) starts it over, within 90% of `browser_timeout_s`, so the capture is the
final document. A page step that changes the page is followed by the same wait for the data calls it started (3 s at
most). A ready document
`classify.interstitial` judges to stand in for the page (it can navigate itself, by a script or refresh, and is either
a 403, 429 or 503 that is no page of the site, or a rendered 2xx document that is a shell or links nowhere: a check
served with success that reloads once passed) is then given until 40% of `browser_timeout_s` from the fetch's start,
and at most 10 s, to navigate on, the wait ending at the main frame's next commit, with nothing clicked or typed, and
the document it navigates to read once ready. Over HTTP no script runs, so the 2xx case is the browser's only. A 2xx
page that renders itself by script is judged as rendered; one that stays a shell costs that bound once. The browser reads a body's wire size before the body. The JSON rung
(`fetch_json`, method `api`) SHALL send through the HTTP rung's client (`acquire/curl_client.py`: impersonation, guard,
caps, cookie jar, proxy pools, reasons) the headers a page's `fetch()` sends: Fetch Metadata of a CORS request,
`Referer`, `Origin`, in a `fetch()`'s order. Refs: §7.1, D-0130, D-0251, D-0268, owner #49, D-1200, D-1201, owner #50,
D-1206, owner #52, D-1262,
D-1264, D-1265, owner #58, D-1320–D-1322, D-1325, D-1433, D-1437, master plan 2026-10-18 recommendation 12, owner
plan 2026-10-19 (crawl speed, P2 browser wait and blocking).
#### Scenario: Interstitial that navigates on
- **WHEN** a 403 document with no site structure replaces itself after more than 2 s
- **THEN** the browser rung reads the document the navigation ends on
#### Scenario: Check served with 200 that reloads
- **WHEN** a 200 document with no links and little text, holding a script, navigates itself after the ready wait ended
- **THEN** the browser rung waits for the navigation and reads the document it ends on
#### Scenario: Refusal that cannot navigate
- **WHEN** a 403 document has no script and no refresh
- **THEN** the browser rung does not wait for a navigation
#### Scenario: Images not loaded
- **WHEN** a page loads an image, a font and a JSON call, and the policy captures no file
- **THEN** the image and font requests are aborted and the JSON call is answered
#### Scenario: Tracker blocked, challenge loaded
- **WHEN** a page loads a script from a server the tracking list names and a vendor's challenge script whose host a
  list also names
- **THEN** the tracker request is aborted and the challenge script loads
#### Scenario: Tag manager loaded, its pixels blocked
- **WHEN** a page loads a tag manager's container, which loads an analytics endpoint and a fraud vendor's
  fingerprinting script, all on listed servers
- **THEN** the container and the fingerprinting script load and the analytics request is aborted
#### Scenario: Data call answered after load
- **WHEN** a detail page's only data call ends 1 s after `load`
- **THEN** the page is read 0.5 s after that call ended, not at `READY_MAX_S`
#### Scenario: Second page of a site in a job
- **WHEN** a job's second page of a site renders after its first passed a challenge
- **THEN** it renders in the first page's context, holding the cookies the challenge set
#### Scenario: Cross-site JSON call
- **WHEN** a page on `https://jobs.example.com/` has its JSON fetched from `https://api.example.net/`
- **THEN** the request carries `Sec-Fetch-Site: cross-site`, `Sec-Fetch-Mode: cors`, `Origin: https://jobs.example.com`
  and no `Sec-Fetch-User`

### Requirement: Network body capture
The browser rung SHALL save, from any origin and in arrival order, the bodies of
fetch, XMLHttpRequest and document responses (not the main frame's navigation) that are JSON by media type, React
Server Components Flight payloads (`text/x-component`, `storage.capture_bundle.is_flight`) or, labelled `text/plain` or
not at all, whose bytes are an RFC 8259 object or array (a guard prefix of at most 16 characters stripped,
`storage.capture_bundle.network_json`), and the 2xx HTML answers (`text/html`, `application/xhtml+xml`) of fetch and
XMLHttpRequest calls to the page's own site (HTML §7.1.1): the fragments the page fetches (Turbo frames, htmx-style
partials), which the page tree reads ([extraction](../extraction/spec.md), "Source documents"); each with its request's method, body and cookie-free headers, the cookie-free
response headers, the resource type and the count of browser actions before it, within the caps in `acquire/browser_capture.py`,
which apply to all captured bodies together. A data call, which the ready wait ("HTTP and browser rungs") waits for, is a fetch or
XMLHttpRequest call to the page's own site (HTML §7.1.1) or one whose `Accept` names a JSON MIME type or
`text/x-component`, so another site's beacons and pings hold no read. Refs: architecture v3 a.3, §7.2, Appendix A #59,
D-0010, D-0540, D-1311, D-1312, D-1369, owner plan 2026-10-19 (crawl speed).
#### Scenario: JSON under another label
- **WHEN** a page fetches `)]}'` and a JSON object labelled `text/plain`, and a text/plain body that is no JSON
- **THEN** the first is kept as received and the second is not
#### Scenario: Flight payload
- **WHEN** a page fetches a body labelled `text/x-component`
- **THEN** it is kept as received with its content type, within the same caps as the JSON bodies
#### Scenario: HTML fragment
- **WHEN** a page fetches an HTML answer from its own site, and one from another site
- **THEN** the first is kept with its content type and resource type, within the same caps, and the second is not

### Requirement: Structural outcome classification (INV-24)
The system SHALL classify each final response, before extraction, from status and structure (the classes and the shell,
linkless page, self-refreshing page and listing-shell rules in `acquire/classify.py`: a 2xx HTML page that is no shell
and has no hyperlink, or that declares a refresh and has hyperlinks but none to a web page (even one short enough to be
a shell), is `blocked`; a listing is a shell unless its structured data lists items or a group of its repeated items
shows `MIN_ITEMS` blocks with more than a link (an image, or text in two or more runs) and copies no navigation, as the
item layer requires of a group (listings spec, "Rows from blocks"; a tag cloud, a pager or the menu's category tiles
lists no items, so the browser renders the grid a script fills); a 401 is
`auth_wall`), and from one kind of site data only: a 2xx HTML document that shows a vendor's stand-in marker
(`adapters/challenges.py`) is `blocked`. A block needs corroboration and usable content beats it: a 403, or a 2xx
document with a stand-in marker, that carries the page's structured data (`classify.usable_content`: a schema.org
Product with offers, an OGP product price, a microdata Product with offers; on a listing the items its structured data
lists) is `ok`. A 2xx answer whose media type is not HTML (`text/html`, `application/xhtml+xml`; a response without a
declared type is sniffed as HTML) is `unsupported_media`: no reader reads it and it gets no browser attempt. A 451
(RFC 7725) is `blocked` with the challenge label `legal`, which names no vendor, and its task ends `geo_blocked`. A 2xx
page fetched as a detail or listing page that a redirect (`classify.Redirect`) led away from the
page asked for (another host or path past a BCP 47 locale segment) is `geo_redirect` when the answering URL names
another region (a BCP 47 region subtag in its first path segment, else a two-letter ccTLD, RFC 1591) and another path,
`soft_404` when it is a site's or an edition's root, and, for a detail page, `redirected_to_listing` when it lists items,
states no product and its path does not keep the asked path's last segment as a word (a slug added); a fetch of no page
kind (a crawl's page) is never classed by its redirect. A redirect to a page whose query carries the asked path, as
given or base64-encoded (RFC 4648), is an interstitial that sends the client back once passed: `blocked`. These classes are the
transport outcome (the capture's `block_class`); a page in any of them yields zero records and ends its task with the
same-named outcome (a 451's `blocked` with `geo_blocked`), never as a page without a price.
Generic code and the remembered fetch method MUST NOT use vendor or challenge-page strings, and blocked and shell pages
end with zero records. A body is decoded once at acquisition by HTML encoding sniffing
(`storage/capture_bundle.decode_html`, D-1152; a JSON body as UTF-8, RFC 8259 §8.1, whatever charset it is labelled
with), and every rule reads that text.
Refs: §7.1, C2, C3, D-0114, D-0932,
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
#### Scenario: Non-HTML answer
- **WHEN** a page's HTTP fetch answers 200 with `Content-Type: application/pdf`
- **THEN** the class is `unsupported_media`, no browser attempt is made, and the task ends `unsupported_media`
#### Scenario: Refused for legal reasons
- **WHEN** a page's HTTP fetch answers 451
- **THEN** the class is `blocked`, the attempt's challenge label is `legal`, and the task ends `geo_blocked`
#### Scenario: Listing showing only the menu's tiles
- **WHEN** a listing's HTTP answer has text and links, no structured data, and its only repeated blocks are category
  tiles with images leading where its `nav` leads, or bare links with one label each
- **THEN** the class is `shell`, and the browser renders it

### Requirement: Error outcomes and reasons
Every exception in a rung SHALL become an `error` attempt with a reason (`timeout`, `body_cap`, `network_error`, ...)
never containing the URL; it stores no body but keeps the last status and headers. A fetch whose kept attempt is a
`timeout` ends its task with outcome `timeout` ([jobs](../jobs/spec.md), "Page outcomes"). Refs: §7.1, D-0127, D-0128.

### Requirement: Bounded bodies (INV-30)
The system SHALL bound untrusted bodies by `max_body_bytes` (compressed) and `max_decompressed_bytes` while streaming,
on every rung, before anything is kept; an oversize body MUST be `error`/`body_cap` with no capture body. A browser
capture keeps at most 10 MB of network bodies in all (`acquire/browser_capture.py`), each read only once its request is done:
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
is `error`/`ssrf_rejected`, never retried. The check splits in two: the URL's form (`SafeConnector.check_form`: scheme, port, host
form, IDNA, a literal address public), which needs no DNS and is all a multi-URL submission checks (rest-api), and the
host's resolution (`dns`, `private_address`), which the fetch checks before it connects. Enforced by: SSRF tests with a stub
resolver and pool tests over every endpoint; active. Refs: §7.1, §18, D-0115, D-0249, D-1323.
#### Scenario: Redirect to a private address
- **WHEN** `https://example.com/` answers 302 to a host resolving to 10.0.0.5
- **THEN** the hop is rejected with `ssrf_rejected` and nothing is fetched from it

### Requirement: Proxy pools
A request's `fetch.proxy_pool` SHALL be used from `CRAWLERAI_PROXY_POOLS` (a proxy URL, or endpoints with mode
`rotate` or `sticky`) over a CONNECT tunnel by every rung, which reports each fetch's endpoint health; an endpoint
failing 3 times in a row SHALL be left out for a quarantine doubling from 1 to 30 min (`core/proxy_health.py`), and a pool never sends
direct. An unknown pool MUST end `error`/`proxy_pool_unknown` sending nothing, and credentials never appear in errors.
Each attempt records the bytes it moved (the HTTP and JSON rungs' HTTP messages, CONNECT included; the bytes the
browser's guard relayed), counted as `proxy_bytes` usage of the pool for a fetch through one. A learning run's recipe
replays go direct. Refs: §7.1, D-0282, D-0286, D-1264, D-1323, D-1324,
D-1355, D-1381.

### Requirement: Egress country
A record SHALL state the country its page was fetched from (`record.egress_country`, ISO 3166-1 alpha-2, null when
unknown) and how that is known (`record.egress_basis`): `pool` for a fetch through a proxy pool that declares its
`country` (`CRAWLERAI_PROXY_POOLS`: `{"endpoints": [...], "mode": ..., "country": "GB"}`, one country per pool), `machine`
for a direct fetch from the machine whose country the operator declares (`CRAWLERAI_EGRESS_COUNTRY`), else `unknown`; a
pool that declares no country is `unknown`, never the machine's. Nothing is looked up from an address (`core/egress.py`).
Refs: owner plan 2026-10-19 P8.
#### Scenario: Pool with a country
- **WHEN** a job's pages go through a pool declaring `GB`
- **THEN** its records have `egress_country` `GB` and `egress_basis` `pool`

### Requirement: Cookies stay inside one fetch (INV-29)
Each fetch SHALL have its own HTTP session or browser context; cookies live in a per-fetch jar matched per RFC 6265
(public-suffix `Domain` ignored), are sent only on matching hops and are discarded at the end; the caller's cookies
(`RequestContext`) seed only that fetch's jar or context, for the fetched URL's host. Three cookie stores outlive a
fetch, under one cookie rule (owner #76: challenge and clearance cookies are kept and replayed like any other): a site's
browser profile ("HTTP and browser rungs", profiles), the browser's own cookie store, which keeps the cookies and
storage the site's pages gave the browser for that site's later pages through the same pool endpoint, in any job and
process, never for a fetch with the caller's cookies, and is handed to the HTTP rung only as a site session; the site
session (`acquire/session.py`); and the stored cookie state (next requirement). A site session is the cookies of the
site's registrable domain that a browser `ok` held after a `blocked` or `shell` HTTP attempt, challenge and clearance
cookies included (owner #76), read without change; keyed by that registrable domain and pool, it seeds later HTTP and
JSON fetches of the site in that domain through the same pool endpoint, and the site's temporary profiles on a direct
route (a pooled context picks its own endpoint; a kept profile holds its own cookies), in process memory, for at most 30
min and 200 fetches; `blocked` drops it, as does a `shell` before any `ok`; a site whose sessions keep being refused
starts in the browser (block history, above). The HTTP and JSON rungs send a session's cookies with their own identity
headers (the impersonation's user agent and client hints), never the browser's: those would pair a browser's user agent
with curl's TLS and HTTP/2 fingerprint. No cookie is logged or captured. Enforced by: cross-fetch, cross-site,
cross-domain, cross-proxy, expiry, no-persistence and caller-cookie tests; active. Refs: §7.1, D-0321, D-0884, D-0902,
owner #58, D-1350–D-1353, D-1433, owner plan 2026-10-19 P2, owner #76.
#### Scenario: Next fetch to the same host
- **WHEN** fetch A receives `Set-Cookie` from `example.com` and fetch B then requests `example.com`, with no site session
  and no stored cookie state
- **THEN** fetch B sends no cookie
#### Scenario: Site session on another site
- **WHEN** `shop.example.com` has a site session and a fetch requests `www.example.org`
- **THEN** the fetch sends none of the session's cookies

### Requirement: Stored cookie state
The on-disk site profile is the browser's cookie state ("HTTP and browser rungs", profiles); its directory holds
Chromium's cookies in plaintext, under the operator-managed `CRAWLERAI_BROWSER_PROFILES`. With `CRAWLERAI_COOKIE_KEY`
set, the system SHALL also keep, per registrable domain and browser engine (`patchright`), the cookies of that domain
that a temporary profile's browser context held after an `ok` page on a direct route, in `site_cookie_state`,
encrypted (Fernet) and rewritten only when the HMAC fingerprint of the plain state changes; a kept profile writes
none. Only cookies are kept: no other storage; challenge and clearance cookies are kept with the rest (owner #76).
Before a write and after a load, cookies with an empty value or past their expiry are dropped; cookies are
de-duplicated by name, domain and path; session cookies stay; a state with nothing left is not written and drops the
kept one. A direct browser `ok` also refreshes the site's live session with its cookies (one holding none of the
domain's drops it). A `shell`, `blocked` or `error` outcome writes nothing, and a `blocked` browser fetch of the site
on a direct route clears its state. The state is read only when a temporary profile of the site opens (no profile
directory configured, or the site's profile held by another process or fetch), which starts with its live site
session's cookies, else the stored state; never per fetch, never by a kept profile, and never by an HTTP or JSON fetch, which takes only the live session. No cookie an HTTP
response sets is kept or handed to the browser. The stored state serves and is written by direct fetches only (no
proxy pool); a fetch with the caller's context neither reads nor writes it. Refs: owner 2026-10-19 (acquisition plan
P2), owner #76.
#### Scenario: A temporary profile loads the state
- **WHEN** a browser fetch of `shop.example.com` in a temporary profile ends `ok` holding `session=1` and
  `cf_clearance=x`, and a later job's temporary profile of `www.example.com` opens
- **THEN** it starts with `session=1` and `cf_clearance=x`
#### Scenario: A kept profile leaves the state alone
- **WHEN** a browser fetch of a site in its kept profile ends `ok`
- **THEN** the stored state is neither read nor written
#### Scenario: Block clears the state
- **WHEN** a browser fetch of a site with stored state ends `blocked` on a direct route
- **THEN** the site has no stored state, and nothing is written

### Requirement: robots.txt
The system SHALL NOT read or obey robots.txt unless the request switches it on with `respect_robots: true` (the
`fetch` member of scrape, batch, crawl, extract and search, and of their schedules; a member of map), owner decision
#75. Off, no robots.txt request is made and neither a disallow nor its `Crawl-delay` applies; a fetch that has no
request (a learning replay or render, the method re-check) goes by the default. On, it SHALL honour robots.txt per
RFC 9309 for user agent `*`, cached per origin for 24 h in `site.robots_snapshot`; a disallowed URL is
`blocked`/`robots` without a request, an unreachable one (5xx or 429) ends `blocked`/`robots_unreachable`, and its
`Crawl-delay` feeds the host's rate. A page an adapter would serve is not held back by its own robots.txt: the
adapter's request obeys its host's robots.txt, the page rungs are not admitted, and an adapter answer that is not `ok`
ends `robots`. Either way, a crawl or map that reads sitemaps reads robots.txt for its `Sitemap:` lines alone
(`crawl/sitemaps.py`). Refs: §7.1, D-0159, D-0866, D-1155, D-1156, owner decision #75.

### Requirement: Per-site rate and backoff
The system SHALL fetch every page and JSON request through one polite fetch (`services/polite.py`): robots.txt, then
the host's rate, then the fetch, then the observation and the back-off; a robots.txt request takes a turn and holds the
host as a page's does (a worker postpones a fetch that has sent nothing, and once robots.txt was requested waits in place
for the page's turn up to its bound). It SHALL space requests to a host by
1 req/s, never below robots `Crawl-delay` when robots.txt is obeyed, postponing a worker task rather than sleeping (a
caller that waits waits in place up to one minute, a turn further off answering `blocked`, reason `slow_down`, with
nothing sent); SHALL hold the host from a fetch's turn until the fetch ends and its answers are observed (a back-off stored), browser navigations included, so no two
fetches are in flight to one host (a navigation and the resources its page loads are one fetch) (owner plan 2026-10-19, P1), and admit no request for work being
cancelled. A process with the database shares the turns and holds with every other (`host_turn`, `acquire/host_turns.py`):
a turn and its hold are taken in one statement, and a hold is a 1-minute lease its process renews while the fetch runs
and gives up as the fetch is cancelled, so a process that dies holds a host at most that long; the scheduler deletes rows whose turn is due and that no lease holds (`expire_host_turns`). It SHALL double a host's spacing on a 429, a 503 or a challenge (at most 15 min),
shrinking it by 10% after 20 `ok` answers in a row, never below that interval. On 429/503 it SHALL pause the host by
one rule (`acquire/politeness.backoff`): the `Retry-After`, else 30 s doubling per try, at most 15 min, a `Retry-After`
past 15 min ending the fetch `blocked`; each answer spends an attempt; a further request of a fetch (the 503
interstitial's one browser attempt) waits out that pause within the caller's bound for waiting in place (the worker's
`QUEUED` bound, a third of the task deadline; a service's one minute), and is not sent past it. Refs: §7.1, D-0163,
D-0165, D-0901, D-1263, D-1327, master plan 2026-10-18 §4 item 5.
#### Scenario: Spacing after a slow-down
- **WHEN** a host with a 1 s interval answers 429 with `Retry-After: 5`, then `ok`
- **THEN** the next request goes no sooner than 5 s after the 429, and the one after it 2 s later

### Requirement: Capture contents and the fetch CLI
A capture SHALL hold the body, network JSON bodies and a manifest (headers, timings, block class, attempts,
`page_kind`, and for a browser capture of a listing the rendered area of each block of its repeated item groups by
element path, `item_areas`, at most 2,000 blocks), with usage counted per attempt; `crawlerai fetch URL --out` writes a
bundle and exits 0 whenever one is written.
Refs: §15, D-0146, D-0250, owner #67.

### Requirement: Acquisition candidates stay unbuilt
The system SHALL NOT include residential proxies, unblockers, CAPTCHA solving, challenge clicking, behaviour emulation,
fingerprint spoofing or real Chrome until the owner admits one (C13); an authenticated crawl runs only on the caller's
own cookies or headers (above), and browser actions are a single-URL listing scrape's (owner #52) and the caller's page
actions (above); no action logs in, enters a credential or answers a CAPTCHA. Refs: §7.2, §22, owner #52, owner #58,
owner delegation
2026-10-17, D-1432, D-1438.

### Requirement: Patchright's documented browser setup (INV-42, INV-43, INV-44)
The browser rung SHALL follow the Patchright README's setup (owner #50): INV-42, it launches Patchright's full
Chromium build (`channel="chromium"`, installed with `patchright install --no-shell chromium`), never the headless
shell; INV-43, it runs in a persistent profile (`launch_persistent_context`) with Playwright's fixed
1280x720 viewport (owner #50 as amended 2026-10-21; the README's `no_viewport` leaves headless Chromium's 800x600
window) and no launch argument (no flag Patchright removes, none that changes the fingerprint, never
`--user-agent`; the guard's WebRTC policy is a profile preference, "HTTP and browser rungs", profiles); INV-44, no
context, page or CDP call sets client hints, extra headers or init scripts, and `evaluate` runs only in Patchright's
isolated world. The one identity change is the context's `user_agent` (owner #71 as amended 2026-10-21): the
browser's own user agent, read once per driver from a browser started with no page (`Browser.getVersion`, its
background requests sent to a closed loopback port), with only the `HeadlessChrome/` token replaced by `Chrome/`. The
page's and dedicated workers' `navigator.userAgent` and the request header then name `Chrome`, and the client hints
stay the browser's own (brands, `fullVersionList`, platform). Service and shared workers keep `HeadlessChrome` in
`navigator.userAgent`, and a service worker's `navigator.userAgentData` reports no brands or full versions, because
Playwright applies the override to a service worker's requests only; that is a known gap, not a goal. The context's `locale` and
`timezone_id` are the request's (`FetchPolicy.locale_hint`, `acquire/locality.py`): the locale as a BCP 47 tag, and
the IANA tz database's zone of its region (`zone1970.tab`) when the region has one, else none. Refs: owner #50, owner
#71 as amended 2026-10-21, D-1204, D-1205, owner plan 2026-10-19 P8, architecture v3 a.3.
Enforced by: `tests/unit/test_browser_setup.py` (launch and context options, source scan); active.

### Requirement: Listing browser actions
For a scrape that asks for them, and by default for a single-URL listing scrape asking for `records` in `auto` whose
page is rendered (never for batch or crawl), the browser rung SHALL run the caller's `fetch.actions`
and `wait_for` on the settled page first (the site's API recipe is not used then), and then act on the item group (the
`acquire/items.py` group with the largest rendered area; on a page with no linked items, the rows of the first series
of its latest data calls, `collect/network_match.py`) through Patchright's isolated world (`crawl/paging.py`): the
hinted mechanism, else next or numbered links, a numbered pager's integer controls, scroll (two rounds), then the
visible control after the last item; it waits up to 5 s per action for new items or a new first item, keeps a document
state before each page turn, and before each scroll or control click a state it drops again when the state after still
shows all its items, and stops at `records` distinct items (100 by default), at the list's end, at 40 actions or at its
time cap, with the reason. A control click that changes the URL is undone and not taken as load-more. Refs: owner #52,
D-1218–D-1225, D-1404, D-1405, D-1513, master plan 2026-10-18
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
rung and slows the host's rate. Refs: owner #58, D-1326, D-1355, D-1470.
#### Scenario: Structural challenge
- **WHEN** HTTP answers 403 with a script-only document that matches no vendor signature
- **THEN** the attempt is `blocked` with `challenge: structural`

### Requirement: Caller request context
A fetch policy MAY carry the caller's headers and cookies (`acquire/types.py` `RequestContext`): the HTTP and JSON rungs
SHALL send the headers only on requests to the fetched URL's host and seed the fetch's jar with the cookies as
host-only cookies of that host; the browser rung SHALL add the cookies to its context before the navigation and set no
header (INV-44). A fetch with a caller context neither takes nor opens a site session, and its values are never
captured or logged (manifests and recorded headers show `**********`). The policy a capture keeps SHALL carry, beside
the names, the HMAC-SHA256 digest of the names and values (`core/context_digest.py`, keyed by a key derived from
`CRAWLERAI_COOKIE_KEY`, else a random key of the process), and a stored capture SHALL stand for a fetch only when that
digest is equal: a capture fetched with other values under the same names, or with no context, never serves a fetch
with one, nor the reverse. Refs: owner delegation 2026-10-17,
owner 2026-10-21, D-1430–D-1434.
#### Scenario: Header to another host
- **WHEN** a fetch with header `Authorization` is redirected from `https://a.example/` to `https://b.example/`
- **THEN** the request to `b.example` carries no `Authorization`, and the capture records none of its value
#### Scenario: Another cookie value
- **WHEN** a page was captured with cookie `sid=alice` and a `fetch.cache` `only` request sends `sid=bob`
- **THEN** that capture does not serve it, and the request fails `not_cached`

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
