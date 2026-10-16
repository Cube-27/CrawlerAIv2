# Adapters Specification

## Purpose

Platform adapters (Greenhouse, Lever, Shopify, Workday, Oracle Recruiting Cloud) and learned API recipes fetch a page's values as JSON instead of HTML.
Rationale: ARCHITECTURE §7.1, §7.2, C6 ([archived](../../changes/archive/2026-10-16-architecture-rev26/ARCHITECTURE.md));
history: SPEC-02 §4.9, SPEC-09, SPEC-15, [ats-adapters](../../changes/archive/2026-10-16-ats-adapters/proposal.md). The JSON rung and politeness are [acquisition](../acquisition/spec.md).

## Requirements

### Requirement: Adapters only for measured multi-tenant platforms (C6)
The system SHALL ship adapters only for multi-tenant platforms, measured on at least 3 tenants not used to build
them, and run every registered adapter unless `CRAWLERAI_DISABLED_ADAPTERS` names it (default empty; unknown or
repeated names refuse startup). API and worker processes build one registry each. Refs: §7.1, C6, D-0011, D-1119, Appendix A #47.
#### Scenario: Default deployment
- **WHEN** `CRAWLERAI_DISABLED_ADAPTERS` is unset
- **THEN** every registered adapter runs, and a page no adapter serves takes the page rungs

### Requirement: Adapter protocol
Each adapter SHALL implement the protocol in `adapters/base.py` (`detect`, `fetch`, `shapes`, `serves`) and MUST NOT
send requests itself: without a caller's `send` no adapter runs. Hostnames and platform names appear only under
`backend/src/crawlerai/adapters/` (C3); tests use synthetic tenants. Refs: §7.1, C3, C9, D-0265, D-1079.

### Requirement: Fallback to the page rungs (INV-40)
A page an adapter does not serve SHALL be fetched by the page rungs when `admit_next` admits it, listing the adapter
attempt first; an adapter 429/5xx pauses the endpoint host (`Retry-After`, else 30 s, at most 15 min) and is not kept.
A host answering without the platform signal is declined for 24 h (in memory); `not_served` and 429/5xx never decline.
Enforced by: `tests/unit/test_adapter_registry.py`, `tests/db/test_adapter_serving.py`; active. Refs: §7.1, D-1082, D-1111.
#### Scenario: Unserved collection page
- **WHEN** the adapter's answer for `https://shop.example/collections/mugs` is `not_served`
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
An adapter SHALL state, for the page it detected (its `AdapterMatch`), the `Shape`s that place schema.org nodes in its
JSON; the adapter collector walks them into entities and candidates with `source_kind='adapter'`, mapped like JSON-LD,
listings as `ItemList` rows. A shape may read a property from further members after its own (`also`) and put a
root before each of a property's string values (`prefixes`). A body that does not match yields no entities, never an
exception. Refs: §8.1, D-0266, D-1087, D-1115, D-1176.

### Requirement: Greenhouse and Lever adapters
They SHALL detect only the hosts and URL forms their public Job Board / Postings API docs name and map `JobPosting`
fields as in `adapters/greenhouse.py` and `adapters/lever.py`; filtered Lever lists, apply pages and undocumented
regional hosts fall through to the page rungs. Refs: D-0267, D-0307, D-0310.

### Requirement: Shopify adapter
It SHALL detect collection paths only (product pages take the page path, D-1118), `POST` the tokenless Storefront
GraphQL endpoint on the page's host with the handle as a variable, and class answers `not_platform` (no
`X-Shopify-API-Version`), `not_served` (no item, GraphQL errors) or `ok`, as in `adapters/shopify.py`. A fetched `ok`
page whose URL has a query is served by the adapter that detects it without the query when the page's canonical link
is that URL (RFC 6596, D-1120). Refs: Appendix A #46, #47, D-1077, D-1078, D-1114, D-1118, D-1120.

### Requirement: Shopify values
Collection items SHALL read as schema.org products (variants under `hasVariant`, no default variant; see
[variants](../variants/spec.md)), with prices only when the shop presents exactly one currency, never inferred from
the URL (C7). Refs: D-1080, D-1081, D-1085, D-1114, D-1118.

### Requirement: Workday adapter
It SHALL detect career sites on `{tenant}.{dc}.myworkdayjobs.com/[{locale}/]{site}` and
`{dc}.myworkdaysite.com/[{locale}/]recruiting/{tenant}/{site}` and their `/job/{location}/{slug}` pages, fetch the
site's CXS endpoints on the page's host (`POST .../jobs` for the first page of 20, `GET .../job/...`), and map rows
with their job URL (site root + `externalPath`) and jobs with title, description, locations as written, date posted,
employment type, hiring organization and URL, as in `adapters/workday.py`. A list URL with a query falls through to
the page rungs. Refs: D-1177.
#### Scenario: Listing row URL
- **WHEN** a listing answer row has `externalPath` `/job/Northtown/Engineer_R-1` for the site `https://t.wd1.myworkdayjobs.com/External`
- **THEN** the row's URL is `https://t.wd1.myworkdayjobs.com/External/job/Northtown/Engineer_R-1`

### Requirement: Oracle Recruiting Cloud adapter
It SHALL detect Candidate Experience sites on `{pod}.fa[.{dc}].oraclecloud.com/hcmUI/CandidateExperience/{lang}/sites/
{site}` (the site's URL, `/requisitions` or `/jobs`) and their `job/{id}` and `preview/{id}` pages, fetch the
documented `recruitingCEJobRequisitions` (first page of 25) and `recruitingCEJobRequisitionDetails` resources on the
page's host, map rows with their job URL (site URL + `/job/{Id}`), and class an answer without items `not_served`,
as in `adapters/oracle_recruiting.py`. Refs: D-1178.

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
