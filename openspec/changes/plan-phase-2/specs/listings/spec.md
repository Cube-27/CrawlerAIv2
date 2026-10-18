## ADDED Requirements

### Requirement: Item groups (segment)
A listing page's repeated item groups SHALL be `MIN_ITEMS` or more sibling blocks of one shape that each are or hold a
hyperlink, outside chrome (`acquire/items.py`), ranked once per parse (`ParsedPage.item_groups`, `content/segment.py`):
by the rendered area of their blocks when the browser capture measured it (`CaptureManifest.item_areas`, recorded for
listing captures), else by blocks showing an image or two or more text runs, then size; a block not rendered (no area,
or hidden by the HTML rendering rules) is left out. The markdown format, role C's item text, `xhr` and the paging
driver read this one ranking. Refs: owner #67, master plan §3.2.
#### Scenario: Tag cloud beside a grid
- **WHEN** a listing holds 30 bare tag links and 4 cards with an image, a link and a price
- **THEN** the cards' group ranks first
#### Scenario: Measured areas
- **WHEN** a browser capture measured a sidebar's 20 links smaller in area than a grid's 6 cards
- **THEN** the grid ranks first, and a card with no area is not one of its blocks

### Requirement: Rows from blocks (align)
Each group whose blocks lead to one item, at least a quorum of `max(MIN_ITEMS, 60%)` of them, `MIN_ITEMS` of them
showing more than their link, SHALL give an `item_block` row per item URL (`collect/items/align.py`); a field is read at
a place shared by a quorum of the blocks whose value its normalizer accepts: the item URL (the one document the block's
links lead to, not the page in another state, an image file or an item's own nested list), the name (the accessible
name of the item link, WCAG label in name, or the block's heading; never a URL; text every block repeats is the
template's), the image, and typed value spotting for money, dates and check-digit identifiers (text in `s`/`del`
excluded). Values are `dom` candidates with locators; the group aligning most fields is first. Refs: owner #67.
#### Scenario: Cards with title, link and price
- **WHEN** a listing shows cards of varying tags and class tokens, each with a heading link and one price
- **THEN** each card is a row with its title, URL and price
#### Scenario: Was and now prices
- **WHEN** a card shows a current price and a second price not struck through
- **THEN** its price is `ambiguous_in_block` and publishes nothing unless a stated row bound to it agrees with one

### Requirement: Stated rows and blocks (bind)
The stated rows SHALL be structured data's (`resolve/listing.py`), else the active config's, else the captured calls'.
Stated rows and the blocks of the group they name most bind one to one by item URL (session parameters, a trailing
slash and added query parameters aside) or by a name the block shows (`collect/items/bind.py`). With no stated rows or
only stubs, the blocks are the rows; otherwise stated rows stay and the group's blocks no stated row names extend them.
A config's rows bind no blocks. A bound entity's values join its row where the row has none for the field or equals
them; a block's link replaces a respelled stated item URL. State and call array rows bind by URL, and a JSON key whose
values equal a block field on `MIN_ITEMS` bound rows is that field's key for every bound row (`collect/induce.py`).
Refs: owner #67, Appendix A #59.
#### Scenario: Stub rows
- **WHEN** an `ItemList` names three items by URL only and the page's cards show their titles and prices
- **THEN** the listing has three rows with the cards' titles, prices and links
#### Scenario: A grown list
- **WHEN** the script lists items 1–3 and the list's blocks show items 1–6
- **THEN** the listing has six rows

### Requirement: Rows from captured calls
On a listing the `xhr` collector SHALL read rows from the calls of one method, origin and path, body shape and row query
(`collect/network_match.py`), the first series in which a row field's path is admitted in `MIN_ITEMS` rows or more (for
a url field also: a link of the page's item groups), each row an `array_row` entity read through the API recipe row
reader; with a learned listing recipe, its map. They are the stated rows where structured data and the config give
none; when they leave a record incomplete role C is asked and its rows replace them. Refs: §8.1, §8.6, Appendix A #59.
#### Scenario: Complete rows of a call
- **WHEN** the rows of a call publish every required field
- **THEN** role C is not asked

### Requirement: Row item URL
A row's item URL field SHALL read schema.org `url`, else the item's `offers.url`, else its `mainEntityOfPage` (a URL or
a page's `url`), a bound block's link replacing a respelling; published row URLs drop each query parameter that two or
more of them carry once with one value and none of the page's own URLs carries (`normalize.url_key`), named in the
result. Refs: owner #67 decisions 1 and 6.
#### Scenario: Item named by its offer
- **WHEN** a listed Product states no `url` and its Offer states `url`
- **THEN** the row's item URL is the Offer's
#### Scenario: Visit parameter on every row
- **WHEN** every row URL carries `sid=abc` and its own `v=<n>`, and the page URL carries neither
- **THEN** the rows publish their URLs with `v=<n>` and without `sid`

### Requirement: Role C rows
Role C SHALL be asked for a listing's row fields when it has no rows, when call rows leave a record incomplete, or when
its rows publish a row field on no row, never beside a config that runs a row field. A role C row takes the item URL of
the one block holding its grounded values (`collect/item_links.py`); with no rows its rows are the listing's (a row
without a required item URL left out), else each fills the row it binds to by item URL. Refs: §8.6, owner #67.

### Requirement: Next pages
Next pages SHALL come from `rel=next`, then the link differing from the page URL in one path segment or query value by
one integer one higher, then a config's `listing.next` (`resolve/pagination.py`); the first `rel=next` link is a
page-level `dom` candidate of `next_page_url`, and a numbered link fills no field (C7). Refs: §8.6, D-0509, D-0514.
#### Scenario: Integer inside a segment
- **WHEN** a listing at `/list/page-2.html` links to `page-3.html` and `sheet-3.html`
- **THEN** `/list/page-3.html` is its next page and `sheet-3.html` is not
