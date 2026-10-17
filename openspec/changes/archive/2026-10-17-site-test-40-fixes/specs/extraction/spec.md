# Delta: extraction

## MODIFIED Requirements

### Requirement: Cold listing rows and pagination
On a listing the system SHALL take rows from `ItemList`/`ListItem` entities, else from 3 or more top-level primary
entities, else from role C; a role C row whose grounded values lie in exactly one block of the repeated item group
holding most rows (block text as the cleaned text shows it; a value that is an element's whole text picks its block),
a block no other row has, takes as a `dom` item-URL candidate the one document the block's hyperlinks, else its
hyperlinks labelled with a row value, lead to (`collect/item_links.py`, Appendix A #47, D-1122, D-1241–D-1244); next
pages come from `rel=next`, then the current+1 integer link, then a config's `listing.next` (`resolve/listing.py`,
`resolve/pagination.py`). (Previously: the largest group only, text values only, the block's text content, and one
document per block.) Refs: §8.6, D-0509, D-0514.
#### Scenario: Title cut short
- **WHEN** a card shows `Widget with a lo…` with `title="Widget with a long name"` and role C grounds the full title
- **THEN** the row takes that card's link
