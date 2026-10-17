## MODIFIED Requirements

### Requirement: HTTP and browser rungs
The HTTP rung SHALL use `curl_cffi` impersonating Chrome (`CRAWLERAI_IMPERSONATE`), at most 5 manual redirects, and
record headers without cookies or proxy credentials. The browser rung SHALL use Patchright's full Chromium build in
headless mode, a fresh context per fetch, one navigation, no scripted actions (a listing scrape's browser actions
excepted, below), capped by `browser_timeout_s`; it reads
the page after `load` once the DOM's structure and text are unchanged for 2 s or, for a 2xx/3xx document, the network
is idle, and keeps the main frame's latest document, following a navigation the document starts itself. A 403, 429
or 503 document that `lacks_site_structure` (`acquire/classify.py`) is first given up to 40% of `browser_timeout_s`
to navigate on, with nothing clicked or typed. The JSON rung (`fetch_json`, `httpx`, method `api`) shares the HTTP
rung's guard, caps, cookie jar and reasons. Refs: §7.1, D-0130, D-0251, D-0268, owner #49, D-1200, D-1201, owner
#50, D-1206, owner #52.
(Previously: no scripted actions, without exception.)
#### Scenario: Interstitial that navigates on
- **WHEN** a 403 document with no site structure replaces itself after more than 2 s
- **THEN** the browser rung reads the document the navigation ends on

### Requirement: Acquisition candidates stay unbuilt
The system SHALL NOT include anti-bot identities, cookie handoff, vendor strategies, residential proxies, unblockers,
CAPTCHA solving, authenticated crawls or browser actions beyond a single-URL listing scrape's (owner #52) until the
owner admits one (C13); no browser action types, submits a form, logs in or answers a CAPTCHA. Refs: §7.2, §22,
owner #52.
(Previously: browser actions were unbuilt.)

## ADDED Requirements

### Requirement: Listing browser actions
Only for a scrape that asks for them, the browser rung SHALL, after its settle, act on the item group (the
`acquire/items.py` group with the largest rendered area) through Patchright's isolated world (`crawl/paging.py`):
the hinted mechanism, else next or numbered links, a numbered pager's integer controls, scroll (two rounds), then the
visible control after the last item; it waits up to 5 s per action for new items or a new first item, keeps each
document state it would otherwise lose as a capture, and stops at `records` distinct items, at the list's end, at 40
actions or at its time cap, with the reason. A control click that changes the URL is undone and not taken as load-more.
Refs: owner #52, D-1218–D-1225.
Enforced by: `tests/unit/test_paging_browser.py` (synthetic pages per mechanism) and `tests/property/test_paging.py`;
active.
#### Scenario: Load-more control
- **WHEN** a listing shows 20 items and a button after the last one adds 20 per click, and `records` is 50
- **THEN** the run clicks it twice, stops with reason `records`, and keeps one capture holding 60 items
#### Scenario: Nothing to page
- **WHEN** a listing shows 12 items and no next link, pager, growth on scroll or control after its items
- **THEN** the run stops with reason `no_mechanism` and keeps one capture
