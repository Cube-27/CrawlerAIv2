# Adapters Specification

## Purpose

Platform adapters fetch a multi-tenant platform's page as its documented public JSON API answer and state how that
JSON holds schema.org nodes, so the adapter collector reads it like structured data. Built adapters: Greenhouse and
Lever (job boards) and Shopify (storefront products and collections). This capability owns detection, the adapter
rung's fallback and decline rules, activation, capture attribution and each adapter's shapes; the JSON fetch, SSRF
and politeness rules are [acquisition](../acquisition/spec.md), and how candidates resolve is
[resolution](../resolution/spec.md) and [variants](../variants/spec.md).
Design rationale: [ARCHITECTURE §7.1](../../design/acquisition.md), [C6](../../design/generalization.md). History:
[SPEC-02](../../changes/archive/2026-10-13-spec-02-acquisition/SPEC-02-acquisition.md) §4.9 and its
[decisions](../../changes/archive/2026-10-13-spec-02-acquisition/decisions.md);
[SPEC-15](../../changes/archive/2026-10-16-spec-15-shopify-adapter/SPEC-15-shopify-adapter.md) and its
[decisions](../../changes/archive/2026-10-16-spec-15-shopify-adapter/decisions.md).

## Requirements

### Requirement: Adapters only for measured multi-tenant platforms (C6)
The system SHALL ship adapters only for multi-tenant platforms, and an adapter SHALL run only when
`CRAWLERAI_ADAPTERS` (comma-separated names, default empty) names it; an unknown or repeated name is refused at
startup. A name is listed only after the adapter was measured on at least 3 tenants not used to build it, with the
aggregate measurement in the PR that activates it. The API and worker processes each build one registry from the
setting, and `EngineData` reads captures with the same registry.
Refs: §7.1, C6, Appendix A #46, SPEC-15 §4.8, D-0011, D-1084, D-1088, D-1117.

#### Scenario: Default deployment
- **WHEN** `CRAWLERAI_ADAPTERS` is unset
- **THEN** no adapter runs and every page takes the page rungs

#### Scenario: Unknown name
- **WHEN** `CRAWLERAI_ADAPTERS=greenhouse,acme`
- **THEN** the process refuses to start

### Requirement: Adapter protocol
Each adapter SHALL provide `name`, `detect(url)` returning a match (tenant and page kind `detail` or `listing`) or
none, `fetch(url, policy, send)` returning a `FetchResult` with method `api` and the JSON as body, `shapes(page_kind,
answer)` and `serves(match, endpoint)`. An adapter MUST NOT send requests itself: no adapter runs without a `send`
from the caller. Hostnames and platform names appear only under `backend/src/crawlerai/adapters/` (C3); adapter
tests use synthetic tenants and name the platform, never a site.
Refs: §7.1, C3, C9, SPEC-02 §4.9, SPEC-15 §4.4, D-0265, D-1079.

#### Scenario: No send
- **WHEN** `acquire` is called without `send`
- **THEN** no adapter is consulted

### Requirement: Fallback to the page rungs (INV-40)
A page an adapter does not serve (an outcome other than `ok`) SHALL be fetched by the page rungs when the site's
rate admits it (`admit_next`), and its result SHALL list every attempt, the adapter's first. An adapter's 429 or 5xx
is not kept: it pauses the endpoint host's rate by its `Retry-After`, else the first backoff (30 s), at most 15 min,
and the page waits that out. When `admit_next` refuses, the adapter result is kept. An API recipe is not tried after
an adapter. A host whose answer lacks the platform's signal SHALL NOT be sent to that adapter again within the
decline window.
Enforced by: unit and DB tests (`tests/unit/test_adapter_registry.py`, `tests/db/test_adapter_serving.py`); status:
built (SPEC-15, tests: SPEC-15 PR 1).
Refs: §7.1, C6, Appendix A #46, SPEC-15 §4.6, §4.9, D-1082, D-1111.

#### Scenario: Unserved product page
- **WHEN** the adapter's answer for `https://shop.example/products/mug` is `not_served`
- **THEN** the page is fetched over HTTP on its turn and the result lists the `api` attempt then the `http` attempt

#### Scenario: Endpoint slow-down
- **WHEN** the endpoint answers 429 with `Retry-After: 60`
- **THEN** the page is fetched no sooner than 60 s later and the host is not declined

### Requirement: Decline window
The registry SHALL decline an adapter for a host for 24 hours after an answer classed `not_platform`, in process
memory, holding at most 10,000 hosts and dropping the oldest first. `not_served` answers and 429/5xx answers MUST NOT
decline the host. Declines apply to serving, not to reading captures.
Refs: SPEC-15 §4.2, D-1078, D-1083, D-1111.

#### Scenario: Non-platform host
- **WHEN** `https://www.example.com/products/a` gets an answer without the platform's signal
- **THEN** the page falls back, and another URL on that host within 24 h is not sent to the adapter

### Requirement: Polite adapter requests
In the services, an adapter's requests SHALL go through `services.fetching.adapter_send`: only where the endpoint
host's robots.txt allows them, at that host's rate, the first request taking the turn the caller was admitted for on
the page's host. A request robots.txt refuses is a `blocked` result that sent nothing, and the page falls back.
Refs: SPEC-15 §4.6, D-1084, D-0731.

#### Scenario: Endpoint disallowed
- **WHEN** the endpoint host's robots.txt disallows the API path
- **THEN** no API request is sent and the page is fetched by the page rungs

### Requirement: Capture attribution (INV-39)
An `api` capture SHALL be read by an adapter only when that adapter detects the capture's page URL (`url`) and its
final URL is one of the adapter's endpoints for that page (`serves(match, final_url)`): the board's or site's own
endpoints on the documented API host for Greenhouse and Lever, the path `/api/{YYYY-MM}/graphql.json` on the page's
own host for Shopify. The same test decides `ActiveConfig.for_capture`.
Enforced by: unit tests (`tests/unit/test_adapter_registry.py`, `tests/unit/test_pipeline.py`); status: built
(SPEC-15, tests: SPEC-15 PR 1).
Refs: §7.1, §15, Appendix A #46, SPEC-15 §4.7, D-0445, D-1083, D-1112.

#### Scenario: Recipe capture of a shop-like URL
- **WHEN** an API recipe's capture has page URL `https://example.test/products/a` and final URL `https://example.test/v2/item`
- **THEN** no adapter reads it

### Requirement: Shapes read as schema.org nodes
An adapter SHALL state per page kind a tuple of `Shape`s: `type`, `at` (member path, `*` for every array item),
`properties` (schema.org property to member path; `null` is no value), nested `nodes`, an `anchor` for a view of its
enclosing object, `stated` values for a documented non-schema.org form, and `every` for a list field's full values.
The adapter collector walks them: each object reached is an entity `adapter:<name>:<normalized path>` with its type
as kind, values are candidates with `source_kind='adapter'` and locator `adapter:<name>:<normalized path>`, mapped by
the same `schema_org_map` rules as JSON-LD. A listing shape is an `ItemList` whose `itemListElement` nodes are the
rows. A row field whose published sub-fields are all an adapter's has evidence `adapter`. A body that is not JSON or
does not match yields no entities (a diagnostic), never an exception.
Refs: §8.1, SPEC-15 §4.4, §4.9, D-0266, D-1079, D-1087, D-1115.

#### Scenario: Listing rows
- **WHEN** a listing answer holds 12 items
- **THEN** the collector gives 12 rows regardless of the three-row rule

### Requirement: Greenhouse adapter
The Greenhouse adapter SHALL detect hosted boards only on the hosts the Job Board API docs name, and fetch
`GET /v1/boards/{board_token}/jobs?content=true` for a board (listing) or `GET /v1/boards/{board_token}/jobs/{job_id}`
for a job (detail). It maps `JobPosting` `title`, `url` (`absolute_url`), `description` (`content`), `jobLocation`
(`location.name`), `datePosted` (`first_published`), `dateModified` (`updated_at`) and `hiringOrganization.name`
(`company_name`). A board on a regional host the docs do not name MUST fall through to the page rungs.
Refs: SPEC-02 §4.9, D-0267, D-0310.

#### Scenario: Job URL
- **WHEN** a hosted board job URL with a numeric job id is fetched
- **THEN** the adapter requests that job from the Job Board API and the capture is a detail `api` capture

### Requirement: Lever adapter
The Lever adapter SHALL detect job sites on the global and EU instance hosts, each sent to its own instance's
Postings API: `GET /v0/postings/{site}?mode=json` (listing) or `GET /v0/postings/{site}/{posting_id}` (detail). It
maps `JobPosting` `title` (`text`), `url` (`hostedUrl`), `description` and `jobLocation` (`categories.location`) only.
A job site URL carrying `location`, `commitment`, `team`, `department`, `level` or `group`, and the
`/{site}/{id}/apply` form, MUST NOT be detected.
Refs: SPEC-02 §4.9, D-0307, D-0308, D-0309.

#### Scenario: Filtered list
- **WHEN** a Lever job site URL has `?team=x`
- **THEN** no adapter detects it and the page rungs fetch it

### Requirement: Shopify detection and confirmation
The Shopify adapter SHALL treat an http(s) URL as a candidate when its path is `/products/{handle}` or
`/collections/{c}/products/{handle}` (detail, any query) or `/collections/{handle}` with no query (listing), each
handle one path segment. It SHALL `POST {scheme}://{host}/api/2026-10/graphql.json` (tokenless Storefront API) with
the handle as a GraphQL variable, never spliced into the query. The answer is: `not_platform` without
`X-Shopify-API-Version`; kept as is when 429 or 5xx, header or not; `not_served` when it has the header but no product
or collection for the handle, GraphQL `errors` (including `THROTTLED`), or a product answer from a shop that does not
present exactly one currency; `ok` otherwise. Locale-prefixed URLs, collection URLs with a query, `/collections/all`,
search and vendor pages are not detected.
Refs: Appendix A #46, SPEC-15 §2, §4.1–§4.3, D-1077, D-1078, D-1111, D-1114.

#### Scenario: Missing signal
- **WHEN** a `/products/x` page's host answers the endpoint 200 without `X-Shopify-API-Version`
- **THEN** the result is `error` `not_platform` and the host is declined

### Requirement: Shopify detail shapes
A product answer SHALL read as a schema.org `ProductGroup` (`name`, `description`, `url` from `onlineStoreUrl`,
`productID`, `brand` from `vendor`, `image` with the featured image as main value and every image in shop order for a
list field) with up to 250 variants as `Product`s under `hasVariant` (`name` from `title`, `sku`, `gtin` from
`barcode`, `productID`), each with one `Offer` anchored at `price` (`price.amount`, `price.currencyCode`,
`availability`). A variant titled `Default Title` has no `name`. The adapter chooses no default variant; publishing
follows the variant rules in [variants](../variants/spec.md). Stock quantity and option names are not read.
Refs: Appendix A #44, #46, SPEC-15 §4.5, D-1085, D-1113, D-1115, D-1116.

#### Scenario: Three variants, one price
- **WHEN** a product answer has three variants priced 10.00 USD
- **THEN** top-level `price` publishes with evidence `adapter` and `variants` has three rows

### Requirement: Shopify availability
A variant's `availability` SHALL be `OutOfStock` when `availableForSale` is false, `BackOrder` when it is true and
`currentlyNotInStock` is true, and `InStock` when true and false; anything else states nothing. The locator is
`currentlyNotInStock` for `BackOrder`, `availableForSale` otherwise.
Refs: C2, SPEC-15 §4.5, D-1080.

#### Scenario: Backorder
- **WHEN** a variant has `availableForSale: true` and `currentlyNotInStock: true`
- **THEN** its availability is schema.org `BackOrder`

### Requirement: Shopify prices only in the shop's one currency
Both queries SHALL ask for `shop.paymentSettings.enabledPresentmentCurrencies`, and prices SHALL be read only when it
holds exactly one currency. Otherwise a product answer is `not_served` (the page falls back and its own price is
read), and a collection answer keeps its rows without Offers. The page URL MUST NOT be read for a market or currency.
Refs: C7, SPEC-15 §4.5, D-1114.

#### Scenario: Multi-currency shop
- **WHEN** a shop presents EUR and USD
- **THEN** a product page takes the page rungs and listing rows publish no price

### Requirement: Shopify listing shapes
A collection answer SHALL read as an `ItemList` at `data.collection.products` of up to the first 250 products, each a
`Product` (`name`, `url` from `onlineStoreUrl`, `image` from the featured image) with two `Offer`s at
`priceRange.minVariantPrice` and `priceRange.maxVariantPrice`. A row's `price` publishes only when the two agree.
Refs: SPEC-15 §2, §4.5, §9, D-1081.

#### Scenario: Price range
- **WHEN** a listed product's range is 10.00 to 15.00
- **THEN** that row publishes no `price`
