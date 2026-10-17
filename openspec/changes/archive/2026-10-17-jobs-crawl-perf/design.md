# Design: jobs-crawl-perf

## Decisions

Decided under the owner's delegation of 2026-10-17 (status `decided (owner-delegated 2026-10-17)`); none changes
`openspec/design/`.

### D-1280 — A job's records are paged from its tasks, by (task id, record id)
- Date: 2026-10-17 · Change/PR: jobs-crawl-perf (#246) · Status: decided (owner-delegated 2026-10-17)
- Decision: `GET /v1/records?job_id` reads the job's tasks by id (keyset on `url_task (job_id, id)`) and joins their
  `task_record` rows, newest task first and, within a task, newest record first. A record several tasks of the job
  stand for is listed once, at the first of them. The cursor stays a record id: it stands where that record does in the
  job; a record the job has no task for gives an empty page. The job's results (`json_values`) already paged by task id.
- Alternatives: keep `record.id IN (the job's task_record rows)`, which builds the whole set per page; a composite
  cursor of (task, record) (changes the public cursor shape).
- Why: each page reads its own tasks only. Record ids and task ids are both UUIDv7, so the order is nearly the old one.
- Reversible: yes

### D-1281 — Indexes, and one reaper query for stuck jobs
- Date: 2026-10-17 · Change/PR: jobs-crawl-perf (#246) · Status: decided (owner-delegated 2026-10-17)
- Decision: `url_task (job_id, status, outcome)` serves the per-job counts of a large crawl, `url_task (job_id, id)`
  the task-id paging, and the partial `job (started_at) WHERE status = 'running'` the two reapers. `fail_stalled_jobs`
  and `expire_learn_runs` keep their names and ends (they end a job differently) and share `stuck_running_jobs`: the
  running jobs of some kinds older than an age, optionally with no task, locked FOR NO KEY UPDATE SKIP LOCKED in id order.
- Why: the backlog asked for the first two indexes only if listing was slow; they cost little beside the task table's
  existing four and the paging needs the second. The reapers had one shape.
- Reversible: yes

### D-1282 — A per-key cap on uncharged role S calls: a lifetime counter
- Date: 2026-10-17 · Change/PR: jobs-crawl-perf (#246) · Status: decided (owner-delegated 2026-10-17)
- Decision: `project.draft_call_cap` (null: none) bounds `api_key.draft_calls`, the model calls with no job to pay for
  (`LLMRequest.job_id` None) made on behalf of the key, counted in one `UPDATE` as the call is made, a failure included.
  `KeyCapped` wraps the API's client per request (REST routers and MCP); a stored draft makes no call and counts nothing.
  A refusal is a 429 `draft_cap_reached`. `PATCH /v1/project/settings` takes both caps; the Settings screen sends the
  loaded `draft_call_cap` back unchanged.
- Alternatives: a window (per day) in a counter table; a cap in the client by key; the per-key rate limit alone.
- Why: the smallest bound that needs one column per side. A key at its cap is raised by the setting, or replaced.
- Reversible: yes

### D-1283 — A listing page's standing record is the task that last stood for its rows
- Date: 2026-10-17 · Change/PR: jobs-crawl-perf (#246) · Status: decided (owner-delegated 2026-10-17)
- Decision: after a records task extracts a listing page, `url_state.standing_task_id` names it (a task that finds it
  unchanged leaves it: it has no extraction to check).
  The next run's standing records are the latest versions of the entities that task's `task_record` rows hold, valid
  when its extraction used the mode and config version this run would, its links are no older than the page's
  `last_changed_at`, and each entity's latest version has the schema's current digest. Then the SimHash and 304 paths
  end the task `unchanged`, as for a detail page.
- Alternatives: one record for the page (a pollutant of the records list); an index on `url_task (canonical_url)`.
- Why: a listing's records are keyed by row URL, so no entity is the page's own. One column answers it.
- Reversible: yes

### D-1284 — The listing diff tracks row URLs, on the host the crawl went to
- Date: 2026-10-17 · Change/PR: jobs-crawl-perf (#246) · Status: decided (owner-delegated 2026-10-17)
- Decision: for a listing schema the listing holds the row URLs of the records the job's tasks stand for: the first of
  the schema's `row_url_fields` a record publishes, canonical, on the crawl's host, beside the matched task URLs. The
  host is that of `job.start_location`, else the start URL's.
- Why: SPEC-11 §4.5 said no job stores listing records; since #206 it does. A redirect to `www.` put every task off the
  start URL's host, so the listing was empty.
- Reversible: yes

### D-1285 — A crawl stores where its start page is; the redirect target is not fetched again
- Date: 2026-10-17 · Change/PR: jobs-crawl-perf (#246) · Status: decided (owner-delegated 2026-10-17)
- Decision: the start task writes `job.start_location` (`crawl.rules.located`) on the attempt that adds URLs; later tasks
  read it from the job row. When it is not the start URL, the frontier never takes it (`Frontier.fetched`): its page is
  the start task's. Only the start page's redirect is deduplicated; another page's redirect target is still a task.
- Why: the start task's capture was a join per task; its target is linked from nearly every page of the site.
- Reversible: yes

### D-1286 — A crawl takes the batch's `budget`
- Date: 2026-10-17 · Change/PR: jobs-crawl-perf (#246) · Status: decided (owner-delegated 2026-10-17)
- Decision: `CrawlRequest.budget` is the same optional `Budget` (`llm_calls`) as a batch's, read by
  `budget_remaining` from the stored request; without it the project's `llm_call_cap` applies.
- Reversible: yes

### D-1287 — #149 is already done
- Date: 2026-10-17 · Change/PR: jobs-crawl-perf (#246) · Status: decided (owner-delegated 2026-10-17)
- Decision: learning calls SPEC-09 discovery, role D and recipe validation (`learning._learned` through `learn_recipe`
  and `attach`; the worker passes `learning_replay`), so the backlog line is deleted with no code.
- Reversible: yes

### D-1288 — `crawl.canonical` moves to `normalize.url_key`
- Date: 2026-10-17 · Change/PR: jobs-crawl-perf (#246) · Status: decided (owner-delegated 2026-10-17)
- Decision: `canonicalize` (the url type's canonical form with the query's pairs sorted, D-0717) lives in
  `crawlerai/normalize/url_key.py`; the listing diff keys row URLs by it, as every job kind keys its tasks, and
  `recurring` may not import `crawl` (layering contract: peers). All callers moved; `crawl/canonical.py` is gone.
- Alternatives: `ignore_imports` for the one import (weakens the contract); a callback bound by each caller of
  `close_run`; the url type's own canonical form without the query order (two keys for one page).
- Reversible: yes
