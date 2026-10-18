## MODIFIED Requirements

### Requirement: Scrape outcomes, not errors, for page failures
A page not reached SHALL answer 200 with its outcome and no format or record; a robots.txt disallow is `blocked` with
null capture and `reason` `robots`, an unreadable robots.txt `blocked` with `reason` `robots_unreachable`, a host whose
turn at its rate is more than a minute off `blocked` with `reason` `slow_down` and nothing sent, and a page a vendor's
challenge kept from being reached `blocked` with `reason` `challenge: <vendor>`. A listing whose extraction gives no
rows answers `reason` `no_rows: not_asked` (`resolve/pipeline.py`: role C, which fills the rows of blocks, was not
asked for rows), also the task's `last_error`, and a `page` member holding the page-scope fields in the record field
shape; `reason` is null for any other page fetched. Request-level failures are problems: an SSRF refusal (DNS failure
included) is 422 `ssrf_rejected` before any job is created; the guard is in [acquisition](../acquisition/spec.md)
(INV-16). (Previously: the no-rows cause was also role C's failure reason or `none_listed`.) Refs: §18, D-0423, D-0426,
D-0504, D-1451, D-1475, D-1476, D-1605.
#### Scenario: Robots disallow
- **WHEN** robots.txt disallows the URL
- **THEN** the answer is 200, outcome `blocked`, `reason` `robots`, with null `capture_id` and no format members
#### Scenario: Robots unreachable
- **WHEN** the URL's robots.txt answers 5xx
- **THEN** the answer is 200, outcome `blocked`, `reason` `robots_unreachable`, and the page is not fetched
#### Scenario: Listing without rows
- **WHEN** a listing whose schema has `next_page_url` and whose page has a `rel=next` link gives no rows
- **THEN** `records` is empty, `reason` is `no_rows: not_asked` and `page.next_page_url` is published
