## MODIFIED Requirements

### Requirement: Cold listing rows and pagination
On a listing the system SHALL take rows from `ItemList`/`ListItem` entities, else from 3 or more top-level primary
entities, else from role C; a role C row whose grounded text lies in exactly one repeated item block, linking to one
document only, takes that block's link as a `dom` item-URL candidate (`collect/item_links.py`, Appendix A #47,
D-1122); next pages come from `rel=next`, then the current+1
integer link, then a config's `listing.next` (`resolve/listing.py`, `resolve/pagination.py`), and the first of the
first two is a page-level `dom` candidate of the schema's `next_page_url` field. Refs: §8.6, D-0509, D-0514, D-1226.
(Previously: the next pages were found but filled no field.)
#### Scenario: Next page of a listing preset
- **WHEN** a listing page with the `commerce_listing` schema has `<link rel="next" href="?page=2">`
- **THEN** `next_page_url` publishes the absolute `?page=2` URL with source kind `dom`
