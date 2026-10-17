# Delta: jobs

## MODIFIED Requirements

### Requirement: Crawl frontier and page-kind rules
The crawl frontier SHALL seed the start URL and sitemap URLs, add in-scope links and pagination candidates, dedupe by
`(job_id, canonical_url)` and by the canonical final URL each fetched task stores (`url_task.final_url`), and cut at
`max_depth` and `limit`. The start task stores where its page is (`job.start_location`, after the site's redirects to a
host of the same site), which gives every later task its scope host; a URL a task was redirected to is never added as
a task. A task takes its first matching page-kind rule; one with no match is fetched for links only (`links_only`); a
matched page missing a required field is `no_match` with no record. No automatic page-type gate (§22). The scope is the
start host, plus its subdomains with `allow_subdomains` and any host with `allow_external`, less `exclude` and within
`include` when given. (Previously: only the start page's redirect target was kept out; subdomains needed an `include`.)
Refs: §13.2, §23, D-0672, D-0674, D-0677, D-1285, D-1382, D-1441.
#### Scenario: Unmatched page
- **WHEN** a crawl with a `detail` rule for `https://example.com/p/*` reaches `https://example.com/about`
- **THEN** that task ends `links_only` and has no record
#### Scenario: Redirected page
- **WHEN** a crawl's task for `https://example.com/p/old` is redirected to `https://example.com/p/new`, which a page
  found later links to
- **THEN** no task is added for `https://example.com/p/new`

## ADDED Requirements

### Requirement: Crawl strategy and best-first scoring
A crawl SHALL take `strategy` `bfs` (default), `dfs` or `best_first`; `query` and `keywords` are accepted only with
`best_first`. A scored crawl stores each task's score (`url_task.score`, 0 to 1) and `claim_tasks` SHALL lease by
`priority`, then score descending (none last), then id. Best first scores a link by BM25 of its anchor text and URL path
against the query, the holding page's relevance, the sitemap `priority` and depth (`crawl/scoring.py`), with no
vocabulary list. A scored crawl SHALL fetch at most `limit` pages: it queues up to five times as many candidates,
keeps the best when full, skips a leased task once the finished and higher-ranked leased pages reach `limit`, and
cancels the queued rest when the last page is spent. `max_pages` is an alias of `limit`. Refs: D-1440, D-1446.
#### Scenario: Best first spends the limit on matches
- **WHEN** a `best_first` crawl with `query` "rate limits" and `limit` 3 starts on a page linking `/guides/rate-limits`,
  `/blog/news` and `/about`, and the guide links `/guides/rate-limits/retry`
- **THEN** the pages fetched are the start page, the guide and its retry page, and the other tasks end `cancelled`
