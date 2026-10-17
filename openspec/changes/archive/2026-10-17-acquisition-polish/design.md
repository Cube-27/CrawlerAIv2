# Design: acquisition polish

## Decisions

### D-1380 — The fetch method is remembered per site and page kind
- Date: 2026-10-17 · Change/PR: acquisition-polish (#256) · Status: decided (owner-delegated 2026-10-17)
- Decision: `site_fetch_method (site_id, page_kind, method, checked_at)` replaces `site.fetch_method` and
  `fetch_method_checked_at`; no row is `http`. A fetch with no page kind reads and writes the detail row: `classify`
  applies the listing rule to listings only, so such a page is classified as a detail page is. The re-check takes due
  rows, tries the latest `ok` capture fetched as that kind, with that page kind.
- Alternatives: a second column pair on `site`; a JSONB map; a nullable kind for kind-less fetches.
- Why: one row per memory is the domain's shape; the recheck and the upsert stay one statement each.
- Reversible: yes

### D-1381 — `proxy_bytes` counts each attempt's bytes; learning replays use the site's pool
- Date: 2026-10-17 · Change/PR: acquisition-polish (#256) · Status: decided (owner-delegated 2026-10-17)
- Decision: `AttemptRecord.transferred` (not stored, not in the API) holds the bytes an attempt moved: curl's debug
  callback kinds HEADER_IN/OUT and DATA_IN/OUT (HTTP messages as transferred, the CONNECT exchange included, no TLS
  framing) for the HTTP and JSON rungs; the bytes the SOCKS guard relayed both ways for the browser rungs (a listing's
  whole run on its navigation attempt). `record_fetch_usage` records them as `proxy_bytes` of the pool for a fetch
  through one. A learning run's replays take `FetchPolicy(proxy_pool=site.proxy_pool)` and record their usage, robots.txt
  fetches included, on the learn job (`Replays(job_id, pool)`).
- Alternatives: count body bytes only; count every fetch's bytes as `proxy_bytes` whether or not a pool carried it.
- Why: the proxy bills what it relays; the live check matched the stub proxy's count byte for byte on the HTTP rung.
- Reversible: yes

### D-1382 — Crawl tasks store their final URL; the frontier skips URLs a task was fetched at
- Date: 2026-10-17 · Change/PR: acquisition-polish (#256) · Status: decided (owner-delegated 2026-10-17)
- Decision: a crawl task stores `url_task.final_url` (canonical) as soon as its page is fetched, before it adds URLs;
  `Frontier.enqueue` leaves out a URL that is any task's canonical or final URL in the job (index on `job_id,
  final_url`). This replaces `Frontier.fetched`, the start page's special case.
- Alternatives: end the later task of a page already fetched with a new outcome (an API shape change).
- Why: smallest generic rule. A target enqueued before its redirecting task was fetched is still fetched as its own
  task; left as a follow-up.
- Reversible: yes

### D-1383 — A listing without words is fingerprinted by its links
- Date: 2026-10-17 · Change/PR: acquisition-polish (#256) · Status: decided (owner-delegated 2026-10-17)
- Decision: when a listing's visible text has no words, its content digest and SimHash are taken over the URLs it
  links to (`content.links`: canonical, deduplicated, document order), one word each. Detail pages without words stay
  unfingerprinted. `url_state.record_fingerprint` is dropped (no reader or writer).
- Alternatives: fingerprint the DOM structure (tag paths), which changes with markup unrelated to the rows.
- Why: a listing's rows are what it lists; their links are the structural trace a wordless listing keeps.
- Reversible: yes

### D-1384 — Adapter declines on the site row; page-host adapter requests reuse the page's rules
- Date: 2026-10-17 · Change/PR: acquisition-polish (#256) · Status: decided (owner-delegated 2026-10-17)
- Decision: `site.adapter_declined` (JSONB, adapter name → ISO 8601 until). A fetch takes `Registry.for_host(host,
  stored)`, a registry seeded with the page host's stored declines, and writes `declined_for(host)` back when it
  differs (a decline made, or one that ran out). A decline of another host (a canonical or referred platform URL) is not
  stored. The process registry keeps no decline. `fetch_politely` hands the page fetch the host rules it read
  (`HostRules`); `page_host_first` answers a page-host request from them, other hosts through `endpoint_rules`.
- Alternatives: a decline table keyed by host; async registry lookups at every `would_serve`.
- Why: the registry's synchronous API stays; one read and at most one write per fetch.
- Reversible: yes

### D-1385 — Shopify collections page through the Storefront cursor
- Date: 2026-10-17 · Change/PR: acquisition-polish (#256) · Status: decided (owner-delegated 2026-10-17)
- Decision: the query asks `products(first: 250, after: $after) { pageInfo { hasNextPage endCursor } ... }`;
  `adapters.paging.fetch_pages` follows `endCursor` while `hasNextPage` holds, up to `MAX_ROWS` (1000) or the
  request's `max_rows`, merging the pages' nodes into the first answer.
- Alternatives: a higher cap for Shopify alone.
- Why: the shared paging walker already bounds rows, time and failures for every adapter (SPEC-15 §4.10).
- Reversible: yes

### D-1386 — Locale-prefixed Shopify collections are asked in their language
- Date: 2026-10-17 · Change/PR: acquisition-polish (#256) · Status: decided (owner-delegated 2026-10-17)
- Decision: a first path segment that is a BCP 47 language subtag with an optional region (RFC 5646) before
  `/collections/{handle}` is detected; the query carries `@inContext(language: $language)` (the subtag upper-cased) and
  `localization { language { isoCode } }`, and an answer in another language is `not_served`. The region is not used:
  prices still need a shop with one presentment currency (D-1114).
- Alternatives: serve in the shop's default language (titles the page does not show); also pass the country (a value
  from a URL code, C7).
- Why: the platform's locale route names the page's language; the answer's own `localization` confirms it.
- Reversible: yes

### D-1387 — No per-host memory of shops with several presentment currencies
- Date: 2026-10-17 · Change/PR: acquisition-polish (#256) · Status: decided (owner-delegated 2026-10-17)
- Decision: closed without code. Since D-1118 product pages send no API request, and a collection of such a shop is
  served in one request (rows without prices, D-1114); nothing falls back, so there is nothing to remember.
- Alternatives: remember the host and skip the API, which would lose the collection's rows.
- Why: the follow-up described product pages, which no longer reach the adapter.
- Reversible: yes

### D-1388 — An HTTP page lacking content asks its adapter referral before the render
- Date: 2026-10-17 · Change/PR: acquisition-polish (#256) · Status: decided (owner-delegated 2026-10-17)
- Decision: in `auto`, an HTTP `ok` page that `needs_render` would send to the browser is first offered to
  `_by_canonical` (query-dropped canonical, or `Referring` referral); an `ok` adapter answer is kept with no render.
  Otherwise the render runs, and the URL asked is not asked again after it. A shell or a block still goes to the
  browser first, since its links say little.
- Alternatives: measure first (the follow-up's suggestion).
- Why: the referral answer is what the fetch keeps either way; the render was a cost with no use (owner #54 renders to
  find rows, which the adapter gives).
- Reversible: yes

### D-1389 — A recipe learner's own error refuses the recipe
- Date: 2026-10-17 · Change/PR: acquisition-polish (#256) · Status: decided (owner-delegated 2026-10-17)
- Decision: `_learned` catches an exception of `learn_recipe` other than `LLMFailure` (which still fails the run,
  D-0738), logs it, and attaches `refused("recipe_error: <exception type>")`; the validated config activates without a
  recipe.
- Alternatives: fail the run (as before).
- Why: the HTML config validated on its own; a recipe is optional (D-0583).
- Reversible: yes
