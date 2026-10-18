## MODIFIED Requirements

### Requirement: Queue, leases and retries
Job and task kinds, statuses and outcomes SHALL be those in `db/models.py`; task errors are outcomes, and a job ends
`failed` only when every task failed or the budget ran out before any completed. Workers SHALL claim tasks with `FOR
UPDATE SKIP LOCKED` by priority then id under a 10-minute lease; a fetch `error` is retried to 3 attempts with backoff
30 s × 2^(n−1) (`core/retry.backoff_delay`, the rule the polite fetch also pauses a host by), a page `blocked` by a
vendor's challenge once, every other outcome is terminal, and an SSRF or redirect refusal fails the task at once.
Politeness is per site in the worker. (Previously: a vendor block was terminal.) Refs: §6, D-0006, D-0632, D-0705,
D-0764.
