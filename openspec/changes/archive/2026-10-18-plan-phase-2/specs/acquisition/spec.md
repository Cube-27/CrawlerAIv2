## MODIFIED Requirements

### Requirement: Capture contents and the fetch CLI
A capture SHALL hold the body, network JSON bodies and a manifest (headers, timings, block class, attempts,
`page_kind`, and for a browser capture of a listing the rendered area of each block of its repeated item groups by
element path, `item_areas`, at most 2,000 blocks), with usage counted per attempt; `crawlerai fetch URL --out` writes a
bundle and exits 0 whenever one is written. Conditional GET is in [jobs](../jobs/spec.md). (Previously: no item areas.)
Refs: §15, D-0146, D-0250, owner #67.
