# Change: jobs, crawl and recurring performance and caps

## Why

Seven follow-ups of merged PRs (#158, #19/#146/#195, #213, #206, #218/#224, #205, #149) leave work linear in a job's
size per request, a crawl that fetches its redirected start page twice, a listing page that is always extracted again,
and two unbounded spends: a crawl with no budget of its own and field-name drafts that no job pays for.

## What Changes

- A job's records are paged from its tasks by id (keyset) instead of from the set of its `task_record` rows.
- Indexes: `url_task (job_id, status, outcome)` and `(job_id, id)`, and `job (started_at) WHERE status = 'running'`;
  `fail_stalled_jobs` and `expire_learn_runs` share one reaper query.
- A crawl stores where its start page is on the job (`job.start_location`) instead of looking up the start task's
  capture, and never adds the page the start URL redirected to as a task of its own.
- A listing page gets a standing record (`url_state.standing_task_id`): an unchanged listing is not extracted again.
  The listing diff tracks a listing crawl's row URLs.
- `CrawlRequest` takes an optional `budget`.
- `project.draft_call_cap` caps the uncharged role S calls (field-name drafts) of each API key.
- #149 (SPEC-09 discovery, role D and recipe validation in learning) is already wired (`learning._learned`,
  `worker.learn`): its backlog line is deleted.

## Impact

- Capabilities: [jobs](../../../specs/jobs/spec.md), [rest-api](../../../specs/rest-api/spec.md),
  [llm](../../../specs/llm/spec.md).
- The baseline migration is edited in place (greenfield): `job.start_location`, `url_state.standing_task_id`,
  `api_key.draft_calls`, `project.draft_call_cap`, three indexes.
- API: `CrawlRequest.budget`, `ProjectSettings.draft_call_cap` (required in `PATCH /v1/project/settings`), a 429
  `draft_cap_reached` problem; `make api-client` regenerated.
- No extraction behaviour change.
