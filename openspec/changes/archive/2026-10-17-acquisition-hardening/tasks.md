# Tasks: acquisition-hardening

## 1. Remembered method

- [x] 1.1 `remember_fetch_method` sets `browser` for a browser `ok` kept over any HTTP attempt of the fetch (a render
  kept over a lacking HTTP `ok` included), with a DB test that the next fetch skips HTTP. (#244)

## 2. Listing shell as the last page

- [x] 2.1 `acquire` keeps an HTTP listing shell (listing rule only) as `ok` when no browser outcome is kept: render
  failed, not admitted, or no render; tests per case. (#244)

## 3. Slow-down and interstitials

- [x] 3.1 `Admit` takes the pause the site asked for; `HostLimiter.wait`, the worker's and the services' admission
  honour it within their bounds; `asked_pause` is the one Retry-After-else-first-backoff rule. (#244)
- [x] 3.2 `classify.interstitial`: status, can navigate (script or refresh), no page of the site; tests per case. (#244)
- [x] 3.3 A 503 interstitial at HTTP gets one browser attempt after the pause; a static 503 and any 429 get none. (#244)
- [x] 3.4 The browser waits for the next main-frame commit by event; a refusal that cannot navigate is not waited on;
  browser tests for a static refusal and a refreshing refusal with links. (#244)

## 4. Proxy and body bounds

- [x] 4.1 `fetch_json` honours the policy's proxy pool through CONNECT tunnels (`acquire/tunnel.py`, shared with the
  browser's guard); unknown pool refused; tests through a stub proxy. (#244)
- [x] 4.2 The browser reads the navigation body's and each JSON body's size before the body. (#244)
