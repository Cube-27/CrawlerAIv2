## MODIFIED Requirements

### Requirement: Cold listing rows and pagination
On a listing the system SHALL take rows from `ItemList`/`ListItem` entities, with the top-level primary entities no
list holds beside them when the page singles none out (a grown list's later items stated as microdata), else from 3 or
more top-level primary entities, else from the `ListItem` entries outside a `BreadcrumbList` that state no `item` (their
own properties read as the row's on the schema's row fields), else from role C; a role C row whose grounded values lie,
at their cleaned-text offsets, in one block of the repeated item group placing most rows, a block no other row has,
takes as a `dom` item-URL candidate the one document the block's hyperlinks lead to (links that only add a query to
one link refine it), else the one its hyperlinks holding a grounded value or whose text is a row value lead to
(`collect/item_links.py`, Appendix A #47, D-1122, D-1241–D-1244, D-1490), and a role C row without the item URL its
schema requires is left out (D-1491); a row's structured URL that is an item block's link but for a trailing slash or
an added query takes that link as a `dom` candidate (D-1495); next pages come from `rel=next`, then the link differing
from the page URL in one path segment or query value by one integer one higher (standing alone or inside the segment,
`page-2.html`), then a config's `listing.next` (`resolve/listing.py`, `resolve/pagination.py`); the first `rel=next`
link is a page-level `dom` candidate of the schema's `next_page_url`, and a numbered link fills no field (C7).
(Previously: a role C row was placed by its values' text, kept without its URL, and structured URLs were kept as
stated.) Refs: §8.6, D-0509, D-0514, D-1226, D-1294, D-1400, D-1403.
#### Scenario: Title cut short
- **WHEN** a card shows `Widget with a lo…` with `title="Widget with a long name"` and role C grounds the full title
- **THEN** the row takes that card's link
#### Scenario: Colour variants
- **WHEN** three cards show one title and price and each row's values are grounded in its own card
- **THEN** each row takes its own card's link
#### Scenario: Next page of a listing preset
- **WHEN** a listing page with the `commerce_listing` schema has `<link rel="next" href="?page=2">`
- **THEN** `next_page_url` publishes the absolute `?page=2` URL with source kind `dom`
#### Scenario: Entries without items
- **WHEN** an `ItemList` holds `ListItem`s with only `name` and `url`, beside a `BreadcrumbList`
- **THEN** each `ItemList` entry is a row with that title and url, and no breadcrumb is
#### Scenario: Integer inside a segment
- **WHEN** a listing at `/list/page-2.html` links to `page-3.html` and `sheet-3.html`
- **THEN** `/list/page-3.html` is its next page and `sheet-3.html` is not
