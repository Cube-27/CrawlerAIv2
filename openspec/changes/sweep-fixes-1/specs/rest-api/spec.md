# Delta: rest-api

## MODIFIED Requirements

### Requirement: Scrape outcomes, not errors, for page failures
A page not reached SHALL answer 200 with its outcome and no format or record; a robots.txt disallow is `blocked` with
null capture and `reason` `robots`, an unreadable robots.txt `blocked` with `reason` `robots_unreachable` (null for a
page fetched). Request-level failures are problems: an SSRF refusal (DNS failure included) is 422 `ssrf_rejected` before
any job is created; the guard is in [acquisition](../acquisition/spec.md) (INV-16). (Previously: no `reason`.) Refs:
§18, D-0423, D-0426, D-0504, D-1451.
#### Scenario: Robots disallow
- **WHEN** robots.txt disallows the URL
- **THEN** the answer is 200, outcome `blocked`, `reason` `robots`, with null `capture_id` and no format members
#### Scenario: Robots unreachable
- **WHEN** the URL's robots.txt answers 5xx
- **THEN** the answer is 200, outcome `blocked`, `reason` `robots_unreachable`, and the page is not fetched
