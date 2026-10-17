# Design: antibot-stack

Part B of the orchestrator's network and anti-bot research note (2026-10-17). The owner delegated the decisions of this
session (2026-10-17). The admission of anti-bot measures from §22 is owner decision #58. B1 is this change's first PR;
B2 (the site session cookie handoff) is its second.

## Decisions

### D-1320: One curl_cffi client for the HTTP and JSON rungs
- Date: 2026-10-17 · Change/PR: antibot-stack (#249) · Status: decided (owner-delegated 2026-10-17)
- `acquire/curl_client.py` holds what both rungs need (C8): the session (with #244's handle-release fix), pinning to the
  checked address or a CONNECT tunnel through the pool endpoint, the INV-30 caps, the reasons and the redirect loop
  through the guard with the fetch's `FetchCookies`. `fetch_http` and `fetch_json` differ only in their first hop and
  redirect rule. The JSON rung's httpx client and the httpcore tunnel backend from #244 are deleted.
- Tests replace the network at `Transport` (one hop to a checked target), so the guard, redirect and cookie rules still
  run in the adapter and recipe tests. The real transport is tested against local servers.
- The JSON rung's failure reasons are now curl's (`network_error: curl 7` for a refused connection or CONNECT), the
  same as the HTTP rung's.

### D-1321: Headers merge into the impersonation; JSON calls in a `fetch()`'s order
- Date: 2026-10-17 · Change/PR: antibot-stack (#249) · Status: decided (owner-delegated 2026-10-17)
- A hop's headers go to curl-impersonate, which keeps a profile header in the profile's position with the request's
  value. A `None` value removes a profile header, and other headers are appended.
- The profile describes a navigation. A JSON call therefore also sets `CURLOPT_HTTPHEADER_ORDER` to the order the
  browser rung's own Chromium uses for a script's `fetch()`, as a header echo service showed (GET and POST), and sends
  `Priority: u=1, i` (RFC 9218 urgency 1). A live check showed the same order and values as the browser's `fetch()`.

### D-1322: What a JSON call sends
- Date: 2026-10-17 · Change/PR: antibot-stack (#249) · Status: decided (owner-delegated 2026-10-17)
- Fetch Metadata §2 for a CORS request with no destination: `Sec-Fetch-Mode: cors`, `Sec-Fetch-Dest: empty`, and
  `Sec-Fetch-Site` from `page_url` to the endpoint. Same site is schemeful and uses the Public Suffix List; along a
  redirect chain the least related hop wins. `Sec-Fetch-User` and `Upgrade-Insecure-Requests` are removed, since only
  a navigation sends them.
- `Referer` follows `strict-origin-when-cross-origin`. `Origin` is sent where Fetch §3.1 sends one (cross-origin, or not
  a GET). It stays the page's origin after a cross-origin redirect: Fetch would send `null`, and a tainted origin is
  left out as a refinement nothing needs yet. A string body with no type is `text/plain;charset=UTF-8` (Fetch §5.2). A
  redirect that becomes a GET drops the body headers (Fetch §4.4 step 12). Recipe headers are applied last and win.

### D-1323: Proxy pools of several endpoints
- Date: 2026-10-17 · Change/PR: antibot-stack (#249) · Status: decided (owner-delegated 2026-10-17)
- `CRAWLERAI_PROXY_POOLS` values are a proxy URL (a one-endpoint pool, as before) or
  `{"endpoints": [...], "mode": "rotate" | "sticky"}`. `mode` is required with a list, so behaviour is never a default
  (C7). Duplicates and empty lists are refused, and error messages never echo a URL.
- `rotate` takes the available endpoints in turn. `sticky` picks by rendezvous hashing over the request's host, so a
  site moves only when its endpoint leaves the choice. The pick is per fetch, for the URL's host, so one fetch's
  redirect hops stay on one endpoint.

### D-1324: Endpoint health and quarantine
- Date: 2026-10-17 · Change/PR: antibot-stack (#249) · Status: decided (owner-delegated 2026-10-17)
- `core/proxy_health.py` keeps per-process state. After 3 consecutive failures an endpoint is quarantined for 1 min,
  doubling with each further failure up to 30 min, and one success ends the run. A failure is a `blocked` outcome, or a
  request with no answer (timeout, network error). SSRF refusals, caps and decoding errors count neither way
  (`outcome.report_proxy`). When every endpoint is quarantined, the one that recovers first is used, never a direct
  request.
- Refinement of the research note: no EWMA success rate, since nothing would read it. The browser rungs pick endpoints
  from the pool but do not report health yet: `browser.py` belongs to the network-layer batch, so this is a follow-up.

### D-1325: The impersonation target follows the browser rung's Chromium
- Date: 2026-10-17 · Change/PR: antibot-stack (#249) · Status: decided (owner-delegated 2026-10-17)
- At startup (`acquire/impersonate.rung_impersonation`, used by the worker, the API, the scheduler, `crawlerai fetch`
  and eval capture), the Chromium major is read from Patchright's `browsers.json`, without a launch.
- If `CRAWLERAI_IMPERSONATE` is unset, the target is curl_cffi's nearest desktop Chrome profile (the newer on a tie),
  with a warning when none matches exactly. If the operator set it, it is kept, with a warning when it differs.
- Today Patchright installs Chromium 153 and curl_cffi's newest profile is `chrome150`. A live check found the same
  HTTP/2 fingerprint and navigation header order, and a JA4 that differs by one TLS extension.

### D-1326: Challenge labels
- Date: 2026-10-17 · Change/PR: antibot-stack (#249) · Status: decided (owner-delegated 2026-10-17)
- Only a `blocked` or `shell` attempt gets a label. A 404 or 500 from an edge that sets bot-manager cookies on every
  response is no challenge, as the live check showed.
- The label is the first vendor whose signature the response shows (a response header name, a cookie name or prefix,
  or a challenge resource path, in `adapters/challenges.py`, C3). Without a vendor match it is `structural` when
  `classify.interstitial` holds, and none otherwise.
- INV-24 holds: the label changes neither the block class nor the remembered method. It is recorded on
  `AttemptRecord.challenge` (manifest, `capture` row, API) and counted as one log record per label and rung.
- No metrics backend exists. The eval report is left unchanged because its hidden-split cells would need the
  suppression review. Browser-rung labels are a follow-up for the same reason as D-1324.

### D-1327: Per-host adaptive rate
- Date: 2026-10-17 · Change/PR: antibot-stack (#249) · Status: decided (owner-delegated 2026-10-17)
- `HostLimiter.observe` adapts a host's spacing to a fetch's attempts, in the manner of RFC 5681 congestion control. A
  429, a 503 or a challenge label doubles the spacing, up to `BACKOFF_MAX` (15 min). After 20 `ok` answers in a row it
  shrinks by 10%, never below the site's interval and robots `Crawl-delay`. `Retry-After` pauses work as before.
- The worker (`fetch_politely`) and the services (scrape, sitemap reads, recipe and adapter requests) report what they
  fetched. Each request is observed once, on its own host: a page fetch reports only its requests to the page's host
  (`page_requests`), because its API requests were already observed on their endpoint's host (`_polite_json`). The state is per process, like the limiter's. 20 and 10% are unmeasured starting points.

### D-1328: B2 in a second PR
- Date: 2026-10-17 · Change/PR: antibot-stack (#249) · Status: decided (owner-delegated 2026-10-17)
- B1 alone is about 3,000 changed lines. B2 needs the browser rung's cookie export in `browser.py`, which the
  network-layer batch is changing now. Tasks 2.1–2.4 stay open, and the change is not archived. This PR does not apply
  the delta's INV-29 amendment, because no code implements it yet.

### D-1329: Anti-bot measures admitted from §22
- Date: 2026-10-17 · Change/PR: antibot-stack (#249) · Status: decided (owner-delegated 2026-10-17)
- Owner decision #58 records it. §22's anti-bot row is admitted for:
  - TLS and HTTP/2 impersonation on every HTTP client;
  - `fetch()`-consistent JSON calls;
  - the adaptive per-host rate;
  - proxy pools with rotation, stickiness and health;
  - challenge labels from vendor signature data;
  - (B2) the in-memory cookie handoff from a browser solve.
- Still out: CAPTCHA or Turnstile solving, clicking challenges, behaviour emulation, fingerprint spoofing or init
  scripts, real Chrome or headed browsers, custom user agents or headers in the browser, persisted cookies, logins,
  unblocker APIs and residential proxies. INV-42–INV-44 are unchanged.

### D-1350: Site sessions keyed by site and pool, pinned to the endpoint
- Date: 2026-10-17 · Change/PR: antibot-stack (#253) · Status: decided (owner-delegated 2026-10-17)
- `acquire/session.py` keeps one `SiteSession` per site and proxy pool in the process's memory (the worker's, and the
  API process's for the services that fetch). A site is `site.host`, the page URL's host, so no site ID is threaded
  through the rungs. The session keeps the endpoint its cookies were earned through and serves only requests sent
  through it: a `rotate` pool sends the site's session fetches through that endpoint, and a quarantined endpoint's
  session is not used. That is the research note's "keyed by site and proxy endpoint", with at most one live session
  per site and pool.
- It holds only the cookies of the site's registrable domain (RFC 6265 §5.1.3 domain matching, the Public Suffix List).
  A JSON request goes with the session of its page's site, and only to an endpoint in that domain. An adapter's
  platform endpoint therefore never gets it. The fetch's jar is seeded from the session (`FetchCookies.seed`), and the
  jar's own matching decides each hop.
- Cookies that the session's fetches set are not written back: the session ends within 30 min and 200 fetches anyway.

### D-1351: What the browser hands over
- Date: 2026-10-17 · Change/PR: antibot-stack (#253) · Status: decided (owner-delegated 2026-10-17)
- `Rungs.exporting` is the browser rung in its exporting form, like `Rungs.conditional` for HTTP. `acquire` uses it
  only for the browser retry after a `blocked` or `shell` HTTP attempt whose label is portable or absent, and only when
  the process keeps sessions. The rung reads `context.cookies()` before the context closes and sets nothing in the
  browser (INV-42–INV-44). A session opens only on the browser's `ok`, with at least one cookie of the domain.
- The identity is the user agent and the low-entropy client hints (`Sec-CH-UA`, `-Mobile`, `-Platform`, W3C UA Client
  Hints §3.1) that the kept document's request sent, read from the recorded request headers. Bot managers bind a
  clearance to the user agent, so the HTTP fetches send the browser rung's own user agent unchanged, `HeadlessChrome`
  included, in place of the impersonation's. The client hints go with it, so the identity stays consistent. A header that
  a hop names itself (a recipe's) still wins. Without a user agent, no session opens.

### D-1352: Portability from the signature data
- Date: 2026-10-17 · Change/PR: antibot-stack (#253) · Status: decided (owner-delegated 2026-10-17)
- `challenge.portable(label)` reads `ChallengeSignature.portable` (adapter data, C3). A structural or absent label is
  portable, and a vendor whose tokens are per-request script headers is not. For a non-portable vendor, the browser
  retry runs in its plain form and nothing is exported.

### D-1353: The remembered method while a session serves
- Date: 2026-10-17 · Change/PR: antibot-stack (#253) · Status: decided (owner-delegated 2026-10-17)
- A browser attempt that opened a session carries `AttemptRecord.site_session`, which is held in memory only and kept out
  of the manifest, the `capture` row and the API like `retry_after`. `remember_fetch_method` leaves such a site on
  `http`, so its next fetches take the HTTP rung with the session. When the session ends, the next refusal is solved in
  the browser again.

### D-1354: A session that never carried the site
- Date: 2026-10-17 · Change/PR: antibot-stack (#253) · Status: decided (owner-delegated 2026-10-17)
- A client-rendered site that sets any cookie would otherwise open a session on every fetch: HTTP shell, browser `ok`,
  new session, HTTP shell again. Each fetch would pay for both rungs, and the site would never be remembered as
  `browser`. So a session refused (`blocked` or `shell`) before it served any `ok` is dropped, and its site opens no
  other for 30 min. The browser retry of that fetch opens none, and the site is remembered as `browser`.
- A session that has served an `ok` and is then `blocked` (its clearance lapsed) is dropped, and the next solve opens a
  new one. The live check showed both cases.

### D-1355: Browser rungs report endpoint health and label challenges
- Date: 2026-10-17 · Change/PR: antibot-stack (#253) · Status: decided (owner-delegated 2026-10-17)
- This is the B1 follow-up (D-1324, D-1326). `fetch_browser` and `fetch_listing` report the pool endpoint's health with
  `outcome.report_proxy`, by the HTTP rung's rule. A listing reports its navigation.
- A `blocked` or `shell` browser document gets a challenge label. The capture records no `Set-Cookie`, so the cookie
  names come from the context's cookies, which are read once for both the label and the export.
- `core.proxy.pool_endpoint` now takes the resolved pool, so the rungs keep the pool to report to.

### D-1356: B2 completes the change
- Date: 2026-10-17 · Change/PR: antibot-stack (#253) · Status: decided (owner-delegated 2026-10-17)
- This PR applies the whole acquisition delta, including the INV-29 amendment and the remembered-method rule, and
  archives the change. Owner decision #58's row cites D-1350–D-1356.
