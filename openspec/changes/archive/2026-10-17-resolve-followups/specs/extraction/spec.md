## MODIFIED Requirements

### Requirement: Cold listing rows and pagination
On a listing the system SHALL take rows from `ItemList`/`ListItem` entities, else from 3 or more top-level primary
entities, else from the `ListItem` entries outside a `BreadcrumbList` that state no `item` (their own properties read
as the row's on the schema's row fields), else from role C; a role C row whose grounded values lie in exactly one
block of the repeated item group holding most rows (block text as the cleaned text shows it; a value that is an
element's whole text picks its block), a block no other row has, takes as a `dom` item-URL candidate the one document
the block's hyperlinks, else its hyperlinks labelled with a row value, lead to (`collect/item_links.py`, Appendix A
#47, D-1122, D-1241–D-1244); next pages come from `rel=next`, then the current+1 integer link, then a config's
`listing.next` (`resolve/listing.py`, `resolve/pagination.py`); the first `rel=next` link is a page-level `dom`
candidate of the schema's `next_page_url`, and a numbered link fills no field (C7).
Refs: §8.6, D-0509, D-0514, D-1226, D-1294.
(Previously: no rows from `ListItem` entries without `item`.)
#### Scenario: Title cut short
- **WHEN** a card shows `Widget with a lo…` with `title="Widget with a long name"` and role C grounds the full title
- **THEN** the row takes that card's link
#### Scenario: Next page of a listing preset
- **WHEN** a listing page with the `commerce_listing` schema has `<link rel="next" href="?page=2">`
- **THEN** `next_page_url` publishes the absolute `?page=2` URL with source kind `dom`
#### Scenario: Entries without items
- **WHEN** an `ItemList` holds `ListItem`s with only `name` and `url`, beside a `BreadcrumbList`
- **THEN** each `ItemList` entry is a row with that title and url, and no breadcrumb is
