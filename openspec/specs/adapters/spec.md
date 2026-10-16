# Adapters Specification

## Purpose

Platform adapters (Greenhouse, Lever, Shopify) and learned API recipes fetch a page's values as JSON instead of HTML.
Rationale: ARCHITECTURE §7.1, §7.2, C6 ([archived](../../changes/archive/2026-10-16-architecture-rev25/ARCHITECTURE.md));
history: SPEC-02 §4.9, SPEC-09, SPEC-15. The JSON rung and politeness are [acquisition](../acquisition/spec.md).

## Requirements

### Requirement: Adapters only for measured multi-tenant platforms (C6)
The system SHALL ship adapters only for multi-tenant platforms and run one only when `CRAWLERAI_ADAPTERS` names it
(default empty; unknown or repeated names refuse startup), after measurement on at least 3 tenants not used to build
it. API and worker processes build one registry each. Refs: §7.1, C6, D-0011, D-1084, D-1117.
#### Scenario: Default deployment
- **WHEN** `CRAWLERAI_ADAPTERS` is unset
- **THEN** no adapter runs and every page takes the page rungs

### Requirement: Adapter protocol
Each adapter SHALL implement the protocol in `adapters/base.py` (`detect`, `fetch`, `shapes`, `serves`) and MUST NOT
send requests itself: without a caller's `send` no adapter runs. Hostnames and platform names appear only under
`backend/src/crawlerai/adapters/` (C3); tests use synthetic tenants. Refs: §7.1, C3, C9, D-0265, D-1079.

### Requirement: Fallback to the page rungs (INV-40)
A page an adapter does not serve SHALL be fetched by the page rungs when `admit_next` admits it, listing the adapter
attempt first; an adapter 429/5xx pauses the endpoint host (`Retry-After`, else 30 s, at most 15 min) and is not kept.
A host answering without the platform signal is declined for 24 h (in memory); `not_served` and 429/5xx never decline.
Enforced by: `tests/unit/test_adapter_registry.py`, `tests/db/test_adapter_serving.py`; active. Refs: §7.1, D-1082, D-1111.
#### Scenario: Unserved product page
- **WHEN** the adapter's answer for `https://shop.example/products/mug` is `not_served`
- **THEN** the page is fetched over HTTP on its turn and the result lists the `api` attempt then the `http` attempt

### Requirement: Polite adapter requests
Adapter requests SHALL go through `services.fetching.adapter_send`: only where the endpoint host's robots.txt allows,
at that host's rate; a refused request is a `blocked` result that sent nothing, and the page falls back. Refs: D-1084.

### Requirement: Capture attribution (INV-39)
An `api` capture SHALL be read by an adapter only when it detects the page URL and the final URL is one of its
endpoints for that page (`serves(match, final_url)`); the same test decides `ActiveConfig.for_capture`.
Enforced by: `tests/unit/test_adapter_registry.py`, `tests/unit/test_pipeline.py`; active. Refs: §7.1, §15, D-0445, D-1112.
#### Scenario: Recipe capture of a shop-like URL
- **WHEN** a recipe capture has page URL `https://example.test/products/a` and final URL `https://example.test/v2/item`
- **THEN** no adapter reads it

### Requirement: Shapes read as schema.org nodes
An adapter SHALL state per page kind the `Shape`s that place schema.org nodes in its JSON; the adapter collector walks
them into entities and candidates with `source_kind='adapter'`, mapped like JSON-LD, listings as `ItemList` rows. A
body that does not match yields no entities, never an exception. Refs: §8.1, D-0266, D-1087, D-1115.

### Requirement: Greenhouse and Lever adapters
They SHALL detect only the hosts and URL forms their public Job Board / Postings API docs name and map `JobPosting`
fields as in `adapters/greenhouse.py` and `adapters/lever.py`; filtered Lever lists, apply pages and undocumented
regional hosts fall through to the page rungs. Refs: D-0267, D-0307, D-0310.

### Requirement: Shopify adapter
It SHALL detect product and collection paths, `POST` the tokenless Storefront GraphQL endpoint on the page's host with
the handle as a variable, and class answers `not_platform` (no `X-Shopify-API-Version`), `not_served` (no item,
GraphQL errors) or `ok`, as in `adapters/shopify.py`. Refs: Appendix A #46, D-1077, D-1078, D-1114.

### Requirement: Shopify values
Products SHALL read as a `ProductGroup` with variants under `hasVariant` (no default variant chosen; see
[variants](../variants/spec.md)), availability from `availableForSale`/`currentlyNotInStock`, and prices only when the
shop presents exactly one currency, never inferred from the URL (C7). Refs: D-1080, D-1081, D-1085, D-1114.

### Requirement: Recipe model
An `api_recipe` SHALL be data (`config_ir/api_recipe/`): a request spec, a `map` of JSONPath-subset queries and a
`proof`; it MUST refuse `Authorization`, `Proxy-Authorization`, `Cookie` and client-owned headers, and is never
executed as code. Refs: §7.2, §12.1, §18, D-0493, D-0498, D-0560.

### Requirement: Recipe discovery and binding
Learning SHALL find the endpoint whose network JSON matches a required field on every sample browser capture, then
bind its parameters deterministically from the page URL (at least two samples, exact round trip), else via LLM role D
with one repair round; a spec that does not reproduce every sample is refused. Refs: §7.2, §11, D-0541, D-0494, D-0611.

### Requirement: Headers proven by replay
Replay SHALL start with `Accept: application/json` only and add one captured header at a time until one passes;
credentials, varying and token-like values are never tried, and when none passes the recipe is `not_learnable`.
Refs: §7.2, D-0559, D-0560.
#### Scenario: Cookie needed
- **WHEN** an endpoint answers only with the captured cookie
- **THEN** the recipe is `not_learnable` and the site stays on its page rungs

### Requirement: Held-out validation
A recipe SHALL be accepted only for a detail schema whose HTML config validated, when every map field reproduces on
every held-out page (at least 3) where it was published; `validation_report.api_recipe` records the result or the
refusal reason either way. Refs: §7.2, D-0581, D-0583, D-0735.

### Requirement: Recipe execution and fallback
`acquire` SHALL run a recipe after adapters and before the page rungs over `httpx`, only for record-only reads; an
`ok` or a 429/503 is kept, anything else falls back to the configured method with the recipe attempts first. Values
resolve in the `adapter` evidence bucket. Refs: §7.2, §10, D-0599, D-0601, D-0728.

### Requirement: Recipe politeness and pagination
The endpoint host SHALL get a `site` row and obey its robots.txt and rate like a page. Pagination comes only from an
operator correction (not built yet: pagination discovery; no service calls the paged executor). Refs: D-0731, D-0603.

### Requirement: Export with a PHP hint
`platform_draft` SHALL carry the recipe as data plus, exactly when present, `api_recipe_php`, rendered with escaped
literals only; nothing generated is executed. Refs: §7.2, §12.2, D-0625, D-0627.
