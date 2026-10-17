## ADDED Requirements

### Requirement: Paged adapter lists
An adapter whose API serves a list in pages SHALL fetch the pages through the caller's `send` (so robots.txt and the
host's rate hold per request) and return them as one `api` capture: the first page's manifest, a merged body and every
attempt. The walk ends at the adapter's last page, when the rows reach `fetch.max_rows` (a soft target: whole pages are
kept) or the hard cap of 1000 rows, on an empty page, or after 30 s; a later page that fails ends it with the pages
read, and only the first page decides the outcome. Refs: D-1300, D-1301.
#### Scenario: Row target
- **WHEN** a list of 1000 postings is fetched with `max_rows` 30 and the pages hold 20
- **THEN** two pages are requested and the capture holds 40 postings
#### Scenario: Later page fails
- **WHEN** the third page of a list is not JSON
- **THEN** the capture is `ok` with the first two pages' rows

### Requirement: Referral from a tenant's own host
An adapter MAY state, from what a fetched page declares about itself (its final URL after redirects, `link
rel=canonical`, `og:url`) and the targets of its links, the platform page the page stands for (`Referring.referred`);
a page the adapter did not detect by URL is then served by that adapter, recorded under the platform page, when the
page is `ok`, the site's rate admits the request and the platform's host is not declined. Only structure decides, never
a list of hosts or words. Refs: D-1302.
#### Scenario: Branded careers page
- **WHEN** a listing page on another host links only to job and sign-in pages of one Workday career site
- **THEN** that site's list is served by the Workday adapter and the result lists the page attempt then the `api` attempts
#### Scenario: Two sites
- **WHEN** a listing page links to two Workday career sites
- **THEN** no site is referred and the page stays as fetched

### Requirement: Ashby, SmartRecruiters, Recruitee, Workable and Rippling adapters
They SHALL detect only the hosted forms their public APIs name (Ashby boards, SmartRecruiters company and posting
pages, Recruitee company hosts, Workable account pages, Rippling boards and jobs), fetch the documented JSON
(SmartRecruiters in pages of 100) and map `JobPosting` title, location(s), date posted, employment type, description,
identifier and URL, and the salary where the API states an amount, as in `adapters/{ashby,smartrecruiters,recruitee,
workable,rippling}.py`; pages the API has no endpoint for fall to the page rungs. Refs: D-1303, D-1305, D-1306, D-1308.

## MODIFIED Requirements

### Requirement: Shapes read as schema.org nodes
An adapter SHALL state, for the page it detected (its `AdapterMatch`), the `Shape`s that place schema.org nodes in its
JSON; the adapter collector walks them into entities and candidates with `source_kind='adapter'`, mapped like JSON-LD,
listings as `ItemList` rows. A shape may read a property from further members after its own (`also`) and put a
root before each of a property's string values (`prefixes`); a field that reads a whole node whose shape maps
properties reads an object of those properties' schema.org names. A body that does not match yields no entities, never
an exception. Refs: §8.1, D-0266, D-1087, D-1115, D-1176, D-1304.
(Previously: a node read whole was the API's own object.)

### Requirement: Workday adapter
It SHALL detect career sites on `{tenant}.{dc}.myworkdayjobs.com/[{locale}/]{site}` and
`{dc}.myworkdaysite.com/[{locale}/]recruiting/{tenant}/{site}` and their `/job/{location}/{slug}` pages, fetch the
site's CXS endpoints on the page's host (`POST .../jobs` in pages of 20 by `offset`, the first page's `total` ending the
list, else a short page; `GET .../job/...`), and map rows with their job URL (site root + `externalPath`) and jobs with
title, description, locations as written, date posted, employment type, hiring organization and URL, as in
`adapters/workday.py`. It SHALL refer a page on another host to the career site it names as itself or, for a listing,
the one site all its Workday links belong to. A list URL with a query falls through to the page rungs. Refs: D-1177,
D-1300, D-1302.
(Previously: the first page of 20 only, and career sites on the platform's hosts only.)
#### Scenario: Listing row URL
- **WHEN** a listing answer row has `externalPath` `/job/Northtown/Engineer_R-1` for the site `https://t.wd1.myworkdayjobs.com/External`
- **THEN** the row's URL is `https://t.wd1.myworkdayjobs.com/External/job/Northtown/Engineer_R-1`
#### Scenario: Pages until a short page
- **WHEN** a site holds 45 postings
- **THEN** offsets 0, 20 and 40 are requested and the capture holds 45 postings

### Requirement: Oracle Recruiting Cloud adapter
It SHALL detect Candidate Experience sites on `{pod}.fa[.{dc}].oraclecloud.com/hcmUI/CandidateExperience/{lang}/sites/
{site}` (the site's URL, `/requisitions` or `/jobs`) and their `job/{id}` and `preview/{id}` pages, fetch the
documented `recruitingCEJobRequisitions` (pages of 100 by `offset` until the first item's `TotalJobsCount`) and
`recruitingCEJobRequisitionDetails` resources on the page's host, map rows with their job URL (site URL + `/job/{Id}`),
and class an answer without items `not_served`, as in `adapters/oracle_recruiting.py`. Refs: D-1178, D-1300, D-1307.
(Previously: the first page of 25 only.)
