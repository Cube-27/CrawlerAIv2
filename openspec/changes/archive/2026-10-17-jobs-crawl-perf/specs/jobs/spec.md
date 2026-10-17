# Delta: jobs

## MODIFIED Requirements

### Requirement: Batch scrape, extract and budgets
`POST /v1/batch/scrape` (1–1000 URLs) and `POST /v1/extract` SHALL answer with a job id and run one task per URL with
role C. Extract globs expand by one map per origin, `limit` ≤ 1000 counts every task, and globs matching nothing are 422.
Extract alone takes `schema.prompt`, drafted from the first three reached URLs while the caller waits (none reached is
422, past 120 s 504). No request kind has a default budget: a job whose request sets no `budget.llm_calls` is bounded
by `project.llm_call_cap`, read when the job checks, null meaning no cap (see [llm](../llm/spec.md)); a crawl takes the
same optional `budget` as a batch. (Previously: a crawl took no `budget` of its own.) Refs: §13.1, D-0628, D-0676,
D-0681, D-0684, D-1044, D-1121, D-1286.

### Requirement: Crawl frontier and page-kind rules
The crawl frontier SHALL seed the start URL and sitemap URLs, add in-scope links and pagination candidates, dedupe by
`(job_id, canonical_url)` and cut at `max_depth` and `limit`. The start task stores where its page is (`job.start_location`,
after the site's redirects to a host of the same site), which gives every later task its scope host, and the page the
start URL redirected to is never added as a task. A task takes its first matching page-kind rule; one with no match is
fetched for links only (`links_only`); a matched page missing a required field is `no_match` with no record. No
automatic page-type gate (§22). (Previously: each task read the start task's capture, and the redirect target was
fetched again as a task.) Refs: §13.2, §23, D-0672, D-0674, D-0677, D-1285.
#### Scenario: Unmatched page
- **WHEN** a crawl with a `detail` rule for `https://example.com/p/*` reaches `https://example.com/about`
- **THEN** that task ends `links_only` and has no record
#### Scenario: Redirected start page
- **WHEN** the crawl of `https://example.com/` is redirected to `https://www.example.com/`, which its pages link to
- **THEN** no task is added for `https://www.example.com/`, and `job.start_location` is that URL

### Requirement: Conditional GET and content fingerprint
Only records tasks of `batch_scrape` and `extract` SHALL use `url_state`, and only with a standing record: the HTTP rung
sends stored validators, and a 304 or an equal SimHash fingerprint (`recurring/state.py`, Hamming 0) ends the task
`unchanged`, linking the standing records, with no extraction or LLM call. A detail page's standing record is the newest
of its entity; a listing page's are the latest versions of the entities the task named by `url_state.standing_task_id`
stood for, valid while that task extracted the page the way it would be now. Replay never reads `url_state` (INV-10).
Known limit: SimHash can miss one-word edits (D-0915, needs-owner). (Previously: a listing page had no standing
record, so it was always extracted.) Refs: §14, D-0637, D-0662, D-0663, D-0952, D-1283.
#### Scenario: Unchanged listing
- **WHEN** a listing page whose text is unchanged is scraped again in a records batch
- **THEN** its task ends `unchanged` with no extraction, and the job lists the rows' records the first run stored

### Requirement: Listing diff and gone URLs
Each `completed` records crawl SHALL mark its rule-matched URLs, and for a listing schema its row URLs
(`resolve.records.row_url_fields`), seen in `url_state`; a URL missing from two consecutive runs of the same crawl gets
`gone_at` and a `url_gone` event, cleared when seen again. The listing is on the host the start page is on. A partial
run (limit hit, empty listing, unreached navigation page, sitemap time cap) counts no misses. (Previously: page URLs
only, on the start URL's host.) Refs: §14, D-0689, D-0691, D-0692, D-0693, D-1284.
