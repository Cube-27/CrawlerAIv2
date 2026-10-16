# Change: job-platform (ATS) adapters

## Why

The owner admitted adapters for the big hiring platforms (2026-10-16), starting with Workday. Their career sites
render job lists in the browser from JSON, so the page path's HTTP rung gets a shell and no rows; the JSON the
sites' own pages call holds every row with its job URL, and each job's stated fields.

## What Changes

- Adapter protocol: `shapes` takes the page's `AdapterMatch`; a `Shape` may read a property from several members
  (`also`) and put a root before a property's string values (`prefixes`), for APIs that state a job's path relative
  to its career site.
- Workday adapter (`adapters/workday.py`): the CXS job list (`POST .../jobs`, first page) and job endpoints.
- Oracle Recruiting Cloud adapter (`adapters/oracle_recruiting.py`): the Candidate Experience REST resources.
- iCIMS gets no adapter: its career portals call no public JSON (D-1179). UKG Pro (UltiPro), ADP, Rippling and
  Paycom are follow-ups.

## Impact

- Capability: [adapters](../../../specs/adapters/spec.md) (delta in `specs/adapters/spec.md`).
- Files: `backend/src/crawlerai/adapters/`, `backend/src/crawlerai/collect/adapter.py`, `collect/run.py`, tests.
