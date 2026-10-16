# Delta: variants

## MODIFIED Requirements

### Requirement: Key-matched clusters (INV-33)
Rows SHALL be matched by key, never by position: rows sharing a value of a key sub-field form a cluster unless they
state different values of a key sub-field listed before it (the preset's `key` runs most to least specific); page and
target URLs are not key values; a cluster with two values of one key sub-field is dropped `row_key_conflict`, a keyless
row `no_row_key`. (Previously: any shared key value joined rows.) Refs: §10, D-0802, D-0963, D-1181.
Enforced by: property tests (order does not change clusters; different keys never merge; linking equals the pairwise
rule); active.
#### Scenario: Joined variants
- **WHEN** two rows share a gtin but state different skus
- **THEN** their cluster is dropped with reason `row_key_conflict`
#### Scenario: Sizes of one sku
- **WHEN** two rows share a sku but state different gtins
- **THEN** they are two rows

### Requirement: Row-mapped field outcome (INV-34)
A row-mapped field SHALL publish when two or more rows publish, with `items` (a `FieldOutcome` per sub-field of each
published row, published ones with full provenance) and `dropped` rows with reasons; one published row leaves it
`missing` (`single_row`): a product without variants has no variant list (owner, 2026-10-16, Appendix A #48);
else it is `missing` with the furthest row reason or `abstained`. (Previously: one row published the field.)
Refs: §13.1, D-0798, D-0799, D-1185. Enforced by: Pydantic models (`FieldOutcome`) and tests; active.
#### Scenario: Unpublished colour
- **WHEN** a published row of two has no `color` candidate
- **THEN** its `items` entry holds `color` with status `missing` and reason `no_candidates`
#### Scenario: One plain Offer
- **WHEN** the target has one Offer with a sku and no variants
- **THEN** `variants` is `missing` with reason `single_row`, and the Offer's price publishes at top level
