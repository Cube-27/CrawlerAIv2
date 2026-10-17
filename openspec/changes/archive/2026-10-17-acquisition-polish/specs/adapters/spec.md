## MODIFIED Requirements

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

### Requirement: Shopify adapter
It SHALL detect collection paths only, also under a locale subfolder (`/{language}[-{region}]/collections/{handle}`;
product pages take the page path, D-1118), `POST` the tokenless Storefront GraphQL endpoint on the page's host with the
handle as a variable, page through the products' cursor up to the adapter row cap, ask a locale-prefixed page in its
language (`@inContext(language:)`), and class answers `not_platform` (no `X-Shopify-API-Version`), `not_served` (no
item, GraphQL errors, or another language than the page's) or `ok`, as in `adapters/shopify.py`. A fetched `ok` page
whose URL has a query is served by the adapter that detects it without the query when the page's canonical link is
that URL (RFC 6596, D-1120). Refs: Appendix A #46, #47, D-1077, D-1078, D-1114, D-1118, D-1120, D-1385, D-1386.
(Previously: the first 250 products, and no locale-prefixed URL.)

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

### Requirement: Held-out validation
A recipe SHALL be accepted only for a detail schema whose HTML config validated, when every map field reproduces on
every held-out page (at least 3) where it was published; `validation_report.api_recipe` records the result or the
refusal reason either way, and an error of the recipe learner that is not an LLM failure refuses the recipe
(`recipe_error: <type>`) without failing the run. Refs: §7.2, D-0581, D-0583, D-0735, D-1389.
(Previously: such an error failed the learning run.)

### Requirement: Recipe politeness and pagination
The endpoint host SHALL get a `site` row and obey its robots.txt and rate like a page; a learning run's replays go
through the site's proxy pool and count as the learn job's usage. Pagination comes only from an operator correction
(not built yet: pagination discovery; no service calls the paged executor). Refs: D-0731, D-0603, D-1381.
(Previously: replays used the default policy and counted no usage.)
