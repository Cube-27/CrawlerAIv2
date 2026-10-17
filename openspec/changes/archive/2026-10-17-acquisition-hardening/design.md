# Design: acquisition-hardening

Six acquisition follow-ups of `openspec/backlog.md` (#52, #64, #225, #228, #229, #242). The owner delegated this
session's decisions (2026-10-17); the policy they add beside owner decisions #49, #50 and #54 is owner decision #56.

## Decisions

### D-1260 — Remember `browser` after a render kept over a lacking HTTP page
- Date: 2026-10-17 · Change/PR: acquisition-hardening (#244) · Status: decided (owner-delegated 2026-10-17)
- `remember_fetch_method` sets `site.fetch_method='browser'` for any browser `ok` kept over an HTTP attempt of the same
  fetch, so a site whose pages need the render (owner #49 offers, #54 listing rows) stops paying HTTP plus browser
  on every fetch (#228). Per site, as the column is (no migration this wave); the 7-day re-check returns it to HTTP
  and a later render sets it again. A render that holds no more than HTTP leaves the site on HTTP.

### D-1261 — An HTTP listing shell kept with no browser outcome is the last page
- Date: 2026-10-17 · Change/PR: acquisition-hardening (#244) · Status: decided (owner-delegated 2026-10-17)
- When the render fails, is not admitted or is not tried, the HTTP page is the fetch's last page; as the browser's is
  extracted whatever its links (`browser.classified`), a shell by the listing rule alone (site structure, no repeated
  items) is kept as `ok` and extracted, so role C's rows from it are kept (#225). A shell without site structure stays
  a shell; the attempt keeps `shell`.

### D-1262 — Interstitials judged by structure; event-driven commit wait
- Date: 2026-10-17 · Change/PR: acquisition-hardening (#244) · Status: decided (owner-delegated 2026-10-17)
- `classify.interstitial`: a 403/429/503 HTML document that can navigate itself (a `script`, a `meta http-equiv=refresh`
  or a `Refresh` header; HTML Standard §4.2.5.3, §7.11.1) and is no page of the site (a refresh, no site structure,
  or no hyperlink to another page of its host). A refusal with neither script nor refresh can never replace itself
  and is not waited on, which removes the 18 s from static 403s (#229). The wait ends on the main frame's next commit
  (an event, not a 0.25 s poll); `_INTERSTITIAL_SHARE` stays 0.4 until a dev run shows challenges that clear later.

### D-1263 — One browser attempt for a 503 interstitial, after the site's pause
- Date: 2026-10-17 · Change/PR: acquisition-hardening (#244) · Status: decided (owner-delegated 2026-10-17)
- A 503 that `interstitial` judges to stand in for the page gets one browser attempt (#225); `Admit` takes the pause
  (`asked_pause`: `Retry-After`, else the first backoff, `BACKOFF_MIN`), which pauses the host's limiter first, so
  other requests to the host wait too. Bounds: the worker's `WAIT_MAX`, a service's `SLOW_DOWN_WAIT_MAX` (1 min); past
  them nothing is sent and the queue's backoff applies as before. A 429 asks only for fewer requests: no browser.

### D-1264 — `fetch_json` through the proxy pool over CONNECT tunnels
- Date: 2026-10-17 · Change/PR: acquisition-hardening (#244) · Status: decided (owner-delegated 2026-10-17)
- `acquire/tunnel.py` holds the one CONNECT client (the browser's guard and the JSON rung share it). The JSON rung
  uses httpx with an httpcore network backend whose connections are tunnels, so `http:` endpoints are tunnelled too
  (spec: every request through a CONNECT tunnel). httpx takes no network backend, so the transport's pool is replaced
  (a private attribute, pinned by the lockfile and covered by the stub-proxy tests). Through a pool the request names
  the host and the proxy resolves it, as in the other rungs; the guard still checks every hop's host first.

### D-1265 — Browser body sizes read before bodies; no CDP streaming
- Date: 2026-10-17 · Change/PR: acquisition-hardening (#244) · Status: decided (owner-delegated 2026-10-17)
- The navigation body's wire size (`request.sizes()`) is checked against `max_body_bytes` before any body is read, and
  a JSON body without `Content-Length` is sized the same way before it is read, so an oversize body never enters the
  worker process. CDP response streaming is not built: the body lives in the browser process either way, and a CDP
  session would sit beside INV-44's review for little gain. The decompressed cap is still checked after the read.

### D-1266 — The listing render's role C cost is closed by D-1260, not by a fingerprint
- Date: 2026-10-17 · Change/PR: acquisition-hardening (#244) · Status: decided (owner-delegated 2026-10-17)
- #242's follow-up asked to judge unchanged content before the render check's extraction. A listing page has no
  standing record (#206), and the stored fingerprint is the kept render's, never the HTTP page's, so the check has
  nothing to compare. With D-1260 a listing that needed the render goes straight to the browser on later fetches, so
  no HTTP extraction (and no role C call on it) runs until the weekly re-check. The #206 follow-up stays open.
