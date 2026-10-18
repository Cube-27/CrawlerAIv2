## ADDED Requirements

### Requirement: Minimum confidence
`POST /v1/scrape`, `/v1/batch/scrape`, `/v1/crawl` and `/v1/extract` (and the MCP tools that take their bodies) SHALL
accept an optional `min_confidence` from 0 to 1, with no default, outside which the request is 422; a `records` field
whose calibrated confidence is below it is `abstained` with reason `below_min_confidence`
([resolution](../resolution/spec.md)). Refs: D-1771.
#### Scenario: Unset
- **WHEN** a request sets no `min_confidence`
- **THEN** every chosen field publishes with its confidence
