# SPEC-02 — Acquisition: HTTP, browser, adapters, politeness, SSRF, captures

Layer: L0 (HTTP fetch, SSRF, captures, outcomes) → L1 (Patchright browser on evidence; Greenhouse and Lever
adapters). Architecture refs: §7.1, §7.2 (discovery capture only; recipes are SPEC-09), §15, §18 (SSRF), C6, C3.

## 1. Summary

Get pages and record what happened (§7). A pure fetch function returns a `CaptureBundle`; persistence is a
separate step so the eval CLI (SPEC-03) can capture hidden pages without touching the main DB. Block and shell
classification use HTTP status and structural body properties only (INV-24). The browser is used on evidence,
never by default (Appendix A #12).

## 2. Scope

Core:
- `curl_cffi` HTTP fetch with Chrome TLS impersonation; `httpx` for adapter/API JSON.
- Patchright headless with network JSON capture; one navigation, bounded waits; UA without `HeadlessChrome` and
  consistent client hints (§7.1).
- Rung selection and `site.fetch_method` memory with periodic re-check.
- Outcome recording (method, status, block class, duration) into `capture` and the bundle manifest.
- Politeness: per-site rate limit (default 1 req/s), 429/503 backoff with `Retry-After`, robots.txt honoured by
  default with operator override recorded on the job, `site.robots_snapshot`.
- SSRF guard (§7.1, §18): fail closed, every redirect hop, proxies included.
- Limits: body cap, compressed-bomb guard, time budgets.
- Optional proxy pool per site (`site.proxy_pool`).
- Adapters: Greenhouse and Lever public job-board APIs (§7.1, C6), returning JSON that the collectors treat as
  `source_kind='adapter'`.
- Browser network capture of JSON bodies for §7.2 step 1 (discovery). Recipe binding, validation and export are
  SPEC-09.

Out of scope (§22 unless noted):
- Anti-bot identities, cookie handoff, vendor strategies, real Chrome + behaviour layer, residential proxies,
  unblockers, CAPTCHA, detection bench.
- More adapters (Shopify JSON, Workday, iCIMS, ADP, Oracle CX).
- Authenticated crawls; browser actions (non-goals).
- Any challenge-page string detection (would be a vendor list; C3/C4).
- Conditional GET and fingerprints (SPEC-11).

## 3. Dependencies

- SPEC-01 (capture table, bundle format, object store, usage events).
- OPEN_QUESTIONS #10: one datacenter/ISP pool configured by hand per site; settings hold `CRAWLERAI_PROXY_POOLS`
  as JSON `{pool_name: proxy_url}`.
- OPEN_QUESTIONS #2: adapters after Greenhouse/Lever are candidates.

## 4. Design

### 4.1 Modules

- `crawlerai.acquire.types` — `FetchPolicy`, `FetchResult`, `BlockClass`.
- `crawlerai.acquire.ssrf` — `resolve_public(host) -> IPv4/6`, `is_public(ip)`, `SafeConnector`.
- `crawlerai.acquire.http` — `fetch_http(url, policy) -> FetchResult` (curl_cffi, manual redirects).
- `crawlerai.acquire.browser` — `fetch_browser(url, policy) -> FetchResult` (Patchright).
- `crawlerai.acquire.socks_guard` — `SocksGuard`, the SSRF guard in front of the browser (4.5).
- `crawlerai.acquire.api` — `fetch_json(request_spec, policy) -> FetchResult` (httpx; used by adapters and SPEC-09).
- `crawlerai.acquire.classify` — `classify(status, headers, body) -> BlockClass`.
- `crawlerai.acquire.politeness` — per-site limiter and backoff state (in-process; see 4.6).
- `crawlerai.acquire.robots` — fetch/parse/cache robots.txt (RFC 9309 matching: longest match, `*` and `$`; with
  `Crawl-delay` and `Sitemap:` extraction; D-0161).
- `crawlerai.acquire.rungs` — `acquire(url, site, policy) -> FetchResult` selecting adapter / API recipe → http →
  browser.
- `crawlerai.acquire.persist` — `store_capture(result, site) -> Capture` (bundle to object store + row).
- `crawlerai.adapters.base` — `Adapter` protocol; `crawlerai.adapters.greenhouse`, `crawlerai.adapters.lever`;
  `crawlerai.adapters.registry.detect(url) -> Adapter | None`.

### 4.2 Types

```python
class FetchPolicy(BaseModel, frozen=True):
    method_hint: Literal["auto", "http", "browser"] = "auto"
    proxy_pool: str | None = None
    respect_robots: bool = True              # false only via operator override, recorded on job.request
    robots_override_reason: str | None = None
    timeout_s: float = 30.0
    browser_timeout_s: float = 45.0
    max_body_bytes: int = 10_000_000
    max_decompressed_bytes: int = 50_000_000
    capture_network_json: bool = True        # browser only
    locale_hint: str | None = None           # request locale, passed to normalizers' context later

class BlockClass = Literal["ok", "blocked", "shell", "not_found", "error"]

class FetchResult(BaseModel, frozen=True):
    bundle: CaptureBundle                    # SPEC-01 4.5; manifest.block_class filled
    method: Literal["http", "browser", "api"]
    duration_ms: int
    attempts: list[AttemptRecord]            # one per rung tried: method, status, block_class, duration_ms, error?
```

### 4.3 Classification (`classify`) — structural only (INV-24)

| Class | Rule (standards/structure only) |
|---|---|
| `not_found` | status 404 or 410. |
| `blocked` | status ∈ {401, 403, 407, 429, 451, 503}. |
| `shell` | status 2xx and the body, after removing `script`, `style`, `noscript`, `template`, has < 200 characters of visible text **and** < 5 `<a href>` links. |
| `error` | any other 4xx or 5xx status, network error, timeout, too many redirects, body-cap exceeded, decode failure (ARCHITECTURE rev 5 §7.1). |
| `ok` | otherwise. |

Rationale: challenge pages served with 200 are *not* detected (that would need vendor strings). They mostly
present as shells and get a browser retry via the shell rule; what remains is measured as `shell`/`ok` in the
acquisition outcome mix (§16.3) and becomes evidence for §22 anti-bot candidates. The thresholds 200 chars /
5 links are starting points to confirm on dev (§ preamble "numbers are starting points").

### 4.4 Rung selection (`acquire`)

```
if adapter := registry.detect(url): return adapter.fetch(url, policy)          # api
if recipe := active_config_api_recipe(site): return fetch_recipe(recipe, url, policy)   # api (SPEC-09 4.8)
method = policy.method_hint if != auto else site.fetch_method or "http"
r = fetch_http(url) if method == "http" else fetch_browser(url)
if method == "http" and r.block_class in {"shell", "blocked"} and (policy.method_hint == "auto"):
    r2 = fetch_browser(url); r = r2 if r2.block_class == "ok" else r   # keep the better outcome, record both attempts
if r.method == "browser" and r.block_class == "ok": site.fetch_method = "browser"
```

- Re-check (§7.1): scheduler task `recheck_fetch_method` every 7 days per site with `fetch_method='browser'`:
  fetch one recent URL over HTTP; if `ok` and not `shell`, reset to `http`.
- Every attempt is appended to `FetchResult.attempts` and persisted in the bundle manifest and `capture` row
  (`block_class` of the final attempt; attempts list in `fetch_policy` jsonb as `attempts`).
- Browser evidence (§7.1): shell, blocked (a browser may pass), or `policy.capture_network_json` requested by
  SPEC-09 discovery.

### 4.5 SSRF (§7.1, §18) — fails closed

- `resolve_public(host)`: resolve A/AAAA once (`getaddrinfo`); reject if any address is private
  (RFC 1918), loopback, link-local (169.254/16, fe80::/10), unique-local (fc00::/7), multicast, unspecified,
  the cloud metadata range (169.254.169.254 is in link-local already), IPv4-mapped IPv6 of any of these, or if
  the host is a literal IP in those ranges. Reject non-http(s) schemes and ports outside {80, 443, 8080, 8443}
  unless `policy.allow_ports` (not in core; reject).
- HTTP: curl_cffi is given `resolve=[f"{host}:{port}:{ip}"]` so the connection goes to the checked IP; automatic
  redirects are **disabled**; the fetcher follows up to 5 redirects manually, running `resolve_public` on each
  hop. `Location` to a non-http(s) scheme ends with `error`.
- Browser: each fetch's context sends every connection through a SOCKS5 proxy on loopback (`acquire.socks_guard`,
  RFC 1928). The browser resolves no names behind it; the guard runs `SafeConnector.check` on each host (once per
  fetch) and connects only to the checked address, so every redirect hop, frame and worker is covered. A request
  interceptor (`route`) can't do this: it sees only the first request of a redirect chain. The first URL is
  checked before a context opens, which also refuses `file:` and `data:`. WebRTC is kept from sending UDP outside
  the proxy.
- Proxy: the proxy resolves DNS, so pinning the IP is impossible. The guard still runs `resolve_public` on the
  hostname before the request and on each manual redirect hop, and the proxy URL itself must be public or
  explicitly allowlisted in settings (`CRAWLERAI_PROXY_POOLS`), as §7.1 states for proxies. A pool is an HTTP proxy
  (`http://[user[:password]@]host[:port]`, `crawlerai.core.proxy`), reached through a CONNECT tunnel (RFC 9110
  §9.3.6) for every page: curl tunnels to it, and the browser's `SocksGuard` opens each checked connection as a
  tunnel through it. A policy naming a pool that isn't configured ends with `error`, `error='proxy_pool_unknown'`,
  without fetching.
- Tests use a stub resolver injected into the guard; no network.

### 4.6 Politeness

- Per-site token bucket, default 1 req/s, overridden by `site.crawl_delay_ms` or robots `Crawl-delay`.
- Backoff: on 429/503 honour `Retry-After` (seconds or HTTP-date), else exponential from 30 s, max 15 min;
  the task is requeued with `next_attempt_at` (SPEC-01) rather than sleeping in the worker.
- Robots: fetched once per origin (scheme, host and port, RFC 9309 §2.3) per 24 h, stored in `site.robots_snapshot`
  by robots.txt URL; disallowed URLs produce outcome `blocked` with `last_error='robots'` unless the job's
  `respect_robots=false` override (recorded in `job.request`).
- Limiter state is per worker process (implementation detail). With several workers this over-admits by the
  worker count; the design point (0.1 tasks/s) makes that acceptable. Anything shared is a candidate only if
  measured.

### 4.7 HTTP fetch

- `curl_cffi.requests.AsyncSession(impersonate="chrome")` with the version pinned in settings
  (`CRAWLERAI_IMPERSONATE`, default the newest supported Chrome profile at lock time).
- Streams the body with a cap (`max_body_bytes` compressed, `max_decompressed_bytes` after decoding); exceeding
  either ends with `error` ("body_cap").
- Records request and response headers (minus cookies and the proxy auth header) in the manifest.
- Usage: `http_requests` +1 per attempt; `proxy_bytes` when a pool is used.

### 4.8 Browser fetch (Patchright headless, owner-tested configuration)

- One persistent browser per worker process, one fresh context per fetch; headless Chromium via Patchright
  (Apache-2.0, 1.63.0 at writing **[verified in Appendix C]**).
- User agent: Chromium's own with `HeadlessChrome` replaced by `Chrome`; client hints (`Sec-CH-UA*`) set to the
  same brand/version via `context.set_extra_http_headers` so they agree with the UA.
- Navigation: `goto(url, wait_until="domcontentloaded")`, then wait up to `browser_timeout_s` for network idle
  with a hard cap; no scripted actions; no scrolling (infinite scroll is handled through §7.2 recipes, SPEC-09).
- Capture: `page.on("response")` saves bodies with `content-type` containing `json`, same-site or any origin, up
  to 2 MB each and 50 per page, in order, into `bundle.network`.
- Body: `page.content()` after the wait (the rendered DOM) **and** the raw navigation response body saved as
  `body.raw.html` in the bundle (implementation detail) so replays can distinguish server HTML from rendered.
- Usage: `browser_seconds` = wall time of the context.

### 4.9 Adapters (Greenhouse, Lever)

- `Adapter` protocol: `name`, `detect(url) -> AdapterMatch | None` (tenant slug + page kind), `fetch(url, policy)
  -> FetchResult` (method `api`, body is JSON), `map(schema_def) -> dict[field, JSONPath]` using the platform's
  documented fields (C2: "a published standard" — the vendor's public API documentation counts as the platform's
  standard, and it lives in the adapter package where hostnames are allowed).
- Detection uses the platforms' documented public hostnames **inside the adapter package only** (C3 exemption).
- Greenhouse: Job Board API `GET /v1/boards/{board}/jobs?content=true` and `/jobs/{id}`; Lever: Postings API
  `GET /v0/postings/{site}?mode=json` and `/v0/postings/{site}/{id}`. Exact endpoints are **[unverified; confirm
  against the vendors' current docs when implementing]**.
- C6 evaluation: an adapter ships `active=false` until the eval report shows it was measured on ≥ 3 tenants not
  used to build it (dev set labels); a settings flag per adapter.
- The adapter returns `source_kind='adapter'` candidates via SPEC-05; nothing in this spec interprets values.

### 4.10 Persistence

`store_capture(result, site, expires_in=30d | None)`: writes bundle to the object store under the production
key layout and inserts a `capture` row. Eval captures (SPEC-03) call `encode()` and write to eval prefixes
themselves; they never call `store_capture`.

### 4.11 Error handling

- Every exception inside a rung becomes an `AttemptRecord(error=...)` with `block_class='error'`; the next rung
  is tried only when the rule in 4.4 says so.
- SSRF rejection is `block_class='error'`, `error='ssrf_rejected'`, not retried, and logged without the URL when
  redaction is on.
- Timeouts are errors; the task is retried per SPEC-01 policy at most 3 times.

## 5. Invariants

INV-11 (blocked/shell → zero records; this spec sets the class, SPEC-05 enforces zero records), INV-16 (SSRF),
INV-24 (classification structural only; the C3 scan covers this package — it must contain no hostnames; only
`adapters/` may). INV-23 for usage events on every attempt. INV-29 (cookies stay inside one fetch: one session or
browser context per fetch, RFC 6265 matching on each hop, nothing stored). INV-30 (bodies bounded by
`max_body_bytes`/`max_decompressed_bytes` before full reading; oversize is an error outcome, never content).

## 6. Testing strategy

- `classify`: unit tables over statuses and synthetic bodies; property test that any body with ≥ 200 visible
  chars or ≥ 5 links is never `shell`.
- SSRF: stub resolver; tests for each private range, IPv4-mapped IPv6, redirect to private, redirect scheme change,
  literal IPs, and the proxy path (hostname pre-check still applied).
- HTTP fetch: local test server (aiohttp/uvicorn fixture) serving redirects, gzip bombs, slow bodies, 429 with
  `Retry-After`; assertions on attempts, caps and backoff scheduling.
- Browser: marked `@pytest.mark.browser`, run in CI with Patchright's Chromium; local test server with a JS-only
  page; asserts rendered body and captured JSON bodies.
- Adapters: tests use recorded JSON fixtures with synthetic tenant names; test names refer to the adapter, which
  is a platform, not a site (C9 compatible; the hostnames live only in the adapter package).
- Replay (SPEC-03): dev captures must be loadable by `decode`.
- INV-29: a cookie set by one fetch is absent from the next fetch to the same host; on a redirect chain, a cookie
  for another domain or path is not sent on a hop (RFC 6265 §5.4). Run for both the HTTP and the browser fetcher.
- INV-30: an oversize body (`max_body_bytes`) and an over-decompressing body (`max_decompressed_bytes`) each end
  in an error outcome with no capture body.

## 7. Acceptance criteria

- L0 done-when contribution: `crawlerai fetch URL --out bundle.zst` produces a bundle that `decode` reads, with
  a correct block class on a local test server.
- 100% of the SSRF test matrix rejects; redirect hop to a private IP is rejected after the public first hop.
- Browser rung produces a rendered body for the JS-only test page and captures its XHR JSON.
- `site.fetch_method` flips to `browser` after a shell → browser-ok sequence, and back after a successful re-check.
- Robots disallow produces `blocked`/`robots` and the override is recorded on the job.

## 8. PR plan

| # | Title | Scope | Checks | Done when |
|---|---|---|---|---|
| 1 | Acquisition types, classify, SSRF guard | `acquire/types,classify,ssrf` + tests | unit, property | Matrix passes. |
| 2 | HTTP fetch (curl_cffi) with manual redirects and caps | `acquire/http` + local server tests | unit | Caps and redirects tested. |
| 3 | Persist capture + `crawlerai fetch` CLI | `acquire/persist`, `cli` | unit | Bundle round trip on a fetched page. |
| 4 | Politeness + robots + backoff via requeue | `acquire/politeness,robots`; worker integration | unit | Retry-After honoured. |
| 5 | Rung selection + fetch_method memory + re-check scheduler task | `acquire/rungs`, scheduler entry | unit | State transitions tested. |
| 6 | Patchright browser rung with network capture | `acquire/browser` | browser-marked tests | JS page rendered, JSON captured. |
| 7 | Proxy pools | settings + both fetchers | unit (local proxy fixture) | Pool used when set. |
| 8 | Adapter protocol + Greenhouse | `adapters/base,registry,greenhouse` | unit with fixtures | Detect + fetch + map. |
| 9 | Lever adapter | `adapters/lever` | unit | Same. |
| 10 | Tests named for INV-29 and INV-30 | tests for `acquire/http,browser` | unit, browser-marked tests | Cookie isolation and body-bound tests pass on both fetchers. |

PRs 1–5 are L0; 6–10 are L1.

## 9. Open issues

- **Review finding (§7.1 "a block that a browser may pass" is undefined).** Resolved in ARCHITECTURE rev 5 §7.1:
  classification uses status codes and structure only; 200-status challenges are not detected by content and
  show up as `shell`/`ok` in the outcome mix (evidence for §22).
- **Review finding (SSRF through a proxy).** Resolved in ARCHITECTURE rev 5 §7.1: through a proxy the IP can't be
  pinned; the hostname is checked before each hop and proxy endpoints must be explicitly configured (4.5).
- **Shell thresholds** (200 chars, 5 links) are unmeasured starting points; §7.1 leaves them to this spec, to be
  confirmed on the dev outcome mix.
- Greenhouse/Lever endpoint paths are **[unverified]** in this spec; verify against vendor docs at implementation.
- Adapter detection by hostname is allowed only inside `adapters/`; the import-linter contract in SPEC-00 keeps
  the package isolated.
