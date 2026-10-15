# SPEC-02 decisions

Decisions for [SPEC-02 — Acquisition: HTTP, browser, adapters, politeness, SSRF, captures](../specs/SPEC-02-acquisition.md).
Template, statuses and rules: [DECISIONS.md](../DECISIONS.md).

### D-0112 — Visible text counts non-whitespace characters of `<body>`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 1 (#16) · Status: decided
- Decision: Count non-whitespace code points in the body text after stripping the four excluded elements; `<title>` is not counted.
- Alternatives: Collapsed-whitespace length including separators.
- Why: §4.3 says "< 200 characters of visible text" without defining characters; this count doesn't depend on how text nodes are joined.
- Reversible: yes

### D-0113 — The shell rule applies only to HTML responses
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 1 (#16) · Status: decided
- Decision: Shell applies when the last `Content-Type` is `text/html` or `application/xhtml+xml`, or absent (browsers sniff).
- Alternatives: Apply to every 2xx body.
- Why: A small JSON body is complete, not an unrendered page.
- Reversible: yes

### D-0114 — A 3xx reaching `classify` is `ok`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 1 (#16) · Status: decided
- Decision: Redirects are followed by the fetcher, which sets too many redirects as `error`.
- Alternatives: Classify 3xx as an error.
- Why: The classify table covers final responses only.
- Reversible: yes

### D-0115 — `is_public` follows the IANA special-purpose registries and rejects reserved IPv6
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 1 (#16) · Status: decided
- Decision: `ipaddress.is_global` and not multicast, recursing into IPv4-mapped and NAT64 (RFC 6052) embedded IPv4. Any other IPv6 in an IANA-reserved block (`is_reserved`, e.g. `::/8` holding the deprecated IPv4-compatible `::/96`, RFC 4291 §2.5.5.1) is rejected.
- Alternatives: Unwrap `::/96` like mapped addresses.
- Why: `is_global` (RFC 6890) is a superset of §4.5's ranges, and some stacks route `::/96` to the embedded IPv4. Fails closed.
- Reversible: yes

### D-0116 — A host that can't be IDNA-encoded is rejected as `host`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 1 (#16) · Status: decided
- Decision: `UnicodeError` from resolution maps to `SsrfRejected("host")`.
- Alternatives: Let it surface as a generic exception.
- Why: Keeps the §4.11 error `ssrf_rejected`.
- Reversible: yes

### D-0117 — Non-dotted-quad IPv4 host forms are rejected
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 1 (#16) · Status: decided
- Decision: Hosts that WHATWG parses as IPv4 but aren't dotted quads (`2130706433`, `0x7f.1`, `127.1`) are rejected as `host`.
- Alternatives: Normalize them to an address and check it.
- Why: curl and browsers resolve them to loopback but a stub resolver doesn't; rejecting keeps the checked address equal to the connected one.
- Reversible: yes

### D-0118 — HTML parser: selectolax (lexbor)
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 1 (#16) · Status: decided
- Decision: `selectolax` (MIT).
- Alternatives: stdlib `html.parser` (no HTML5 tree building).
- Why: ARCHITECTURE §19 names it for HTML.
- Reversible: yes

### D-0126 — `fetch_http` takes the engine version and browser profile from the caller
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 2 (#18) · Status: decided
- Decision: `fetch_http(url, policy, *, engine_version, impersonate, connector=None)`.
- Alternatives: Read `core.engine_version`; give `impersonate` a default.
- Why: `ENGINE_VERSION` arrives in SPEC-01 PR 7; with no default, `settings.impersonate` stays the only source of the profile.
- Reversible: yes

### D-0127 — Outcomes without a status line, and error bodies
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 2 (#18) · Status: decided
- Decision: No response status line (SSRF rejection of the first URL, connection failure, budget spent) gives manifest `status_code=0` and `AttemptRecord.status=None`. Every `error` outcome stores an empty body but keeps the last response's status and headers.
- Alternatives: Make `status_code` optional in the bundle format; keep partial bodies.
- Why: Leaves the SPEC-01 bundle format unchanged; an error yields no records (INV-11), and a truncated body would mislead replays.
- Reversible: yes

### D-0128 — Fetch error reasons never include the URL
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 2 (#18) · Status: decided
- Decision: Reasons are `timeout`, `body_cap`, `decode_error`, `too_many_redirects`, `ssrf_rejected: <reason>` and `network_error: curl <code>`.
- Alternatives: curl's message text.
- Why: curl messages contain host names; §4.11 redaction.
- Reversible: yes

### D-0129 — Connections are pinned with a wildcard `CURLOPT_RESOLVE`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 2 (#18) · Status: decided
- Decision: `CURLOPT_RESOLVE "*:<port>:<ip>"`.
- Alternatives: A per-host entry; `CURLOPT_CONNECT_TO`.
- Why: A per-host entry silently falls back to DNS when curl's form of the host (IDNA, percent-decoding, trailing dot) differs from the guard's.
- Reversible: yes

### D-0130 — `CRAWLERAI_IMPERSONATE` is typed as curl_cffi's `BrowserTypeLiteral`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 2 (#18) · Status: decided
- Decision: Default `chrome150`.
- Alternatives: A free string.
- Why: An unknown profile fails when settings load, not on the first fetch.
- Reversible: yes

### D-0143 — `crawlerai fetch` passes the package version as engine version until SPEC-01 PR 7
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 3 (#22) · Status: decided
- Decision: `fetch_http`/`store_capture` take the engine version as a parameter; the CLI passes `version("crawlerai")` until PR 7 replaces it.
- Alternatives: Wait for PR 7.
- Why: PR 7 was in flight. Bundles from the CLI before PR 7 carry `0.1.0`.
- Reversible: yes

### D-0144 — `store_capture` writes the object before the row
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 3 (#22) · Status: decided
- Decision: The object is written first, and the row is inserted after it in the caller's transaction, so a row never names a missing bundle.
- Alternatives: Insert the row first.
- Why: A failed insert leaves only an unreferenced object, which an orphan sweep could remove if one is ever measured to be needed; `expire_captures` deletes by row.
- Reversible: yes

### D-0145 — No `CURLINFO_PRIMARY_IP` check
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 3 (#22) · Status: decided
- Decision: Not added.
- Alternatives: Compare the connected address with the checked one after each response (#18 follow-up).
- Why: `CURLOPT_RESOLVE "*:port:ip"` also overrides literal-IP URLs, so curl can't connect anywhere else; the check could never fire or be tested.
- Reversible: yes

### D-0146 — `crawlerai fetch --out` must lie under the working directory
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 3 (#22) · Status: decided
- Decision: `--out` is resolved and rejected (exit 2) unless it lies under the working directory.
- Alternatives: Write anywhere (SonarCloud S8707).
- Why: Same shape as D-0142.
- Reversible: yes

### D-0147 — `crawlerai fetch` exits 0 whenever a bundle is written
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 3 (#22) · Status: decided
- Decision: Including an `error` outcome; the outcome is reported in the JSON summary's `block_class` and `error`.
- Alternatives: Non-zero exit on an `error` outcome.
- Why: The outcome is data, not a CLI failure.
- Reversible: yes

### D-0159 — The robots.txt snapshot is JSON in `site.robots_snapshot`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 4 (#26) · Status: decided
- Decision: `{fetched_at, status_code, body}`, fresh for 24 h.
- Alternatives: A `robots_fetched_at` column (migration); a per-process cache only.
- Why: The 24 h rule needs a fetch time; avoids a schema change.
- Reversible: yes

### D-0160 — Only the `*` robots group applies
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 4 (#26) · Status: decided
- Decision: Rules and `Crawl-delay` are read for user agent `*`.
- Alternatives: A `crawlerai` product token.
- Why: Fetches impersonate Chrome and announce no token of their own (RFC 9309 §2.2.1).
- Reversible: yes

### D-0161 — robots.txt matching follows RFC 9309 (spec clarification)
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 4 (#26) · Status: decided
- Decision: SPEC-02 §4.1's "stdlib `urllib.robotparser` semantics" means rules, `Crawl-delay` and `Sitemap:`; matching follows RFC 9309 §2.2.2–2.2.3 (longest match, `allow` on a tie, `*`/`$`), using Protego 0.7 (BSD-3-Clause). SPEC-02 §4.1 wording updated.
- Alternatives: `urllib.robotparser` (first match in file order, wildcards literal); our own matcher beside robotparser.
- Why: ARCHITECTURE §7.1 says robots.txt is honoured; robotparser fetches pages common files disallow (#26 review).
- Reversible: yes

### D-0162 — robots.txt status handling
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 4 (#26) · Status: decided
- Decision: 2xx is parsed (first 500 KiB, UTF-8); 4xx or more than 5 redirects means allow all; 5xx, network error, timeout or SSRF rejection means unreachable: a transient task failure with nothing stored, and `blocked` once attempts run out.
- Alternatives: Block the task as `robots` at once; end it `failed` after retries.
- Why: RFC 9309 §2.3.1.4 reads unreachable as "disallow all"; a blip shouldn't end tasks or cache "disallow all" for 24 h.
- Reversible: yes

### D-0163 — A 429/503 spends an attempt; once attempts run out the task ends `blocked`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 4 (#26) · Status: decided
- Decision: `Failed(transient=True, after=<Retry-After>, exhausted='blocked')` requeues after Retry-After or the usual backoff while `attempts < MAX_ATTEMPTS`, then ends `done`/`blocked` with `last_error='http 429'`.
- Alternatives: Requeue without counting; end as `failed`.
- Why: §4.3 bounds retries; §7.1 classes 429/503 as `blocked`.
- Reversible: yes

### D-0164 — A Retry-After beyond 15 min ends the task `blocked`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 4 (#26) · Status: decided
- Decision: No retry; the limiter pauses the host for 15 min. A delay too large for `timedelta` or `int()` counts as the longest pause.
- Alternatives: Honour any value; clamp to 15 min.
- Why: Neither retries before the server allows nor holds the job open.
- Reversible: yes

### D-0165 — Request interval and rate waits
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 4 (#26) · Status: decided
- Decision: Interval = the site's `crawl_delay_ms` or 1 s, never below the robots `Crawl-delay`. Any wait > 0 returns `Postpone` (attempt given back), never a sleep. robots.txt fetches skip the limiter.
- Alternatives: Let the site setting override robots; sleep through short waits; count robots fetches.
- Why: The operator may go faster than the default but not faster than robots.txt asks; the worker runs tasks one at a time, so a sleep stalls other sites; at most one robots fetch per site per 24 h per worker.
- Reversible: yes

### D-0203 — The browser is not tried after a 429 or 503
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 5 (#31) · Status: decided
- Decision: An HTTP `blocked` with status 429 or 503 is kept, with no browser retry; politeness applies the backoff (D-0163).
- Alternatives: Retry every `blocked` in the browser, as §4.4's sketch does.
- Why: RFC 6585 §4 and RFC 9110 §15.6.4 ask for fewer requests; a second rung would be one more request inside the backoff window.
- Reversible: yes

### D-0204 — `site.fetch_method` turns `browser` only on evidence against HTTP
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 5 (#31) · Status: decided
- Decision: `remember_fetch_method` sets `browser` only when the kept result is a browser `ok` and an HTTP attempt in the same fetch was `shell` or `blocked`; a `method_hint` browser fetch changes nothing.
- Alternatives: §4.4's literal `if r.method == "browser" and ok`.
- Why: §7.1 remembers "the method that worked" after HTTP failed; a forced browser fetch says nothing about HTTP.
- Reversible: yes

### D-0205 — The fetch-method re-check
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 5 (#31) · Status: decided
- Decision: Due means `fetch_method='browser'` and `fetch_method_checked_at` null or older than 7 days, oldest first. It fetches the site's latest `ok` capture after robots.txt, one site per transaction; every re-check sets `fetch_method_checked_at`. No `ok` capture, a robots disallow, or unreachable robots.txt keeps `browser`.
- Alternatives: The latest capture of any class; a queued re-check task.
- Why: A page known to exist makes a miss evidence about the method; no job kind exists for a queued re-check; batch 1 bounds row-lock time.
- Reversible: yes

### D-0206 — `acquire` is pure
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 5 (#31) · Status: decided
- Decision: `acquire(url, policy, remembered: FetchMethod, rungs: Rungs)`; `remember_fetch_method(conn, site_id, result)` writes.
- Alternatives: `acquire(url, site, policy)` reading and writing the DB.
- Why: Rung selection is tested without a database, and the caller owns the transaction (ENGINEERING).
- Reversible: yes

### D-0249 — The browser's SSRF guard is a per-fetch SOCKS5 proxy
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 6 (#46) · Status: decided
- Decision: Each context gets `proxy=socks5://127.0.0.1:<port>` served by `SocksGuard`, which checks each (host, port) with `SafeConnector.check` once per fetch and connects to the checked IP; loopback and link-local bypass is disabled explicitly (`<-loopback>`, Chromium's implicit bypass rules). The first URL is checked before the context opens; WebRTC non-proxied UDP is disabled. SPEC-02 §4.1 and §4.5 are clarified to match; ARCHITECTURE §7.1 is unchanged.
- Alternatives: §4.5's `route("**/*")` handler (saw only the first URL of a redirect chain in Patchright 1.63, and lets the browser re-resolve DNS); an HTTP forward proxy (needs a request parser).
- Why: Meets §7.1's "resolve once and connect only to that public IP, on every redirect hop" for everything the browser opens (INV-16).
- Reversible: yes

### D-0250 — Browser captures store the raw navigation body
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 6 (#46) · Status: decided
- Decision: `CaptureBundle.raw_body` and `CaptureManifest.raw_html_sha256` (optional), stored as `body.raw.html` for browser captures; `bundle_version` stays 1 and older manifests decode with `None`.
- Alternatives: Bump `bundle_version`; store it as a network entry.
- Why: SPEC-02 §4.8 / D-0010 ask for both bodies; the member is additive.
- Reversible: yes

### D-0251 — `browser_timeout_s` is a hard cap on the whole browser fetch
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 6 (#46) · Status: decided
- Decision: `goto` gets what remains; the network-idle wait ends at 90% of it; the rest reads the DOM and bodies. A page that never goes idle is read then, not an error; past the cap is `error`/`timeout`.
- Alternatives: A separate idle timeout.
- Why: §4.8's "wait up to `browser_timeout_s` for network idle with a hard cap"; one bound.
- Reversible: yes

### D-0252 — Browser outcome details follow the HTTP fetcher
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 6 (#46) · Status: superseded by D-0320 (the size cap only)
- Decision: The size cap is `max_decompressed_bytes` on both bodies; failures report `timeout`, `ssrf_rejected: <reason>` or `network_error: net::ERR_*`, never the URL (D-0128); the navigation response is not captured as a network body; `browser` tests skip without Chromium except under `CI`.
- Alternatives: `max_body_bytes`; capture a JSON document as a network body.
- Why: Consistent with D-0127 and D-0128; the document is already `body.html`.
- Reversible: yes

### D-0265 — `Adapter.map` takes a field → schema.org projection and the page kind
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 8 (#52) · Status: decided
- Decision: SPEC-02 §4.9 says `map(schema_def)`, but the layers contract puts `schemas` above `acquire : adapters`. The caller (collect, above schemas) passes `{field: schema.org path}` and the page kind; only top-level fields are mapped.
- Alternatives: Relax the layer contract.
- Why: Same information, no contract change (C8).
- Reversible: yes

### D-0266 — Adapter JSONPaths use RFC 9535 bracket notation
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 8 (#52) · Status: decided
- Decision: `$['location']['name']`, `$['jobs'][*]['title']`.
- Alternatives: Dot notation.
- Why: RFC 9535 Normalized Paths; can't be mistaken for a hostname by the C3 scan.
- Reversible: yes

### D-0267 — Greenhouse endpoints verified; no guessed regional host
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 8 (#52) · Status: decided
- Decision: `GET /v1/boards/{token}/jobs?content=true` and `/jobs/{id}`, verified against the platform's public docs on 2026-10-13, closing SPEC-02 §9's "[unverified]" item for Greenhouse. Boards on regional hosts the docs don't name are not detected and fall through to the generic rungs.
- Alternatives: Guess a regional API host.
- Why: C7: decline rather than guess.
- Reversible: yes

### D-0268 — `acquire/api.fetch_json` (GET only) lands with the adapters
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 8 (#52) · Status: decided
- Decision: `JsonRequest(url, page_url)`, GET only; SPEC-09 extends it for recipes; proxy support follows SPEC-02 PR 7.
- Alternatives: Build it in SPEC-09.
- Why: The adapter's fetch needs it now.
- Reversible: yes

### D-0269 — The active adapter set is a `Registry` argument
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 8 (#52) · Status: decided
- Decision: A per-adapter settings flag is a follow-up.
- Alternatives: A settings flag now.
- Why: Settings are SPEC-02 PR 7's scope, and nothing builds the registry in production yet.
- Reversible: yes

### D-0282 — A proxy pool is an HTTP proxy used through a CONNECT tunnel
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 7 (#53) · Status: decided
- Decision: `http://[user[:password]@]host[:port]`, always tunnelled (http pages too): curl gets `HTTPPROXYTUNNEL`; the browser's `SocksGuard` chains each checked connection to the pool with CONNECT. SPEC-02 §4.5 clarified.
- Alternatives: SOCKS5 or HTTPS proxies; absolute-form forwarding; pointing Chromium straight at the pool (leaves hops unchecked, D-0249).
- Why: OPEN_QUESTIONS #10's datacenter/ISP pools speak CONNECT (RFC 9110 §9.3.6); tunnelling keeps the proxy from rewriting requests; chaining behind the guard keeps INV-16.
- Reversible: yes

### D-0283 — An unknown proxy pool ends the fetch with `error='proxy_pool_unknown'`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 7 (#53) · Status: decided
- Decision: A policy naming a pool not in `CRAWLERAI_PROXY_POOLS` fetches nothing.
- Alternatives: Fetch directly; raise.
- Why: C7: no fallback that silently changes where requests come from; an outcome like other fetch failures (§4.11).
- Reversible: yes

### D-0284 — The configured proxy endpoint is the SSRF allowlist entry
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 7 (#53) · Status: decided
- Decision: The proxy's own address isn't SSRF-checked; being configured in settings is §4.5's explicit allowlist.
- Alternatives: Check it like a target.
- Why: §7.1/§4.5: "public or explicitly allowlisted in settings".
- Reversible: yes

### D-0285 — Settings errors hide input; `ProxyEndpoint` hides credentials in its repr
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 7 (#53) · Status: decided
- Decision: `hide_input_in_errors`; username and password stay out of reprs.
- Alternatives: Default reprs.
- Why: Proxy and database URLs carry credentials.
- Reversible: yes

### D-0286 — A refused proxy tunnel reports as curl does
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 7 (#53) · Status: decided
- Decision: `network_error: curl 7` over HTTP; a SOCKS general failure in the browser; no separate `proxy_error` class.
- Alternatives: A `proxy_error` class.
- Why: curl gives a refused CONNECT the same code as an unreachable server; separating them needs per-handle state.
- Reversible: yes

### D-0307 — Lever endpoints verified; both documented instances detected
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 9 (#62) · Status: decided
- Decision: `GET /v0/postings/{site}?mode=json` and `/v0/postings/{site}/{posting_id}`, verified against the platform's public Postings API docs on 2026-10-13, closing SPEC-02 §9's "[unverified]" item for Lever. The global and EU job site hosts are each sent to their own instance's API host.
- Alternatives: The global host only.
- Why: The docs name both instances.
- Reversible: yes

### D-0308 — Filtered Lever job site lists and application forms are not detected
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 9 (#62) · Status: decided
- Decision: A job site URL carrying one of the list endpoint's documented filter or group parameters (`location`, `commitment`, `team`, `department`, `level`, `group`), and the `/{site}/{id}/apply` form, fall through to the generic rungs.
- Alternatives: Forward the filters to the API (the docs don't say the job site uses the same parameters).
- Why: C7: decline rather than guess.
- Reversible: yes

### D-0309 — No `datePosted` or `hiringOrganization.name` mapping for Lever
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 9 (#62) · Status: decided
- Decision: Lever maps `JobPosting.title`, `url`, `description` and `jobLocation` only.
- Alternatives: Map undocumented fields.
- Why: The documented posting fields have no posting date or company name.
- Reversible: yes

### D-0310 — `PATH_SEGMENT` and `json_path` live in `adapters/base`
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 9 (#62) · Status: decided
- Decision: The URL path-segment pattern and the RFC 9535 bracket-notation builder are shared by the adapters.
- Alternatives: A copy per adapter.
- Why: C8: the same logic was needed twice.
- Reversible: yes

### D-0320 — The browser holds both body caps, at storage
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 10 (#64) · Status: decided
- Decision: The browser fetch holds the navigation body to `max_body_bytes` (its size on the wire, `Request.sizes()`) and to `max_decompressed_bytes`; an oversize body is a `body_cap` error with no capture body (INV-30). Both are checked after the response finishes and before anything is kept: Patchright has no streaming read, so Chromium's own limits bound the memory. Supersedes D-0252's size cap.
- Alternatives: Stream the body through CDP `Fetch.takeResponseBodyAsStream` (a larger change; a possible follow-up row).
- Why: INV-30, and the same two caps as the HTTP and JSON fetchers.
- Reversible: yes

### D-0321 — JSON-fetch cookies match on the hop's host name
- Date: 2026-10-13 · Spec/PR: SPEC-02 PR 10 (#64) · Status: decided
- Decision: `fetch_json` keeps cookies in a per-fetch jar matched on each hop's host name, with host-only cookies kept to their host (RFC 6265 §5.3 step 6, §5.4); httpx's own jar, which would match on the pinned address, refuses every cookie.
- Alternatives: Drop cookies on every hop (also meets INV-29, but differs from the other fetchers); pin the address at the connection layer so httpx's jar sees host names (a larger change).
- Why: INV-29. `Domain=` uses the stdlib's heuristic rather than public-suffix data; a follow-up row can add it.
- Reversible: yes

### D-0865 — A fetch's further requests wait for their turn; the worker waits in place
- Date: 2026-10-16 · Spec/PR: follow-ups (#197) · Status: decided
- Decision: `acquire(..., admit_next=)` awaits the hook before each request after its first (the browser retry, the page after a failed recipe). The scrape service passes `admitted`; the worker passes `HostLimiter.wait`, waiting in place rather than postponing. `fetch_politely` backs off when any attempt got a 429 or 503. Completes D-0634's open items.
- Alternatives: Postpone the task; skip the retry when no turn is free.
- Why: The first request is already sent: postponing would send it again each run and never reach the retry; skipping loses the browser fallback.
- Reversible: yes

### D-0866 — `site.robots_snapshot` holds a snapshot per robots.txt URL
- Date: 2026-10-16 · Spec/PR: follow-ups (#197) · Status: decided
- Decision: A JSON map `{robots_url: snapshot}` in the same `Text` column; stale entries are dropped on write, and a value of the old single-snapshot shape counts as none and is fetched again.
- Alternatives: A table keyed by origin; a data migration.
- Why: RFC 9309 §2.3 (robots.txt per scheme, host and port); no DDL change, every reader goes through `site_robots`, and an old value's origin is unknown.
- Reversible: yes

### D-0884 — Public suffixes for `Domain=` cookies
- Date: 2026-10-16 · Spec/PR: follow-up (#200) · Status: decided
- Decision: The Public Suffix List is a fetched manifest entry pinned to a commit of the list's repository (MPL-2.0, NOTICE). The JSON rung's per-fetch jar ignores a cookie whose `Domain` is a public suffix other than the setting host (RFC 6265 §5.3 step 5); without the file the list is empty and only the single-label rule applies. The HTTP rung is a follow-up.
- Alternatives: Commit the list (its host names trip the C3 scan); the standard library's heuristic only.
- Why: C4 data for a standard rule; curl_cffi keeps cookies in libcurl, built here without libpsl.
- Reversible: yes
