## MODIFIED Requirements

### Requirement: Scrape outcomes, not errors, for page failures
A page not reached SHALL answer 200 with its outcome and no format or record; a robots.txt disallow is `blocked` with
null capture and `reason` `robots`, an unreadable robots.txt `blocked` with `reason` `robots_unreachable`, a host whose
turn at its rate is more than a minute off `blocked` with `reason` `slow_down` and nothing sent, and a page a vendor's
challenge kept from being reached `blocked` with `reason` `challenge: <vendor>`. A listing whose extraction gives no
rows answers `reason` `no_rows: <cause>` (`resolve/pipeline.py`: role C not asked, its failure reason, or none listed),
also the task's `last_error`, and a `page` member holding the page-scope fields in the record field shape; `reason` is
null for any other page fetched. Request-level failures are problems: an SSRF refusal (DNS failure included) is 422
`ssrf_rejected` before any job is created; the guard is in [acquisition](../acquisition/spec.md) (INV-16). (Previously:
a vendor block answered no reason, and a scrape waited for any turn.) Refs: §18, D-0423, D-0426, D-0504, D-1451, D-1475,
D-1476.
#### Scenario: Robots disallow
- **WHEN** robots.txt disallows the URL
- **THEN** the answer is 200, outcome `blocked`, `reason` `robots`, with null `capture_id` and no format members
#### Scenario: Robots unreachable
- **WHEN** the URL's robots.txt answers 5xx
- **THEN** the answer is 200, outcome `blocked`, `reason` `robots_unreachable`, and the page is not fetched
#### Scenario: Listing without rows
- **WHEN** a listing with a `rel=next` link gives no rows and role C is unavailable
- **THEN** `records` is empty, `reason` is `no_rows: llm_unavailable` and `page.next_page_url` is published

### Requirement: Scrape browser actions
`POST /v1/scrape` SHALL take an optional `browser_actions` (`records`, a soft row target, default 100; `hint`:
`load_more`, `show_more`, `pagination`, `next` or `scroll`), refused 422 unless `page_kind` is `listing`, and with
`max_age` > 0 or `method_hint` `http`; batch has no such member. A listing scrape asking for `records` in `auto` without
it grows its list with the default `browser_actions` when its page is rendered (owner decision 11 of the master plan,
2026-10-18). The request's `fetch.actions` and `wait_for` run first on the settled page. With `records` asked, each
further kept document state is a capture with its own extraction under its own URL, stored once the first state's did
not fail; the answer lists records once each (a failed further state makes it `partial`), `capture_id` and formats are
the first state's, and `browser_actions` reports the mechanism, stop reason, actions, pages and items. (Previously: only
a request naming `browser_actions` grew its list.) Refs: owner #52, D-1218, D-1222, D-1223, D-1513.
#### Scenario: Detail page
- **WHEN** a scrape with `page_kind` `detail` sets `browser_actions`
- **THEN** the answer is a 422 problem naming `browser_actions` and no job is created
#### Scenario: Steps before paging
- **WHEN** a listing scrape sets `browser_actions` and `fetch.actions` with a click on a consent button
- **THEN** the click runs before the paging driver reads the page, and `fetch.attempts` carries its outcome
