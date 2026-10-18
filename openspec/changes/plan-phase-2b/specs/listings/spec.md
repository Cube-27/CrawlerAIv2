## MODIFIED Requirements

### Requirement: Item groups (segment)
A listing page's repeated item groups SHALL be `MIN_ITEMS` or more sibling blocks of one shape that each are or hold a
hyperlink, outside chrome (`acquire/items.py`), ranked once per parse (`ParsedPage.item_groups`, `content/segment.py`):
by the rendered area of their blocks when the browser capture measured it (`CaptureManifest.item_areas`, recorded for
listing captures), else by blocks showing an image or two or more text runs, then size; a block not rendered (no area,
or hidden by the HTML rendering rules) is left out. The markdown format, `xhr` and the paging driver read this one
ranking. (Previously: role C's item text read it too.) Refs: owner #67, master plan §3.2.
#### Scenario: Tag cloud beside a grid
- **WHEN** a listing holds 30 bare tag links and 4 cards with an image, a link and a price
- **THEN** the cards' group ranks first
#### Scenario: Measured areas
- **WHEN** a browser capture measured a sidebar's 20 links smaller in area than a grid's 6 cards
- **THEN** the grid ranks first, and a card with no area is not one of its blocks

### Requirement: Rows from captured calls
On a listing the `xhr` collector SHALL read rows from the calls of one method, origin and path, body shape and row query
(`collect/network_match.py`), the first series in which a row field's path is admitted in `MIN_ITEMS` rows or more (for
a url field also: a link of the page's item groups), each row an `array_row` entity read through the API recipe row
reader; with a learned listing recipe, its map. They are the stated rows where structured data and the config give
none; when they leave a record incomplete role C fills, through their bound blocks, the fields they lack. (Previously:
role C's rows replaced them.) Refs: §8.1, §8.6, Appendix A #59, D-1603.
#### Scenario: Complete rows of a call
- **WHEN** the rows of a call publish every required field
- **THEN** role C is not asked

### Requirement: Role C rows
Role C SHALL be asked for the blocks whose bound rows lack a row field, each for the fields its row lacks but the item
URL, when a row field is published on no row or a row lacks a required one, and never beside a config that runs a row
field; and in a separate call over the whole cleaned text for the missing page fields when a required one is missing.
Its values fill the blocks' rows; it makes no row, so a listing without rows answers `no_rows: not_asked`.
(Previously: role C was asked for rows when the listing had none, and its rows were placed on blocks by their links or
replaced rows read from blocks alone.) Refs: §8.6, owner #67, D-1603, D-1604, D-1605.
#### Scenario: Only rows lacking a required field
- **WHEN** one of five bound rows lacks a required row field and every row field is published on some row
- **THEN** role C is asked for that block only, for the fields its row lacks
#### Scenario: Listing without blocks
- **WHEN** a listing has no stated rows and no aligned item group
- **THEN** role C is not asked for rows and the answer's reason is `no_rows: not_asked`
