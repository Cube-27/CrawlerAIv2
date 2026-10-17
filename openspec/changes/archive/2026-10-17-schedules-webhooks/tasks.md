# Tasks

## 1. Schedules

- [x] 1.1 `schedule` table, `job.schedule_id`; `core/cadence.py` (5-field cron in an IANA zone, intervals, missed runs). (#259)
- [x] 1.2 `services/schedules.py`: create (checked as a submission, records schema by id, scrape as a batch), update,
      pause/resume, run now, delete; `run_due_schedules` scheduler entry, exactly once under `SKIP LOCKED`. (#259)
- [x] 1.3 `/v1/schedules` router, `GET /v1/jobs?schedule_id=`, MCP schedule tools. (#259)
- [x] 1.4 UI: Schedules screen (list, history, pause/resume/run now/delete) and "Schedule this" in the playground. (#259)
- [x] 1.5 CLI: `crawlerai schedules list|pause|resume`. (#259)

## 2. Webhook events

- [x] 2.1 `webhook_events` and `webhook_batch` on batch, crawl and extract requests (`WebhookOptions`). (#259)
- [x] 2.2 Outbox: `webhook_event` rows written with the task end, the records stored, `url_gone` and the job's end. (#259)
- [x] 2.3 `form_deliveries` (batching) and `deliver_webhooks` (body, signature, 5 attempts, SSRF guard). (#259)
- [x] 2.4 UI: webhook settings in the Options of Batch, Crawl and Extract. (#259)

## 3. Specs and verification

- [x] 3.1 Spec deltas (jobs, rest-api, frontend), §22 admission, the webhook payloads in the rest-api spec. (#259)
- [x] 3.2 Live: a 1-minute schedule against a public page via the API runs two jobs, and a local receiver gets signed
      deliveries. (#259)
