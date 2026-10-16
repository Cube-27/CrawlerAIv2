# Variants Specification

## Purpose

Variants covers products that offer several variants (sizes, colours) each with its own identifiers, price and
availability: row-mapped `list<object>` fields whose rows are structured-data nodes, row discovery and key matching,
per-row resolution with provenance per sub-field, and the common-value rule for the single top-level offer and
identifier fields. The schema grammar is [schemas](../schemas/spec.md); single-value resolution is
[resolution](../resolution/spec.md); row labels and scoring are [evaluation](../evaluation/spec.md).
Design rationale: [ARCHITECTURE §10](../../design/resolution.md) (variant matrix). History: [SPEC-13](../../changes/archive/2026-10-15-spec-13-variant-matrix/SPEC-13-variant-matrix.md) and its [decisions](../../changes/archive/2026-10-15-spec-13-variant-matrix/decisions.md).

## Requirements

### Requirement: Path alternatives
A `schema_org` path MAY hold up to 4 alternatives separated by `|`; the system SHALL take the union of every
alternative's candidates, dropping a selection only when an earlier alternative already reached the same (entity,
locator). No alternative outranks another: agreement or precedence decides as for a single path.
Refs: SPEC-13 §4.1, D-0787, D-0789.

#### Scenario: sku on Product or Offer
- **WHEN** a field maps `Product.sku|Offer.sku` and the target's Product and its Offer both state `A-1`
- **THEN** both are candidates and the field publishes `A-1` on agreement

### Requirement: Row-mapped fields and sub-field candidates
A `list` field whose `item` is an `object` and which has a `schema_org` row path and a `key` (one to three
`identifier` or `url` sub-fields) SHALL be row-mapped. Its row path yields no candidates; each sub-field yields
candidates as a top-level field does, with `Candidate.field = "<field>.<sub-field>"`, entity the alternative's root
entity, and the value's own locator. Rows are found in resolution, not by collectors. JSON-LD and microdata give the
same sub-field candidates.
Refs: §5.2, §10, Appendix A #37, SPEC-13 §4.2, D-0788, D-0790; grammar rules in [schemas](../schemas/spec.md).

#### Scenario: Microdata parity
- **WHEN** the same variant set is rendered as JSON-LD and as microdata
- **THEN** the published `variants` values are equal as multisets

### Requirement: Row discovery
Given the target and a row-mapped field, the system SHALL reach rows by following each alternative whose root the
target is an instance of, step by step through `parent`/`via`; only paths starting at the target count. An
`AggregateOffer` is never a row, and a reached entity with another reached entity of the same field below it is not
a row. A row's scope is the row entity and the entities below it, stopping at another row and at entities under
`isRelatedTo`, `isSimilarTo` or an `ItemList`. A sub-field candidate in no row's scope is rejected `not_in_row`.
Refs: SPEC-13 §4.3, D-0793, D-0808.

#### Scenario: One Offer per variant
- **WHEN** a Product's `offers` holds three Offers with distinct skus and no `hasVariant`
- **THEN** each Offer is one row

#### Scenario: AggregateOffer alone
- **WHEN** a Product's only offer is an `AggregateOffer` with `lowPrice` and `highPrice`
- **THEN** no row is found

### Requirement: Key-matched clusters (INV-33)
Rows SHALL be matched by key, never by position: rows that share a value of some key sub-field link, and linked rows
form a cluster (connected components, independent of comparison order). Key values are a row's `Ok`, INV-13-screened
key candidates; a url equal to the request, final or canonical URL or to the target's own `url`, IRI or
`mainEntityOfPage` is not a key value, and a url the target and an Offer both carry is a key only when exactly one row
carries it. A cluster with two different values of one key sub-field is dropped `row_key_conflict`; a row with no key
value is dropped `no_row_key`. A published row holds only sub-field values owned by the entities of one cluster.
Clusters are ordered by their earliest row entity in collector order. `productID` and `variesBy` values are no keys.
Refs: §10, Appendix A #37, SPEC-13 §4.4, D-0802, D-0850, D-0963, D-0966.
Enforced by: property tests (row and source order do not change clusters; different keys never merge) and unit tests; status: SPEC-13 (tests: SPEC-13 PR 2).

#### Scenario: Variants repeating the group URL
- **WHEN** every variant's `url` is the page URL and each states a distinct sku
- **THEN** rows are matched by sku and the url is not a key value

#### Scenario: Joined variants
- **WHEN** two rows share a gtin but state different skus
- **THEN** their cluster is dropped with reason `row_key_conflict`

### Requirement: Per-row resolution
Each cluster SHALL resolve like an entity with its scope as owner: validity and URL-parameter screening unchanged;
exact-match sub-fields publish only when every kept candidate agrees, else `conflict`; text and url sub-fields use
`source_precedence.yaml`. Evidence and τ apply per sub-field in `list.<type>|<evidence>` calibration buckets, with τ
0.97 when the list field and the sub-field are both required, else 0.95. A row publishes when at least one key
sub-field publishes, else it is dropped `key_unpublished`; its other sub-fields publish or not one by one.
Refs: §10, SPEC-13 §4.5, D-0800, D-0805.

#### Scenario: Sub-field disagreement
- **WHEN** a cluster's JSON-LD and microdata rows state different prices
- **THEN** that row's `price` is `conflict` and the row still publishes if its key does

### Requirement: Atomic offers per row (INV-35)
A variant row's price, currency and availability SHALL come from one Offer in that row (INV-15 per row); with
several Offers in one row the `offers_disagree` / `offer_split` rule applies inside the row. A row's stock quantity
comes from the same Offer, and a variant whose Offer states none has none. Per-seller rows are not modelled.
Refs: §10 atomic offers, Appendix A #37, #39, SPEC-13 §4.5, §4.7.
Enforced by: resolver test; status: SPEC-13 (tests: SPEC-13 PR 2).

#### Scenario: Two sellers in one row
- **WHEN** one row's scope holds two Offers with different prices
- **THEN** that row's `price` is `conflict` with reason `offers_disagree`

### Requirement: Row-mapped field outcome (INV-34)
A row-mapped field SHALL be `published` when at least one row publishes, its `value` the list of row objects holding
only published sub-fields. Its `evidence` is `agreed` when every published sub-field of every row is `agreed`, else
`structured`; `confidence` is the minimum over published sub-fields and `calibrated` true only when all are;
`locator` is the first published row's entity id and `source_kind` its first published sub-field's. `items` holds one
entry per published row (aligned with `value`) with a `FieldOutcome` per sub-field, and `dropped` the unpublished
rows with their locators and reason. With no row published, the field is `abstained`/`below_tau` only when every
variant was dropped `key_unpublished` with an abstaining key sub-field, else `missing` with the furthest reason
(`no_rows` < `no_row_key` < `row_key_conflict` < `key_unpublished`). Every sub-field outcome of a published row
carries a status and reason, and every published sub-field carries `evidence`, `confidence`, `calibrated`,
`source_kind` and `locator`.
Refs: §10, §13.1, Appendix A #37, SPEC-13 §4.5, §4.8, D-0798, D-0799.
Enforced by: Pydantic models (sub-fields use `FieldOutcome`) and tests; status: SPEC-13 (tests: SPEC-13 PR 2).

#### Scenario: Unpublished colour
- **WHEN** a published row has no `color` candidate
- **THEN** its `items` entry holds `color` with status `missing` and reason `no_candidates`

### Requirement: No default variant; common values only (INV-38)
A detail page's top-level price, currency, availability and stock quantity SHALL publish only a value every Offer of
the target and of its `hasVariant` members states alike; otherwise they stay `conflict` with reason
`offers_disagree`. No variant is a default, whatever variant a request, final or canonical URL names. Values that vary
publish only in the row-mapped `variants` field, whose rows keep their own values even where all agree. A
single-variant product publishes at the top level. The rule holds whether or not the schema has a `variants` field.
Refs: §10, Appendix A #37, #44, SPEC-13 §4.6, D-0945, D-1057, D-1059.
Enforced by: resolver tests (`tests/unit/test_common_variant_fields.py`) and a property test over generated URL sets (`tests/property/test_common_variant_fields.py`); status: active.

#### Scenario: URL names one variant
- **WHEN** the request URL is a variant's own URL and the variants' prices differ
- **THEN** top-level `price` is `conflict` (`offers_disagree`) and each price is in its `variants` row

#### Scenario: Shared price
- **WHEN** every variant's Offer states 19.90 EUR
- **THEN** top-level `price` publishes 19.90 EUR

### Requirement: Selected variant by URL (INV-36, superseded)
INV-36 (top-level offer fields from the single variant a page URL names) SHALL NOT apply; it is superseded by INV-38
(owner, 2026-10-16, Appendix A #44) and `select_variant` / `other_variant` are removed.
Refs: SPEC-13 §4.6, D-1057.
Enforced by: formerly a resolver test and a property test over generated URL sets; status: superseded by INV-38 (owner, 2026-10-16, Appendix A #44).

#### Scenario: Former rule
- **WHEN** a page URL names exactly one variant
- **THEN** that variant's Offer is not selected as the offer source

### Requirement: Variant fill for sku and gtin
A top-level `sku` or `gtin` identifier field for which no candidate (valid or not, page-level included) is owned by
the target SHALL take its variants' candidates only when every variant has one and all agree; otherwise it stays as
it was. A value the target states is never replaced, and no other top-level field (`name`, `brand`, `image_url`,
`url`, `color`) is filled.
Refs: §10, SPEC-13 §4.6, D-0785, D-0794, D-0795.

#### Scenario: Group states its own sku
- **WHEN** the ProductGroup states sku `G-1` and its variants state `A-1`, `A-2`
- **THEN** top-level `sku` is `G-1`

### Requirement: Detail targets only
The variant rules (rows, common values, variant fill) SHALL apply to a detail page's target only; listing rows and
the listing page resolve unchanged.
Refs: SPEC-13 §4.6, D-0796.

#### Scenario: Listing of products with variants
- **WHEN** a listing row is a ProductGroup with `hasVariant` members
- **THEN** no variant rule is applied to that row

### Requirement: Sources of rows
Rows SHALL come only from JSON-LD, microdata/RDFa Lite and adapters' schema.org shapes. `js_state`, `xhr`, Open
Graph, configs and role C MUST NOT give sub-field candidates. Learning gets the schema without row-mapped fields and
reports `not_learned: row_field`; drift does not track them. Role C is never asked for a row-mapped field or any
`object` or `list<object>` field, so a required row-mapped field no structured source fills leaves the page `partial`.
Refs: §10, SPEC-13 §4.9, SPEC-15 §4.4, D-0791, D-0797, D-0801; see [adapters](../adapters/spec.md).

#### Scenario: Config mode
- **WHEN** a site's config is active and its JSON-LD states variants
- **THEN** `variants` still publishes from JSON-LD

### Requirement: Preset `variants` field
Preset `commerce_detail` SHALL have one optional `variants` field with row path
`ProductGroup.hasVariant|Product.offers|Product.offers.offers`, `key: ["gtin", "sku", "url"]`, and sub-fields
`variant_id` (identifier, custom, `Product.productID`), `sku`, `gtin`, `price` (`Offer.price+priceCurrency`),
`availability` (`schema:ItemAvailability`), `stock_quantity` (count, `Offer.inventoryLevel`), `url`, `name`, `size`,
`color`, `material`, `pattern`. Required fields are unchanged, so completeness and `record_fingerprint` are unchanged.
Refs: §5.3, Appendix A #37, #39, #42, SPEC-13 §4.7, D-0963.

#### Scenario: Page with no variants
- **WHEN** a product page states no variants
- **THEN** `variants` is unpublished and the page can still be complete

### Requirement: Row shape in records
`record.data.<field>` SHALL be the list of row objects and `record.field_meta.<field>` the usual meta plus optional
`items` and `dropped` keys, absent for other fields. Sub-field candidates are stored with `field = "<field>.<sub>"`;
candidates of dropped rows take the row's reason. An exception in row resolution fails the page as `error`, and
nothing is partly published.
Refs: §13.1, SPEC-13 §4.8, §4.11, D-0800.

#### Scenario: Reordered variants
- **WHEN** a recurring crawl sees the same variants in a new order
- **THEN** `variants` is reported in `changed_fields`

### Requirement: Row labels and scoring
Row-mapped fields SHALL be labeled in `label_version` 2 and scored by matching engine rows to label rows by key, as
specified in [evaluation](../evaluation/spec.md); an engine row whose key is a `distractor_keys` value counts as wrong
product (not measured yet: variant labels on dev wait on milestone M).
Refs: SPEC-13 §4.10, D-0803, D-0804, D-0805, D-0905.

#### Scenario: Distractor key
- **WHEN** an engine row's sku equals a labeled distractor key
- **THEN** the eval counts one wrong-product value
