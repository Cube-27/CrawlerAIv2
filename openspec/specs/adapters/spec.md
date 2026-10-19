# Adapters Specification

## Purpose

Platform adapters (Greenhouse, Lever, Shopify, Workday, Oracle Recruiting Cloud, Ashby, SmartRecruiters, Recruitee, Workable, Rippling, BambooHR, Teamtailor, UKG Pro, Personio, ADP Workforce Now) and learned API recipes fetch a page's values as JSON instead of HTML.
 The JSON rung and politeness are [acquisition](../acquisition/spec.md).

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
A host answering without the platform signal is declined for 24 h, stored on its site row (`site.adapter_declined`)
and read by every process; `not_served` and 429/5xx never decline.
Enforced by: `tests/unit/test_adapter_registry.py`, `tests/db/test_adapter_serving.py`; active.
Refs: §7.1, D-1078, D-1082, D-1111, D-1384.
(Previously: declined in each process's memory.)
#### Scenario: Unserved collection page
- **WHEN** the adapter's answer for `https://shop.example/collections/mugs` is `not_served`
- **THEN** the page is fetched over HTTP on its turn and the result lists the `api` attempt then the `http` attempt

### Requirement: Polite adapter requests
Adapter requests SHALL go through `services.fetching.adapter_send`: only where the endpoint host's robots.txt allows,
at that host's rate; a refused request is a `blocked` result that sent nothing, and the page falls back. A request on
the page's own host goes by the robots.txt and interval the caller read for the page, without reading them again.
Refs: D-1084, D-1384.
(Previously: the page host's rules were read again.)

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
root before each of a property's string values (`prefixes`); an amount the API's documentation states as an integer
count of the currency's minor unit is scaled to the major unit by the places the documentation states, a constant or
a member of the node (`minor_units`), and any other value of that property is dropped; an amount no documentation
gives a unit for is never scaled; a field that reads a whole node whose shape maps
properties reads an object of those properties' schema.org names. Each entity carries what identifies its item as a
JSON-LD entity does (its identifier values and item URLs), so resolution merges it with the page's own statement of the
item. A body that does not match yields no entities, never an exception. Refs: §8.1, D-0266, D-1087, D-1115, D-1176,
D-1304, D-1336.
(Previously: an adapter's entities carried no identity and could not merge with the page's JSON-LD.)
#### Scenario: One item in the API and in the page
- **WHEN** a detail page's JSON-LD `JobPosting` and the adapter's posting state one identifier or one item URL
- **THEN** they are one entity, with the values of both

### Requirement: Greenhouse and Lever adapters
They SHALL detect only the hosts and URL forms their public Job Board / Postings API docs name and map `JobPosting`
fields as in `adapters/greenhouse.py` and `adapters/lever.py`; filtered Lever lists, apply pages and undocumented
regional hosts fall through to the page rungs. A job read for a hosted Greenhouse board page SHALL have the board's job
route on the page's host as its URL; one read for an embedded board keeps the API's `absolute_url`. A posting answer's
documented apply link (Lever and SmartRecruiters `applyUrl`) is its ApplyAction's `target` (`adapters.base.apply_action`).
(Previously: apply links were not mapped.) Refs: D-0267, D-0307, D-0310, D-1483, D-1493.

### Requirement: Shopify adapter
It SHALL detect collection paths only, also under a locale subfolder (`/{language}[-{region}]/collections/{handle}`;
product pages take the page path, D-1118), `POST` the tokenless Storefront GraphQL endpoint on the page's host with the
handle as a variable, page through the products' cursor up to the adapter row cap, ask a locale-prefixed page in its
language (`@inContext(language:)`), and class answers `not_platform` (no `X-Shopify-API-Version`), `not_served` (no
item, GraphQL errors, another language than the page's, a shop presenting other than exactly one currency, whose
page the page path reads, or a listed product without a price above zero, which the page may still show: an answer
never takes the page path's prices away) or `ok`, as in `adapters/shopify.py`. A fetched `ok` page
whose URL has a query is served by the adapter that detects it without the query when the page's canonical link is
that URL (RFC 6596, D-1120). Refs: Appendix A #46, #47, D-1077, D-1078, D-1114, D-1118, D-1120, D-1385, D-1386.
(Previously: the first 250 products, and no locale-prefixed URL; a shop of several currencies was served without
prices; an answer with zero prices was served.)

### Requirement: Shopify values
Collection items SHALL read as schema.org products (variants under `hasVariant`, no default variant; see
[variants](../variants/spec.md)), with prices only when the shop presents exactly one currency, never inferred from
the URL (C7); a stored answer of a shop of several currencies reads without prices. Refs: D-1080, D-1081, D-1085, D-1114, D-1118.

### Requirement: Workday adapter
It SHALL detect career sites on `{tenant}.{dc}.myworkdayjobs.com/[{locale}/]{site}` and
`{dc}.myworkdaysite.com/[{locale}/]recruiting/{tenant}/{site}` and their `/job/{location}/{slug}` pages, fetch the
site's CXS endpoints on the page's host (`POST .../jobs` in pages of 20 by `offset`, the first page's `total` ending the
list, else a short page; `GET .../job/...`), and map rows with their job URL (site root, led by the page's own locale when its path has one, + `externalPath`, so a row's URL equals the link the page renders) and jobs with
title, description, locations as written, date posted, employment type, hiring organization and URL, as in
`adapters/workday.py`. It SHALL refer a page on another host to the career site it names as itself or, for a listing,
the one site all its Workday links belong to (in the locale those links all state, when they agree). A list URL with a query falls through to the page rungs. Refs: D-1177,
D-1300, D-1302.
(Previously: the first page of 20 only, and career sites on the platform's hosts only; row URLs without the page's locale.)
#### Scenario: Listing row URL
- **WHEN** a listing answer row has `externalPath` `/job/Northtown/Engineer_R-1` for the site `https://t.wd1.myworkdayjobs.com/External`
- **THEN** the row's URL is `https://t.wd1.myworkdayjobs.com/External/job/Northtown/Engineer_R-1`
#### Scenario: Pages until a short page
- **WHEN** a site holds 45 postings
- **THEN** offsets 0, 20 and 40 are requested and the capture holds 45 postings

### Requirement: Oracle Recruiting Cloud adapter
It SHALL detect Candidate Experience sites on `{pod}.fa[.{dc}].oraclecloud.com/hcmUI/CandidateExperience/{lang}/sites/
{site}` (the site's URL, `/requisitions` or `/jobs`) and their `job/{id}` and `preview/{id}` pages, fetch the
documented `recruitingCEJobRequisitions` (pages of 100 by `offset` until the first item's `TotalJobsCount`) and
`recruitingCEJobRequisitionDetails` resources on the page's host, map rows with their job URL (site URL + `/job/{Id}`),
and class an answer without items `not_served`, as in `adapters/oracle_recruiting.py`. Refs: D-1178, D-1300, D-1307.
(Previously: the first page of 25 only.)

### Requirement: Paged adapter lists
An adapter whose API serves a list in pages SHALL fetch the pages through the caller's `send` (so robots.txt and the
host's rate hold per request) and return them as one `api` capture: the first page's manifest, a merged body and every
attempt. The walk ends at the adapter's last page, when the rows reach `fetch.max_rows` (a soft target: whole pages are
kept) or the hard cap of 1000 rows, on an empty page, or after 30 s; a later page that fails ends it with the pages
read, and only the first page decides the outcome. Refs: D-1300, D-1301.
#### Scenario: Row target
- **WHEN** a list of 1000 postings is fetched with `max_rows` 30 and the pages hold 20
- **THEN** two pages are requested and the capture holds 40 postings
#### Scenario: Later page fails
- **WHEN** the third page of a list is not JSON
- **THEN** the capture is `ok` with the first two pages' rows

### Requirement: Referral from a tenant's own host
An adapter MAY state, from what a fetched page declares about itself (its final URL after redirects, `link
rel=canonical`, `og:url`) and the targets of its links, the platform page the page stands for (`Referring.referred`);
a page the adapter did not detect by URL is then served by that adapter, recorded under the platform page, when the
page is `ok`, the site's rate admits the request and the platform's host is not declined. An HTTP page that would be
rendered for lacking what the caller reads asks its referral or canonical URL first, and is rendered only when no
adapter serves it. Only structure decides, never a list of hosts or words. Refs: D-1302, D-1388.
(Previously: the page was rendered first.)
#### Scenario: Branded careers page
- **WHEN** a listing page on another host links only to job and sign-in pages of one Workday career site
- **THEN** that site's list is served by the Workday adapter and the result lists the page attempt then the `api`
  attempts, with no render
#### Scenario: Two sites
- **WHEN** a listing page links to two Workday career sites
- **THEN** no site is referred and the page stays as fetched

### Requirement: Ashby, SmartRecruiters, Recruitee, Workable and Rippling adapters
They SHALL detect only the hosted forms their public APIs name (Ashby boards, SmartRecruiters company and posting
pages, Recruitee company hosts, Workable account pages, Rippling boards and jobs), fetch the documented JSON
(SmartRecruiters in pages of 100) and map `JobPosting` title, location(s), date posted, employment type, description,
identifier and URL, and the salary where the API states an amount, as in `adapters/{ashby,smartrecruiters,recruitee,
workable,rippling}.py`; pages the API has no endpoint for fall to the page rungs. Refs: D-1303, D-1305, D-1306, D-1308.

### Requirement: BambooHR, Teamtailor, UKG Pro, Personio and ADP adapters
They SHALL detect only the hosted forms their public data names (BambooHR career sites, Teamtailor company hosts' job
lists, UKG Pro job boards and their opportunity pages, Personio company hosts' lists, ADP Workforce Now career centers
by company and center id), fetch the documented JSON, JSON Feed, search API, embedded opportunity or XML feed (UKG in
pages of 50 by `Top` and `Skip`; a list that holds no row, a redirect to the platform's own site, or a page that embeds
nothing is `not_served`) and map `JobPosting` title, locations, date posted, employment type, description, identifier,
URL and the pay where the platform states one, as in `adapters/{bamboohr,teamtailor,ukg,personio,adp}.py`; Teamtailor
and Personio have no endpoint for one job, so a job page falls to the page rungs. Refs: D-1330, D-1333, D-1334, D-1335.
#### Scenario: Board without a careers site
- **WHEN** a company's careers list endpoint answers a redirect to the platform's own site
- **THEN** the adapter's answer is `not_served` and the page is fetched by the page rungs
#### Scenario: Job id from the page
- **WHEN** a career center page names a `jobId` that one requisition of the list states as its external id
- **THEN** that requisition's endpoint is fetched and its capture carries the id for the job's URL

### Requirement: Answers that are not JSON
A request MAY be `raw` (`JsonRequest.raw`): a 2xx answer is then `ok` whatever its body, every other status classifies as
for JSON. An adapter that sends one SHALL record a capture whose body is the JSON its shapes read (the feed read by the
bounded XML reader, the object a page embeds), or answer `not_served`; the collector only ever reads JSON. The XML
reader SHALL resolve no entity, load no DTD, reach no network, refuse a DOCTYPE and bound nesting. Refs: D-1331, D-1332.
#### Scenario: XML with entities
- **WHEN** a feed declares an entity or a DOCTYPE
- **THEN** it is not read and the adapter's answer is `not_served`

### Requirement: Recipe model
An `api_recipe` SHALL be data (`config_ir/api_recipe/`): a request spec, a `map` of JSONPath-subset queries, an
optional `pagination` of kind `param` (a page number or offset), `cursor`, `next_url` or `link` (RFC 8288), set in the
query or the JSON body (`model.py`), and a `proof`; it MUST refuse `Authorization`, `Proxy-Authorization`, `Cookie`
and client-owned headers, and is never executed as code. Refs: §7.2, §12.1, §18, Appendix A #59, D-0493, D-0498,
D-0560, D-1360.

### Requirement: Recipe discovery and binding
Learning SHALL find the endpoint whose network JSON matches a required field on every sample browser capture, then
bind its parameters deterministically from the page URL (at least two samples, exact round trip), else via LLM role D
with one repair round; a spec that does not reproduce every sample is refused. A query value that looks like a token
and is the same on every sample is bound from a page value that holds it on every sample, else left out of the
endpoint URL before binding and role D (`binding.withhold_tokens`), so no recipe stores it and the replay decides. A
listing's endpoint is the call series whose rows match published row values on every sample capture with calls, its
pagination inferred from a series of two or more calls (`pagination.py`), bound from two listing URLs at least
(`listing.py`). A page whose capture holds no calls (for a listing, no second call) is rendered in the browser with
capture, a listing with its browser actions: at most 3 sample and 3 held-out pages per run. (Previously: a constant
query value was always a literal.) Refs: §7.2, §11, Appendix A #59, D-0541, D-0494, D-0611, D-1361, D-1364, D-1366,
D-1407.
#### Scenario: Paged calls of a listing
- **WHEN** listing pages loaded their rows from `/search?cat=<category>&page=1` and `&page=2`
- **THEN** the recipe binds `cat` from the page URL and paginates `page` from 1 by 1
#### Scenario: A key in the endpoint URL
- **WHEN** every sample's endpoint URL carries the same 24-character `key` value that no page value holds
- **THEN** the bound URL has no `key` item, and the stored recipe does not hold the value

### Requirement: Headers proven by replay
Replay SHALL start with `Accept: application/json` only and add one captured header at a time until one passes;
credentials, varying and token-like values are never tried, and when none passes the recipe is `not_learnable`.
Refs: §7.2, D-0559, D-0560.
#### Scenario: Cookie needed
- **WHEN** an endpoint answers only with the captured cookie
- **THEN** the recipe is `not_learnable` and the site stays on its page rungs

### Requirement: Held-out validation
A recipe SHALL be accepted only for a schema whose HTML config validated, when every map field reproduces on every
held-out page (at least 3) where it was published, a detail answer also stating the page's product as serving
requires (for a listing: replaying its first two pages gives the rows of the
page's captured calls, in order, each mapped raw value equal); `validation_report.api_recipe` records the result or
the refusal reason either way, and an error of the recipe learner that is neither an LLM failure nor a database
error (a replay's usage not stored fails the run) refuses the recipe (`recipe_error: <type>`) without failing the run.
Refs: §7.2, Appendix A #59, D-0581, D-0583, D-0735, D-1365, D-1389, D-1584.
(Previously: such an error failed the learning run.)
#### Scenario: Second page changed
- **WHEN** a held-out listing's replayed second page answers other rows than its captured second call
- **THEN** the recipe is refused `not_reproduced`

### Requirement: Recipe execution and fallback
`acquire` SHALL run a recipe after adapters and before the page rungs over `httpx`, only for record-only reads; an
`ok` or a 429/503 is kept, anything else falls back to the configured method with the recipe attempts first. A
detail recipe's `ok` answer is kept only when it states the requested product (acquisition spec, "Data calls": one of
the request's bound parameter values, or a URL with the page's path); else it is `error`, `not_the_product`, and falls
back. Values resolve in the `adapter` evidence bucket. The recipe is the one replay of a site's API. Refs: §7.2, §10, D-0599, D-0601, D-0728.

### Requirement: Recipe politeness and pagination
The endpoint host SHALL get a `site` row and obey its robots.txt and rate like a page. A listing scrape with browser
actions, and a worker's batch or crawl task reading a listing's records, on a site whose active (for a job: pinned)
recipe has pagination SHALL be served by it over HTTP (`RecipeRung.pages`), each page a capture and its records under
the task, until a page has no rows, the pagination names no new next page (or one on another origin), the scrape's
`records` target, 50 pages (for a crawl, its `limit` when lower) or the actions' time cap, each request at its host's
rate; when the first page is not served the browser actions run, or the task's page is fetched by the page rungs.
(Previously: the worker's tasks served a listing recipe's first page only.) Refs: Appendix A #59, D-0731, D-0603,
D-1363, D-1368, D-1406.
#### Scenario: Records target
- **WHEN** a cursor-paged recipe answers three rows a page and the scrape asks for 5 records
- **THEN** two pages are requested over HTTP, six records are returned and no browser runs
#### Scenario: Every page in a batch
- **WHEN** a batch task reads a listing whose cursor-paged recipe answers 8 rows in pages of 3
- **THEN** three pages are requested and the task stores 8 records

### Requirement: Export with a PHP hint
`platform_draft` SHALL carry the recipe as data plus, exactly when present, `api_recipe_php`, rendered with escaped
literals only; nothing generated is executed. Refs: §7.2, §12.2, D-0625, D-0627.
