# Extraction (delta)

## MODIFIED Requirements

### Requirement: Cold listing rows and pagination
On a listing the system SHALL take rows from `ItemList`/`ListItem` entities, with the top-level primary entities no
list holds beside them when the page singles none out (a grown list's later items stated as microdata), else from 3 or
more top-level primary entities, else from the `ListItem` entries outside a `BreadcrumbList` that state no `item` (their
own properties read as the row's on the schema's row fields), else from role C; a role C row whose grounded values lie
in exactly one block of the repeated item group holding most rows (block text as the cleaned text shows it; a value
that is an element's whole text picks its block), a block no other row has, takes as a `dom` item-URL candidate the one
document the block's hyperlinks, else its hyperlinks labelled with a row value, lead to (`collect/item_links.py`,
Appendix A #47, D-1122, D-1241–D-1244); next pages come from `rel=next`, then the link differing from the page URL in
one path segment or query value by one integer one higher (standing alone or inside the segment, `page-2.html`), then a
config's `listing.next` (`resolve/listing.py`, `resolve/pagination.py`); the first `rel=next` link is a page-level `dom`
candidate of the schema's `next_page_url`, and a numbered link fills no field (C7). (Previously: listed rows excluded
unlisted top-level entities, and only an integer standing alone as a segment or value numbered pages.)
Refs: §8.6, D-0509, D-0514, D-1226, D-1294, D-1400, D-1403.
#### Scenario: Title cut short
- **WHEN** a card shows `Widget with a lo…` with `title="Widget with a long name"` and role C grounds the full title
- **THEN** the row takes that card's link
#### Scenario: Next page of a listing preset
- **WHEN** a listing page with the `commerce_listing` schema has `<link rel="next" href="?page=2">`
- **THEN** `next_page_url` publishes the absolute `?page=2` URL with source kind `dom`
#### Scenario: Entries without items
- **WHEN** an `ItemList` holds `ListItem`s with only `name` and `url`, beside a `BreadcrumbList`
- **THEN** each `ItemList` entry is a row with that title and url, and no breadcrumb is
#### Scenario: Integer inside a segment
- **WHEN** a listing at `/list/page-2.html` links to `page-3.html` and `sheet-3.html`
- **THEN** `/list/page-3.html` is its next page and `sheet-3.html` is not

### Requirement: Listing rows from captured calls
On a listing the `xhr` collector SHALL read rows from the calls of one method, origin and path, body shape and row query
(`collect/network_match.py`: only query or body values vary; an array of `MIN_ITEMS` or more object items each holding a
visible string of its own; a request sent again counts once), the first such series in which a row field's path,
relative to a row, is admitted by the state admission rule (for a url field also: a link of one of the page's repeated
item blocks) in `MIN_ITEMS` rows or more; that path is read in every row through the API recipe row reader
(`collect/api.py`), each row an `array_row` entity; where the site's active config has a listing recipe, the calls of
its endpoint and row query are read with the recipe's map instead, text fields included (`network_match.LearnedCalls`).
Where structured data or the config give rows, a call row sharing an item URL or identifier with exactly one of them
(and it with no other call row) fills that row's fields it holds no candidate of, and a call row naming no row's item
whose item URL is a link of the block group holding most rows' item URLs is a row too (`resolve/call_rows.py`); else
resolution takes the call rows, and when they leave a record incomplete role C is asked, and its rows, if any, replace
them. (Previously: call rows served only where structured data and the config gave none.) Refs: §8.1, §8.6, Appendix A
#59, D-1313, D-1314, D-1315, D-1367, D-1401, D-1402.
#### Scenario: Rows a call proves
- **WHEN** a listing with no structured rows loaded four items whose prices it shows for three
- **THEN** the call gives four rows, each with its price, and no title (text admits by equality only)
#### Scenario: Learned map
- **WHEN** a browser capture of a listing whose recipe maps `title` holds a call of the recipe's endpoint
- **THEN** its rows carry the titles, which equality alone would not admit
#### Scenario: Complete rows of a call
- **WHEN** the rows of a call publish every required field
- **THEN** role C is not asked
#### Scenario: A call fills a structured row
- **WHEN** an `ItemList` states three products without prices and the page's call carries each one's URL and price
- **THEN** each row publishes its call's price in the `network` bucket, its title staying the `jsonld` one
#### Scenario: A grown list
- **WHEN** the script lists items 1–3 and the list's blocks show items 1–6, a call having loaded 4–6
- **THEN** the listing has six rows; a call of items shown in another block group adds none
