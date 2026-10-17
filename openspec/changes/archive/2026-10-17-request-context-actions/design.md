# Design: caller request context and page actions

## Shape

- Request side: `services.scrape_steps.FetchOptions` (the `fetch` member every page request shares) gains `headers`,
  `cookies` (secret values, `SecretStr`), `wait_for`, `actions` and `cache`. One vocabulary of steps,
  `config_ir/page_actions.py`, validates what the caller writes: a target is a CSS selector (translated to XPath 1.0
  as an IR `css` step is), an XPath 1.0 expression or visible text.
- Fetch side: `acquire.types.FetchPolicy` carries `context: RequestContext | None` (serialized with every value
  redacted) and `steps: tuple[PageStep, ...]` (XPath targets only). `acquire/page_steps.py` runs the steps on the
  rendered page; the browser rung calls it between the settle and the read, and records `StepOutcome`s on its attempt.
- The listing paging driver (owner #52) keeps its own structural controls: it is not caller-written, and its steps are
  chosen from the page's item group, not named by the caller.

## Decisions

### D-1430 The request context lives in `fetch`, with secret values
- Date: 2026-10-17 · Change/PR: request-context-actions (#262) · Status: decided (owner-delegated 2026-10-17)
- Decision: `headers`, `cookies`, `wait_for`, `actions` and `cache` are members of `fetch` (`services/fetch_options.py`), which scrape, batch, crawl and extract share, so every surface (REST, MCP tools, the playground, `crawlerai fetch`) takes them at once. Header and cookie values are `SecretStr`; names stay visible. `FetchPolicy.context` carries them to the rungs.
- Alternatives: top-level request members per endpoint; a separate `context` object.
- Why: one member already holds how pages are fetched (C8); MCP tools take the request models, so nothing is duplicated.
- Reversible: yes.

### D-1431 Which headers a caller may set, and where they go
- Date: 2026-10-17 · Change/PR: request-context-actions (#262) · Status: decided (owner-delegated 2026-10-17)
- Decision: a header is refused (422) when its name is a Fetch Standard §2.2.2 forbidden request-header name or starts with `proxy-` or `sec-`, or is `User-Agent`; `Cookie` goes in `cookies`. The HTTP and JSON rungs send the headers on requests to the fetched URL's host only (a redirect elsewhere carries none), replacing the impersonation's header of the same name in place. The browser sets no header (INV-44 unchanged, as the owner override of 2026-10-17 keeps INV-42..44), so `headers` with `method_hint` `browser` or with page steps is 422, and in `auto` a browser retry goes without them.
- Alternatives: `context.set_extra_http_headers` for non-fingerprint headers (breaks INV-44, `test_browser_setup.py`); route interception adding headers (still sets headers).
- Why: the standard's list is the set a page's own script may not set; the browser's identity stays Patchright's own.
- Reversible: yes.

### D-1432 Secrets stay out of captures, logs and answers
- Date: 2026-10-17 · Change/PR: request-context-actions (#262) · Status: decided (owner-delegated 2026-10-17)
- Decision: every serialization shows a header or cookie value as `**********`: a capture's manifest (`fetch_policy.context`), its recorded request headers (caller headers redacted, and `Authorization` no longer recorded at all, RFC 9110 §11.6.2), a scrape's stored `job.request`, `GET /v1/jobs/{id}/request`, reprs and logs. An asynchronous job (batch, crawl, extract) keeps the values in `job.request`, which its workers read (`KEEP_SECRETS` serialization context). robots.txt is fetched without the context, and a fetch with a context neither takes nor opens a site session (its cookies are the caller's, not the site's).
- Alternatives: a separate encrypted column; refusing secrets on asynchronous jobs.
- Why: workers read the request from the database; the deployment's own database already holds what its jobs need. Scrubbing values when the job ends is a follow-up.
- Reversible: yes.

### D-1433 Caller cookies are host-only cookies of the fetched URL (INV-29 amended)
- Date: 2026-10-17 · Change/PR: request-context-actions (#262) · Status: decided (owner-delegated 2026-10-17)
- Decision: the HTTP and JSON rungs seed the fetch's jar with the caller's cookies as host-only cookies of the URL's host, path `/` (RFC 6265 §5.3 step 6); the browser adds them with `BrowserContext.add_cookies` before the navigation, given the URL's root. None outlives the fetch.
- Alternatives: `Domain` cookies for the registrable domain; a raw `Cookie` header.
- Why: the narrowest scope that reaches the page; a cookie never goes to another host.
- Reversible: yes.

### D-1434 `fetch.proxy_pool` is checked against the configured pools
- Date: 2026-10-17 · Change/PR: request-context-actions (#262) · Status: decided (owner-delegated 2026-10-17)
- Decision: a pool not in `CRAWLERAI_PROXY_POOLS` is 422 (`fetch.proxy_pool`) before any job, on scrape, batch, crawl and extract (REST and MCP), and `crawlerai fetch --proxy-pool` exits 2; `Fetching.proxy_pools` holds the names.
- Alternatives: keep failing each fetch with `proxy_pool_unknown`.
- Why: a typo is the caller's error, answered at once rather than as a failed job.
- Reversible: yes.

### D-1435 Cache modes, and which capture stands for a fetch
- Date: 2026-10-17 · Change/PR: request-context-actions (#262) · Status: decided (owner-delegated 2026-10-17)
- Decision: `default` reuses a capture within `max_age` (scrape) as before; `bypass` always fetches (and a worker sends no validators); `only` serves the latest stored capture (within `max_age`, or any age at 0) or fails: a scrape is 404 `not_cached` with its job failed, a worker task fails `not_cached`. A capture stands for a fetch only when it was made with the same page steps and the same context names (`services/stored_captures.py`).
- Alternatives: `only` ignoring how the capture was made; a separate `cache_ttl`.
- Why: a capture of a page after a click is not the page without it; names, not values, are stored (D-1432).
- Reversible: yes.

### D-1436 One vocabulary of page steps, in `config_ir`
- Date: 2026-10-17 · Change/PR: request-context-actions (#262) · Status: decided (owner-delegated 2026-10-17)
- Decision: `config_ir/page_actions.py` is the one vocabulary a caller writes: `wait` (ms, an element, `network_idle`), `click` (an element or visible text), `scroll` (to bottom, by pixels, until stable), `press` (a key), `type` (an element, text). An element is named as an IR step names one: a CSS selector carried as its XPath 1.0 translation (`CssStep`), or an XPath checked as XPath 1.0. `to_steps` writes `acquire.types.PageStep`s, which `acquire/page_steps.py` runs. `wait_for` is a wait step written short. The listing paging driver (owner #52) keeps its own structural controls (it names elements from its own parse, not from the caller), and `config_ir/step_wire.py` (role A's selector steps) is unchanged: no model writes page steps.
- Alternatives: a second selector syntax in `acquire`; steps keyed by Playwright method names.
- Why: C8; `acquire` sits under `config_ir`, so the translation lives above it and the rung runs XPath only.
- Reversible: yes.

### D-1437 How steps run and fail
- Date: 2026-10-17 · Change/PR: request-context-actions (#262) · Status: decided (owner-delegated 2026-10-17)
- Decision: at most 20 steps, each within its `timeout_ms` (default 5 s, at most 15 s); a step that changes the page is followed by a quiet-content wait of up to 3 s. The first step that does not complete (`not_found`, `timeout`, `refused`, `error`) ends the run, the rest `skipped`, and the page is read as it is; each outcome is on the attempt (`AttemptRecord.steps`), so answers and job results show it. Steps and `wait_for` make the fetch a browser one (`method_hint` `http` is 422); the browser's time cap grows by the steps' budget.
- Alternatives: failing the fetch on a failed step; continuing past it.
- Why: later steps usually depend on earlier ones, and a partly acted page is still data the caller can judge from the outcomes.
- Reversible: yes.

### D-1438 No credential entry: a `type` into a password field is refused (§22 admission)
- Date: 2026-10-17 · Change/PR: request-context-actions (#262) · Status: decided (owner-delegated 2026-10-17)
- Decision: browser actions are admitted from §22 beyond owner #52 for the caller's page steps, typing and key presses included; a `type` into an `input type=password` (HTML §4.10.5.1.20) or a field whose autofill names a credential (`current-password`, `new-password`, `one-time-code`, HTML §4.10.18.7.1) is `refused`. Still never logins, CAPTCHA solving or credential entry by the engine; a caller's own session reaches a page only as its cookies or headers.
- Alternatives: no typing at all; allowing any field.
- Why: search boxes and filters need typing; credentials are the line the owner keeps.
- Reversible: yes.

### D-1439 Batch, crawl and extract apply the steps to every page
- Date: 2026-10-17 · Change/PR: request-context-actions (#262) · Status: decided (owner-delegated 2026-10-17)
- Decision: the `fetch` of a batch, crawl or extract applies its context, `wait_for` and `actions` to every page the job fetches (a crawl's sitemaps go over HTTP with the context only). A scrape's `browser_actions` (listing paging) takes no `fetch.actions` or `fetch.wait_for` (422) until the paging driver runs caller steps first.
- Alternatives: per-URL actions; steps on the start page only.
- Why: one request describes how its pages are fetched; per-URL steps can be a later member.
- Reversible: yes.
