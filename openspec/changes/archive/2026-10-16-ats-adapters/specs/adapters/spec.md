# Delta: adapters

## MODIFIED Requirements

### Requirement: Shapes read as schema.org nodes
An adapter SHALL state, for the page it detected (its `AdapterMatch`), the `Shape`s that place schema.org nodes in its
JSON; the adapter collector walks them into entities and candidates with `source_kind='adapter'`, mapped like JSON-LD,
listings as `ItemList` rows. A shape may read a property from further members after its own (`also`) and put a
root before each of a property's string values (`prefixes`). A body that does not match yields no entities, never an
exception. Refs: §8.1, D-0266, D-1087, D-1115, D-1176.

## ADDED Requirements

### Requirement: Workday adapter
It SHALL detect career sites on `{tenant}.{dc}.myworkdayjobs.com/[{locale}/]{site}` and
`{dc}.myworkdaysite.com/[{locale}/]recruiting/{tenant}/{site}` and their `/job/{location}/{slug}` pages, fetch the
site's CXS endpoints on the page's host (`POST .../jobs` for the first page of 20, `GET .../job/...`), and map rows
with their job URL (site root + `externalPath`) and jobs with title, description, locations as written, date posted,
employment type, hiring organization and URL, as in `adapters/workday.py`. A list URL with a query falls through to
the page rungs. Refs: D-1177.
#### Scenario: Listing row URL
- **WHEN** a listing answer row has `externalPath` `/job/Northtown/Engineer_R-1` for the site `https://t.wd1.myworkdayjobs.com/External`
- **THEN** the row's URL is `https://t.wd1.myworkdayjobs.com/External/job/Northtown/Engineer_R-1`

### Requirement: Oracle Recruiting Cloud adapter
It SHALL detect Candidate Experience sites on `{pod}.fa[.{dc}].oraclecloud.com/hcmUI/CandidateExperience/{lang}/sites/
{site}` (the site's URL, `/requisitions` or `/jobs`) and their `job/{id}` and `preview/{id}` pages, fetch the
documented `recruitingCEJobRequisitions` (first page of 25) and `recruitingCEJobRequisitionDetails` resources on the
page's host, map rows with their job URL (site URL + `/job/{Id}`), and class an answer without items `not_served`,
as in `adapters/oracle_recruiting.py`. Refs: D-1178.
