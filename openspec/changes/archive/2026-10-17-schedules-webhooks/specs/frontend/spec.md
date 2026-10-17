## MODIFIED Requirements

### Requirement: App shell and navigation
The shell SHALL have a sidebar with groups Playground (from `screens/playground/modes.ts`), Data (Jobs, Schedules, Records, Schemas, Sites), Evaluate (Labeling, only when `GET /healthz` reports `eval_ui: true`) and Settings plus theme toggle; the current entry carries `aria-current="page"`; routes are in `frontend/src/app/router.tsx`. (Previously: no Schedules.) Refs: D-0451, D-0452, D-0834, D-1418.
#### Scenario: Labeling hidden
- **WHEN** `/healthz` answers `eval_ui: false`, fails, or has not answered
- **THEN** the Labeling entry is not shown

## ADDED Requirements

### Requirement: Schedules screen and Schedule this
`/schedules` SHALL list the schedules (name, kind, cadence, next run, last run and its job or error) with Pause or
Resume, Run now and Delete, and a schedule's page its jobs from `GET /v1/jobs?schedule_id=`; Scrape, Batch, Crawl and
Extract offer "Schedule this", which creates a schedule from the request the primary action would send
(`frontend/src/screens/schedules/`). Refs: D-1418.
#### Scenario: Schedule a crawl
- **WHEN** a user fills Crawl, chooses "Schedule this" and an interval of 60 minutes
- **THEN** `POST /v1/schedules` carries `kind: "crawl"`, that crawl's request and `interval_s: 3600`

### Requirement: Webhook options
The Options of Batch, Crawl and Extract SHALL hold Webhook URL, Events and Batch (events and seconds), mapping to
`webhook_url`, `webhook_events` and `webhook_batch`; an empty URL sends none of them. Refs: D-1419.
