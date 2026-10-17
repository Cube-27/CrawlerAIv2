# Adapters (delta)

## MODIFIED Requirements

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
