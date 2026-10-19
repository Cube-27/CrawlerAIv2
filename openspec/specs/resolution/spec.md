# Resolution Specification

## Purpose

Resolution decides, per schema field of a page, what publishes from [extraction](../extraction/spec.md)'s candidates
and how far it is trusted, and builds the record with per-field metadata and the page outcome (`resolve/`).

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

### Requirement: Currency evidence ranks money candidates
Among a money field's kept candidates, those whose currency rests on the strongest evidence (no `Ok.basis`, then
`page`, `locale`, `unknown`; [normalization](../normalization/spec.md)) SHALL decide by agreement; a candidate on weaker
evidence stays only when it equals one of them (it agrees), else it is rejected `weaker_currency`. Refs: owner #68.
#### Scenario: Unknown currency beside a stated one
- **WHEN** JSON-LD says 19.90 USD and a DOM text says `$21.00` that no evidence settles
- **THEN** `price` publishes 19.90 USD and the DOM candidate is rejected `weaker_currency`

### Requirement: Source precedence for text, url and image
For `text`, `long_text`, `url` and `image_url` the system SHALL publish from the first source kind in the type's order
in `backend/data/source_precedence.yaml` that has a valid owned candidate; unranked kinds never win, and disagreement
within the winning kind is `conflict` unless independent candidates of the first other kind in that order that names
one of its values settle it. A candidate that is a fragment of another of the field's candidates ranks nowhere
(`resolve/supersede.py`): a `long_text` that is a prefix or ellipsis-cut prefix of a longer one, or an Open Graph
description beside a longer one of another kind; a `text` that is another kind's value plus ` - ` or ` | ` and more
text; an Open Graph list of images whose files are all among a longer list's of another kind (`og:image` is the
object's representative image, as its description is a summary). Image values naming the same files (`resource_key`: authority and path without the size, conversion and options the path states, any scheme or query; a list's as the set of its files) are renditions: they agree, and of renditions those whose URLs are all
`https` (else all) are kept and of a single image's the largest publishes (`url.largest_rendition`, as a list ranks them), else the first. A value of the page's state JSON (`js_state`) ranks after every other kind. (Previously: no `js_state` rank; no fragment rule; an Open Graph image list outranked a gallery holding it; the key kept a stated size; the first `https` rendition published, whatever its size.) Refs: §10, D-0439, D-0944, D-1182,
D-1292, D-1660, D-1773. Enforced by: resolver tests; active.
#### Scenario: Gallery array
- **WHEN** JSON-LD `Product.image` lists three URLs and `og:image` equals the second
- **THEN** `image_url` publishes the second URL
#### Scenario: Namers disagree
- **WHEN** `og:image` names the second gallery URL by its file and a `dom` image names the first
- **THEN** `image_url` publishes the second URL, Open Graph ranking before `dom`
#### Scenario: An http twin
- **WHEN** two merged JSON-LD blocks state one image over `http` and over `https?w=800`
- **THEN** `image_url` publishes the `https` URL
#### Scenario: A truncated description
- **WHEN** JSON-LD states a description cut at 250 characters and `dom` states the full text
- **THEN** `description` publishes the full text
#### Scenario: A state value beside a page value
- **WHEN** a `title` has a state value and a `dom` value that differ
- **THEN** `title` publishes the `dom` value, and a state value alone publishes

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
a detail page's `T.url` field (`T.url` in every alternative of its path) `canonical_link` (RFC 6596), then
`final_url`, each a named function (`resolve/derive.py`). (Previously: a field whose last rank was `T.url`, such as
`apply_url`, took the page URL too.) Refs: §9, §10, Appendix A #40, D-0442, D-0910, D-1625. Enforced by: resolver
tests; active.
#### Scenario: No url candidate
- **WHEN** a detail page has no url candidate and `<link rel=canonical href="https://example.com/p/1">`
- **THEN** `url` publishes that URL with `derived_by=canonical_link`, source kind `derived`, evidence `derived`
#### Scenario: No stated apply link
- **WHEN** a job page states no apply link and role C claims none
- **THEN** `apply_url` stays `missing`

### Requirement: Evidence, confidence and min_confidence
Each published field SHALL carry one evidence bucket (`resolve/evidence.py`; `agreed` needs two independent kinds;
`network` for a value of the page's captured calls, Appendix A #59; `state` for a value of the page's state JSON) and
the fitted dev confidence of its `(type, evidence)` bucket from `calibration.json`, which holds only buckets measured on
at least 20 labelled values (the others are uncalibrated, `calibrated=false`). A money value whose currency only the
locale settles or nothing settles (`basis` `locale`, `unknown`) is measured apart, in bucket `money|<evidence>|<basis>`,
for its lower confidence (owner #68); every published field notes its `basis` in `field_meta` when it has one. Every
chosen value publishes with that
confidence unless the request sets `min_confidence` and the bucket is calibrated below it: the field is then
`abstained` with reason `below_min_confidence`. An uncalibrated bucket never abstains. (Previously: a calibrated bucket
below τ, 0.97 required and 0.95 otherwise, abstained `below_tau`; a lone `js_state` value had no bucket.)
Refs: §10, §16.3, D-0455, D-0456, D-1316, D-1740, D-1770, D-1771, D-1773.
#### Scenario: Calibrated bucket below the minimum
- **WHEN** a money bucket has n=40 and precision 0.9 and the request sets `min_confidence` 0.95
- **THEN** the field is `abstained` with reason `below_min_confidence`, and with no `min_confidence` it publishes with
  confidence 0.9 and `calibrated=true`
#### Scenario: Bucket below the floor
- **WHEN** a bucket has n=19 and the request sets `min_confidence` 0.99
- **THEN** the field publishes with `calibrated=false`
#### Scenario: Value of a captured call
- **WHEN** a field's only candidate is a visible price read from a captured call
- **THEN** it publishes with evidence `network`, uncalibrated while that bucket is below the floor
#### Scenario: Value of state JSON
- **WHEN** a field's only candidate is a value read at a key the item layer proved
- **THEN** it publishes with evidence `state`

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
