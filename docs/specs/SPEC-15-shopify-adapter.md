# SPEC-15 — Shopify adapter: storefront pages through the Storefront API

Layer: admitted candidate (ARCHITECTURE §22 "More platform adapters", admitted for Shopify by the owner 2026-10-16,
Appendix A #46); builds on SPEC-02 §4.4 and §4.9 (adapters), SPEC-05 §4.5 (adapter collector), SPEC-13 (variant
rows). Architecture refs: §7.1, §8.1, §8.2, §8.6, §10, C2, C3, C6, C7, C9.

## 1. Summary

Shops on one hosted commerce platform often state no item-level structured data on their collection (listing)
pages, so a cold listing yields no rows; their product pages state JSON-LD, but its variant data is often partial
(SPEC-13 §1 evidence). The platform gives every shop a public, documented JSON API on the shop's own domain. This
spec adds:

1. a **Shopify adapter**: collection pages of a shop are fetched as the Storefront API's GraphQL answer for that
   collection, read as schema.org `ItemList`/`Product`/`Offer` nodes. Product pages take the page path, which reads
   the fields only the page states (D-1118);
2. **schema.org shapes** for every adapter: an adapter states how its JSON holds schema.org nodes, and the adapter
   collector reads those nodes with the same path rules as JSON-LD and microdata (SPEC-05 §4.5, SPEC-13 §4.2), so
   adapters give variant rows, Offers and several types per page. Greenhouse and Lever move to shapes;
3. **fallback**: a page an adapter does not serve (any outcome but `ok`, unless it asks for fewer requests) is
   fetched by the generic rungs, as a page an API recipe does not serve is (SPEC-09 §4.10);
4. **activation**: every adapter runs unless the deployment disables it (D-1119), and the services send an adapter's requests as
   politely as a page's (robots.txt of the endpoint, the host's rate).

Nothing outside `backend/src/crawlerai/adapters/` names the platform (C3).

## 2. Scope

Core (admitted by the owner, Appendix A #46):
- Detection of collection pages by the platform's documented URL route, confirmed per response by the platform's
  documented API version header (§4.2).
- Listing: the first 250 products of a collection. Prices only from a shop that presents one currency (§4.5).
- Shapes for Greenhouse, Lever and Shopify; the adapter collector reads shapes only (the `map` method goes).
- Fallback to the generic rungs; a host whose answer lacks the platform's signal is not tried again for a while.
- `CRAWLERAI_DISABLED_ADAPTERS` (the adapters that do not run), bound into the API and worker processes with polite
  JSON requests.

Out of scope:
- Product pages (D-1118), locale-prefixed shop URLs (`/fr/collections/…`) and collection URLs with a query the
  page's canonical link keeps (`?page=2`, `sort_by`, filters): they show a localized page or a subset or order the
  unqueried collection does not reproduce. They take the generic path.
- More than 250 products of a collection (cursor paging), `/collections/all`, search and vendor pages.
- Size and colour from option names (option names are free text in the shop's language, so reading them would need
  a phrase list, C4), stock quantity (the API documents it as needing an access token), variant URLs.
- Any other platform adapter (§22 keeps Workday CXS, iCIMS, ADP, Oracle CX).

## 3. Dependencies

- SPEC-02: `acquire`, `fetch_json`, the adapter protocol and registry, politeness and robots.txt.
- SPEC-05: collectors, `schema_org_map` (`Node`, `field_candidates`, `entity_urls`), intent, listings.
- SPEC-13: row-mapped fields, rows reached through `ProductGroup.hasVariant`, atomic offers, variant fill.
- SPEC-07/SPEC-10: the services and the worker that call `acquire` (scrape, batch, crawl, extract).

## 4. Design

### 4.1 Endpoints (verified 2026-10-16)

Storefront API (shopify.dev/docs/api/storefront, version `2026-10`): one GraphQL endpoint per shop,
`POST /api/{version}/graphql.json`, answering JSON. **Tokenless access** serves products and collections without an
access token, with a query complexity limit of 1,000. Every API response carries `X-Shopify-API-Version`, the
version that served it (shopify.dev/docs/api/usage/versioning); an inaccessible version falls forward to the oldest
supported one. Fields read (Storefront API reference, `Product`, `ProductVariant`, `Collection`, `MoneyV2`):

| Object | Fields |
|---|---|
| `Product` | `id`, `title`, `onlineStoreUrl`, `featuredImage { url }` ("functionally equivalent to `images(first: 1)`"), `priceRange { minVariantPrice maxVariantPrice }` |
| `MoneyV2` | `amount` (decimal string), `currencyCode` (ISO 4217) |
| `Collection` | `products(first: 250) { nodes { … } }` |
| `Shop` | `paymentSettings { enabledPresentmentCurrencies }` ("A list of enabled currencies (ISO 4217 format) that the shop accepts") |

A tokenless request names no buyer context (`@inContext`), and the answer prices in the shop's primary market
(observed 2026-10-16: the answer's currency was the shop's primary currency whatever the requesting vantage, while
the page HTML showed the vantage's market).

The Ajax API's `/products/{handle}.js` was rejected: it states prices as integers with no currency, so the money
normalizer could not read them without a fallback currency (C7). The undocumented `products.json` endpoints were not
considered.

### 4.2 Detection

A URL is a **candidate** when it is http(s), its path is the platform's online store route for a collection
(Liquid `routes`, collection URLs), `/collections/{handle}` with a handle that is one `PATH_SEGMENT`, and it has no
query. A URL with a query is served as its canonical when the page, fetched by the page rungs, names that URL without
the query as its canonical link (RFC 6596, HTML Standard `link rel=canonical`): the page says the parameters it drops
do not identify it, and no list of parameter names decides (C4). The adapter's request then takes a turn of its own at
the host's rate, and its answer is recorded under the canonical URL (D-1120).

The path alone is not the platform: other sites use these paths. The platform's signal is in the API's answer:
- `fetch` sends the query of the page kind (§4.3) to `{scheme}://{host}/api/{version}/graphql.json` with the handle
  as a GraphQL variable (never spliced into the query text).
- An answer **without `X-Shopify-API-Version`** is not the platform's: the fetch is `error` `not_platform`, and the
  registry declines the adapter for that host for 24 hours (in-process, at most 10,000 hosts, oldest dropped first).
  A non-platform site therefore gets at most one such request per process per day.
- An answer with the header whose `data` holds no collection for the handle, or that holds GraphQL `errors`, is
  `error` `not_served`: the platform answered, but not for this page. The host is not declined.
- An answer with status 429 or 5xx (RFC 6585 §4, RFC 9110 §15.6) is kept as it is, header or not: it says the server
  cannot answer now, not whether it is the platform's. The host is not declined, and the page falls back (§4.6).
- Otherwise the answer is `ok`, a capture with method `api`, recorded under the page URL (SPEC-02 §4.9).

`*.myshopify.com` hosts need no special case: the same routes and the same signal apply.

### 4.3 Queries

One fixed GraphQL document in the adapter, well under the complexity limit: `collection(handle: $handle) {
products(first: 250) { nodes { id title onlineStoreUrl featuredImage priceRange } } }`, which also asks for `shop {
paymentSettings { enabledPresentmentCurrencies } }`. A version change is a one-line change of the adapter's `API_VERSION`.

### 4.4 Shapes: an adapter's JSON as schema.org nodes

An adapter states, per page kind, `shapes(page_kind) -> tuple[Shape, ...]`:

```python
Shape(type="ItemList", at=("data", "collection", "products"),
      nodes={"itemListElement": (Shape(type="Product", at=("nodes", "*"),
                                       properties={"name": ("title",), "url": ("onlineStoreUrl",)}, ...),)})
```

- `at`: member names from the enclosing node's JSON object (the document for a root) to this node's object; `*`
  takes every item of an array.
- `properties`: schema.org property → member names to its values from the node's object; `*` as above. `null` is
  no value (RFC 8259: the API states none).
- `nodes`: schema.org property → the nested node shapes its values are.
- `anchor`: for a node that is a view of its enclosing object (`at=()`), the member that names it, so its entity
  has an id of its own (Greenhouse's Organization at the job's `company_name`).

`shapes(page_kind, answer)` sees the answer, so the shapes may depend on what it states (§4.5, listing prices).

The adapter collector (`collect/adapter.py`) walks the shapes over the document: each object a shape reaches is an
entity (`adapter:<name>:<normalized path>`, kind its type, parent the enclosing entity, `via` the property), and a
`Node` for `schema_org_map`. Candidates come from `field_candidates(..., source_kind="adapter")`, so a field's
alternatives, sub-properties of identifiers, `.name` stand-ins, list fields, and the sub-fields of a row-mapped
field (SPEC-13 §4.2) read adapter JSON exactly as they read JSON-LD. Each value's locator is
`adapter:<name>:<normalized path of the value>` (SPEC-05 §4.3). Entity URLs are `entity_urls` of the node.

A listing's rows are listed: every adapter's listing shape is an `ItemList` whose `itemListElement` nodes are the
rows (schema.org ItemList), so the rows do not depend on SPEC-05 §4.7's three-row rule.

### 4.5 Shopify shapes

**Detail**: not served (D-1118). The round-3 measurement (D-1117) showed the answer lacks values only the page
states (its default variant's sku, condition, rating, review count), so a product page takes the page path.

**Currency.** The answer prices in the shop's primary market (§4.1); a page shows its visitor's market, in that
market's currency when the shop presents several. Nothing in the answer says which market a page showed, and the
page URL is not read for one (C7). So prices are read only from a shop whose `enabledPresentmentCurrencies` is one
currency: then every page of the shop states that currency. Otherwise a collection answer keeps its rows without their
Offers (the generic path gives a collection page no item rows).

**Listing** (`commerce_listing`): an `ItemList` at `data.collection.products` whose `itemListElement` nodes are
`Product`s (`name`, `url` ← `onlineStoreUrl`, `image` ← featured image), each with two `Offer`s under `offers`, at
`priceRange.minVariantPrice` and `priceRange.maxVariantPrice` (none for a shop with several currencies, above). The
row's `price` publishes only when the two bounds agree (the exact-match rule, INV-14): equal bounds are the one price
of every variant; different ones are a range, and no single row price is chosen.

### 4.6 Acquisition and fallback (SPEC-02 §4.4)

`acquire(url, policy, remembered, rungs, *, send=…)`: when the registry has an adapter for `url` (detected, and not
declined for the host), its `fetch(url, policy, send)` goes first. Its result is kept when it is `ok`, or when
`admit_next` refuses a further request. Otherwise the page is fetched by the page rungs (HTTP, browser) as if there
were no adapter, after `admit_next`, and the result lists both attempts. A slow-down (429/503) of the endpoint falls
back too: its `Retry-After`, else the first backoff, pauses the endpoint host's rate (at most the longest backoff,
SPEC-02 §4.6), and the page, a request of its own, waits that out through `admit_next` (§4.9). A site's API recipe is not tried after an
adapter. `send` is the JSON fetch adapters use; without it no adapter runs.

`send` in the services (`services.fetching.adapter_send`): the endpoint is fetched only where its host's robots.txt
allows it, at the host's rate; the first request takes the turn the caller was admitted for (the page's host), as a
recipe's first request does (SPEC-09 §4.8). A robots.txt refusal is a `blocked` result that sent nothing, and the page
falls back.

### 4.7 Reading a capture (SPEC-05 §4.5, D-0445)

An `api` capture is read by an adapter only when the adapter detects its page URL (`url`) **and** its final URL is
one of the adapter's endpoints for that page (`serves(match, final_url)`: the board's or site's own endpoints on the
documented API host for Greenhouse and Lever; the path `/api/{YYYY-MM}/graphql.json` on the page's host for
Shopify). An API recipe's capture of a page whose URL looks
like a shop route is therefore never read as the adapter's. The same test decides `ActiveConfig.for_capture`.

### 4.8 Activation (C6)

Every registered adapter runs (owner, 2026-10-16, D-1119); `CRAWLERAI_DISABLED_ADAPTERS` (comma-separated names,
default none) names the ones that do not. An unknown or repeated name fails at start. The API and worker processes
build one registry from it (its decline memory lives as long as the process); `EngineData` carries the same registry,
so captures are read with it.

### 4.9 Error handling

- Every network, status, size and decode failure is `fetch_json`'s (SPEC-02 §4.7) and falls back (§4.6).
- A body that is not JSON, or whose shape does not match, yields no entities (collector diagnostic), never an
  exception.
- A shop that rate-limits the API (429, or GraphQL `THROTTLED` with status 200 and `errors`), or an endpoint answering
  a 5xx, gives a 429/5xx outcome or `not_served`: either way the page falls back on its turn at the host's rate, and the
  host is not declined. A worker task whose page was fetched `ok` after an endpoint's slow-down keeps that page.

## 5. Invariants

New (appended to `docs/INVARIANTS.md`):
- **INV-39**: An `api` capture is read by an adapter only when that adapter detects the capture's page URL and its
  final URL is one of the adapter's endpoints.
- **INV-40**: A page an adapter does not serve (an outcome other than `ok`) is fetched by the page rungs when the
  site's rate admits it, and its result lists every attempt; a host whose answer lacks the platform's signal is
  not sent to that adapter again within the decline window.

Existing invariants that apply: INV-11, INV-13, INV-14, INV-15, INV-16, INV-22, INV-23, INV-29, INV-30, INV-33,
INV-35, INV-38.

## 6. Testing strategy

All fixtures are synthetic: hosts under `example.test`, invented products and handles, JSON written to the
documented shapes (C3, C9). Tests name the adapter, a platform, never a shop.
- **Property (Hypothesis)**: detection over generated paths (only the §4.2 routes with one valid handle detect;
  a dot-segment or a second segment never does); listing rows equal the products, each with its own price only when
  its bounds agree.
- **Unit**: the decline rule (no header → `not_platform` and the host declined; header with a null collection →
  `not_served`, host kept; expiry and the size bound); `acquire` falls back on a non-`ok` adapter result and keeps a
  429; a page whose canonical drops only its query is served by the canonical's adapter; `serves`/`reader`
  attribution; shapes for Greenhouse and Lever give the candidates their maps gave.
- **Replay** (`tests/replay`): a synthetic listing capture through `extract_page` with `commerce_listing`: listing
  rows, with and without prices.

## 7. Acceptance criteria

- ~~On a synthetic product answer with three variants of one price, …~~ Product pages are not served (D-1118).
- On a synthetic collection answer, every product is a row with `title` and `url`; `price` publishes only for rows
  whose bounds agree.
- A non-platform answer falls back to the page rungs; the host is not tried again within the window.
- INV-39 and INV-40 each have a test that fails when the rule is removed.
- C6: measured on at least three shops not used to build the adapter (counts of rows per listing and field coverage
  on detail pages, adapter vs the generic path), aggregate only, in the PR.

## 8. PR plan

| # | Title | Scope | Checks | Done when |
|---|---|---|---|---|
| 1 | Shapes for adapters; fallback; attribution | `adapters/base` (`Shape`, protocol `fetch(url, policy, send)`, `shapes`, `serves`), `adapters/registry` (`reader`, declines), Greenhouse and Lever as shapes, `collect/adapter` (shapes), `collect/run`, `resolve/task`, `acquire/rungs` (fallback), SPEC-02/05/13 text | unit, property | Greenhouse/Lever candidates unchanged; INV-39, INV-40 tests pass. |
| 2 | Shopify adapter | `adapters/shopify` (detection, queries, shapes, availability), registry | unit, property, replay | §7 detail and listing criteria pass on synthetic answers. |
| 3 | Activation and polite sending | `core/settings` (`adapters`), `acquire` registry builder, `services/fetching.adapter_send`, scrape and worker call sites, `EngineData` registry | unit | A configured adapter runs in scrape and the worker, through robots.txt and the host's rate. |
| 4 | C6 measurement and activation note | PR evaluation section; Appendix A #46 note | eval (local, aggregate only) | ≥ 3 unseen shops measured. |

Rows 1–3 depend on each other in order; row 4 needs row 3.

## 9. Open issues

- **Collections over 250 products.** The API pages by cursor; the shop's own `?page=N` pages do not map onto
  cursors without fetching every earlier page. A listing crawl through the adapter stops at 250 products. Measure
  how often a collection is larger before adding cursor paging.
- **Locale-prefixed URLs.** The API serves a locale through `@inContext`; mapping a URL prefix to a language and
  country is left out until a dev page needs it.
- **Product pages.** Served by the page path (D-1118). Joining the adapter's answer to the page's own collectors (one
  more source beside the page capture) would add the answer's variants and identifiers where the theme states none;
  it needs a capture holding both and a measure of cross-source conflicts first.
