# Delta: acquisition

## MODIFIED Requirements

### Requirement: HTTP and browser rungs
The HTTP rung SHALL use `curl_cffi` impersonating Chrome (`CRAWLERAI_IMPERSONATE`), at most 5 manual redirects, and
record headers without cookies or proxy credentials. The browser rung SHALL use Patchright's full Chromium build in
headless mode, a fresh context per fetch, one navigation, no scripted actions, capped by `browser_timeout_s`; it reads
the page after `load` once the DOM's structure and text are unchanged for 2 s or, for a 2xx/3xx document, the network
is idle, and keeps the main frame's latest document, following a navigation the document starts itself. A 403, 429
or 503 document that `lacks_site_structure` (`acquire/classify.py`) is first given up to 40% of `browser_timeout_s`
to navigate on, with nothing clicked or typed. The JSON rung (`fetch_json`, `httpx`, method `api`) shares the HTTP
rung's guard, caps, cookie jar and reasons. (Previously: Patchright headless Chromium; every 4xx document read after
2 s of DOM quiet.) Refs: §7.1, D-0130, D-0251, D-0268, owner #49, D-1200, D-1201, owner #50, D-1206.
#### Scenario: Interstitial that navigates on
- **WHEN** a 403 document with no site structure replaces itself after more than 2 s
- **THEN** the browser rung reads the document the navigation ends on

## ADDED Requirements

### Requirement: Patchright's documented browser setup (INV-42, INV-43, INV-44)
The browser rung SHALL follow the Patchright README's setup (owner #50): INV-42, it launches Patchright's full
Chromium build (`channel="chromium"`, installed with `patchright install --no-shell chromium`), never the headless
shell; INV-43, its only launch argument is the guard's WebRTC policy (no flag Patchright removes, none that changes
the fingerprint); INV-44, no context, page or CDP call sets a user agent, client hints, extra headers or init scripts,
and `evaluate` runs only in Patchright's isolated world. Refs: owner #50, D-1204, D-1205.
Enforced by: `tests/unit/test_browser_setup.py` (launch and context options, source scan); active.
