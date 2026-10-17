## MODIFIED Requirements

### Requirement: Crawl frontier and page-kind rules
The crawl frontier SHALL seed the start URL and sitemap URLs, add in-scope links and pagination candidates, dedupe by
`(job_id, canonical_url)` and by the canonical final URL each fetched task stores (`url_task.final_url`), and cut at
`max_depth` and `limit`. The start task stores where its page is (`job.start_location`, after the site's redirects to a
host of the same site), which gives every later task its scope host; a URL a task was redirected to is never added as
a task. A task takes its first matching page-kind rule; one with no match is fetched for links only (`links_only`); a
matched page missing a required field is `no_match` with no record. No automatic page-type gate (§22). (Previously:
only the start page's redirect target was kept out.) Refs: §13.2, §23, D-0672, D-0674, D-0677, D-1285, D-1382.
#### Scenario: Unmatched page
- **WHEN** a crawl with a `detail` rule for `https://example.com/p/*` reaches `https://example.com/about`
- **THEN** that task ends `links_only` and has no record
#### Scenario: Redirected page
- **WHEN** a crawl's task for `https://example.com/p/old` is redirected to `https://example.com/p/new`, which a page
  found later links to
- **THEN** no task is added for `https://example.com/p/new`

### Requirement: Conditional GET and content fingerprint
Only records tasks of `batch_scrape` and `extract` SHALL use `url_state`, and only with a standing record: the HTTP rung
sends stored validators, and a 304 or an equal content digest (BLAKE2b of the visible words, nonce-like tokens left out,
`recurring/simhash.py`; for a listing without words, of the URLs it links to, in order; the SimHash stored beside it
only reports how far a change moved) ends the task `unchanged`, linking the standing records, with no extraction or LLM
call. A detail page's standing record is the newest of its entity; a listing page's are the latest versions of the
entities the task named by `url_state.standing_task_id` stood for, valid while that task extracted the page the way it
would be now. Replay never reads `url_state` (INV-10). (Previously: a listing without words was always extracted.)
Refs: §14, D-0637, D-0662, D-0663, D-0952, D-1283, D-1340, D-1383.
#### Scenario: Unchanged listing
- **WHEN** a listing page whose text is unchanged is scraped again in a records batch
- **THEN** its task ends `unchanged` with no extraction, and the job lists the rows' records the first run stored
#### Scenario: One-word edit
- **WHEN** a page's visible text changes by one word and its SimHash stays equal
- **THEN** its content digest differs and the page is extracted again
#### Scenario: Listing without words
- **WHEN** a listing of image links with no visible words is scraped again with the same links, then with one more
- **THEN** the second run is `unchanged` and the third is extracted
