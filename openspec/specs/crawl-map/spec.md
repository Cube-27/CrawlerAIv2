# Crawl and Map Specification

## Purpose

URL discovery: `POST /v1/map` (sitemaps plus page links) and the `POST /v1/crawl` frontier with canonicalization,
deduplication, include/exclude globs, depth and limit, page-kind rules per URL pattern, `links_only` for unmatched
pages and `no_match` for discovered pages that don't resolve. Job mechanics (queue, results, events) are in
[jobs](../jobs/spec.md); fetching and politeness in [acquisition](../acquisition/spec.md); pagination candidates in
[extraction](../extraction/spec.md).
Design rationale: [ARCHITECTURE §13.2](../../design/api.md), [§23](../../design/build-order.md). History:
[SPEC-10](../../changes/archive/2026-10-14-spec-10-jobs-crawl-extract-mcp/SPEC-10-jobs-crawl-extract-mcp.md) and its
[decisions](../../changes/archive/2026-10-14-spec-10-jobs-crawl-extract-mcp/decisions.md).

## Requirements

### Requirement: Crawl canonical form
Every job kind SHALL key `url_task.canonical_url` by `crawl.canonical.canonicalize`: the url type's canonical form
(WHATWG/RFC 3986 normalizations, fragment removed) with the query's non-empty `&` pairs stably sorted by their
form-decoded name (`URLSearchParams.sort()` order), the pairs' bytes kept. An empty query keeps its `?`. It MUST NOT
drop parameters by name (no `utm_*` list, C4) and MUST NOT fold a directory index file (`/index.html` and `/` stay
apart).
Refs: §13.2, SPEC-10 §4.1, D-0649, D-0717, D-0992.

#### Scenario: Query order
- **WHEN** `https://example.com/p?b=2&a=1` is canonicalized
- **THEN** the result is `https://example.com/p?a=1&b=2`

#### Scenario: Idempotent
- **WHEN** a canonical URL is canonicalized again
- **THEN** it is unchanged

### Requirement: Include and exclude globs
`include` and `exclude` SHALL be `fnmatch`-style globs over the canonical URL, at most 20 per list. A URL that an
`exclude` glob matches is dropped (exclude wins); with a non-empty `include`, only URLs it matches are kept. Patterns
come from requests; `crawl/` names no host (INV-03).
Refs: SPEC-10 §4.1, §6, D-0835.

#### Scenario: Exclude wins
- **WHEN** a URL matches both an `include` and an `exclude` glob
- **THEN** it is not kept

### Requirement: Scope host follows the start page's redirect
The scope host of `map` and `crawl` SHALL be the exact host the start page is on: the canonical host of the start
page capture's final URL when that is the start host, a subdomain of it, or a domain it is a subdomain of (RFC 1034
§3.1); a redirect to any other host, an API-recipe capture, or a start page with no capture keeps the start URL's
host. Subdomains are crawled only through explicit `include` globs.
Refs: §6, SPEC-10 §4.4, §9, D-0037, D-0991.

#### Scenario: Apex redirects to www
- **WHEN** the start URL `https://example.com/` redirects to `https://www.example.com/`
- **THEN** sitemaps, robots.txt and links are read on `www.example.com`

### Requirement: Map
`POST /v1/map {url, include, exclude, limit=5000 (≤ 5000), use_sitemaps=true, use_links=true}` SHALL answer `{urls,
sources: {sitemap, links}, truncated}` synchronously. It always fetches the start page (also with `use_links: false`),
and with `use_links` takes the page's `links` on the scope host (HTTP rung only). Sitemap URLs come first; `sources`
counts the returned URLs, a URL both found counting as a sitemap's. A `job(kind='map')` row records usage only; the
result is not persisted. Targets pass the SSRF guard (422 `ssrf_rejected`).
Refs: §13.1, SPEC-10 §4.4, D-0038, D-0651, D-0652.

#### Scenario: Counts add up
- **WHEN** a map returns 12 URLs
- **THEN** `sources.sitemap + sources.links` is 12

### Requirement: Map time cap and truncation
At 60 s a map SHALL return the URLs found so far with `truncated: true`, and its job ends `completed`. `truncated` is
also true when more URLs than `limit` were found or the 50k or depth cap was hit. The start page's links are fetched
before the sitemaps.
Refs: SPEC-10 §4.4, D-0651.

#### Scenario: Slow sitemaps
- **WHEN** sitemap reading passes 60 s
- **THEN** the answer is 200 with the URLs found so far and `truncated: true`

### Requirement: Sitemap reading
Sitemaps SHALL be the robots.txt `Sitemap:` lines on the scope host, else `/sitemap.xml` there; lines naming other
hosts are ignored. Indexes are followed on that host to depth 3 (root depth 0); at most 50,000 canonical page URLs are
read; gzip is accepted. Only XML urlsets and indexes are read, matched by local element name with or without the
sitemaps.org namespace; plain-text sitemaps and a missing, malformed or oversize (> 50 MB uncompressed) sitemap are
skipped. Page URLs on any host are then kept or dropped by the request's scope.
Refs: SPEC-10 §4.4, sitemaps.org protocol, D-0650, D-0653, D-0654.

#### Scenario: Text sitemap
- **WHEN** `/sitemap.xml` returns an HTML page
- **THEN** it yields no URLs

### Requirement: Crawl request
`POST /v1/crawl {url, include, exclude, max_depth=3, limit=500 (≤ 5000), formats, schema?, page_kind_rules,
fetch?, locale?, webhook_url?}` SHALL answer `{job_id}`. `schema` is `{id}`, `{inline}` or `{fields}` (drafted for
the rules' one page kind); `schema.prompt` is 422 and there is no `budget` member. `records` is asked alone and needs
a non-empty `page_kind_rules` all of the schema's page kind.
Refs: §13.1, SPEC-10 §4.5, D-0674, D-0675, D-0676, D-0929.

#### Scenario: Records without rules
- **WHEN** a crawl asks for `records` with no `page_kind_rules`
- **THEN** the answer is 422 `validation`

### Requirement: Crawl frontier
The frontier SHALL seed the start URL; the start task reads the sitemaps politely (within map's 60 s, on the attempt
that ends it, even when the start page is disallowed or not reached) and adds in-scope URLs, up to `limit`, as depth-0
seeds. Each fetched page adds its `links` and pagination candidates, canonicalized, whose host is the scope host or a
subdomain of it, even if an `include` glob matches another host. `url_task` UNIQUE (`job_id`, `canonical_url`)
deduplicates; `depth` is the parent's + 1, cut at `max_depth`; `limit` counts enqueued tasks.
Refs: §13.2, SPEC-10 §4.5, D-0672, D-0673, D-0838.

#### Scenario: Depth cut
- **WHEN** a page at depth 3 links to new URLs and `max_depth` is 3
- **THEN** no task is enqueued for them

#### Scenario: Duplicate link
- **WHEN** two pages link to the same canonical URL
- **THEN** the job has one task for it

### Requirement: Page-kind rules and links_only
A task SHALL take the page kind of the first `page_kind_rules` pattern its canonical URL matches and be extracted
with the job's schema in the site's progressive mode. A task matching no rule MUST NOT be extracted: it is fetched for
links only, keeps its capture, gets no formats, and ends `links_only`. A format crawl with no rules gives every reached
page its formats.
Refs: §13.2, §23, SPEC-10 §4.5, D-0674, D-0677.

#### Scenario: Unmatched page
- **WHEN** a crawl with a `detail` rule for `https://example.com/p/*` reaches `https://example.com/about`
- **THEN** that task ends `links_only` and has no record

### Requirement: no_match for discovered pages
Crawl URLs are crawl-discovered: a matched page whose required fields don't all publish SHALL end `no_match`, produce
no record, and be counted in the job's `outcomes`.
Refs: §10, §23, SPEC-10 §4.5, SPEC-05 §4.10.

#### Scenario: Discovered page missing a required field
- **WHEN** a rule-matched page lacks a required field
- **THEN** its outcome is `no_match` and no record is stored

### Requirement: Crawl politeness and fetching
Crawl fetches SHALL follow the per-site politeness of acquisition, so a crawl of one site runs at about 1 request/s
whatever the worker count. Crawl tasks fetch whole pages with no conditional GET (link discovery needs the body), and
every task URL passes the SSRF guard before its fetch, as do sitemap locations and redirect hops.
Refs: §7, SPEC-10 §4.5, §6, D-0678, D-0705, D-0706.

#### Scenario: Private sitemap location
- **WHEN** a sitemap lists a URL on a host that resolves to a private address
- **THEN** that URL is never fetched

### Requirement: No page-type gate
The system SHALL NOT detect page types automatically; it relies on page-kind rules, link-only crawling of unmatched
URLs, ownership and intent stages, `no_match` for discovered pages and `complete=false` for caller-supplied pages. The
extension point (one optional stage before the collectors, outcome `wrong_page_type`) is deferred (§22, not built).
Refs: §23, Appendix A #5, #10.

#### Scenario: Search page in a crawl
- **WHEN** a crawl reaches a URL no rule matches
- **THEN** it is crawled for links only, never classified or extracted
