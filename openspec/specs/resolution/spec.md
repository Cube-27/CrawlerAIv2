# Resolution Specification

## Purpose

Resolution decides, for every schema field of a page, what publishes and how much it is trusted: validity, intent,
ownership and a simple preference rule, then atomic offers, derived values, evidence buckets, dev-measured
confidence and the record with per-field metadata and the page outcome. It starts from the candidates
[extraction](../extraction/spec.md) produces; per-variant rows are [variants](../variants/spec.md); the fitting of
calibration and precedence on dev is [evaluation](../evaluation/spec.md).
Design rationale: [ARCHITECTURE §10](../../design/resolution.md). History: [SPEC-05](../../changes/archive/2026-10-16-spec-05-extraction-and-resolution/SPEC-05-extraction-and-resolution.md) and its [decisions](../../changes/archive/2026-10-16-spec-05-extraction-and-resolution/decisions.md).

## Requirements

### Requirement: One extraction path
The system SHALL resolve every page through one function, `extract_page`, used by the worker, `scrape` and the
replay harness alike. An exception in resolution SHALL yield outcome `error` (stored as `failed`) with no fields and
no record; nothing is partly published.
Refs: §8.1, SPEC-05 §4.1, §4.14, D-0483, D-0504, D-0506.

#### Scenario: Resolver bug
- **WHEN** resolution raises on a page
- **THEN** the outcome is `error` and no record is stored

### Requirement: Validity
The system SHALL pass every candidate through its type normalizer; an `Invalid` or `Ambiguous` candidate keeps its
reason (`invalid`, `ambiguous`) and MUST NOT publish.
Refs: §10, SPEC-05 §4.7; normalizers in [normalization](../normalization/spec.md).

#### Scenario: Ambiguous currency
- **WHEN** the only price candidate is `$10` and the page context does not settle the currency
- **THEN** the field does not publish and the candidate is rejected `ambiguous`

### Requirement: Intent selects one target or none
`select_target(request_url, final_url, canonical_url, entities)` SHALL consider the entities of the schema's primary
types (the required fields' path roots, without Offer unless it is the only root), excluding those with an
`ItemList`/`ListItem` ancestor, those under a primary entity's `isRelatedTo`/`isSimilarTo`, and `hasVariant`
members. One candidate is the target; otherwise the one whose `urls` contain a canonicalized request, final or
canonical URL; several or none is ambiguous, and every field is `conflict` (`intent_ambiguous`), never a guess. The
`page` entity is the target only when the page has no primary-type entity at all; URL tests are never applied to
variants.
Refs: §8.2 rule 3, §10, Appendix A #36, SPEC-05 §4.6, D-0413, D-0414, D-0415, D-0785.

#### Scenario: Recommendation list
- **WHEN** a page holds the main Product and 4 Products inside an `ItemList`
- **THEN** the main Product is the target

#### Scenario: Two unrelated products
- **WHEN** two top-level Products exist and neither's URLs match the page URLs
- **THEN** every field is `conflict` with reason `intent_ambiguous`

### Requirement: Ownership stage
The target SHALL own its own candidates, the page-level ones, and those of an Offer (or subtype) whose parent is the
target or one of its `hasVariant` members; a candidate owned otherwise is rejected `not_owned` and MUST NOT publish.
An Offer nested inside an AggregateOffer, and a variant's own sku, name, gtin or image, are not the target's.
Refs: §8.2 rule 3, §10, SPEC-05 §4.6, D-0416, D-0417, D-0785.

#### Scenario: Variant's own sku
- **WHEN** a ProductGroup target has `hasVariant` Products each stating a sku
- **THEN** those skus are not owned by the target (see variant fill in [variants](../variants/spec.md))

### Requirement: Exact-match agreement (INV-14)
For exact-match types (money, identifier, enum, date, datetime, range, location, count, number) the system SHALL
publish only when every valid, owned, kept candidate agrees after normalization; two that disagree produce
`conflict` and no value. The chosen candidate is the first kept one in collector order. A `list` field follows its
item type's rule; an `object` field publishes on agreement.
Refs: §10, SPEC-05 §4.7, D-0437.
Enforced by: property test; status: SPEC-05.

#### Scenario: Two prices disagree
- **WHEN** JSON-LD says 19.90 EUR and microdata says 21.00 EUR for the target
- **THEN** `price` is `conflict` and has no value

### Requirement: Source precedence for text, url and image
For `text`, `long_text`, `url` and `image_url` the system SHALL publish from the first source kind in that type's
order in `backend/data/source_precedence.yaml` (stamped `source_split: dev`) that has a valid owned candidate;
lower-ranked disagreeing candidates are rejected `precedence`. A kind absent from the order never wins (`unranked`);
with no precedence file every such field is `missing`/`unranked`. Two disagreeing candidates of the winning kind are
`conflict`/`disagree`, unless they are one entity's values and exactly one is equalled by an independent candidate
of another kind (or, for image_url, names the same file), which then publishes. The initial order, before any dev
fit, is `[adapter, api, jsonld, microdata, og, dom, config, llm]` for all four types.
Refs: §10, SPEC-05 §4.7, D-0439, D-0443, D-0486, D-0757, D-0944, D-0956.

#### Scenario: Gallery array
- **WHEN** JSON-LD `Product.image` lists three URLs and `og:image` equals the second
- **THEN** `image_url` publishes the second URL

### Requirement: Missing reasons name the furthest stage
An unpublished field SHALL state why: `missing` with the furthest screening stage a candidate reached (`invalid` <
`ambiguous` < `not_owned` < `url_param`) or `no_candidates`, `conflict` with `disagree`, `offers_disagree`,
`offer_split` or `intent_ambiguous`, `abstained` with `below_tau` or `no_bucket`. Every rejected candidate keeps its
own reason, and the outcome records the kept candidates.
Refs: SPEC-05 §4.2, D-0438, D-0533.

#### Scenario: Only an unowned value
- **WHEN** the only price candidate belongs to a related product
- **THEN** `price` is `missing` with reason `not_owned`

### Requirement: Atomic offers (INV-15)
Price, currency and availability of a published offer SHALL come from one source object: the anchor Offer is the one
holding kept candidates for the most Offer-rooted fields (first seen on a tie). Candidates from different Offers that
disagree make the field `conflict`/`offers_disagree`; an Offer field with no kept candidate from the anchor is
`offer_split`. With several Offers (the target's own and its variants'), a field publishes only when all agree. An
`AggregateOffer` `lowPrice`/`highPrice` MUST NOT publish as the current price.
Refs: §10, SPEC-05 §4.8, D-0440; per-row and common-value rules in [variants](../variants/spec.md).
Enforced by: resolver test; status: SPEC-05.

#### Scenario: Price and availability from two Offers
- **WHEN** Offer A states only price and Offer B states only availability
- **THEN** the field without a value from the anchor Offer is `conflict` with reason `offer_split`

### Requirement: Derived values (INV-07)
Derived values SHALL fill only `missing` fields (never `conflict`) and carry `derived_by`. The only derivations are,
in order: `absolutize` (a relative url/image_url candidate resolved against the base URL, keeping its source
candidate's kind, locator and bucket), then for a detail page's `T.url` field `canonical_link` (RFC 6596), then
`final_url`. A page-URL derivation publishes with source kind `derived`, locator `derived:<derived_by>` and the
`derived` evidence bucket. Each derivation is a named function with a standards justification.
Refs: §9, §10, Appendix A #40, SPEC-05 §4.8, D-0355, D-0442, D-0910, D-0911.
Enforced by: resolver tests; status: SPEC-05.

#### Scenario: No url candidate
- **WHEN** a detail page has no url candidate and `<link rel=canonical href="https://example.com/p/1">`
- **THEN** `url` publishes that URL with `derived_by=canonical_link`, source kind `derived`, evidence `derived`

### Requirement: Evidence buckets
Each published field SHALL carry one `evidence` value, by priority: `adapter` (adapter or api chosen); `agreed` (two
or more independent candidates of different source kinds among the chosen and agreeing ones; `independent=false`
js_state/xhr values never count); else the chosen kind's bucket: `structured` (jsonld, microdata, og), `dom`,
`config_corroborated` / `config_uncorroborated` (also for `operator` fields), `llm_grounded`, `derived`. A lone
js_state/xhr value fits no bucket and abstains `no_bucket`.
Refs: §10, SPEC-05 §4.9, D-0455, D-0956.

#### Scenario: Independent agreement
- **WHEN** JSON-LD and a visible checkable js_state value give the same price
- **THEN** `price` has evidence `agreed`

### Requirement: Confidence, calibration and τ
A field's `confidence` SHALL be the dev precision of its `(field type, evidence)` bucket in `calibration.json`;
`calibrated` is true when the bucket has n ≥ 30 and a precision. A calibrated bucket below τ (0.97 for required
fields and required-group members, 0.95 otherwise) abstains `below_tau`, keeping its evidence and confidence in
`field_meta`. Uncalibrated buckets publish with `calibrated=false` and `confidence` null. No `calibration.json`
exists until the first dev fit (milestone M), so every field is uncalibrated today. Calibration and precedence
inputs are dev-only (INV-02, see [evaluation](../evaluation/spec.md)).
Refs: §10, §16.3, SPEC-05 §4.9, §4.11, D-0454, D-0456, D-0458, D-0758.

#### Scenario: Calibrated bucket below τ
- **WHEN** a required money field's bucket has n=40 and precision 0.969
- **THEN** the field is `abstained` with reason `below_tau`

### Requirement: Record confidence
Record confidence SHALL be the minimum confidence over the published required fields and required-group members,
and null when any of them is uncalibrated. A listing page's record confidence is its least confident row's, and each
listing record carries it.
Refs: §10, SPEC-05 §4.9, D-0456, D-0511, D-0931.

#### Scenario: One uncalibrated required field
- **WHEN** one required field publishes with `calibrated=false`
- **THEN** the record confidence is null

### Requirement: Provenance on every field (INV-22)
Every candidate SHALL carry a locator, and `field_meta` SHALL hold `{status, reason, evidence, confidence,
calibrated, source_kind, locator, derived_by}` for every schema field; every published field carries `evidence`,
`confidence`, `calibrated`, `source_kind` and `locator`. `record.data` holds published values only.
Refs: §6, §13.1, SPEC-05 §4.10, D-0354, D-0454.
Enforced by: Pydantic models and tests; status: SPEC-05.

#### Scenario: Published field metadata
- **WHEN** `name` publishes from JSON-LD
- **THEN** its `field_meta` holds evidence `structured`, `calibrated`, `confidence`, source kind `jsonld` and a
  `jsonld:` locator

#### Scenario: Unpublished field metadata
- **WHEN** `brand` has no candidates
- **THEN** `field_meta.brand` has status `missing` and reason `no_candidates`, and `record.data` has no `brand`

### Requirement: Incomplete pages
A page whose required fields and groups all publish SHALL have outcome `extracted` and `record.complete=true`. When
one does not: a caller-supplied URL (`scrape`, `batch_scrape`, `extract`, including URLs from a caller's glob) stores
and returns the record with per-field statuses, `complete=false` and outcome `partial`; a crawl-discovered URL
produces `no_match` and no record. A listing is `extracted` when it has rows and all are complete, `no_match` when no
record is kept, else `partial`; a caller-supplied listing with no rows is `partial` with no record.
Refs: §10, §23, SPEC-05 §4.10, D-0513, D-0930.

#### Scenario: Crawl page missing price
- **WHEN** a crawl-discovered detail page leaves the required `price` missing
- **THEN** the outcome is `no_match` and no record is stored

### Requirement: Entity key
A detail record's `entity_key` SHALL be the hex sha256 of `site_id` + the task's canonical URL; a listing row's uses
its published `T.url` value, else `<task canonical URL>#<row position>`, and a URL listed twice gives one record.
Refs: SPEC-05 §4.10, D-0459, D-0488, D-0512.

#### Scenario: Same URL twice
- **WHEN** the same detail URL is extracted in two runs
- **THEN** both records have the same `entity_key`

### Requirement: LLM gap hook
In `cold` mode the system SHALL ask role C, once per detail page, only for required fields that are `missing` and
missing members of required groups no member fills; in `active` mode only for fields the config does not cover or
drift suspended. `conflict` and `abstained` fields, `object` fields and `list<object>` fields are never sent. Role C
candidates (`source_kind='llm'`, `text:` locator, owned by the target) pass the same validity and τ stages in the
`llm_grounded` bucket. A listing without structured rows asks role C for rows.
Refs: §8.4, SPEC-05 §4.13, D-0489, D-0797; role C itself in [llm](../llm/spec.md).

#### Scenario: Conflicting price
- **WHEN** `price` is `conflict` after preference in cold mode
- **THEN** role C is not asked for `price`

### Requirement: Nothing after resolution changes a value (INV-27)
No layer after resolution SHALL change a published value: records storage, exporters, the API, MCP and the UI
serialize what resolution published. A wrong value is fixed in extraction, a config or an operator correction (C5).
The opt-in `csv_safe` CSV export only prefixes `'` to formula-like cells and leaves default output unchanged.
Refs: §10, C5, Appendix A #32, #40, D-0291, D-0879.
Enforced by: property test that exported and API values equal the stored record's values, and review; status: SPEC-05, SPEC-07, SPEC-08, SPEC-10 (test: SPEC-10 PR 1).

#### Scenario: Records API
- **WHEN** a record is read through `GET /v1/records` and the MCP server
- **THEN** each published value equals the stored record's value
