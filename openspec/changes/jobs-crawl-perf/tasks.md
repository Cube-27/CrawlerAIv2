# Tasks: jobs-crawl-perf

## 1. Job records and indexes
- [ ] 1.1 `GET /v1/records?job_id` pages from the job's tasks by id; a record several tasks stand for is listed once. (#246)
- [ ] 1.2 Indexes `url_task (job_id, status, outcome)`, `url_task (job_id, id)` and `job (started_at) WHERE status = 'running'`. (#246)
- [ ] 1.3 `fail_stalled_jobs` and `expire_learn_runs` share one reaper query. (#246)

## 2. Crawl
- [ ] 2.1 The start task stores where its page is on the job; later tasks read it from the job. (#246)
- [ ] 2.2 The page the start URL redirected to is never a task of its own. (#246)
- [ ] 2.3 `CrawlRequest.budget`. (#246)

## 3. Recurring
- [ ] 3.1 A listing page's standing record: an unchanged listing is not extracted again. (#246)
- [ ] 3.2 The listing diff tracks row URLs of a listing crawl. (#246)

## 4. Caps
- [ ] 4.1 `project.draft_call_cap`: a per-key cap on uncharged role S calls. (#246)

## 5. Backlog
- [ ] 5.1 Close #149: learning already calls discovery, role D and recipe validation; delete the line. (#246)
