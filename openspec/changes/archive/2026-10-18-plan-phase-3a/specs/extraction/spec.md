## MODIFIED Requirements

### Requirement: Cleaned text and visibility index
The system SHALL render cleaned text in one walk that drops non-rendered and HTML-hidden elements and joins inline text
per CSS Text 3 (`content/text.py`); an element whose text ends in an ellipsis and whose `title` extends it reads as
that title; the walk records each shown link (`a[href]`) and image (`img[src]`) with its span, path, target and
announced name; `visible(value)` is a whole-word match on that text plus shown elements' `alt`, `title`, `value` and
`content`. (Previously: links and images were not recorded.) Refs: SPEC-05 §4.4, D-0334..D-0339, D-1154, D-1624.
#### Scenario: Price split across inline elements
- **WHEN** the page shows `$<span>19</span>.99`
- **THEN** the cleaned text holds `$19.99` and `visible("9.99")` is false
