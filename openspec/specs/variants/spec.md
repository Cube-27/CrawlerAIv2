# Variants Specification

## Purpose

Variants covers products with several variants: row-mapped `list<object>` fields, row discovery and key matching,
per-row resolution, and the common-value rule for top-level offer fields (`resolve/rows.py`).
Rationale: ARCHITECTURE §10 ([archived](../../changes/archive/2026-10-16-architecture-rev26/ARCHITECTURE.md)); history: SPEC-13.

## Requirements

### Requirement: Path alternatives and row-mapped fields
A `schema_org` path MAY hold up to 4 `|` alternatives, whose candidates the system SHALL union with no ranking. A
`list<object>` field with a row path and a `key` is row-mapped: each sub-field yields candidates as `<field>.<sub>`,
and rows are found in resolution. Refs: §5.2, Appendix A #37, D-0787, D-0790; grammar in [schemas](../schemas/spec.md).
#### Scenario: Microdata parity
- **WHEN** the same variant set is rendered as JSON-LD and as microdata
- **THEN** the published `variants` values are equal as multisets

### Requirement: Row discovery
The system SHALL reach rows only along alternatives rooted at the target; an `AggregateOffer` is never a row, and a
sub-field candidate in no row's scope is rejected `not_in_row`. Refs: SPEC-13 §4.3, D-0793, D-0808.
#### Scenario: AggregateOffer alone
- **WHEN** a Product's only offer is an `AggregateOffer` with `lowPrice` and `highPrice`
- **THEN** no row is found

### Requirement: Key-matched clusters (INV-33)
Rows SHALL be matched by key, never by position: rows sharing a value of a key sub-field form a cluster unless they
state different values of a key sub-field listed before it (the preset's `key` runs most to least specific); page and
target URLs are not key values; a cluster with two values of one key sub-field is dropped `row_key_conflict`, a keyless
row `no_row_key`. Refs: §10, D-0802, D-0963, D-1181.
Enforced by: property tests (order does not change clusters; different keys never merge; linking equals the pairwise
rule); active.
#### Scenario: Joined variants
- **WHEN** two rows share a gtin but state different skus
- **THEN** their cluster is dropped with reason `row_key_conflict`
#### Scenario: Sizes of one sku
- **WHEN** two rows share a sku but state different gtins
- **THEN** they are two rows

### Requirement: Per-row resolution
Each cluster SHALL resolve like an entity: agreement, precedence, evidence and τ per sub-field in `list.<type>`
buckets; a row publishes when a key sub-field publishes, else it is dropped `key_unpublished`. Refs: §10, D-0800, D-0805.

### Requirement: Atomic offers per row (INV-35)
A row's price, currency, availability and stock quantity SHALL come from one Offer in that row (INV-15 per row).
Refs: §10, Appendix A #37, #39. Enforced by: resolver test; active.
#### Scenario: Two sellers in one row
- **WHEN** one row's scope holds two Offers with different prices
- **THEN** that row's `price` is `conflict` with reason `offers_disagree`

### Requirement: Row-mapped field outcome (INV-34)
A row-mapped field SHALL publish when two or more rows publish, with `items` (a `FieldOutcome` per sub-field of each
published row, published ones with full provenance) and `dropped` rows with reasons; one published row leaves it
`missing` (`single_row`): a product without variants has no variant list (owner, 2026-10-16, Appendix A #48);
else it is `missing` with the furthest row reason or `abstained`.
Refs: §13.1, D-0798, D-0799, D-1185. Enforced by: Pydantic models (`FieldOutcome`) and tests; active.
#### Scenario: Unpublished colour
- **WHEN** a published row of two has no `color` candidate
- **THEN** its `items` entry holds `color` with status `missing` and reason `no_candidates`
#### Scenario: One plain Offer
- **WHEN** the target has one Offer with a sku and no variants
- **THEN** `variants` is `missing` with reason `single_row`, and the Offer's price publishes at top level

### Requirement: No default variant; common values only (INV-38)
A detail page's top-level price, currency, availability and stock quantity SHALL publish only a value every Offer of the
target and its variants states alike, else `conflict`/`offers_disagree`, whatever variant a URL names; varying values
publish only in the row-mapped field. Refs: Appendix A #37, #44, D-1057, D-1059.
Enforced by: `tests/unit/test_common_variant_fields.py` and `tests/property/test_common_variant_fields.py`; active.
#### Scenario: URL names one variant
- **WHEN** the request URL is a variant's own URL and the variants' prices differ
- **THEN** top-level `price` is `conflict` (`offers_disagree`) and each price is in its `variants` row

### Requirement: Selected variant by URL (INV-36, superseded)
INV-36 SHALL NOT apply: superseded by INV-38 (owner, 2026-10-16, Appendix A #44). Enforced by: nothing; superseded.

### Requirement: Variant fill for sku and gtin
A top-level `sku` or `gtin` field with no candidate owned by the target SHALL take its variants' value only when every
variant has one and all agree; no other field is filled. Refs: §10, D-0794, D-0795.

### Requirement: Scope and sources of rows
Variant rules SHALL apply to a detail page's target only. Rows come only from JSON-LD, microdata/RDFa Lite and adapters'
schema.org shapes; learning, drift and role C skip row-mapped fields. Refs: SPEC-13 §4.9, D-0791, D-0796, D-0801.

### Requirement: Preset field, storage and scoring
`commerce_detail` SHALL carry one optional `variants` field (see the preset file); rows are stored in `record.data` with
`items`/`dropped` in `field_meta`, and are scored by key per [evaluation](../evaluation/spec.md). Refs: §5.3, D-0803, D-0963.

### Requirement: Standalone variants
A root Product whose `inProductGroupWithID` is the `productGroupID` of exactly one standalone ProductGroup, or whose
`isVariantOf` holds a ProductGroup or names one by its IRI, SHALL be that group's `hasVariant` member; a standalone
Product sharing an identifier or item URL with a group's member is that member (`resolve/identity.py`). Neither
`variesBy` nor identifier prefixes relate them. (Previously: `isVariantOf` left the group the Product's child.)
Refs: SPEC-13 §9, D-0966, D-1293, D-1344.
#### Scenario: Variants naming their group
- **WHEN** a ProductGroup with `productGroupID` G-1 and `color` Blue sits beside two Products stating
  `inProductGroupWithID` G-1
- **THEN** the group is the target, `color` publishes Blue, and `variants` holds both Products' rows
#### Scenario: Group held by isVariantOf
- **WHEN** the page's Product holds its ProductGroup in `isVariantOf`, and the group lists two variants
- **THEN** the group is the target and `variants` holds the two variants' rows, the Product joining the one it states
