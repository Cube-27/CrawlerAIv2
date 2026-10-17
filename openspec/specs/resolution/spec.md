# Resolution Specification

## Purpose

Resolution decides, per schema field of a page, what publishes from [extraction](../extraction/spec.md)'s candidates
and how far it is trusted, and builds the record with per-field metadata and the page outcome (`resolve/`).
Rationale: ARCHITECTURE §10 ([archived](../../changes/archive/2026-10-16-architecture-rev26/ARCHITECTURE.md)); history: SPEC-05.

## Requirements

### Requirement: One extraction path
The system SHALL resolve every page through `extract_page`, used by the worker, `scrape` and replays alike; an
exception yields outcome `error` (stored `failed`) with no fields and no record. Refs: §8.1, D-0483, D-0506.

### Requirement: Candidate validity
Every candidate SHALL pass its type normalizer ([normalization](../normalization/spec.md)), else it is
rejected `invalid`/`ambiguous`. Which entity a candidate belongs to is
[identity-and-intent](../identity-and-intent/spec.md). Refs: §8.2, D-1379.

### Requirement: Exact-match agreement (INV-14)
For exact-match types the system SHALL publish only when every valid, owned, kept candidate agrees after
normalization, else `conflict` with no value. Refs: §10, D-0437.
Enforced by: property test; active.
#### Scenario: Two prices disagree
- **WHEN** JSON-LD says 19.90 EUR and microdata says 21.00 EUR for the target
- **THEN** `price` is `conflict` and has no value

### Requirement: Source precedence for text, url and image
For `text`, `long_text`, `url` and `image_url` the system SHALL publish from the first source kind in the type's order
in `backend/data/source_precedence.yaml` that has a valid owned candidate; unranked kinds never win, and disagreement
within the winning kind is `conflict` unless independent candidates of the first other kind in that order that names
one of its values settle it. Image values naming the same files (`resource_key`: authority and path, any scheme or
query; a list's as the set of its files) are renditions: they agree, and of renditions the first whose URLs are all
`https` publishes. Refs: §10, D-0439, D-0944, D-1182, D-1292.
#### Scenario: Gallery array
- **WHEN** JSON-LD `Product.image` lists three URLs and `og:image` equals the second
- **THEN** `image_url` publishes the second URL
#### Scenario: Namers disagree
- **WHEN** `og:image` names the second gallery URL by its file and a `dom` image names the first
- **THEN** `image_url` publishes the second URL, Open Graph ranking before `dom`
#### Scenario: An http twin
- **WHEN** two merged JSON-LD blocks state one image over `http` and over `https?w=800`
- **THEN** `image_url` publishes the `https` URL

### Requirement: Missing reasons name the furthest stage
An unpublished field SHALL state its status and reason (the furthest screening stage reached, or the conflict or
abstain cause, per `resolve/types.py`); every rejected candidate keeps its own reason. Refs: SPEC-05 §4.2, D-0438, D-0533.

### Requirement: Atomic offers (INV-15)
Price, currency and availability SHALL come from one anchor Offer; Offers that disagree give `offers_disagree`, a field
the anchor lacks gives `offer_split`, and an `AggregateOffer` range never publishes as the price. Refs: §10, D-0440;
per-row and common-value rules in [variants](../variants/spec.md). Enforced by: resolver test; active.
#### Scenario: Price and availability from two Offers
- **WHEN** Offer A states only price and Offer B states only availability
- **THEN** the field without a value from the anchor Offer is `conflict` with reason `offer_split`

### Requirement: Derived values (INV-07)
Derived values SHALL fill only `missing` fields and carry `derived_by`; the only derivations are `absolutize`, then for
a detail page's `T.url` `canonical_link` (RFC 6596), then `final_url`, each a named function (`resolve/derive.py`).
Refs: §9, §10, Appendix A #40, D-0442, D-0910. Enforced by: resolver tests; active.
#### Scenario: No url candidate
- **WHEN** a detail page has no url candidate and `<link rel=canonical href="https://example.com/p/1">`
- **THEN** `url` publishes that URL with `derived_by=canonical_link`, source kind `derived`, evidence `derived`

### Requirement: Evidence, confidence and τ
Each published field SHALL carry one evidence bucket (`resolve/evidence.py`; `agreed` needs two independent kinds;
`network` for a value of the page's captured calls, Appendix A #59; a lone `js_state` value has none and abstains
`no_bucket`) and the dev precision of its `(type, evidence)` bucket from `calibration.json`; a calibrated bucket below
τ (0.97 required, 0.95 otherwise) abstains `below_tau`. Until the first dev fit every field is uncalibrated.
Refs: §10, §16.3, D-0455, D-0456, D-1316.
#### Scenario: Calibrated bucket below τ
- **WHEN** a required money field's bucket has n=40 and precision 0.969
- **THEN** the field is `abstained` with reason `below_tau`
#### Scenario: Value of a captured call
- **WHEN** a field's only candidate is a visible price read from a captured call
- **THEN** it publishes with evidence `network`, uncalibrated

### Requirement: Record confidence
Record confidence SHALL be the minimum over published required fields and required-group members, null when any is
uncalibrated; a listing's records carry their least confident row's. Refs: §10, D-0456, D-0931.

### Requirement: Provenance on every field (INV-22)
Every candidate SHALL carry a locator and `field_meta` SHALL hold status and reason for every schema field, plus
`evidence`, `confidence`, `calibrated`, `source_kind` and `locator` for every published one; `record.data` holds
published values only. Refs: §6, §13.1, D-0354. Enforced by: Pydantic models and tests; active.
#### Scenario: Unpublished field metadata
- **WHEN** `brand` has no candidates
- **THEN** `field_meta.brand` has status `missing` and reason `no_candidates`, and `record.data` has no `brand`

### Requirement: Incomplete pages
A page whose required fields and groups all publish SHALL be `extracted` and complete; otherwise a caller-supplied URL
stores the record as `partial` and a crawl-discovered URL is `no_match` with no record. Refs: §10, §23, D-0513, D-0930.
#### Scenario: Crawl page missing price
- **WHEN** a crawl-discovered detail page leaves the required `price` missing
- **THEN** the outcome is `no_match` and no record is stored

### Requirement: LLM gap hook
The system SHALL ask role C ([llm](../llm/spec.md)) once per detail page only for missing required fields and unfilled
required groups (in `active` mode only those the config neither covers nor lists as absent, which stay `missing` with
reason `absent`); `conflict`, `abstained`, `object` and `list<object>` fields are never sent, and its candidates pass
the same stages as `llm_grounded`. Refs: §8.4, D-0489, D-0797, D-1341.

### Requirement: Nothing after resolution changes a value (INV-27)
No layer after resolution (storage, exporters, API, MCP, UI) SHALL change a published value; fixes go to extraction,
a config or an operator correction (C5). Opt-in `csv_safe` only prefixes `'` to formula-like cells. Refs: §10, D-0879.
Enforced by: a property test that exported and API values equal the stored record's, and review; active.
#### Scenario: Records API
- **WHEN** a record is read through `GET /v1/records` and the MCP server
- **THEN** each published value equals the stored record's value
