## ADDED Requirements

### Requirement: Webhook deliveries panel
A job's run page and a job's page SHALL show, for a job that has a `webhook_url`, a collapsed Deliveries panel listing
`GET /v1/jobs/{id}/webhook-deliveries` in a `PagedTable` (status, attempts, the receiver's HTTP status, events, last
error, created, next attempt), read again every 5 s while a delivery is pending; a job without a webhook has none
(`frontend/src/components/WebhookDeliveries.tsx`). Refs: D-1511, D-1512.
#### Scenario: A refused delivery
- **WHEN** a job's one delivery is `pending` after a 503
- **THEN** the panel's row shows `pending`, attempts, 503 and the error `status 503`

### Requirement: A listing's page fields and why it has no rows
The scrape output SHALL show the answer's `page` fields (a listing that kept no record) as a Page fields table under
the records in Table and as `page` beside `data` in JSON, and a `no_rows: <cause>` reason as a sentence with the
server's reason as its tooltip (`screens/playground/output/`). Refs: D-1475, D-1476, D-1515.
#### Scenario: Next page of an empty listing
- **WHEN** a scrape answers `records: []`, `page.next_page_url` and reason `no_rows: none_listed`
- **THEN** Table shows `next_page_url` under Page fields, JSON holds `"page"`, and the header says no rows were found

## MODIFIED Requirements

### Requirement: Schedules screen and Schedule this
`/schedules` SHALL list the schedules (name, kind, cadence, next run, last run and its job or error) with Edit, Pause or
Resume, Run now and Delete, and a schedule's page its jobs from `GET /v1/jobs?schedule_id=`; Edit changes the name,
cadence and request (JSON) and sends only what changed (`PATCH /v1/schedules/{id}`); Scrape, Batch, Crawl and Extract
offer "Schedule this", and a run of Batch, Crawl or Extract "Schedule this run" (its stored request), which create a
schedule (`frontend/src/screens/schedules/`). (Previously: no Edit, no Schedule this run.) Refs: D-1418, D-1514.
#### Scenario: Schedule a crawl
- **WHEN** a user fills Crawl, chooses "Schedule this" and an interval of 60 minutes
- **THEN** `POST /v1/schedules` carries `kind: "crawl"`, that crawl's request and `interval_s: 3600`
#### Scenario: Edit the cadence
- **WHEN** a user edits a schedule's name and changes its cadence to a cron expression
- **THEN** `PATCH` carries the new `name`, `cron` and `timezone`, and no `request`
