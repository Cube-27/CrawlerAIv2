# Schemas Specification

## Purpose

A schema is a row in the database that names the fields to extract, each with a field type; code knows field
types, never page-specific fields. This capability covers the field type registry, the schema document rules, the
four presets, custom schemas, prompt and field-name drafts as stored schemas, page kind, in-place edits and the
preset sync command. How each type's values are read is [normalization](../normalization/spec.md); role S itself is
[llm](../llm/spec.md); the HTTP shape of `/v1/schemas` is [rest-api](../rest-api/spec.md).
Design rationale: [ARCHITECTURE §5](../../design/schemas.md). History: [SPEC-04](../../changes/archive/2026-10-16-spec-04-schemas-and-normalization/SPEC-04-schemas-and-normalization.md) and its [decisions](../../changes/archive/2026-10-16-spec-04-schemas-and-normalization/decisions.md).

## Requirements

### Requirement: Field types
The system SHALL support exactly these field types: `text`, `long_text`, `money` ({amount, ISO 4217 currency},
atomic), `enum` (a code from a referenced vocabulary), `url`, `image_url`, `identifier` ({scheme, value}), `date`,
`datetime`, `location` ({text, locality, region, country, remote_flag}), `range` ({min, max, currency or unit,
period}), `count` (non-negative integer), `number` (decimal as stated), `list<T>` and `object{…}`. A new type SHALL
be added only when a schema needs it, together with its one normalizer module (C8).
Refs: §5.1, SPEC-04 §2, Appendix A #39, #42, D-0921, D-0960.

#### Scenario: Unknown type in a document
- **WHEN** a schema document declares a field of a type not in the list
- **THEN** the document is refused as invalid

#### Scenario: Frontend type lists follow the generated type
- **WHEN** a type is added to `FieldType`
- **THEN** the regenerated client type adds it to the frontend schema editor label and scalar lists (D-0924, D-0962)

### Requirement: Schema document shape
A schema document SHALL have a `name`, a `page_kind`, at least one field in `fields`, and optional
`required_groups`. Schema and field names SHALL match `^[a-z][a-z0-9_]{0,63}$`. Nesting through `list.item` and
`object.fields` SHALL be at most 3 levels, a top-level field being level 1. Type parameters SHALL match the type:
`vocab` only and always for `enum`, `scheme` (`gtin`, `isbn`, `mpn`, `sku`, `custom`) for `identifier`, `item` for
`list`, at least one sub-field for `object`.
Refs: §5.2, SPEC-04 §4.2, D-0241.

#### Scenario: Too deep
- **WHEN** a document nests a field four levels deep
- **THEN** it is refused with the field path and "nested deeper than 3 levels"

#### Scenario: Bad name
- **WHEN** a field is named `Price-EUR`
- **THEN** the document is refused

### Requirement: Descriptions on every field
Every top-level field and every object sub-field SHALL carry a non-empty `description` (at most 2000 characters),
since LLM roles read it; a list's `item` is described by its list field. Preset fields SHALL carry descriptions.
Refs: §5.2, SPEC-04 §4.2, D-0241.

#### Scenario: Missing description
- **WHEN** a field has no `description`
- **THEN** the document is refused with "every field needs a description"

### Requirement: Required fields and required groups
`required` SHALL default to false. "Core fields" SHALL mean the fields with `required: true` plus the
`required_groups`, where at least one field of each group must publish. Each group SHALL name at least one field and
only top-level fields of the document.
Refs: §5.2, SPEC-04 §4.2, §9.

#### Scenario: Group naming an unknown field
- **WHEN** `required_groups` is `[["sku", "ean"]]` and the document has no `ean` field
- **THEN** the document is refused naming the unknown field

#### Scenario: Either member satisfies the group
- **WHEN** a `commerce_detail` page publishes `gtin` but no `sku`
- **THEN** the `[["sku", "gtin"]]` group is satisfied

### Requirement: Field scope
`scope` SHALL be `row` or `page`, default `row`. On a `detail` document every field SHALL be `row`; on a `listing`
document `page` fields (such as `next_page_url`) belong to the page, not to a row.
Refs: §5.2, SPEC-04 §4.2.

#### Scenario: Page scope on a detail schema
- **WHEN** a `detail` document has a field with `scope: "page"`
- **THEN** it is refused: a detail page has one entity

### Requirement: schema.org paths
A field's `schema_org` SHALL be a dotted path that starts at a schema.org type (UpperCamelCase) and follows
properties (lowerCamelCase). `+` SHALL join a second property into one atomic value (`Offer.price+priceCurrency`).
`|` SHALL separate up to four alternatives, whose candidates are pooled with none outranking another. Paths and
`vocab` references (`schema:<Enumeration>` or `type:<name>`) SHALL be checked for syntax only; they are not checked
against the pinned schema.org file.
Refs: §5.2, Appendix A #37, SPEC-04 §4.2, SPEC-13 §4.1, D-0240.

#### Scenario: Five alternatives
- **WHEN** a path has five `|`-separated alternatives
- **THEN** the document is refused

#### Scenario: Alternatives pool
- **WHEN** a field maps `Product.sku|Offer.sku`
- **THEN** candidates from both paths are pooled and resolved as usual

### Requirement: Row-mapped lists and key
A `list` whose `item` is an `object` and which has a `schema_org` path SHALL be row-mapped: the path names the row
entities and has no `+`, the item has no `schema_org` of its own, its sub-fields are leaf types with their own
paths (or none), and `key` names 1–3 distinct `identifier` or `url` sub-fields that match one row across sources.
`key` SHALL be required on a row-mapped list and refused anywhere else. A list of objects without `schema_org` keeps
literal keys. How rows resolve is [variants](../variants/spec.md).
Refs: §5.2, SPEC-04 §4.2, SPEC-13 §4.2.

#### Scenario: key outside a row-mapped list
- **WHEN** a plain `text` field declares `key`
- **THEN** the document is refused

#### Scenario: Nested sub-field in a row
- **WHEN** a row-mapped list's item has a `list` sub-field
- **THEN** the document is refused: row sub-fields are leaf values

### Requirement: Page kind
Every schema SHALL have a `page_kind`: `detail` (one primary entity, possibly with nested lists) or `listing`
(rows plus page-level fields). The caller SHALL choose the page kind per request, or per URL pattern in crawls.
Refs: §5.5, §13.2.

#### Scenario: Listing schema
- **WHEN** a `listing` schema is used on a listing page
- **THEN** row fields publish per row and `page` fields once for the page

### Requirement: Presets
The system SHALL ship four presets as JSON files, each field mapped to its schema.org path:
- `commerce_detail`: required `title`, `price`, `availability` (`schema:ItemAvailability`), `url`, `image_url`;
  `required_groups: [["sku", "gtin"]]`; optional `brand` (`Product.brand.name`), `stock_quantity` (count,
  `Offer.inventoryLevel`), `description`, `additional_images`, `color`, `material`, `gender`, `condition`
  (`schema:OfferItemCondition`), `rating` (number, `aggregateRating.ratingValue`), `review_count`, `mpn`,
  `product_id` (`productID`), and row-mapped `variants` keyed by `gtin`, `sku`, `url`, each row with `variant_id`,
  `sku`, `gtin`, `price`, `availability`, `stock_quantity`, `url`, `name`, `size`, `color`, `material`, `pattern`.
- `commerce_listing`: row `title`, `url` required, `price` optional; page `next_page_url`.
- `job_detail`: required `title`, `company`, `locations` (list of location), `description` (long_text),
  `apply_url` (`JobPosting.url`), `date_posted` (date).
- `job_listing`: row `title`, `url` required, `location` optional; page `next_page_url`.
"When shown" fields SHALL be optional. A preset SHALL hold no derived field (no counts of variants or images).
Refs: §5.3, Appendix A #35, #37, #39, #42, SPEC-04 §4.2, D-0015, D-0245, D-0781, D-0923, D-0961, D-0967.

#### Scenario: Page without a brand
- **WHEN** a product page states no brand
- **THEN** the `commerce_detail` record can still be complete

#### Scenario: Stated optional fields only
- **WHEN** a page states rating and condition but no review count
- **THEN** `rating` and `condition` publish and `review_count` does not

### Requirement: Preset sync
`crawlerai schemas sync` (run by `make migrate`) SHALL insert a missing preset and update a changed one in place as
an edit, sending that preset's sites back to learning. A preset name held by a non-preset schema SHALL be refused
(`PresetConflict`) with nothing written. A preset file SHALL be named after its schema and carry no version.
Refs: §5.3, SPEC-04 §4.2, D-0242, D-0950.

#### Scenario: Changed preset file
- **WHEN** a preset file gains an optional field and sync runs
- **THEN** the stored preset is rewritten in place and its active configs are suspended for relearning

#### Scenario: Name taken
- **WHEN** a user schema is named `job_detail` and sync runs
- **THEN** sync fails and writes nothing

### Requirement: Custom schemas
Callers SHALL create `user` schemas through the API or UI. A preset name, a taken name, or an edit or retirement of
a preset SHALL be refused as a conflict (409); an invalid document is refused with (path, reason) errors. Retiring
SHALL set `status` to `retired` and keep the row, since records and configs reference it. `origin` is one of
`preset`, `user`, `prompt_draft`; `status` is `active` or `retired`.
Refs: §5.4, SPEC-04 §4.2, SPEC-07 §4.6.

#### Scenario: Retire a preset
- **WHEN** a caller deletes a preset
- **THEN** the request is refused with 409

#### Scenario: Inline schema
- **WHEN** a request carries an inline schema whose name is stored with a different document, or is retired
- **THEN** it is refused as a conflict; an inline schema never edits a stored one

### Requirement: Edit in place, no versions
There SHALL be one schema per name, edited in place, with no schema versions. An edit that changes the document
SHALL suspend the schema's `active` site configs (drafts stay) and set its progressive states to `cold` with no run
in flight; an unchanged document SHALL change nothing. Records and configs reference `schema_id`, and a record
counts for the current document only when its `schema_digest` (sha256 of the canonical document) equals the
current one. A job runs with the document it pinned at submit (INV-28); a learning run overtaken by an edit ends
`failed` with `schema_edited`.
Refs: §5.2, Appendix A #43, SPEC-04 §4.2, D-0950; superseded: D-0243.

#### Scenario: Edit triggers relearning
- **WHEN** a user schema with an active config gains a field
- **THEN** the config becomes `suspended` and the site's progressive state becomes `cold`

#### Scenario: No-op edit
- **WHEN** an edit sends the stored document unchanged
- **THEN** no config or state changes

### Requirement: Prompt drafts
A prompt without a schema SHALL be drafted by role S into a schema (from the prompt and 1–3 sample pages), stored
with `origin='prompt_draft'` under `draft_` + the first 12 hex digits of sha256 of the whitespace-normalized
prompt, returned with the results for editing, and reused for the same prompt without a new call. Adopting a draft
SHALL create a `user` schema under a new name. Prompts are accepted on scrape and extract only.
Refs: §5.4, SPEC-06 §4.5, D-0771, D-0810.

#### Scenario: Same prompt twice
- **WHEN** two requests send the same prompt text
- **THEN** both use one stored draft and the second makes no role S call

### Requirement: Field-name drafts
A request's `schema.fields` (1–50 distinct field names, on scrape, batch, crawl and extract) SHALL be drafted by
role S, before any job is stored, into a schema whose top-level fields are exactly those names, for the request's
page kind (a crawl uses its rules' one page kind). The draft is named `draft_` + sha256("fields\n" + page_kind +
"\n" + sorted names joined by "\n")[:12], so the same names in any order give one stored draft. `POST
/v1/schemas/draft` SHALL return that draft for editing; an edited draft runs inline under its own name.
Refs: §5.4, Appendix A #41, D-0925, D-0926, D-0927, D-0928, D-0929.

#### Scenario: Names in another order
- **WHEN** one request sends `fields: ["b", "a"]` and another `["a", "b"]` for the same page kind
- **THEN** both resolve to the same stored draft

#### Scenario: Too many names
- **WHEN** a request sends 51 field names
- **THEN** it is refused with 422
