## ADDED Requirements

### Requirement: Advanced fetch options and actions editor
The Options of Scrape, Batch, Crawl and Extract SHALL hold an Advanced section (collapsed by default): headers and
cookies (one `Name: value` / `name=value` per line), proxy pool, wait for and cache, sent as the `fetch` members while
filled; and an actions editor that adds, edits, reorders and removes steps (at most 20), sent as `fetch.actions`.
Refs: owner delegation 2026-10-17, D-1430, D-1436.
#### Scenario: A click step
- **WHEN** the user adds a Click step with selector `.more`
- **THEN** the request's `fetch.actions` is `[{"type": "click", "selector": ".more"}]`
