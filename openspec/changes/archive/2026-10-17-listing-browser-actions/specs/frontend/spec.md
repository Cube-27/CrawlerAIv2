## ADDED Requirements

### Requirement: Scrape browser actions options
Scrape's Options SHALL hold a Browser actions switch, Records (empty: the server's 100) and Paging hint (Detect, or
one hint), enabled only for page kind Listing and kept in place, disabled, otherwise; the switch on sends
`browser_actions` with the filled members, and never for another page kind. Refs: owner #52, D-1227.
#### Scenario: Detail page kind
- **WHEN** the switch is on and the page kind is changed to Detail
- **THEN** the rows stay where they are, disabled, and the request has no `browser_actions`
