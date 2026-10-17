## MODIFIED Requirements

### Requirement: Recipe model
An `api_recipe` SHALL be data (`config_ir/api_recipe/`): a request spec, a `map` of JSONPath-subset queries, an
optional `pagination` of kind `param` (a page number or offset), `cursor`, `next_url` or `link` (RFC 8288), set in the
query or the JSON body (`model.py`), and a `proof`; it MUST refuse `Authorization`, `Proxy-Authorization`, `Cookie`
and client-owned headers, and is never executed as code. Refs: §7.2, §12.1, §18, Appendix A #59, D-0493, D-0498,
D-0560, D-1360.
(Previously: pagination of kind `param` in the query only.)

### Requirement: Recipe discovery and binding
Learning SHALL find the endpoint whose network JSON matches a required field on every sample browser capture, then
bind its parameters deterministically from the page URL (at least two samples, exact round trip), else via LLM role D
with one repair round; a spec that does not reproduce every sample is refused. A listing's endpoint is the call series
whose rows match published row values on every sample capture with calls, its pagination inferred from a series of
two or more calls (`pagination.py`), bound from two listing URLs at least (`listing.py`). A page whose capture holds no
calls (for a listing, no second call) is rendered in the browser with capture, a listing with its browser actions: at
most 3 sample and 3 held-out pages per run. Refs: §7.2, §11, Appendix A #59, D-0541, D-0494, D-0611, D-1361, D-1364,
D-1366.
(Previously: detail pages only, from stored browser captures only; D-0604 refused listings.)
#### Scenario: Paged calls of a listing
- **WHEN** listing pages loaded their rows from `/search?cat=<category>&page=1` and `&page=2`
- **THEN** the recipe binds `cat` from the page URL and paginates `page` from 1 by 1

### Requirement: Held-out validation
A recipe SHALL be accepted only for a schema whose HTML config validated, when every map field reproduces on every
held-out page (at least 3) where it was published (for a listing: replaying its first two pages gives the rows of the
page's captured calls, in order, each mapped raw value equal); `validation_report.api_recipe` records the result or
the refusal reason either way. Refs: §7.2, Appendix A #59, D-0581, D-0583, D-0735, D-1365.
(Previously: detail schemas only.)
#### Scenario: Second page changed
- **WHEN** a held-out listing's replayed second page answers other rows than its captured second call
- **THEN** the recipe is refused `not_reproduced`

### Requirement: Recipe politeness and pagination
The endpoint host SHALL get a `site` row and obey its robots.txt and rate like a page. A listing scrape with browser
actions on a site whose active recipe has pagination SHALL be served by it over HTTP (`RecipeRung.pages`), each page
a capture, until a page has no rows, the pagination names no new next page (or one on another origin), the request's
`records` target, 50 pages or the site's rate refuses; when the first page is not served the browser actions run.
Refs: Appendix A #59, D-0731, D-0603, D-1363, D-1368.
(Previously: pagination from an operator correction only; no service called the paged executor.)
#### Scenario: Records target
- **WHEN** a cursor-paged recipe answers three rows a page and the scrape asks for 5 records
- **THEN** two pages are requested over HTTP, six records are returned and no browser runs
