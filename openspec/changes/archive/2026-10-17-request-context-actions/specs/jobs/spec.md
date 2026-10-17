## ADDED Requirements

### Requirement: Request context and actions per page
Batch, crawl and extract jobs SHALL fetch every page with the request's `fetch` context, `wait_for` and `actions`
(D-1439); the job keeps the secret values in `job.request` for its workers, and `GET /v1/jobs/{id}/request` answers
them as `**********`. `fetch.cache` `only` serves each task from the latest `ok` capture of its URL made with the same
actions and context names, or fails the task `not_cached`; `bypass` sends no validators. Refs: owner delegation
2026-10-17, D-1432, D-1435, D-1439.
#### Scenario: Stored request
- **WHEN** a batch is submitted with cookie `sid` and its request is read back
- **THEN** the answer's `fetch.cookies.sid` is `**********`
