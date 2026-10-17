# Change: paged adapter lists, Workday on a tenant's own host, five more platform adapters

## Why

An adapter answered the first page of a list only (Workday 20 postings, Oracle Recruiting 25), so a scrape of a career
site with hundreds of postings returned a small fraction of them. A Workday site served on the tenant's own domain
was not recognised at all, and five more hosted job-board platforms publish the same public JSON their own pages load.
The owner delegated the decision to admit them (2026-10-17, owner decision #57, §22 "More platform adapters").

## What Changes

- **Paged lists.** An adapter fetches every page of a list through the caller's polite `send`, bounded by the
  request's row target (`fetch.max_rows`, soft) and a hard cap, and the pages merge into one `api` capture. Workday
  CXS pages by `limit` 20 and `offset`, the total stated on the first page only, ending on a short page; Oracle
  Recruiting by `limit` 100 and `offset` until `TotalJobsCount`.
- **Workday on the tenant's own host.** A page fetched from another host whose redirect, canonical link, `og:url` or
  links point to a Workday career site is served from that site's CXS endpoints (structural signals only), through
  a new optional adapter capability (`Referring`).
- **New adapters** with `JobPosting` shapes: Ashby, SmartRecruiters (pages of 100), Recruitee, Workable (v1 widget)
  and Rippling (list and detail). Each maps title, locations, date posted, employment type, description, salary
  (where the API states one), identifier and URL. They run by default (`CRAWLERAI_DISABLED_ADAPTERS` opts out).
- A node a shape gives properties is read as an object of schema.org names (a `MonetaryAmount` with `currency`,
  `minValue`, `maxValue`, `unitText`), as a JSON-LD node is, so a `range` field reads a salary.

## Impact

- Capabilities: [adapters](../../../specs/adapters/spec.md).
- Design: Appendix A #57; §22 "More platform adapters".
- Files: `backend/src/crawlerai/adapters/` (paging, five adapters, Workday, Oracle, registry, base),
  `acquire/{rungs,page_refs,types}.py`, `collect/adapter.py`, `services/scrape_steps.py` (`FetchOptions.max_rows`),
  `frontend/openapi.json` and the generated client types.
