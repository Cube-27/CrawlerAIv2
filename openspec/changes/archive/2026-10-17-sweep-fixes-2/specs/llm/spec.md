## MODIFIED Requirements

### Requirement: Role C input, claims and candidates
Role C SHALL read flat cleaned text, never raw HTML, cut at 40,000 (detail) or 80,000 (listing) characters, and reply
one `{shown, value, start, end}` claim per asked field; a value under `shown: false` is not taken (C7). On a listing
whose repeated item blocks (`acquire.items.item_blocks`) cover `MIN_ITEMS` or more items in the cleaned text, it reads
those items' spans of the cleaned text only (`content/item_text.py`), and each grounded span is mapped back to its
cleaned-text offsets. Grounded values are normalized into `Candidate(source_kind='llm', independent=True)`.
(Previously: a listing's whole cleaned text.) Refs: §8.4, D-0025, D-0521, D-1097, D-1478.
#### Scenario: Field not shown
- **WHEN** a claim is `{shown: false, value: "x"}`
- **THEN** no candidate is made and the field stays `missing`
#### Scenario: Listing items behind a long menu
- **WHEN** a listing's cleaned text holds 60,000 characters of menu before four item blocks
- **THEN** role C reads the four items' text, and a grounded title's locator is its offset in the cleaned text
