## Decisions

### D-1510 — Secrets leave a job's request when it ends; a schedule keeps none
- Date: 2026-10-18 · Change/PR: ops-followups (#268) · Status: decided (owner-delegated 2026-10-17)
- Decision: `transition_job` replaces every caller header and cookie value in `job.request` by `**********` when the job reaches an end status (`core/redaction.py`, which also holds `REDACTED` and `redacted_request`); a running job keeps them for its workers. A schedule keeps no secret value: a request with `fetch.headers` or `fetch.cookies` is refused 422 (`Unschedulable`), since a stored placeholder was sent as the value by every run. A stored run's request (secrets shown as `**********`) is refused the same way.
- Alternatives: encrypt values on the schedule (needs a deployment key setting and a crypto dependency the repo does not have); keep the values on scheduled jobs only; scrub only when no schedule needs them.
- Why: nothing reads the values after the job ends; the conservative choice stores no secret beyond a job's life. Authenticated recurring crawls wait for a key setting (follow-up).
- Reversible: yes

### D-1511 — Webhook deliveries are readable, keep the receiver's status, and expire after 30 days
- Date: 2026-10-18 · Change/PR: ops-followups (#268) · Status: decided (owner-delegated 2026-10-17)
- Decision: `webhook_delivery.response_code` holds the status the receiver answered the last attempt with (NULL when it gave none), added to the baseline migration with a partial index on `created_at` for ended rows. `GET /v1/jobs/{id}/webhook-deliveries` and the MCP tool `webhook_deliveries` list a job's deliveries newest first by cursor with `event_count`; `next_attempt_at` is set only while pending. The scheduler entry `expire_webhooks` deletes ended deliveries (`delivered` and `failed`) older than 30 days with their events, oldest first in batches; a pending delivery is never deleted.
- Alternatives: expire `delivered` only (a failed one would stay forever); 7 days; keep events and drop deliveries.
- Why: the backlog asked for delivered rows to expire; a failed delivery is as stale and, unlike candidates, its only reader is this endpoint; 30 days is the candidates' TTL.
- Reversible: yes

### D-1512 — The Deliveries panel is collapsed and appears only for a job with a webhook
- Date: 2026-10-18 · Change/PR: ops-followups (#268) · Status: decided (owner-delegated 2026-10-17)
- Decision: `WebhookDeliveries` is a `Collapsible` (nothing is read until opened) in the run page and the job page, absent when `webhook_url` is null; its `PagedTable` reads again every 5 s while a delivery is pending.
- Alternatives: a tab; always shown.
- Why: DESIGN.md's collapsed-detail pattern; most jobs have no webhook.
- Reversible: yes

### D-1513 — The paging driver runs the caller's steps first, and the recipe stands aside
- Date: 2026-10-18 · Change/PR: ops-followups (#268) · Status: decided (owner-delegated 2026-10-17)
- Decision: `fetch_listing` runs the policy's steps (`browser.stepped`) after the settle and before the first read, inside the render's time cap plus the steps' budget; the first kept state's attempt carries their outcomes. `check_browser_actions` no longer refuses `fetch.actions` or `wait_for` (amends D-1439). With steps, the site's API recipe is not tried, since its HTTP pages would skip them.
- Alternatives: steps before each paged state; steps after the first state; running the recipe and the steps.
- Why: a consent banner or filter changes the page the driver acts on once; later states are the same document or its next pages.
- Reversible: yes

### D-1514 — Schedules are edited as name, cadence and request JSON, and made from a stored run
- Date: 2026-10-18 · Change/PR: ops-followups (#268) · Status: decided (owner-delegated 2026-10-17)
- Decision: Edit is a dialog with the create dialog's name and cadence fields plus the request as JSON text; it sends only changed members (`kind` with a changed `request`), so an unchanged request is not checked again and an interval that is not whole minutes is not rounded. "Schedule this run" reads `GET /v1/jobs/{id}/request` and opens the create dialog with it; a run with caller secrets gets the server's 422 (D-1510).
- Alternatives: per-field request editors; rebuilding the playground form from the stored request.
- Why: the PATCH takes the whole request and checks it; one JSON field covers every kind without a second form.
- Reversible: yes

### D-1515 — The playground names the page fields and the no-rows cause
- Date: 2026-10-18 · Change/PR: ops-followups (#268) · Status: decided (owner-delegated 2026-10-17)
- Decision: a scrape's `page` shows as a Page fields table (the shared `FieldsTable`) and as `page` beside `data` in the JSON; a `no_rows: <cause>` reason shows as a sentence for `none_listed`, `not_asked` and any other cause (the row reader's failure), with the server's string as its tooltip.
- Alternatives: fold `page` into the first record; show the code only.
- Why: D-1475 and D-1476 added the members for callers; the playground is the first place a caller reads them.
- Reversible: yes

### D-1516 — Config approval needs nothing more
- Date: 2026-10-18 · Change/PR: ops-followups (#268) · Status: decided (owner-delegated 2026-10-17)
- Decision: Reject and Approve were driven through the UI against a live API: approve activates the waiting version and suspends the one it replaced, reject suspends the waiting version and the active one goes on serving; both buttons then disappear. Nothing is built; no backlog line remains for it beyond the existing pause note.
- Alternatives: a confirmation toast; a confirm dialog.
- Why: both actions are reversible by a later learn run and the status chip shows the outcome.
- Reversible: yes
