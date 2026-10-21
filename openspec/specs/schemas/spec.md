# Schemas Specification

## Purpose

A schema is a database row naming the fields to extract, each with a field type; code knows field types, never
page-specific fields. Values are read by [normalization](../normalization/spec.md); `/v1/schemas` is
[rest-api](../rest-api/spec.md).

## Requirements

### Requirement: Field types
The system SHALL support exactly the field types of `FieldType` in `backend/src/crawlerai/schemas/types.py`; a new
type SHALL be added only when a schema needs it, with its one normalizer module (C8). Refs: §5.1, D-0921, D-0960.
#### Scenario: Unknown type
- **WHEN** a schema document declares a field of a type not in `FieldType`
- **THEN** the document is refused as invalid

### Requirement: Schema document shape
A document SHALL have a `name`, a `page_kind` (`detail` or `listing`), at least one field and optional
`required_groups`; names match `^[a-z][a-z0-9_]{0,63}$`, nesting is at most 3 levels, type parameters match the
type, and every field and object sub-field carries a non-empty `description`. Validation: `schemas/types.py`. Refs: §5.2, D-0241.
#### Scenario: Invalid documents
- **WHEN** a document nests four levels deep, names a field `Price-EUR`, or omits a description
- **THEN** it is refused with the field path and reason

### Requirement: Required fields and required groups
Core fields SHALL be the `required: true` fields plus `required_groups` (at least one member of each group must
publish); a group names only top-level fields of the document. `required` defaults to false. Refs: §5.2, §9.
#### Scenario: Group naming an unknown field
- **WHEN** `required_groups` names a field the document lacks
- **THEN** the document is refused naming that field

### Requirement: Field scope and page kind
`scope` SHALL be `row` (default) or `page`; a `detail` document has only `row` fields, and on a `listing` document
`page` fields publish once per page. The caller chooses the page kind per request, or per URL pattern in crawls. Refs: §5.2, §5.5, §13.2.
#### Scenario: Page scope on a detail schema
- **WHEN** a `detail` document has a `scope: "page"` field
- **THEN** it is refused

### Requirement: schema.org paths
`schema_org` SHALL be a dotted path from a schema.org type through properties; each `+` joins another property of
the last node into one atomic value (`AggregateOffer.lowPrice+highPrice+priceCurrency`), `|` separates pooled
alternatives and `>` ranks them (those after it are read on an entity only where those before it reach no value), up
to four alternatives in all. A step MAY carry filter predicates that keep only the nodes they match:
`{name=Value}` a node whose `name` equals `Value` as an IRI or a term, `{name}` a node stating `name`, `{!name}` one
not stating it (`Offer.priceSpecification{priceType=StrikethroughPrice}.price`). A path's root SHALL be a type,
each step, predicate name and joined name a property of the pinned schema.org vocabulary, each predicate value one of
its enumeration members or types, and a `schema:` `vocab`
reference an enumeration of it; a schema a caller creates or edits that names others is refused with the error at the
field (a process without the vocabulary file checks syntax only). `job_detail.apply_url` is
`JobPosting.potentialAction.target`. Refs: §5.2, D-0240, D-1374, D-1493, D-1626, architecture-v3 d.1.
#### Scenario: Price roles from predicates
- **WHEN** an Offer states its price and a `priceSpecification` with `priceType` `StrikethroughPrice`, and a schema
  maps `list_price` to `Offer.priceSpecification{priceType=StrikethroughPrice}.price+priceCurrency`
- **THEN** `list_price` reads the struck price and the preset's `price` reads the Offer's own price
#### Scenario: Five alternatives
- **WHEN** a path has five `|`- or `>`-separated alternatives
- **THEN** the document is refused
#### Scenario: Unknown property
- **WHEN** a field's path is `Product.colour` and the vocabulary has no property `colour`
- **THEN** the schema is refused with an error at `fields.<name>.schema_org`
#### Scenario: Stated apply link
- **WHEN** a JobPosting states a `potentialAction` with a `target` and a `url`
- **THEN** `apply_url` publishes the target; without the action, its `url` is not taken

### Requirement: Row-mapped lists and key
A `list` of `object` with a `schema_org` path SHALL be row-mapped: leaf sub-fields only, a row path that neither
joins (`+`) nor ranks (`>`) its alternatives nor filters its steps (predicates), and a `key` of 1–3 `identifier` or `url` sub-fields; `key` is required
there and refused elsewhere. Row resolution is
[variants](../variants/spec.md). Refs: §5.2, SPEC-13 §4.2.
#### Scenario: Misplaced key or nested row field
- **WHEN** a `text` field declares `key`, or a row item has a `list` sub-field
- **THEN** the document is refused

### Requirement: Presets
The system SHALL ship the four presets under `backend/src/crawlerai/schemas/presets/`, every field mapped to a
schema.org path and described; "when shown" fields are optional and no preset holds a derived field (such as a
count of variants or images). A job's places are a list of locations (`locations`) in both job presets.
`commerce_detail.price`, `commerce_detail.variants.price` and `commerce_listing.price` are
`Offer.price{!priceType}{!validForMemberTier}+priceCurrency|Offer.priceSpecification{!priceType}{!validForMemberTier}{!referenceQuantity}{!priceComponentType}.price+priceCurrency|Offer.priceSpecification{priceType=SalePrice}{!validForMemberTier}{!referenceQuantity}{!priceComponentType}.price+priceCurrency`:
the active price (a sale price included), never a list, struck, member or unit price, nor a price component (a down
payment, an instalment). A path's predicates give a money field reaching schema.org `price` its price role:
`{referenceQuantity}` a unit price, `{priceType=StrikethroughPrice}` or `ListPrice` a list price,
`{validForMemberTier}` a member price, none required or only `{priceType=SalePrice}` the active price. The other price
roles are fields a user adds to the schema, not preset fields; their recommended paths are:

| Field | Type | `schema_org` |
|---|---|---|
| `list_price` | money | `Offer.priceSpecification{priceType=StrikethroughPrice}.price+priceCurrency\|Offer.priceSpecification{priceType=ListPrice}.price+priceCurrency` |
| `unit_price` | money | `Offer.priceSpecification{referenceQuantity}.price+priceCurrency` |
| `unit_price_reference` | text | `Offer.priceSpecification{referenceQuantity}.referenceQuantity` |
| `member_price` | money | `Offer.priceSpecification{validForMemberTier}.price+priceCurrency` |
| `price_range` | range | `AggregateOffer.lowPrice+highPrice+priceCurrency` |
| `seller` | text | `Offer.seller.name\|Offer.offeredBy.name` |

Refs: §5.3,
D-0015, D-0245, D-0961, D-0967, D-1477, owner decision #74.

### Requirement: Preset sync
`crawlerai schemas sync` (run by `make migrate`) SHALL insert a missing preset and edit a changed one in place,
sending its sites back to learning; a preset name held by a non-preset schema fails with `PresetConflict` and
writes nothing. Preset files are named after their schema and carry no version. Refs: §5.3, D-0242, D-0950.
#### Scenario: Name taken
- **WHEN** a user schema is named `job_detail` and sync runs
- **THEN** sync fails and writes nothing

### Requirement: Custom schemas
Callers SHALL create `user` schemas through the API or UI; a taken or preset name, or an edit or retirement of a
preset, is a 409 conflict. Retiring sets `status` to `retired` and keeps the row. An inline schema never edits a
stored one. Refs: §5.4, SPEC-07 §4.6.
#### Scenario: Retire a preset
- **WHEN** a caller deletes a preset
- **THEN** the request is refused with 409

### Requirement: Edit in place, no versions
There SHALL be one schema per name, edited in place. A changed document suspends the schema's active configs and
sets its progressive states to `cold`; an unchanged one changes nothing. A record counts for the current document
only when its `schema_digest` matches; a job runs with the document pinned at submit. Refs: §5.2, D-0950.
#### Scenario: Edit triggers relearning
- **WHEN** a user schema with an active config gains a field
- **THEN** the config becomes `suspended` and the site's progressive state `cold`

### Requirement: Label synonyms
A schema row SHALL carry `labels`, the label synonyms role S drafted for its labelled fields (every field but a list
or an object), by field ([llm](../llm/spec.md)): null until drafted, editable through
`PUT /v1/schemas/{id}/labels` (a preset's too; a retired schema is 409, an unknown or unlabelled field 422), and
cleared when the document changes. They are no part of the document: they change neither its digest nor its configs.
#### Scenario: Edit clears the synonyms
- **WHEN** a schema with drafted synonyms gains a required group
- **THEN** its `labels` are null and its next use drafts them again

### Requirement: Prompt and field-name drafts
A prompt (scrape, extract) or a list of 1–50 field names (scrape, batch, crawl, extract) SHALL be drafted by role S
([llm](../llm/spec.md)) into a stored `prompt_draft` schema named `draft_` + 12 hex digits of a digest of the
normalized input, reused without a new call; `POST /v1/schemas/draft` returns it for editing. Refs: §5.4, D-0771, D-0925–D-0929.
#### Scenario: Same input twice
- **WHEN** two requests send the same prompt, or the same field names in another order
- **THEN** both use one stored draft and the second makes no role S call
