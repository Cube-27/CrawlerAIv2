## MODIFIED Requirements

### Requirement: Embedded JSON state and XHR admission
The system SHALL admit a scalar from `<script>` JSON, JS assignments or captured XHR bodies only when it equals another
kind's candidate (`independent=false`, owned by that candidate's entity), or when the field has none, the value is
visible and its type is checkable (`collect/admission.py`); text-like types admit by equality only. A value admitted by
visibility inside an array row (an object item of an array holding two or more objects, or an array's only object when
its own scope writes a URL that names a document, not a media file) is owned by that row's `array_row` entity, whose
`urls` are the URLs in its scope up to nested rows; elsewhere it is owned by `page`. An array row writing a URL is an
`array_row` entity even when it owns no value, so a listing's rows bind to it ([listings](../listings/spec.md)). Each
field, normalized value and owner is one candidate, the one with the shortest locator. (Previously: only a row owning a
value was an entity.) Refs: §8.1, Appendix A #34, #55, D-0418, D-0943, D-1250–D-1252, D-1254, D-1343, D-1345.
#### Scenario: Visible text in state
- **WHEN** a visible state string is the only candidate for a `text` field
- **THEN** it is not admitted
#### Scenario: Price in a row of state
- **WHEN** a visible state price is the only candidate for a `money` field and sits in the second object of an array
  of two objects
- **THEN** it is owned by that object's `array_row` entity, not by `page`
#### Scenario: Related item alone in its array
- **WHEN** an array's only object writes another page's URL and a visible price
- **THEN** the price is owned by that object's `array_row` entity and is not the detail target's

### Requirement: No generic DOM heuristics
Collectors SHALL contain no hostname, class fragment, phrase list or card selector; per-site selectors live only in
configs. Repeated-structure rows and typed value spotting are read only by the item layer
([listings](../listings/spec.md)), from structure, field types and named standards. (Previously: repeated-structure
extraction and typed value spotting were not built.) Refs: C2, C3, C13, owner #67.
#### Scenario: Site literal in a collector
- **WHEN** a change adds a hostname or class fragment under `collect/`
- **THEN** the site-literal scan fails

### Requirement: Page content formats
The system SHALL produce `markdown`, `html`, `raw_html`, `links` and `metadata` from the `ParsedPage` with no per-site
cleaning (`content/`); `markdown` is `""` when there is no main content, keeps the space after an inline element in a
`div`, `td` or `li`, and a listing capture appends the first of the page's ranked repeated item groups
(`ParsedPage.item_groups`, [listings](../listings/spec.md)) as a list, a listing without one being read in recall
mode. A JSON body (an `api` capture's) is never read as HTML: its `links` are its absolute http(s) URL string values
in document order, never markup inside a value; its `markdown` (and `markdown_fit`) is the answer pretty-printed in
one fenced `json` code block; its `html` is `""`. (Previously: the group with the most structural evidence was chosen
by the format itself.) Refs: §8.5, SPEC-07 §4.5, D-0401, D-0993, D-1275, D-1276, D-1277, D-1450, D-1473, D-1474;
endpoint in [rest-api](../rest-api/spec.md).
#### Scenario: No main content
- **WHEN** trafilatura finds no main content
- **THEN** `markdown` is the empty string
#### Scenario: Tag cloud beside a grid
- **WHEN** a listing holds 30 bare tag links and 4 cards with an image, a link and a price
- **THEN** the cards are the listed items
#### Scenario: API answer
- **WHEN** an adapter's JSON answer holds a posting URL and a description whose markup links elsewhere
- **THEN** `links` holds the posting URL and nothing read from the description's markup, `markdown` is the answer in a
  `json` code block and `html` is empty

## REMOVED Requirements

### Requirement: Cold listing rows and pagination
Moved to [listings](../listings/spec.md) ("Stated rows", "Role C rows", "Next pages"), rewritten for the item layer.

### Requirement: Listing rows from captured calls
Moved to [listings](../listings/spec.md) ("Rows from captured calls"); the call-row join is the bind step's.

### Requirement: Row item URLs without session parameters
Moved to [listings](../listings/spec.md) ("Row item URL").
