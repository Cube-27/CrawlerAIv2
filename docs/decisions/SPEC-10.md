# SPEC-10 decisions

Decisions for [SPEC-10 — Async jobs, map, crawl frontier, extract, batch, SSE, webhooks and the MCP server](../specs/SPEC-10-jobs-crawl-extract-mcp.md).
Template, statuses and rules: [DECISIONS.md](../DECISIONS.md).

### D-0577 — Job results: records as `RecordPage`, exports as a JSON envelope
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 1 (#120) · Status: decided
- Decision: `GET /v1/jobs/{id}/results` answers `format=json` with a `RecordPage` (as `/v1/records`) and the export formats with `{format, content, next_cursor}`, the exporter's text in `content`.
- Alternatives: Raw `text/csv`/`text/markdown` bodies with the cursor in a `Link` header (RFC 8288).
- Why: One JSON contract for the generated client and MCP; a download endpoint (and CSV formula-injection handling, #115 follow-up) can come with SPEC-12.
- Reversible: yes

### D-0578 — Job results are newest first; an export needs the job's schema
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 1 (#120) · Status: decided
- Decision: Results are ordered newest first by record id, as `/v1/records`; an export uses the job's pinned `schema_id`, and a job without one answers 409.
- Alternatives: Oldest first; an empty export.
- Why: Reuses the records service and its cursor; without a schema there are no columns.
- Reversible: yes

### D-0579 — Cancel cancels queued tasks at once and settles the job
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 1 (#120) · Status: decided
- Decision: `DELETE /v1/jobs/{id}` cancels the job's queued tasks, then locks the job (the queue's lock order), sets `cancel_requested`, ends a queued job as `cancelled` and settles a running one (cancelled once nothing is claimed). A repeat cancel answers 200 unchanged; a completed or failed job answers 409.
- Alternatives: Leave queued tasks for workers to cancel on claim; 200 for ended jobs.
- Why: Counts are right at once and no worker claims a task only to cancel it; DELETE is idempotent (RFC 9110 §9.2.2).
- Reversible: yes

### D-0580 — Page outputs of format-only jobs come with SPEC-10 PR 2
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 1 (#120) · Status: superseded by D-0630 (page outputs are made from the capture, not stored)
- Decision: `/results` serves records only; page outputs (formats of a job without a schema) come with `batch/scrape`, which stores them.
- Alternatives: Store page outputs in this row.
- Why: Nothing stores them yet; outside this row's scope.
- Reversible: yes

### D-0628 — A batch takes a schema by id or inline, not a prompt
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 2 (#128) · Status: decided
- Decision: `POST /v1/batch/scrape` accepts `schema.id` or `schema.inline`; a `schema.prompt` is a 422.
- Alternatives: Draft from the first URL synchronously, as `extract` (SPEC-10 PR 5) will.
- Why: The draft needs a fetched page, which a batch submit does not wait for; the conservative reading of `schema?` in §4.3.
- Reversible: yes

### D-0629 — `records` is asked alone in a batch
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 2 (#128) · Status: decided
- Decision: A batch with `records` takes no other format.
- Alternatives: Accept other formats and serve only records.
- Why: §4.2 serves records for schema jobs and page outputs for format jobs; accepting both would silently drop the formats.
- Reversible: yes

### D-0630 — Page outputs are made from the capture when read
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 2 (#128) · Status: decided
- Decision: `GET /v1/jobs/{id}/results` for a job without a schema answers `PageOutputPage`: every task, oldest first by task id, with the formats the job asked for, made from its capture on read (supersedes D-0580).
- Alternatives: A `page_output` table; blobs in the object store.
- Why: A format is a function of the capture (§15): nothing else to store or expire; outputs go with the capture (30 days). Listing every task keeps the cursor stable while the job runs.
- Reversible: yes

### D-0631 — A records job pins its engine data and site configs in `job.pinned`
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 2 (#128) · Status: decided
- Decision: `job.pinned` (migration 0013, `JobPins`) holds the precedence orders and calibration and, per host, the config active for the schema version and page kind at submit; the schema version is `job.schema_id` (INV-28). A pinned config runs after it is suspended or replaced (its drift window then records nothing); a host without one stays cold for the job. LLM settings are not pinned: batch binds no role C.
- Alternatives: Refuse tasks whose `engine_version` differs from the worker's; look up the active config per task.
- Why: Workers load their own data files and configs change while a job runs; pinning keeps a job's remaining tasks the same.
- Reversible: yes

### D-0632 — A fetch error in a worker task is transient
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 2 (#128) · Status: decided
- Decision: A batch task whose fetch ends in `error` is retried up to `MAX_ATTEMPTS`, then `failed`; a refused redirect fails at once (INV-16).
- Alternatives: Fail permanently, as the synchronous scrape does.
- Why: The queue's retry exists for transient network errors, and nobody is waiting.
- Reversible: yes

### D-0633 — One browser per worker, restarted at most once per task
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 2 (#128) · Status: decided
- Decision: `worker.browser.SharedBrowser`: a fetch that leaves the browser disconnected relaunches it and fetches again; if that one dies too, its result stands and the next task launches a new one.
- Alternatives: A browser per fetch, as the API does.
- Why: INV-31 and SPEC-02 §4.8 (one browser per worker process).
- Reversible: yes

### D-0634 — `fetch_politely` fetches robots.txt with its own rung
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 2 (#128) · Status: decided
- Decision: `fetch_politely(..., fetch_robots=)`; the batch handler passes the HTTP rung for robots.txt and `acquire` for the page (#31 follow-up). Admitting the browser retry through `HostLimiter` and checking every attempt for `SLOW_DOWN` stay open.
- Alternatives: One fetch for both.
- Why: Through `acquire`, a robots.txt classifies as a shell and is fetched again in the browser.
- Reversible: yes

### D-0635 — No `budget` member on a batch
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 2 (#128) · Status: decided
- Decision: `BatchScrapeRequest` has no `budget`.
- Alternatives: Accept and ignore it.
- Why: A batch makes no LLM calls (no prompt, no role C), so a budget would bound nothing.
- Reversible: yes

### D-0636 — Shared scrape steps live in `services/scrape_steps`; `ScrapeInvalid` is `SchemaUnusable`
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 2 (#128) · Status: decided
- Decision: The steps scrape and batch share moved to `services/scrape_steps.py`, and `ScrapeInvalid` was renamed `SchemaUnusable`.
- Alternatives: `services/page_task.py`.
- Why: The C3 scan reads `services.page` as a host under the `.page` TLD; the error is not scrape's alone.
- Reversible: yes

### D-0639 — Webhook delivery is an outbox row the scheduler delivers
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 6 (#132) · Status: decided
- Decision: `transition_job` inserts `webhook_delivery(job_id)` when a job with a `webhook_url` ends. The scheduler's `deliver_webhooks` (5 s, batch 1, `FOR UPDATE SKIP LOCKED`) attempts it: a 2xx is `delivered`; otherwise it retries after 30 s × 4^(n−1) and is `failed` after 3 attempts. `last_error` never contains the URL.
- Alternatives: Deliver inline from the process that ends the job; keep the attempt state in `job_event` rows.
- Why: The job's end and the webhook it owes commit together, so none is lost, and delivery never slows a task (§4.2, §4.8).
- Reversible: yes

### D-0640 — `job.api_key_id` records the submitting key
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 6 (#132) · Status: decided
- Decision: A nullable FK, set by `batch/scrape`. The webhook is signed with that key's `webhook_secret`; a job with no key is never sent unsigned, its delivery is `failed`.
- Alternatives: The key id inside `job.request` (the frozen caller request); one global secret.
- Why: §4.2 names a per-key secret, and jobs had no link to a key.
- Reversible: yes

### D-0641 — `apikey create` prints the webhook secret
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 6 (#132) · Status: decided
- Decision: The CLI prints `webhook_secret` once, with the key.
- Alternatives: An endpoint that reveals it.
- Why: A receiver can't check a signature without the secret; only the CLI creates keys (INV-32).
- Reversible: yes

### D-0642 — Webhook signature encoding
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 6 (#132) · Status: decided
- Decision: `X-CrawlerAI-Signature: sha256=` + lowercase hex HMAC-SHA256 (RFC 2104) of the exact body bytes, keyed with the UTF-8 bytes of the stored hex secret.
- Alternatives: Key with the hex-decoded bytes.
- Why: Receivers can use the printed string as-is.
- Reversible: no — receivers depend on it

### D-0643 — Webhook redirects are not followed
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 6 (#132) · Status: decided
- Decision: A 3xx is a failed attempt. Every attempt passes the SSRF guard and connects only to the checked address.
- Alternatives: Follow redirects, checking each hop.
- Why: Re-POSTing a signed body to a target the caller didn't name is not the conservative reading of §4.2.
- Reversible: yes

### D-0644 — `progress` is computed by the stream, not stored
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 6 (#132) · Status: decided
- Decision: After each batch of stored events, the stream sends `progress` (task `counts` and `outcomes`, as in the job summary) with no `id`.
- Alternatives: Store a `progress` row on every task finish.
- Why: That is a count per task, linear in the job's size, which `settle_job` avoids. Resume still works because `progress` carries no id.
- Reversible: yes

### D-0645 — Task events are read from the task's rows at finish
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 6 (#132) · Status: decided
- Decision: The queue's `_finish` records `task_fetched` (from `url_task.capture_id`), `task_extracted` (the task's last extraction) and `task_abstained` (its records' `field_meta.status = abstained`), for `done` and `failed` tasks only.
- Alternatives: Each handler records its own events.
- Why: One place, and handlers need no change.
- Reversible: yes

### D-0646 — SSE resume is by id, with a known limit across processes
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 6 (#132) · Status: decided
- Decision: Resume uses `id > Last-Event-ID`, as §4.2 says. An event another process commits late, with a smaller uuid7, can be skipped by a live client that already holds a larger id (D-0103: no cross-process order). The end event is last, because the job row lock serializes it.
- Alternatives: A commit-ordered sequence column.
- Why: §4.2 specifies id order; review lists the gap as a possible follow-up.
- Reversible: yes

### D-0649 — Crawl canonical form sorts the query by name
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 3 (#130) · Status: decided
- Decision: `crawl.canonical` is the url type's canonical form with the query's non-empty `&` pairs stably sorted by their form-decoded name (UTF-16 code units), WHATWG `URLSearchParams.sort()` order; the pairs keep their bytes and are not re-serialized. An empty query keeps its `?` (SPEC-04 §4.4).
- Alternatives: No sorting; full `URLSearchParams` re-serialization.
- Why: SPEC-10 §4.1 asks for a sorted query and only WHATWG/RFC 3986 normalizations; `sort()` is the WHATWG one. Re-serializing would rewrite bytes (`%20` → `+`) a server may read differently.
- Reversible: yes

### D-0650 — `map` sitemap scope and depth
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 3 (#130) · Status: decided
- Decision: Only sitemaps on the start URL's exact host are fetched (robots `Sitemap:` lines elsewhere are ignored; `/sitemap.xml` is the fallback). A root is depth 0 and an index child +1, read to depth 3. The 50k cap counts canonical page URLs read. Page URLs from sitemaps on any host are kept or dropped by the request's scope, so an `include` can name a subdomain (D-0037).
- Alternatives: Fetch cross-host sitemaps robots.txt lists; count index entries toward the 50k.
- Why: The most conservative reading of "same exact host" (§4.4, D-0037): every fetch stays on one site's robots and rate.
- Reversible: yes

### D-0651 — `map` past its timeout returns what it found
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 3 (#130) · Status: decided
- Decision: At 60 s, `map` returns the URLs found so far with `truncated: true`, and the job is `completed`. `truncated` also covers more URLs than `limit`, the 50k cap and the depth cap. The start page's links are fetched before the sitemaps.
- Alternatives: A 504 problem, as `scrape` does.
- Why: Discovery has a useful partial answer, and `truncated` tells the caller it is incomplete.
- Reversible: yes

### D-0652 — `map` `sources` count returned URLs, sitemap first
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 3 (#130) · Status: decided
- Decision: `sources.sitemap + sources.links == len(urls)`; a URL both sources found counts as a sitemap's. Sitemap URLs come first in `urls`.
- Alternatives: Count each source's distinct finds, overlapping.
- Why: The counts describe the answer the caller got.
- Reversible: yes

### D-0653 — XML sitemaps only, read by element name
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 3 (#130) · Status: decided
- Decision: Only XML urlsets and indexes are read, matched by local element name with or without the sitemaps.org namespace; plain-text sitemaps are skipped.
- Alternatives: Also read text sitemaps.
- Why: A soft-404 HTML page would read as a text sitemap; XML declines cleanly (C7). The text format can be added if dev shows sites that need it.
- Reversible: yes

### D-0654 — `.sitemaps.org` in the site-literal allowlist
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 3 (#130) · Status: decided
- Decision: Allow `.sitemaps.org` under standards bodies in `tools/site_literal_allowlist.txt`.
- Alternatives: None: the protocol's XML namespace is `http://www.sitemaps.org/schemas/sitemap/0.9`.
- Why: It is the protocol's own host, like `www.w3.org` (C3 allows standards hosts).
- Reversible: yes

### D-0655 — Shared fetch steps in `services.fetching`
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 3 (#130) · Status: decided
- Decision: `Fetching` moves from `services.scrape` to a new `services.fetching`, with `site_rules`, `admitted` and one SSRF refusal path: `TargetRejected` (replacing `ScrapeRejected`), `check_target` and `refusal(result)` (scrape and map raise on it, the `batch_scrape` handler returns `Failed`); the 422 is `api.problems.target_refused`. `site_row`, `DEFAULT_PROJECT` and `record_fetch_usage` stay in `services.scrape_steps` (#128); `record_fetch_usage` takes attempt records, so no caller keeps a page body only to count it.
- Alternatives: Import `scrape`'s private helpers; a `MapRejected` copy of `ScrapeRejected`.
- Why: One copy of the INV-16 refusal check and of the waiting fetch's robots and rate steps for every service that fetches (SPEC-10 PR 4/7 reuse them).
- Reversible: yes

### D-0672 — `include` globs admit the start host and its subdomains only
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 4 (#137) · Status: decided
- Decision: The crawl frontier takes a URL only if its host is the start URL's host or a subdomain of it (RFC 1034 §3.1), even when an `include` glob matches a URL on another host. `map`'s `Scope` is unchanged.
- Alternatives: Any host an `include` matches.
- Why: This settles the #130 follow-up. It is the conservative reading of D-0037 and §4.5 ("on the same host"): a crawl never fetches from a site the caller did not name.
- Reversible: yes

### D-0673 — Sitemap seeds are read by the start URL's task, in the worker
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 4 (#137) · Status: decided
- Decision: The start task reads the sitemaps over HTTP, politely: it waits for the site's rate in place, within map's 60 s timeout. It adds the URLs in scope (up to `limit`) as depth-0 seeds with no parent, even when the start page is disallowed or not reached. A refused or timed-out sitemap read keeps the seeds read so far.
- Alternatives: Read sitemaps at submit, which would block the caller up to 60 s; one task per sitemap.
- Why: Submit stays fast, and the seeds commit atomically with the start task. A retry after a transient failure reads the sitemaps again; the seeds deduplicate (review of #137).
- Reversible: yes

### D-0674 — A records crawl needs rules of one page kind, the schema's
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 4 (#137) · Status: decided
- Decision: `formats: ["records"]` (asked alone) needs a non-empty `page_kind_rules`, all with the schema's page kind (listing refused as in scrape and batch). Format crawls take rules of any kind. A format crawl with no rules gives every reached page its formats; with rules, unmatched pages are `links_only`.
- Alternatives: Extract every page when there are no rules.
- Why: A job has one schema with one page kind, and a records crawl without rules would extract nothing (§13.2).
- Reversible: yes

### D-0675 — Crawl `limit` ≤ 5000, default 500; `max_depth` default 3
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 4 (#137) · Status: decided
- Decision: The bounds of `map` (D-0038, its `MAX_LIMIT` reused) and the §4.5 example.
- Alternatives: No upper bound.
- Why: `limit` bounds the job's tasks, and a crawl enqueues at most what a map of the site returns.
- Reversible: yes

### D-0676 — No `prompt`, no `budget` on a crawl
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 4 (#137) · Status: decided
- Decision: As batch (D-0628, D-0635): `schema.prompt` is a 422 and there is no `budget` member.
- Alternatives: Draft the schema from the start page synchronously.
- Why: Drafting needs a fetched page and role S; PR 5 builds that for `extract`, and crawl can reuse it then.
- Reversible: yes

### D-0677 — Page outputs only for `extracted` tasks
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 4 (#137) · Status: decided
- Decision: `/v1/jobs/{id}/results` lists every task of a format job (D-0630), but gives formats only to a task whose outcome is `extracted`. A `links_only` page keeps its capture (for its links) and shows no formats.
- Alternatives: Leave `links_only` tasks out of the listing.
- Why: Listing every task keeps the cursor stable while the job runs. For batch jobs nothing changes: a done task with an `ok` page is `extracted`.
- Reversible: yes

### D-0678 — Pinned configs cover the start host only; crawl tasks do not use conditional GET
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 4 (#137) · Status: decided
- Decision: A records crawl pins the config active for the start URL's host at submit; pages on a subdomain an `include` admits are extracted cold for the whole job. Crawl tasks fetch whole pages (no validators, no 304 `unchanged`): link discovery needs the body. Batch keeps SPEC-11's conditional GET through `steps.fetch_page(recurring=...)`.
- Alternatives: Pin at first fetch per host; conditional GET for crawl pages that lead nowhere.
- Why: INV-28 pins at submit, when the subdomains are not known. Recurring crawls are SPEC-11 PR 4's to decide.
- Reversible: yes

### D-0681 — `extract` glob syntax: a `*` makes a glob, on one literal origin
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 5 (#140) · Status: decided
- Decision: An `urls` entry is a glob when it contains `*`. `?` and `[` alone leave it a URL; inside a glob they match as in `fnmatch`, like `include` patterns. A glob's scheme and authority must be literal, and its origin is canonicalized (`crawl.rules.url_glob`).
- Alternatives: Treat `?` and `[` as glob characters too.
- Why: A query starts with `?` (RFC 3986 §3.4) and an IPv6 host sits in `[]` (§3.2.2), so the alternative would make every URL with a query a glob. §4.6 expands a glob "on its host".
- Reversible: yes

### D-0682 — A glob is expanded by a map of its canonical origin
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 5 (#140) · Status: decided
- Decision: The map starts at `https://host/`, so it reads the sitemaps robots.txt lists and the links on the root page. Globs on one origin share one map, and the maps for different origins run at once.
- Alternatives: Start from the glob's literal path prefix.
- Why: The path prefix may not exist as a page; sitemaps are found from the host whatever the start URL. Politeness is per host.
- Reversible: yes

### D-0683 — `extract` `limit` ≤ 1000, default 1000; no URL is a 422
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 5 (#140) · Status: decided
- Decision: `limit` counts every task, with the given URLs placed before the URLs the globs found. When the globs match nothing and no other URL is given, the request is a 422 (`NothingToExtract`) and no extract job is stored.
- Alternatives: The map's 5000; an empty job.
- Why: 1000 is the batch bound (§4.3) for caller-supplied URLs. An empty job would report `completed` and hide that the globs matched nothing.
- Reversible: yes

### D-0684 — A prompt is drafted from the pages reached among the first three task URLs
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 5 (#140) · Status: decided
- Decision: The first three task URLs (given URLs first) are fetched politely, with every rung, while the caller waits. The pages reached are the samples; no other URL is tried. If none is reached, the answer is a 422 and the job is `failed`. Sample fetches are not stored, and the worker fetches those pages again. The draft step is bounded by 120 s (D-0028); past that the answer is a 504.
- Alternatives: Keep trying URLs until three are reached; store the sample captures for the tasks.
- Why: §4.6 says "the first 1–3 concrete URLs", and the latency stays bounded. Reusing captures would couple the API's fetch with the task's fetch.
- Reversible: yes

### D-0685 — A prompt's job is stored and started before its draft
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 5 (#140) · Status: decided
- Decision: The job is inserted and set `running` before the draft, so the draft's LLM and fetch usage and its `budget.llm_calls` attach to the job. Once the draft is made, its schema, pins and tasks are written in one transaction. Any failure of the draft moves the job `running → failed` with no tasks.
- Alternatives: Draft first, under no job, then insert.
- Why: The LLM client charges a job's budget and usage (SPEC-06 §4.7), which needs a job row. Follow-ups: a cancel that arrives during the draft (lock the row before inserting tasks); a process that dies during the draft leaves the job `running`, as with map and scrape.
- Reversible: yes

### D-0686 — `POST /v1/extract` always returns the schema it extracts with
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 5 (#140) · Status: decided
- Decision: `{job_id, schema}` carries the schema for an `id` or `inline` schema as well as for a prompt's draft.
- Alternatives: Return `schema` only for a prompt.
- Why: The answer has one shape, and the caller sees the version the job pinned (INV-28).
- Reversible: yes

### D-0696 — MCP over HTTP is stateless, answers JSON, and has no DNS-rebinding check
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 7 (#144) · Status: decided
- Decision: The `/mcp` endpoint uses the SDK's stateless mode with JSON responses. DNS-rebinding protection is off.
- Alternatives: Stateful sessions; SSE responses; the SDK's localhost-only Host allowlist.
- Why: Stateless lets any API process take any request, with no session affinity. Every request authenticates with a bearer key that a browser never sends on its own (ARCHITECTURE §18, no cookies). The SDK's default Host allowlist would refuse every non-localhost deployment.
- Reversible: yes — they are constructor arguments in `build_server`.

### D-0697 — The API sits above the MCP server; key lookup and runtime setup move to `services`
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 7 (#144) · Status: decided
- Decision: `.importlinter` layers `api` over `mcp_server` (they were independent siblings). `api/keys.py` moves to `services/keys.py`, and the app's runtime setup moves to `services/runtime.py` (`Runtime`, `open_runtime`, `fetching_from_settings`).
- Alternatives: A third composition module that imports both; FastMCP's OAuth `TokenVerifier`; duplicating the key lookup in `mcp_server`.
- Why: SPEC-10 §4.7 mounts the server in the API app and has both transports use the same auth. `mcp_server` still imports nothing from `api`.
- Reversible: yes

### D-0698 — MCP tool shapes
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 7 (#144) · Status: decided
- Decision: `scrape`, `map`, `crawl_start` and `extract` take the REST body as `request`. A later markdown page is `scrape(cursor=...)` with no `request`; the cursor is `<capture_id>:<offset>`, and the page is rebuilt from the capture (§15). `extract` returns `{job_id, schema}`, as REST does (D-0686). `crawl_status` and `extract_status` share one body and return `{job, results}`, 10 results per page with a `cursor`, without checking the job's kind. `get_site_config(host)` lists the site's configs; `export_config(config_id, format)`.
- Alternatives: Flattened arguments; a separate markdown-paging tool (§13.3 lists exactly ten); re-scraping with `max_age` for later pages (that could read a newer capture).
- Why: One service call per tool, with the REST models as the input schemas. Of the readings of "`{job_id}`", this conservative one keeps the draft, which ARCHITECTURE §13.1 returns.
- Reversible: yes

### D-0699 — The stdio server looks up `CRAWLERAI_API_KEY` on every call, with no rate limit
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 7 (#144) · Status: decided
- Decision: `crawlerai.mcp_server.stdio.key_bind` authenticates the key at each tool call; a revoked key fails the call.
- Alternatives: Authenticate once at startup; put the API's token bucket in front.
- Why: It is the same lookup as REST, and a revocation takes effect at once. A local stdio process has one client, so the network rate limit does not apply.
- Reversible: yes

### D-0705 — A worker checks a page task's URL with the SSRF guard before it fetches
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 8 (#145) · Status: decided
- Decision: `steps.fetch_page` runs `fetching.connector.check(task.url)` first; a refusal returns `Failed(<guard reason>, transient=False)` with no site row, capture or usage. A crawl-discovered subdomain that resolves to a private address was refused only at the robots.txt fetch, which `fetch_politely` retries as unreachable, so the task ended `blocked` instead of failing at once (SPEC-02 §4.11). A failed DNS lookup (`dns`) now also fails the task at once, as the page rung's refusal already did.
- Alternatives: Fail the task on any refused attempt, robots.txt's included: that would also make a public host whose robots.txt redirects to a private address an SSRF failure rather than an unreachable robots.txt (RFC 9309 §2.3.1.4). Check at enqueue in the frontier: a lookup per discovered link, and it does not hold at fetch time.
- Why: The same up-front check `scrape` and `map` make (`check_target`, D-0655); one extra resolution per task, while the rung still pins its own check.
- Reversible: yes

### D-0706 — The SSRF matrix pins only the test site past the guard
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 8 (#145) · Status: decided
- Decision: `tests/db/test_ssrf_endpoints.py` runs the real `SafeConnector` and `fetch_http` against a local server; only the test site's host at the server's port is pinned to it. Redirect hops, sitemap and link locations and subdomains go through the real guard with a stub resolver.
- Alternatives: Stub rungs that report a refusal, as the per-service tests do.
- Why: The matrix exercises production's checks on every hop, not a stub's report of them.
- Reversible: yes

### D-0707 — `GET /v1/jobs` adds no index or migration
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 9 (#146) · Status: decided
- Decision: The list reads `job` ordered by its primary key, descending, with `kind`/`status` as filters; the page's task counts use `url_task`'s (`job_id`, `canonical_url`) unique index.
- Alternatives: An index on `job (kind, status, id)` in migration 0016.
- Why: The primary-key index serves the order and the cursor; jobs are few next to tasks, so the filters cost a short scan. An index can be added with evidence that a filtered list is slow.
- Reversible: yes

### D-0708 — The jobs list is not scoped to the key's project
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 9 (#146) · Status: decided
- Decision: `GET /v1/jobs` lists every job, as `GET /v1/jobs/{id}` and `GET /v1/records` read every project's rows today; learning jobs (no key) are listed too.
- Alternatives: Only the jobs of the calling key's project; only jobs a key submitted.
- Why: It keeps one access rule across the job routes; scoping them all is a separate change.
- Reversible: yes

### D-0709 — The SPEC-12 jobs-table row is row 10, not row 9
- Date: 2026-10-14 · Spec/PR: SPEC-10 PR 9 (#146) · Status: decided
- Decision: SPEC-12 §8 row 10 "Jobs table on /jobs" (`screens/jobs`, vitest, L3).
- Alternatives: Row 9 as assigned.
- Why: SPEC-12 row 9 (labeling nav) already exists and is done (#93).
- Reversible: yes

### D-0835 — `include` and `exclude` take at most 20 globs
- Date: 2026-10-15 · Spec/PR: SPEC-10 follow-ups (#195) · Status: decided
- Decision: `MAX_PATTERNS` = 20 globs per `include` or `exclude` list (map, crawl), and per host for extract's globs, which become that host's map `include`.
- Alternatives: 50 or 100 per list; no bound.
- Why: Every URL read is matched against each glob on the event loop, measured at about 0.8 µs a match: two lists of 20 over a map's 50k sitemap URLs take about 1.6 s at worst (50 per list took 4 s).
- Reversible: yes

### D-0837 — In-process jobs left `running` with no task fail after a lease
- Date: 2026-10-15 · Spec/PR: SPEC-10 follow-ups (#195) · Status: decided
- Decision: The scheduler's `fail_stalled_jobs` ends `failed` the `map` and `extract` jobs still `running` with no task one `LEASE` after they started, 100 per turn.
- Alternatives: Give them a claimed task (`insert_claimed`), as the synchronous scrape does.
- Why: A process runs them while the caller waits, with no lease; their time caps (60 s for a map, the draft's) are far under `LEASE`, so one still running has lost its process.
- Reversible: yes

### D-0838 — A crawl's start task reads the sitemaps on the attempt that ends it
- Date: 2026-10-15 · Spec/PR: SPEC-10 follow-ups (#195) · Status: decided
- Decision: The start task reads the site's sitemaps only on an attempt that is neither postponed nor retried (`ends_task`), including one whose fetch failed before the page (robots.txt unreachable, a 429 or 503).
- Alternatives: Skip the read when the job already has depth-0 seeds.
- Why: A retry no longer reads the sitemaps again, and seeds are still added when the start page was never reached, as §4.5 says.
- Reversible: yes

### D-0839 — One `Refusal` class marks what a caller may be told
- Date: 2026-10-15 · Spec/PR: SPEC-07 §4.3, SPEC-10 §4.7 (#195) · Status: decided
- Decision: `core.errors.Refusal` is the base of the services' refusals (and `LLMFailure`, `SchemaNotFound`); MCP passes their message on, and any other exception is answered with `UNEXPECTED`, as REST's 500 is.
- Alternatives: A hand-kept tuple of exception classes in the MCP server.
- Why: One marker keeps the interfaces from drifting apart when a service adds a refusal.
- Reversible: yes

### D-0875 — A `ValidationError` raised inside an MCP tool is unexpected
- Date: 2026-10-16 · Spec/PR: SPEC-10 follow-ups (#199) · Status: decided
- Decision: `_REFUSALS` drops `ValidationError`; `crawl_status` parses its cursor itself and refuses a bad one as `not a results cursor`.
- Alternatives: Type the tool argument as a UUID (changes its input schema).
- Why: FastMCP validates arguments before a tool runs; any other `ValidationError` is a service's parse of stored rows, which REST answers 500 `UNEXPECTED` (review of #195).
- Reversible: yes

### D-0912 — `csv_safe` is accepted only with `format=csv_records`
- Date: 2026-10-16 · Spec/PR: SPEC-10 §4.2 (#204) · Status: decided
- Decision: Any other format with `csv_safe=true` answers 422. The UI sends it from `exportJobPage`, so every CSV download carries it. Cells starting with `=`, `+`, `-`, `@`, tab or CR get a leading `'`, numbers included.
- Alternatives: Ignore it for other formats.
- Why: As `include` with `json_values`: an option that cannot apply is refused, not dropped.
- Reversible: yes

### D-0951 — A job pins its schema document (INV-28)
- Date: 2026-10-16 · Spec/PR: greenfield (#210) · Status: decided
- Decision: `job.pinned.schema` holds the schema document at submit (`JobPins.schema_`); the worker extracts with it, so an edit during a job changes none of that job's records.
- Alternatives: read the schema row per task (an edit would change a running job's records).
- Why: INV-28 named the schema version; with versions gone the document itself is pinned.
- Reversible: yes
