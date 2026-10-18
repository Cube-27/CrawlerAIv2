## MODIFIED Requirements

### Requirement: Role C input, claims and candidates
Role C SHALL read flat cleaned text, never raw HTML, cut at 40,000 (detail) or 80,000 (listing) characters, and reply
one `{shown, value, start, end}` claim per asked field; a value under `shown: false` is not taken (C7). On a listing
whose first ranked item group (`ParsedPage.item_groups`, [listings](../listings/spec.md)) covers `MIN_ITEMS` or more
items in the cleaned text, it reads those items' spans of the cleaned text only (`content/item_text.py`), in calls of
as many items as their rows' claims fit the reply, up to 200 items, the page fields asked in the first call; each row's
values are grounded in one item (of those holding most of them, the first after the previous row's), a value found
only in another item is dropped, and each grounded span is mapped back to its cleaned-text offsets. Grounded values are
normalized into `Candidate(source_kind='llm', independent=True)`. (Previously: the items were `item_blocks`'.)
Refs: §8.4, D-0025, D-0521, D-1097, D-1478, D-1490, D-1496.
#### Scenario: Field not shown
- **WHEN** a claim is `{shown: false, value: "x"}`
- **THEN** no candidate is made and the field stays `missing`
#### Scenario: Listing items behind a long menu
- **WHEN** a listing's cleaned text holds 60,000 characters of menu before four item blocks
- **THEN** role C reads the four items' text, and a grounded title's locator is its offset in the cleaned text
#### Scenario: Items that repeat their values
- **WHEN** three items show the same title and price and every claim's offsets point at the first
- **THEN** the three rows are grounded in the three items, in page order
#### Scenario: Long listing
- **WHEN** a listing shows 100 items and one call's reply fits 42 rows
- **THEN** role C makes three calls, over items 1–42, 43–84 and 85–100, and records each call

### Requirement: When role C is asked
In cold mode role C SHALL be asked on a detail page only when a required field or group is `missing` (with every
missing optional field in the same call); in `active` mode only for fields the config neither runs nor lists as absent.
A listing calls it once, as [listings](../listings/spec.md) "Role C rows" states. Not in captures replay. The
`c_prefill` variant stores grounded `Ok` values only as a `draft` label, never ground truth
([evaluation](../evaluation/spec.md)). (Previously: a cold listing called it only when structured data gave no rows.)
Refs: §8.4, D-0520, D-1006, D-0538, D-1341, owner #67.
