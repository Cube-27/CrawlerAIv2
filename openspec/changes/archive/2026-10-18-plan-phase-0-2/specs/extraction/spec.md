# Extraction delta

## ADDED Requirements

### Requirement: Row item URLs without session parameters
A listing's published row item URLs SHALL drop each query parameter that two or more row URLs all carry once with one
same value and that none of the page's own URLs carries (`normalize.url_key.session_parameters`); a parameter with
distinct values per row is kept. The extraction result names the parameters dropped. Refs: owner (2026-10-18, master
plan decision 6).
#### Scenario: Visit parameter on every row
- **WHEN** every row URL carries `sid=abc` and its own `v=<n>`, and the page URL carries neither
- **THEN** the rows publish their URLs with `v=<n>` and without `sid`
