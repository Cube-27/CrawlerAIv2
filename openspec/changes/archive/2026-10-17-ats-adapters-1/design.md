# Design: paged adapter lists, Workday on a tenant's own host, five more adapters

## Shape

- **Paging.** `adapters/paging.fetch_pages(first, policy, send, next_page, merge, rows)` sends the first request,
  then asks the adapter's `next_page(answers)` for each following one while the rows are under the target
  (`FetchPolicy.max_rows`, else the hard cap) and the time budget lasts. The result is the first page's `FetchResult`
  with the merged body (re-hashed in its manifest) and every kept page's attempt. A list of one page is returned as
  answered. Each adapter supplies three small functions (next request, merge, row count).
- **Referral.** `adapters.base.Referring` (optional, `runtime_checkable`): `referred(refs, kind)` returns a platform
  page URL from `PageRefs` (`own`: final URL, canonical link, `og:url`; `links`). `acquire.page_refs.page_refs` reads
  them from the fetched HTML; `Registry.referred` asks the active referring adapters (reading the page only when one
  exists); `acquire._by_canonical` serves the result like the query-dropped canonical case.
- **Node objects.** `collect/adapter._Node.as_object`: a node whose shape maps properties or nodes reads, as a whole,
  as an object of schema.org names.

## Decisions

### D-1300 — Pages are merged into one capture by the adapter
- Date: 2026-10-17 · Change/PR: ats-adapters-1 (#248) · Status: decided (owner-delegated 2026-10-17)
- Decision: an adapter's `fetch` walks the pages through the caller's polite `send` and returns one `api` result: the
  first page's manifest and final URL, a merged JSON body shaped like one page (Workday `jobPostings`, Oracle's first
  item's `requisitionList`, SmartRecruiters `content`), and every page's attempt. No new storage, no new protocol
  member; `serves` and the shapes are unchanged.
- Alternatives: one capture per page (the pipeline reads one capture per page and a listing's rows would be split
  across tasks); a paging protocol the caller drives (touches every caller, and politeness is already in `send`).
- Why: INV-39 and the collector read one capture; the merge keeps every consumer as it was.
- Reversible: yes

### D-1301 — Row bound: `fetch.max_rows` (soft), a hard cap of 1000 rows and 30 s
- Date: 2026-10-17 · Change/PR: ats-adapters-1 (#248) · Status: decided (owner-delegated 2026-10-17)
- Decision: `FetchOptions.max_rows` (scrape, batch, crawl) becomes `FetchPolicy.max_rows`, a soft row target like
  `browser_actions.records` (#52): the walk ends once it has at least that many rows. Without it the walk ends at
  1000 rows, an empty page or 30 s of paging, whichever comes first; a later page that fails ends the walk with the
  pages read (only the first page decides the outcome). It is an optional request member (API client regenerated).
- Alternatives: reuse `browser_actions.records` (it routes the scrape to the browser and is refused with `max_age`);
  a fixed cap only (no way to ask for fewer); no time bound (a 5000-posting site at the host's rate outlasts the
  scrape's 60 s default).
- Why: "bounded by the request's records/limit and a hard cap"; politeness holds per request through `send`.
- Reversible: yes

### D-1302 — A page on a tenant's own host is referred by structure
- Date: 2026-10-17 · Change/PR: ats-adapters-1 (#248) · Status: decided (owner-delegated 2026-10-17)
- Decision: after the page rungs, an adapter implementing `Referring` may name the platform page the page stands for.
  Workday takes, in order, a URL the page names as itself (final URL after redirects, canonical link, `og:url`) that
  it detects in the kind the fetch asked for; else, for a listing only, the one career site (tenant, site) all
  Workday-host links of the page belong to (job, sign-in and list links, with or without a locale or query); links to
  two sites, or none, say nothing. The answer is recorded under the platform page, like the canonical-without-query
  case, only when the page is `ok`, the site's rate admits it and the host is not declined.
- Alternatives: probing the platform's endpoint on every host (a request per site, D-1082 declines per host); a
  host table (C3, C7); requiring a job link (a branded list that loads its jobs by script links only to the site).
- Why: structural signals only (HTML links, RFC 6596 canonical, Open Graph `og:url`, RFC 9110 redirects), documented in
  the adapter. A branded page that links to one platform site and is scraped as a listing is the page the caller
  means; a caller who wants the page itself gets it with `page_kind` detail or `method_hint` browser.
- Reversible: yes

### D-1303 — Five platform adapters admitted; detail pages only where the API has an endpoint
- Date: 2026-10-17 · Change/PR: ats-adapters-1 (#248) · Status: decided (owner-delegated 2026-10-17)
- Decision: Ashby (list), SmartRecruiters (list in pages of 100, posting), Recruitee (list, offer), Workable (v1 widget
  list) and Rippling (list, job) are admitted from §22 "More platform adapters" (owner decision #57), on the hosts the
  platforms' own pages use; a posting page whose API has no endpoint (Ashby, Workable) takes the page rungs. Recorded
  as owner decision #57. Each platform's public JSON was measured live on at least 3 tenants other than the one used to build the shapes (Ashby 6, SmartRecruiters 4, Recruitee 3, Workable 3, Rippling 4 boards answering the documented fields), C6.
- Alternatives: the whole list for a detail page (rows would compete for the page's target by URL); Workable's v2
  per-job endpoint (a second request shape for one more field set; later).
- Why: C6 (multi-tenant platforms, measured on at least 3 tenants), D-1177/D-1178 shape.
- Reversible: yes

### D-1304 — A node whose shape maps properties reads as a schema.org object
- Date: 2026-10-17 · Change/PR: ats-adapters-1 (#248) · Status: decided (owner-delegated 2026-10-17)
- Decision: when a field's path ends at a node (`JobPosting.baseSalary`, `JobPosting.jobLocation`) the raw value is the
  object of the node's mapped properties (and nodes) under their schema.org names, as JSON-LD states a node; a node
  whose shape maps nothing is still the API's own object.
- Alternatives: the API's object always (a `range` field cannot read an API's `{min, max}`); a second salary mechanism
  (C8).
- Why: parity with the JSON-LD collector, which the field normalizers read (SPEC-04 range accepts `MonetaryAmount`).
- Reversible: yes

### D-1305 — Salary is a `MonetaryAmount` node of the component that states an amount
- Date: 2026-10-17 · Change/PR: ats-adapters-1 (#248) · Status: decided (owner-delegated 2026-10-17)
- Decision: Ashby (`compensation.summaryComponents`), Recruitee (`salary`) and Rippling (`payRangeDetails`) map
  `currency`, `minValue`, `maxValue` and `unitText` as the API writes them; a component with no lower amount (equity, an
  empty salary object) is no node (anchor). Values are not interpreted in the adapter (C7). Where a platform's period
  text is not a schema.org `unitText` (an Ashby interval such as "1 YEAR") the range normalizer declines the period and
  the field stays unpublished until it reads the text (follow-up).
- Alternatives: the platforms' summary strings (K-suffixed, no period); inferring the period (C7).
- Why: data the API states, extracted as stated.
- Reversible: yes

### D-1306 — A platform API host that disallows crawlers keeps its adapter on the page rungs
- Date: 2026-10-17 · Change/PR: ats-adapters-1 (#248) · Status: decided (owner-delegated 2026-10-17)
- Decision: SmartRecruiters' API host's robots.txt disallows every agent but one, so by default its adapter's request is
  `blocked` (`robots`) and the page falls to the page rungs (INV-40); the adapter serves when an operator overrides
  robots.txt for the job (`respect_robots=false` with a reason), or if the host changes its file. No special case.
- Alternatives: skip the adapter (the same API is open to an operator's override); override robots.txt for APIs
  (never by default, ARCHITECTURE §7.1).
- Why: politeness is the contract (SPEC-15 §4.6); the adapter was verified on recorded answers, and live only up to the
  refusal.
- Reversible: yes

### D-1307 — Oracle Recruiting pages of 100
- Date: 2026-10-17 · Change/PR: ats-adapters-1 (#248) · Status: decided (owner-delegated 2026-10-17)
- Decision: the list is requested with `limit=100` (the career site's own 25 is a UI choice; 100 was measured to answer)
  and paged by `offset` until the first item's `TotalJobsCount` (the outer `hasMore` is always false).
- Why: a quarter of the requests for the same rows.
- Reversible: yes

### D-1308 — Description is the posting's main text only
- Date: 2026-10-17 · Change/PR: ats-adapters-1 (#248) · Status: decided (owner-delegated 2026-10-17)
- Decision: SmartRecruiters reads `jobAd.sections.jobDescription`, Rippling `description.role`, Recruitee `description`;
  the sections kept apart (qualifications, company text, requirements) are not concatenated: two values of one property
  are two candidates in conflict for a single-valued field, and joining them would be inventing a value.
- Follow-up: a section-joining shape member, if the owner wants the whole ad.
- Reversible: yes
