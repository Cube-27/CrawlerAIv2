## MODIFIED Requirements

### Requirement: Page content formats
The system SHALL produce `markdown`, `html`, `raw_html`, `links` and `metadata` from the `ParsedPage` with no per-site
cleaning (`content/`); `markdown` is `""` when there is no main content, keeps the space after an inline element in a
`div`, `td` or `li`, and a listing capture appends its repeated linked-item group with the most structural evidence
(items with an image or several text runs, then size) as a list, a listing without one being read in recall mode.
Refs: §8.5, SPEC-07 §4.5, D-0401, D-0993, D-1275, D-1276, D-1277; endpoint in [rest-api](../rest-api/spec.md).
(Previously: the largest group, and precision mode for every page.)
#### Scenario: No main content
- **WHEN** trafilatura finds no main content
- **THEN** `markdown` is the empty string
#### Scenario: Tag cloud beside a grid
- **WHEN** a listing holds 30 bare tag links and 4 cards with an image, a link and a price
- **THEN** the cards are the listed items
