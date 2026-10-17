## MODIFIED Requirements

### Requirement: Playground modes and command bar
The playground SHALL serve Scrape `/`, Batch `/batch`, Crawl `/crawl`, Map `/map`, Extract `/extract` behind a link-tab mode switch without visible group captions, with one centred command bar (input row, then Options, Format, Schema, Get code and the primary button) that does not move between the single-URL modes at desktop width; Batch's URL box shows ten lines and scrolls inside (`frontend/src/screens/playground/`). Refs: Appendix A #38, #45, #51, D-0817, D-1043, D-1213.

### Requirement: Clean JSON output and run view
Output SHALL be read as `json_values` items `{url, outcome, records, metadata?}` (endpoint owned by [jobs](../jobs/spec.md)); `JsonView`, shown first with line numbers and indent guides, holds a page's one record as an object or its records as an array, metadata under `data` beside it when asked for; a job run lives at `<route>?job=<id>` with status, Cancel, JSON/CSV exports, `RunProgress`, a `PagedTable` of items with per-row drawer, and a collapsed `ActivityFeed` worded in `activityText.ts`, where an unknown event shows its kind name. Refs: #51, D-0825, D-0826, D-0829, D-0832, D-0879, D-0984, D-1211, D-1212.
