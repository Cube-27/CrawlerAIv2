# Change: five more platform adapters, adapter entities with identity

## Why

Five more hosted job-board platforms publish the same public data their own career pages load, so a scrape of one of
their boards read rendered pages (or nothing, for a script-built list) instead of the data. The owner delegated the
decision to admit them (2026-10-17, owner decision #57, §22 "More platform adapters"). Separately, an adapter's entity
carried no identity (#247 left it out), so its statement of an item could not merge with the page's own JSON-LD
statement of the same item.

## What Changes

- **New adapters** with `JobPosting` shapes, registered and on by default: BambooHR (careers list and detail), Teamtailor
  (the JSON Feed of jobs, with the schema.org members each item carries), UKG Pro (the search API's pages by `Top` and
  `Skip`, and the opportunity page's embedded object, with pay), Personio (the XML feed) and ADP Workforce Now (the
  requisition list, and a requisition by the external id the page names).
- **Non-JSON answers.** A request may be `raw`: a 2xx answer is `ok` whatever its body, and the adapter records the
  JSON it reads from it (a feed, an embedded object), so the capture the collector reads stays JSON.
- **A bounded XML reader** (`adapters/xml_reader.py`): entities and DTDs off, a DOCTYPE refused, converting a feed into
  the arrays-by-name JSON a `Shape` reads.
- **Identity.** The adapter collector builds its entities as every structured collector does
  (`schema_org_map.entity`): the shape's identifier values and item URLs are the entity's identity, so resolution
  (`resolve.identity`) merges it with the page's JSON-LD entity for the same item.

## Impact

- Capabilities: [adapters](../../specs/adapters/spec.md).
- Design: Appendix A #57 (extended); §22 "More platform adapters".
- Files: `backend/src/crawlerai/adapters/` (five adapters, `answer.py`, `xml_reader.py`, registry, paging,
  SmartRecruiters), `acquire/api.py` (`JsonRequest.raw`), `collect/adapter.py`.
